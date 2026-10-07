use crate::model_store::{ModelManifest, ModelSpec};
use crate::runtime_config::{RuntimeConfig, RuntimePaths};
use anyhow::Result;
use serde_json::{Value, json};
use std::path::PathBuf;
use std::process::Stdio;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};
use tokio::process::{Child, Command};
use tokio::sync::{Mutex, Semaphore};

const MAX_BODY: usize = 8 * 1024 * 1024;
const MAX_HEADERS: usize = 16384;
const MAX_EMBED_CHARS: usize = 2000;
const MAX_PAIR_CHARS: usize = 48000;
const MAX_RESTARTS: usize = 3;
const LOG_CAP: u64 = 20 * 1024 * 1024;

type Reply = (u16, Value);
fn error(status: u16, kind: &str) -> Reply {
    let fix = match kind {
        "model_missing_or_invalid" => {
            "Run code-diver setup to verify and repair the model cache, then restart the user service"
        }
        "llama_server_unavailable" | "child_launch_failed" => {
            "Configure an executable llama-server build >=9430 using setup --llama-server /absolute/path and check execute permissions"
        }
        "restart_limit" | "child_exited" | "child_start_timeout" => {
            "Run code-diver doctor; check llama-server build, model integrity and available memory before restarting the user service"
        }
        "log_unavailable" => {
            "Check runtime log directory permissions and free space, then restart the user service"
        }
        "child_port_unavailable" => {
            "Check local socket and file descriptor limits, then retry or restart the user service"
        }
        "daemon_shutting_down" => "Wait for the user service to restart, then retry",
        "request_queue_timeout" | "daemon_overloaded" => {
            "Reduce concurrent requests and retry; check daemon.max_concurrency and request_timeout_secs"
        }
        "context length exceeded" | "invalid_or_oversized_input" => {
            "Shorten query/document pairs or split embedding batches; retain the model manifest's tested serving settings"
        }
        "backend_timeout" => {
            "Reduce request size and run code-diver doctor; check memory pressure and request_timeout_secs"
        }
        "backend_unavailable" | "backend_transfer_failed" | "backend_rejected_request" => {
            "Run code-diver doctor and check the supervised llama-server model and serving settings; retry only after backend recovery"
        }
        code if code.starts_with("backend_") => {
            "Run code-diver doctor; use a supported llama-server build with the manifest's model and serving settings; malformed backend results are never accepted"
        }
        "not_found" => "Use GET /health, GET /v1/models, POST /v1/embeddings or POST /v1/rerank",
        "forbidden_host" | "browser_or_chunked_request_forbidden" => {
            "Use a non-browser loopback HTTP client with a localhost Host header; omit Origin and Transfer-Encoding"
        }
        "json_required" | "invalid_json" => "Send valid JSON with Content-Type: application/json",
        "headers_too_large" => "Reduce HTTP headers and retry with a loopback HTTP/1.1 client",
        _ => {
            "Send a complete HTTP/1.1 request with one loopback Host header and, for POST, one JSON Content-Type and accurate Content-Length; omit duplicate headers"
        }
    };
    (
        status,
        json!({"error":{"type":kind,"message":kind,"fix":fix}}),
    )
}

struct Worker {
    process: Option<Child>,
    port: u16,
    active: usize,
    last_used: Instant,
    failures: usize,
    window: Instant,
}
impl Worker {
    fn new() -> Self {
        Self {
            process: None,
            port: 0,
            active: 0,
            last_used: Instant::now(),
            failures: 0,
            window: Instant::now(),
        }
    }
    async fn stop(&mut self) {
        if let Some(mut child) = self.process.take() {
            let _ = child.kill().await;
            let _ = child.wait().await;
        }
    }
}

struct Daemon {
    config: RuntimeConfig,
    paths: RuntimePaths,
    manifest: ModelManifest,
    client: reqwest::Client,
    workers: [Mutex<Worker>; 2],
    permits: [Semaphore; 2],
    log: Mutex<()>,
}

impl Daemon {
    async fn event(&self, role: usize, event: &str) -> std::io::Result<()> {
        use std::io::Write;
        let _guard = self.log.lock().await;
        let path = self.paths.logs.join(if role == 0 {
            "embedder.log"
        } else {
            "reranker.log"
        });
        let limit = self.config.daemon.log_max_bytes.min(LOG_CAP);
        match std::fs::symlink_metadata(&path) {
            Ok(meta) if !meta.is_file() => return Err(std::io::Error::other("unsafe log file")),
            Ok(meta) if meta.len() > limit => {
                std::fs::OpenOptions::new()
                    .write(true)
                    .open(&path)?
                    .set_len(limit)?;
            }
            Err(e) if e.kind() != std::io::ErrorKind::NotFound => return Err(e),
            _ => {}
        }
        let bytes = format!("{event}\n");
        let bytes = &bytes.as_bytes()[..bytes.len().min(limit as usize)];
        if std::fs::metadata(&path).map(|m| m.len()).unwrap_or(0) + bytes.len() as u64 > limit {
            let count = self.config.daemon.log_retained_files.min(3);
            if count > 1 {
                let oldest = path.with_extension(format!("log.{}", count - 1));
                if oldest.exists() {
                    std::fs::remove_file(oldest)?;
                }
                for i in (1..count - 1).rev() {
                    let from = path.with_extension(format!("log.{i}"));
                    if from.exists() {
                        std::fs::rename(from, path.with_extension(format!("log.{}", i + 1)))?;
                    }
                }
                if path.exists() {
                    std::fs::rename(&path, path.with_extension("log.1"))?;
                }
            } else if path.exists() {
                std::fs::remove_file(&path)?;
            }
        }
        let mut options = std::fs::OpenOptions::new();
        options.create(true).append(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        options.open(path)?.write_all(bytes)
    }

    async fn acquire(&self, role: usize) -> std::result::Result<u16, Reply> {
        let mut worker = self.workers[role].lock().await;
        if worker.window.elapsed() > Duration::from_secs(60) {
            worker.failures = 0;
            worker.window = Instant::now();
        }
        let alive = worker
            .process
            .as_mut()
            .is_some_and(|c| matches!(c.try_wait(), Ok(None)));
        if !alive {
            if worker.process.is_some() {
                worker.stop().await;
                worker.failures += 1;
            }
            if worker.failures >= MAX_RESTARTS {
                return Err(error(503, "restart_limit"));
            }
            let spec = if role == 0 {
                &self.manifest.models.embedder
            } else {
                &self.manifest.models.reranker
            };
            let model = self.paths.models.join(&spec.file);
            if !std::fs::symlink_metadata(&model).is_ok_and(|m| m.is_file() && m.len() == spec.size)
            {
                return Err(error(503, "model_missing_or_invalid"));
            }
            let listener = TcpListener::bind("127.0.0.1:0")
                .await
                .map_err(|_| error(503, "child_port_unavailable"))?;
            worker.port = listener
                .local_addr()
                .map_err(|_| error(503, "child_port_unavailable"))?
                .port();
            drop(listener);
            let binary = self
                .config
                .llama_server
                .clone()
                .or_else(|| {
                    std::env::var_os("PATH").and_then(|path| {
                        std::env::split_paths(&path)
                            .map(|p| p.join("llama-server"))
                            .find(|p| p.is_file())
                    })
                })
                .ok_or_else(|| error(503, "llama_server_unavailable"))?;
            let mut cmd = Command::new(binary);
            cmd.env_clear()
                .args(child_args(&self.config, role, worker.port, model));
            if let Some(path) = std::env::var_os("PATH") {
                cmd.env("PATH", path);
            }
            // Raw child output can contain input texts or environment secrets.
            cmd.stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .kill_on_drop(true);
            worker.process = Some(cmd.spawn().map_err(|_| {
                worker.failures += 1;
                error(503, "child_launch_failed")
            })?);
            if self.event(role, "child_started").await.is_err() {
                worker.stop().await;
                return Err(error(503, "log_unavailable"));
            }
            let deadline =
                Instant::now() + Duration::from_secs(self.config.daemon.startup_timeout_secs);
            loop {
                if !worker
                    .process
                    .as_mut()
                    .is_some_and(|c| matches!(c.try_wait(), Ok(None)))
                {
                    worker.stop().await;
                    worker.failures += 1;
                    return Err(error(503, "child_exited"));
                }
                if Instant::now() >= deadline {
                    worker.stop().await;
                    worker.failures += 1;
                    return Err(error(504, "child_start_timeout"));
                }
                if self
                    .client
                    .get(format!("http://127.0.0.1:{}/health", worker.port))
                    .timeout(Duration::from_millis(200))
                    .send()
                    .await
                    .is_ok_and(|r| r.status().is_success())
                {
                    break;
                }
                tokio::time::sleep(Duration::from_millis(25)).await;
            }
        }
        worker.active += 1;
        Ok(worker.port)
    }

    async fn proxy(&self, role: usize, body: Value) -> Reply {
        let _permit = match tokio::time::timeout(
            Duration::from_secs(self.config.daemon.request_timeout_secs),
            self.permits[role].acquire(),
        )
        .await
        {
            Ok(Ok(permit)) => permit,
            Ok(Err(_)) => return error(503, "daemon_shutting_down"),
            Err(_) => return error(504, "request_queue_timeout"),
        };
        for attempt in 0..2 {
            let port = match self.acquire(role).await {
                Ok(p) => p,
                Err(e) => return e,
            };
            let route = if role == 0 { "embeddings" } else { "rerank" };
            let response = self
                .client
                .post(format!("http://127.0.0.1:{port}/v1/{route}"))
                .json(&body)
                .send()
                .await;
            let mut result = match response {
                Ok(mut response) => {
                    let status = response.status().as_u16();
                    let mut bytes = Vec::new();
                    let mut failure = None;
                    loop {
                        match response.chunk().await {
                            Ok(Some(chunk)) if bytes.len() + chunk.len() <= MAX_BODY => {
                                bytes.extend_from_slice(&chunk)
                            }
                            Ok(None) => break,
                            Ok(Some(_)) => {
                                failure = Some(error(502, "backend_response_too_large"));
                                break;
                            }
                            Err(e) => {
                                failure = Some(error(
                                    if e.is_timeout() { 504 } else { 503 },
                                    "backend_transfer_failed",
                                ));
                                break;
                            }
                        }
                    }
                    failure.unwrap_or_else(|| validate_response(role, status, &bytes))
                }
                Err(ref e) => error(
                    if e.is_timeout() { 504 } else { 503 },
                    if e.is_timeout() {
                        "backend_timeout"
                    } else {
                        "backend_unavailable"
                    },
                ),
            };
            if result.0 == 200 {
                let expected = if role == 0 {
                    body["input"].as_array().map_or(1, Vec::len)
                } else {
                    let count = body["documents"].as_array().map_or(0, Vec::len);
                    body["top_n"]
                        .as_u64()
                        .map_or(count, |n| (n as usize).min(count))
                };
                let key = if role == 0 { "data" } else { "results" };
                let rows = result.1[key].as_array().unwrap();
                if rows.len() != expected {
                    result = error(502, "backend_incomplete_result");
                } else if role == 1 {
                    let mut indices = std::collections::BTreeSet::new();
                    let count = body["documents"].as_array().map_or(0, Vec::len);
                    if !rows.iter().all(|r| {
                        let index = r["index"].as_u64().unwrap();
                        index < count as u64 && indices.insert(index)
                    }) {
                        result = error(502, "backend_invalid_indices");
                    }
                }
            }
            let mut worker = self.workers[role].lock().await;
            worker.active -= 1;
            worker.last_used = Instant::now();
            let dead = !worker
                .process
                .as_mut()
                .is_some_and(|c| matches!(c.try_wait(), Ok(None)));
            if result.0 == 503 && dead && attempt == 0 {
                continue;
            }
            if result.0 != 200 {
                let _ = self.event(role, "request_failed").await;
            }
            return result;
        }
        error(503, "backend_unavailable")
    }

    async fn reap_idle(&self) {
        for (role, worker) in self.workers.iter().enumerate() {
            if let Ok(mut worker) = worker.try_lock() {
                if worker.active != 0
                    || worker.process.is_none()
                    || worker.last_used.elapsed()
                        < Duration::from_secs(self.config.daemon.idle_timeout_secs)
                {
                    continue;
                }
                worker.stop().await;
                let _ = self.event(role, "idle_stop").await;
            }
        }
    }

    async fn route(&self, method: &str, path: &str, body: &[u8]) -> Reply {
        match (method, path) {
            ("GET", "/health") => {
                let mut children = Vec::new();
                for worker in &self.workers {
                    match worker.try_lock() {
                        Ok(mut w) => children.push(json!({"loaded":w.process.as_mut().is_some_and(|c| matches!(c.try_wait(), Ok(None))),"inflight":w.active})),
                        Err(_) => children.push(json!({"state":"starting"})),
                    }
                }
                (
                    200,
                    json!({"status":"ok","service":"code-diver","children":children}),
                )
            }
            ("GET", "/v1/models") => (
                200,
                json!({"object":"list","data":[model_info(&self.manifest.models.embedder),model_info(&self.manifest.models.reranker)]}),
            ),
            ("POST", "/v1/embeddings" | "/v1/rerank" | "/rerank") => {
                let role = usize::from(path != "/v1/embeddings");
                let value: Value = match serde_json::from_slice(body) {
                    Ok(v) => v,
                    Err(_) => return error(400, "invalid_json"),
                };
                if !valid_request(role, &value) {
                    return error(400, "invalid_or_oversized_input");
                }
                self.proxy(role, value).await
            }
            _ => error(404, "not_found"),
        }
    }
}

fn model_info(spec: &ModelSpec) -> Value {
    json!({"id":spec.label,"object":"model","owned_by":"code-diver"})
}

fn valid_request(role: usize, value: &Value) -> bool {
    let text = |v: &Value, max| {
        v.as_str()
            .is_some_and(|s| !s.is_empty() && s.chars().count() <= max)
    };
    if !value.is_object() {
        return false;
    }
    if role == 0 {
        if value.get("encoding_format").is_some_and(|v| v != "float") {
            return false;
        }
        text(&value["input"], MAX_EMBED_CHARS)
            || value["input"].as_array().is_some_and(|a| {
                !a.is_empty() && a.len() <= 256 && a.iter().all(|v| text(v, MAX_EMBED_CHARS))
            })
    } else {
        if value
            .get("top_n")
            .is_some_and(|v| !v.as_u64().is_some_and(|n| n > 0 && n <= 256))
        {
            return false;
        }
        text(&value["query"], MAX_PAIR_CHARS)
            && value["documents"].as_array().is_some_and(|a| {
                !a.is_empty()
                    && a.len() <= 256
                    && a.iter().all(|v| {
                        text(v, MAX_PAIR_CHARS)
                            && v.as_str().unwrap().chars().count()
                                + value["query"].as_str().unwrap().chars().count()
                                <= MAX_PAIR_CHARS
                    })
            })
    }
}

fn validate_response(role: usize, status: u16, bytes: &[u8]) -> Reply {
    if status != 200 {
        if status != 504 && backend_context_overflow(bytes) {
            return error(400, "context length exceeded");
        }
        return error(
            if status == 400 || status == 413 || status == 422 {
                400
            } else if status == 504 {
                504
            } else {
                503
            },
            "backend_rejected_request",
        );
    }
    let mut value: Value = match serde_json::from_slice(bytes) {
        Ok(v) => v,
        Err(_) => return error(502, "backend_invalid_json"),
    };
    let key = if role == 0 { "data" } else { "results" };
    let Some(rows) = value[key].as_array_mut() else {
        return error(502, "backend_invalid_result");
    };
    if rows.is_empty() {
        return error(502, "backend_empty_result");
    }
    if role == 0 {
        if !rows.iter().all(|r| {
            r["embedding"].as_array().is_some_and(|a| {
                !a.is_empty()
                    && a.iter().all(|v| v.as_f64().is_some_and(f64::is_finite))
                    && a.iter().any(|v| v.as_f64().is_some_and(|n| n != 0.0))
            })
        }) {
            return error(502, "backend_invalid_embedding");
        }
    } else {
        if !rows.iter().all(|r| {
            r["index"].as_u64().is_some()
                && r["relevance_score"].as_f64().is_some_and(f64::is_finite)
        }) {
            return error(502, "backend_invalid_scores");
        }
        rows.sort_by(|a, b| {
            b["relevance_score"]
                .as_f64()
                .unwrap()
                .total_cmp(&a["relevance_score"].as_f64().unwrap())
        });
    }
    (200, value)
}

fn cpu_threads() -> usize {
    let available = std::thread::available_parallelism()
        .map(usize::from)
        .unwrap_or(1);
    let quota = std::fs::read_to_string("/sys/fs/cgroup/cpu.max")
        .ok()
        .and_then(|s| {
            let mut parts = s.split_whitespace();
            let quota: usize = parts.next()?.parse().ok()?;
            let period: usize = parts.next()?.parse().ok()?;
            (period > 0).then(|| quota.div_ceil(period).max(1))
        })
        .or_else(|| {
            let quota: usize = std::fs::read_to_string("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
                .ok()?
                .trim()
                .parse()
                .ok()?;
            let period: usize = std::fs::read_to_string("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
                .ok()?
                .trim()
                .parse()
                .ok()?;
            (period > 0).then(|| quota.div_ceil(period).max(1))
        });
    quota.unwrap_or(available).min(available)
}

fn backend_context_overflow(bytes: &[u8]) -> bool {
    let Ok(value) = serde_json::from_slice::<Value>(bytes) else {
        return false;
    };
    let message = value["error"]
        .as_str()
        .or_else(|| value["error"]["message"].as_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    [
        "input too large to process",
        "context length exceeded",
        "context_length_exceeded",
        "exceeds the available context size",
    ]
    .iter()
    .any(|marker| message.contains(marker))
        || message
            .strip_prefix("input (")
            .and_then(|rest| rest.split_once(" tokens) is too large to process"))
            .is_some_and(|(tokens, detail)| {
                !tokens.is_empty()
                    && tokens.bytes().all(|byte| byte.is_ascii_digit())
                    && detail.contains("batch size")
            })
}

fn child_args(
    config: &RuntimeConfig,
    role: usize,
    port: u16,
    model: PathBuf,
) -> Vec<std::ffi::OsString> {
    let mut args: Vec<std::ffi::OsString> = ["--host", "127.0.0.1", "--port"]
        .into_iter()
        .map(Into::into)
        .collect();
    args.extend([
        port.to_string().into(),
        "--model".into(),
        model.into_os_string(),
        "--embedding".into(),
        "--pooling".into(),
        if role == 0 {
            config.daemon.embedder_pooling.clone()
        } else {
            config.daemon.reranker_pooling.clone()
        }
        .into(),
    ]);
    if role == 1 {
        args.push("--reranking".into());
    }
    let limits = if role == 0 {
        (
            config.daemon.embedder_ctx,
            config.daemon.embedder_batch,
            config.daemon.embedder_ubatch,
        )
    } else {
        (
            config.daemon.reranker_ctx,
            config.daemon.batch,
            config.daemon.ubatch,
        )
    };
    for (key, value) in [
        ("--ctx-size", limits.0),
        ("--batch-size", limits.1),
        ("--ubatch-size", limits.2),
        (
            "--threads",
            config.daemon.threads.unwrap_or_else(cpu_threads),
        ),
    ] {
        args.extend([key.into(), value.to_string().into()]);
    }
    args
}

fn host_ok(host: &str, port: u16) -> bool {
    ["localhost", "127.0.0.1", "[::1]"]
        .iter()
        .any(|h| host == *h || host == format!("{h}:{port}"))
}

async fn read_request(
    stream: &mut TcpStream,
    port: u16,
) -> std::result::Result<(String, String, Vec<u8>), Reply> {
    let mut header = Vec::new();
    while !header.ends_with(b"\r\n\r\n") {
        if header.len() >= MAX_HEADERS {
            return Err(error(400, "headers_too_large"));
        }
        header.push(
            stream
                .read_u8()
                .await
                .map_err(|_| error(400, "incomplete_request"))?,
        );
    }
    let header = std::str::from_utf8(&header).map_err(|_| error(400, "invalid_headers"))?;
    let mut lines = header.split("\r\n");
    let parts: Vec<_> = lines.next().unwrap_or("").split_whitespace().collect();
    if parts.len() != 3 || parts[2] != "HTTP/1.1" {
        return Err(error(400, "invalid_request_line"));
    }
    let mut host = None;
    let mut length = None;
    let mut content = None;
    for line in lines.filter(|l| !l.is_empty()) {
        let (key, value) = line
            .split_once(':')
            .ok_or_else(|| error(400, "invalid_headers"))?;
        let value = value.trim();
        if key.eq_ignore_ascii_case("host") && host.replace(value).is_some() {
            return Err(error(400, "duplicate_host"));
        }
        if key.eq_ignore_ascii_case("content-length") && length.replace(value).is_some() {
            return Err(error(400, "duplicate_length"));
        }
        if key.eq_ignore_ascii_case("content-type") && content.replace(value).is_some() {
            return Err(error(400, "duplicate_content_type"));
        }
        if key.eq_ignore_ascii_case("transfer-encoding") || key.eq_ignore_ascii_case("origin") {
            return Err(error(403, "browser_or_chunked_request_forbidden"));
        }
    }
    if !host.is_some_and(|h| host_ok(h, port)) {
        return Err(error(403, "forbidden_host"));
    }
    let mut body = Vec::new();
    if parts[0] == "POST" {
        if !content.is_some_and(|c| {
            c.split(';')
                .next()
                .unwrap_or("")
                .trim()
                .eq_ignore_ascii_case("application/json")
        }) {
            return Err(error(415, "json_required"));
        }
        let size: usize = length
            .and_then(|l| l.parse().ok())
            .filter(|n| *n > 0 && *n <= MAX_BODY)
            .ok_or_else(|| error(400, "invalid_body_length"))?;
        body.resize(size, 0);
        stream
            .read_exact(&mut body)
            .await
            .map_err(|_| error(400, "incomplete_body"))?;
    }
    Ok((parts[0].into(), parts[1].into(), body))
}

async fn connection(mut stream: TcpStream, daemon: Arc<Daemon>, port: u16) {
    let request =
        tokio::time::timeout(Duration::from_secs(10), read_request(&mut stream, port)).await;
    let reply = match request {
        Ok(Ok((method, path, body))) => daemon.route(&method, &path, &body).await,
        Ok(Err(reply)) => reply,
        Err(_) => error(408, "request_read_timeout"),
    };
    send_reply(stream, reply).await;
}

async fn send_reply(mut stream: TcpStream, reply: Reply) {
    let body = serde_json::to_vec(&reply.1).unwrap();
    let header = format!(
        "HTTP/1.1 {} Response\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        reply.0,
        body.len()
    );
    let _ = tokio::time::timeout(Duration::from_secs(10), async {
        stream.write_all(header.as_bytes()).await?;
        stream.write_all(&body).await
    })
    .await;
}

/// Runs in the current process; service installation and detachment belong to the host layer.
pub async fn run(config: RuntimeConfig, paths: RuntimePaths, _foreground: bool) -> Result<()> {
    config.validate()?;
    paths.ensure_dirs()?;
    let manifest = match config.profile.model_manifest_source()? {
        Some(source) => crate::model_store::load_manifest(source).await?,
        None => ModelManifest::embedded()?,
    };
    let listener = TcpListener::bind((config.daemon.bind.as_str(), config.daemon.port))
        .await
        .map_err(|cause| anyhow::anyhow!("daemon loopback bind {}:{} failed: {cause}; stop the conflicting listener or choose an unused daemon.port in runtime config", config.daemon.bind, config.daemon.port))?;
    let port = listener.local_addr()?.port();
    let client = reqwest::Client::builder()
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(Duration::from_secs(config.daemon.request_timeout_secs))
        .build()
        .map_err(|_| anyhow::anyhow!("daemon HTTP client initialization failed; verify system TLS configuration and re-run code-diver doctor"))?;
    let concurrency = config.daemon.max_concurrency;
    let daemon = Arc::new(Daemon {
        config,
        paths,
        manifest,
        client,
        workers: [Mutex::new(Worker::new()), Mutex::new(Worker::new())],
        permits: [Semaphore::new(concurrency), Semaphore::new(concurrency)],
        log: Mutex::new(()),
    });
    let mut tasks = tokio::task::JoinSet::new();
    let mut tick = tokio::time::interval(Duration::from_millis(250));
    let shutdown = shutdown_signal();
    tokio::pin!(shutdown);
    loop {
        tokio::select! {
            _ = &mut shutdown => break,
            result = listener.accept() => {
                let (stream, peer) = result.map_err(|cause| anyhow::anyhow!("daemon accept failed: {cause}; check file descriptor limits and restart the user service"))?;
                if peer.ip().is_loopback() {
                    if tasks.len() < 256 { tasks.spawn(connection(stream,daemon.clone(),port)); }
                    else { let _ = tokio::time::timeout(Duration::from_millis(100),send_reply(stream,error(503,"daemon_overloaded"))).await; }
                }
            }
            _ = tasks.join_next(), if !tasks.is_empty() => {},
            _ = tick.tick() => {
                daemon.reap_idle().await;
            }
        }
    }
    tasks.abort_all();
    while tasks.join_next().await.is_some() {}
    for worker in &daemon.workers {
        worker.lock().await.stop().await;
    }
    Ok(())
}

async fn shutdown_signal() {
    #[cfg(unix)]
    {
        if let Ok(mut signal) =
            tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
        {
            tokio::select! { _ = signal.recv() => {}, _ = tokio::signal::ctrl_c() => {} }
            return;
        }
    }
    let _ = tokio::signal::ctrl_c().await;
}

#[cfg(test)]
#[path = "../tests/daemon_cases/mod.rs"]
mod tests;

#[cfg(test)]
mod m5c_tests {
    use super::*;

    #[test]
    fn diagnostics_preserve_protocol_codes_and_supply_safe_repairs() {
        for (code, action) in [
            ("model_missing_or_invalid", "setup"),
            ("child_launch_failed", "--llama-server"),
            ("backend_invalid_json", "doctor"),
            ("context length exceeded", "Shorten"),
            ("forbidden_host", "loopback"),
            ("invalid_body_length", "Content-Length"),
        ] {
            let reply = error(503, code);
            assert_eq!(reply.1["error"]["type"], code);
            assert_eq!(reply.1["error"]["message"], code);
            assert!(reply.1["error"]["fix"].as_str().unwrap().contains(action));
        }
    }

    #[test]
    fn m5c_production_manifest_matches_daemon_flags() {
        let config = RuntimeConfig::default();
        let defaults = crate::runtime_config::reranker_serving_defaults();
        let args = child_args(&config, 1, 9000, "model.gguf".into());
        for (flag, value) in [
            ("--ctx-size", defaults.ctx),
            ("--batch-size", defaults.batch),
            ("--ubatch-size", defaults.ubatch),
        ] {
            assert!(
                args.windows(2)
                    .any(|pair| pair[0] == flag && pair[1] == value.to_string().as_str())
            );
        }
        assert!(!args.iter().any(|arg| arg == "--parallel"));
    }
}
