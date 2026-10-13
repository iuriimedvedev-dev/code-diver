//! `code-diver shim`: a stateless stdio MCP process that forwards requests to a `serve` daemon.
//!
//! MCP clients launch stdio servers; this lets them launch the shim as an ordinary one while the
//! catalog, graph and models stay loaded once in the long-lived `serve` process. The shim keeps no
//! session state: `initialize`, `ping` and notifications are answered locally (so a client can
//! always start), `tools/list` falls back to a built-in list while the daemon is away, and every
//! other request is forwarded over a fresh connection with retry, backoff and a deadline.
//!
//! The first version of the shim was written by Angkira against v0.4.5; it is ported here onto the
//! current MCP server with the hardening listed in the commit history.

use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Duration, Instant};

use serde_json::{Value, json};
use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};
use tokio::net::UnixStream;
use tokio::sync::Semaphore;
use tokio::task::JoinSet;

use crate::mcp::{initialize_result, record, tools};
use crate::serve::BUSY_CODE;

/// How long a request may keep trying to reach the daemon.
pub(crate) const SHIM_DEADLINE: Duration = Duration::from_secs(20);
/// `tools/list` must not stall a client's startup; after this the built-in list is served.
pub(crate) const SHIM_LIST_DEADLINE: Duration = Duration::from_secs(3);
/// How long the daemon may take to answer a request it accepted (a search can rerank slowly).
pub(crate) const SHIM_RESPONSE_TIMEOUT: Duration = Duration::from_secs(120);
/// Candidate limit advertised by the built-in tool list (the engine's default).
const FALLBACK_CANDIDATE_LIMIT: usize = 34;
const BACKOFF_START: Duration = Duration::from_millis(200);
const BACKOFF_MAX: Duration = Duration::from_secs(1);
const MAX_RESPONSE_BYTES: u64 = 32 * 1024 * 1024;
const MAX_IN_FLIGHT: usize = 64;
const UNREACHABLE_CODE: i64 = -32000;

#[derive(Clone)]
pub(crate) struct ShimConfig {
    pub socket: PathBuf,
    pub deadline: Duration,
    pub list_deadline: Duration,
    pub response_timeout: Duration,
}

impl ShimConfig {
    pub(crate) fn new(socket: PathBuf) -> Self {
        Self {
            socket,
            deadline: SHIM_DEADLINE,
            list_deadline: SHIM_LIST_DEADLINE,
            response_timeout: SHIM_RESPONSE_TIMEOUT,
        }
    }
}

/// Why one forwarding attempt failed, and whether trying again can help.
#[derive(Debug, PartialEq, Eq)]
enum Attempt {
    /// Nothing or only part of the exchange happened; the same request may be sent again.
    Retry(String),
    /// The daemon took the request and did not answer in time, or answered something unusable.
    Fatal(String),
}

pub(crate) fn next_backoff(delay: Duration) -> Duration {
    (delay * 3 / 2).min(BACKOFF_MAX)
}

fn retry(what: &'static str) -> impl FnOnce(std::io::Error) -> Attempt {
    move |e| Attempt::Retry(format!("{what}: {e}"))
}

async fn forward_once(
    socket: &Path,
    line: &str,
    response_timeout: Duration,
) -> Result<String, Attempt> {
    let stream = UnixStream::connect(socket)
        .await
        .map_err(retry("connect"))?;
    let (reader, mut writer) = stream.into_split();
    writer
        .write_all(line.as_bytes())
        .await
        .map_err(retry("write"))?;
    writer.write_all(b"\n").await.map_err(retry("write"))?;
    writer.flush().await.map_err(retry("flush"))?;
    let mut reader = BufReader::new(reader.take(MAX_RESPONSE_BYTES + 1));
    let mut response = Vec::new();
    let read = tokio::time::timeout(response_timeout, reader.read_until(b'\n', &mut response))
        .await
        .map_err(|_| {
            Attempt::Fatal(format!(
                "the daemon accepted the request but did not answer within {}s",
                response_timeout.as_secs()
            ))
        })?
        .map_err(retry("read"))?;
    if read == 0 {
        return Err(Attempt::Retry(
            "the daemon closed the connection without a response".into(),
        ));
    }
    if response.last() != Some(&b'\n') {
        return Err(if response.len() as u64 > MAX_RESPONSE_BYTES {
            Attempt::Fatal(format!(
                "the daemon's response exceeds {MAX_RESPONSE_BYTES} bytes"
            ))
        } else {
            Attempt::Retry("the daemon closed the connection mid-response".into())
        });
    }
    let text = String::from_utf8(response)
        .map_err(|_| Attempt::Fatal("the daemon sent a response that is not UTF-8".into()))?;
    let text = text.trim_end().to_string();
    let busy = serde_json::from_str::<Value>(&text)
        .ok()
        .is_some_and(|v| v["error"]["code"] == BUSY_CODE);
    if busy {
        return Err(Attempt::Retry(
            "the daemon is at its connection limit".into(),
        ));
    }
    Ok(text)
}

/// Forward one request line, retrying with backoff until `deadline`. Retrying is safe because
/// every tool is read-only; a request the daemon already accepted is never sent twice after a
/// timeout, only after the connection broke before a response arrived.
pub(crate) async fn forward(
    socket: &Path,
    line: &str,
    deadline: Duration,
    response_timeout: Duration,
) -> Result<String, String> {
    let start = Instant::now();
    let mut delay = BACKOFF_START;
    loop {
        let reason = match forward_once(socket, line, response_timeout).await {
            Ok(response) => return Ok(response),
            Err(Attempt::Fatal(reason)) => return Err(reason),
            Err(Attempt::Retry(reason)) => reason,
        };
        if start.elapsed() + delay > deadline {
            return Err(reason);
        }
        tokio::time::sleep(delay).await;
        delay = next_backoff(delay);
    }
}

fn rpc_result(id: Value, result: Value) -> String {
    json!({"jsonrpc": "2.0", "id": id, "result": result}).to_string()
}

fn rpc_error(id: Value, code: i64, message: &str) -> String {
    crate::mcp::error(id, code, message).to_string()
}

fn unreachable_message(cfg: &ShimConfig, reason: &str) -> String {
    format!(
        "code-diver serve is unreachable at {} after {}s ({reason}). Start it with: \
         code-diver serve --listen unix:{}",
        cfg.socket.display(),
        cfg.deadline.as_secs(),
        cfg.socket.display()
    )
}

/// Handle one stdin line in the shim; `None` means nothing is sent back.
pub(crate) async fn handle_shim_line(cfg: &ShimConfig, line: &str) -> Option<String> {
    let request: Value = match serde_json::from_str(line) {
        Ok(value) => value,
        Err(_) => {
            return Some(rpc_error(
                Value::Null,
                -32700,
                "Invalid JSON or request exceeds 1 MiB",
            ));
        }
    };
    let method = request.get("method").and_then(Value::as_str);
    if !request.is_object() || request["jsonrpc"] != "2.0" || method.is_none() {
        let id = request.get("id").cloned().unwrap_or(Value::Null);
        return Some(rpc_error(id, -32600, "Invalid JSON-RPC request"));
    }
    // Notifications get no response and carry nothing the stateless daemon needs.
    let id = request.get("id").cloned()?;
    let params = request.get("params").cloned().unwrap_or_else(|| json!({}));
    match method? {
        "initialize" => Some(match initialize_result(&params) {
            Ok(result) => rpc_result(id, result),
            Err((code, message)) => rpc_error(id, code, message),
        }),
        "ping" => Some(rpc_result(id, json!({}))),
        "tools/list" => {
            match forward(&cfg.socket, line, cfg.list_deadline, cfg.response_timeout).await {
                Ok(response) => Some(response),
                Err(_) => Some(rpc_result(id, tools(FALLBACK_CANDIDATE_LIMIT))),
            }
        }
        method => {
            match forward(&cfg.socket, line, cfg.deadline, cfg.response_timeout).await {
                Ok(response) => Some(response),
                Err(reason) => {
                    let message = unreachable_message(cfg, &reason);
                    // A failed tool call is a tool result the agent can read, as in `mcp`.
                    Some(if method == "tools/call" {
                        rpc_result(
                            id,
                            json!({"content":[{"type":"text","text":message}],"isError":true}),
                        )
                    } else {
                        rpc_error(id, UNREACHABLE_CODE, &message)
                    })
                }
            }
        }
    }
}

/// Stateless stdio shim: stays up while stdin is open, even if the daemon is not running.
pub(crate) async fn run_shim(cfg: ShimConfig) -> Result<(), String> {
    let stdout = Arc::new(tokio::sync::Mutex::new(tokio::io::stdout()));
    let mut reader = BufReader::new(tokio::io::stdin());
    let in_flight = Arc::new(Semaphore::new(MAX_IN_FLIGHT));
    let mut tasks = JoinSet::new();
    while let Some(bytes) = record(&mut reader, None).await? {
        let permit = in_flight
            .clone()
            .acquire_owned()
            .await
            .map_err(|_| "shim request limiter closed".to_string())?;
        let (cfg, stdout) = (cfg.clone(), stdout.clone());
        tasks.spawn(async move {
            let _permit = permit;
            let line = String::from_utf8_lossy(&bytes);
            let line = line.trim();
            // A blank line is skipped; an oversized one arrives empty and gets a parse error.
            if line.is_empty() && !bytes.is_empty() {
                return;
            }
            if let Some(response) = handle_shim_line(&cfg, line).await {
                let mut out = stdout.lock().await;
                let _ = out.write_all(response.as_bytes()).await;
                let _ = out.write_all(b"\n").await;
                let _ = out.flush().await;
            }
        });
        while tasks.try_join_next().is_some() {}
    }
    while tasks.join_next().await.is_some() {}
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::net::UnixListener;

    fn unreachable_config(dir: &Path) -> ShimConfig {
        ShimConfig {
            socket: dir.join("none.sock"),
            deadline: Duration::from_millis(700),
            list_deadline: Duration::from_millis(300),
            response_timeout: Duration::from_millis(300),
        }
    }

    fn parse(response: Option<String>) -> Value {
        serde_json::from_str(&response.expect("a response")).unwrap()
    }

    #[test]
    fn backoff_grows_by_half_and_is_capped() {
        let mut delay = BACKOFF_START;
        let mut seen = vec![delay.as_millis()];
        for _ in 0..8 {
            delay = next_backoff(delay);
            seen.push(delay.as_millis());
        }
        assert_eq!(seen[..4], [200, 300, 450, 675]);
        assert!(seen.windows(2).all(|pair| pair[0] <= pair[1]));
        assert_eq!(*seen.last().unwrap(), BACKOFF_MAX.as_millis());
    }

    #[tokio::test]
    async fn local_answers_never_touch_the_daemon() {
        let dir = tempfile::tempdir().unwrap();
        let cfg = unreachable_config(dir.path());
        let start = Instant::now();
        let init = parse(
            handle_shim_line(
                &cfg,
                r#"{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}"#,
            )
            .await,
        );
        assert_eq!(init["result"]["protocolVersion"], "2024-11-05");
        assert_eq!(init["result"]["serverInfo"]["name"], "code-diver");
        assert_eq!(
            init["result"]["serverInfo"]["version"],
            env!("CARGO_PKG_VERSION")
        );
        let bad = parse(
            handle_shim_line(&cfg, r#"{"jsonrpc":"2.0","id":2,"method":"initialize"}"#).await,
        );
        assert_eq!(bad["error"]["code"], -32602);
        let ping =
            parse(handle_shim_line(&cfg, r#"{"jsonrpc":"2.0","id":3,"method":"ping"}"#).await);
        assert_eq!(ping["result"], json!({}));
        assert_eq!(ping["id"], 3);
        assert!(
            handle_shim_line(
                &cfg,
                r#"{"jsonrpc":"2.0","method":"notifications/initialized"}"#
            )
            .await
            .is_none()
        );
        assert!(start.elapsed() < Duration::from_millis(250));
    }

    #[tokio::test]
    async fn malformed_lines_get_standard_errors() {
        let dir = tempfile::tempdir().unwrap();
        let cfg = unreachable_config(dir.path());
        let parse_error = parse(handle_shim_line(&cfg, "{not json").await);
        assert_eq!(parse_error["error"]["code"], -32700);
        assert_eq!(parse_error["id"], Value::Null);
        let invalid = parse(handle_shim_line(&cfg, r#"{"jsonrpc":"2.0","id":7}"#).await);
        assert_eq!(invalid["error"]["code"], -32600);
        assert_eq!(invalid["id"], 7);
    }

    #[tokio::test]
    async fn tools_list_falls_back_and_calls_report_how_to_start_the_daemon() {
        let dir = tempfile::tempdir().unwrap();
        let cfg = unreachable_config(dir.path());
        let list = parse(
            handle_shim_line(&cfg, r#"{"jsonrpc":"2.0","id":2,"method":"tools/list"}"#).await,
        );
        let names: Vec<&str> = list["result"]["tools"]
            .as_array()
            .unwrap()
            .iter()
            .map(|tool| tool["name"].as_str().unwrap())
            .collect();
        assert!(names.contains(&"code_diver_search") && names.contains(&"code_diver_read"));

        let start = Instant::now();
        let call = parse(
            handle_shim_line(
                &cfg,
                r#"{"jsonrpc":"2.0","id":9,"method":"tools/call","params":{"name":"code_diver_search","arguments":{"query":"x"}}}"#,
            )
            .await,
        );
        assert!(start.elapsed() < Duration::from_secs(3));
        assert_eq!(call["id"], 9);
        assert_eq!(call["result"]["isError"], true);
        let text = call["result"]["content"][0]["text"].as_str().unwrap();
        assert!(text.contains("code-diver serve --listen unix:"), "{text}");
        assert!(text.contains("none.sock"), "{text}");

        let health =
            parse(handle_shim_line(&cfg, r#"{"jsonrpc":"2.0","id":4,"method":"health"}"#).await);
        assert_eq!(health["error"]["code"], UNREACHABLE_CODE);
    }

    /// Daemon double: each accepted connection is handled by the next scripted behavior.
    async fn scripted_daemon(
        socket: &Path,
        script: Vec<&'static str>,
    ) -> tokio::task::JoinHandle<usize> {
        let listener = UnixListener::bind(socket).unwrap();
        tokio::spawn(async move {
            let mut served = 0;
            for step in script {
                let (stream, _) = listener.accept().await.unwrap();
                served += 1;
                let (reader, mut writer) = stream.into_split();
                let mut line = String::new();
                BufReader::new(reader).read_line(&mut line).await.unwrap();
                match step {
                    "drop" => {}
                    "busy" => {
                        let busy = crate::mcp::error(Value::Null, BUSY_CODE, "busy").to_string();
                        writer
                            .write_all(format!("{busy}\n").as_bytes())
                            .await
                            .unwrap();
                    }
                    "hang" => {
                        tokio::time::sleep(Duration::from_secs(30)).await;
                    }
                    _ => {
                        let id: Value = serde_json::from_str::<Value>(&line).unwrap()["id"].clone();
                        writer
                            .write_all(
                                format!("{}\n", rpc_result(id, json!({"ok": true}))).as_bytes(),
                            )
                            .await
                            .unwrap();
                    }
                }
            }
            served
        })
    }

    #[tokio::test]
    async fn dropped_and_busy_connections_are_retried_until_an_answer_arrives() {
        let dir = tempfile::tempdir().unwrap();
        let mut cfg = unreachable_config(dir.path());
        cfg.deadline = Duration::from_secs(10);
        let daemon = scripted_daemon(&cfg.socket, vec!["drop", "busy", "answer"]).await;
        let response = parse(
            handle_shim_line(
                &cfg,
                r#"{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{}}"#,
            )
            .await,
        );
        assert_eq!(response["result"]["ok"], true);
        assert_eq!(response["id"], 5);
        assert_eq!(daemon.await.unwrap(), 3);
    }

    #[tokio::test]
    async fn a_daemon_that_accepts_but_never_answers_is_not_asked_twice() {
        let dir = tempfile::tempdir().unwrap();
        let mut cfg = unreachable_config(dir.path());
        cfg.deadline = Duration::from_secs(10);
        cfg.response_timeout = Duration::from_millis(300);
        let daemon = scripted_daemon(&cfg.socket, vec!["hang"]).await;
        let start = Instant::now();
        let response = parse(
            handle_shim_line(
                &cfg,
                r#"{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{}}"#,
            )
            .await,
        );
        assert!(
            start.elapsed() < Duration::from_secs(5),
            "bounded by the response timeout"
        );
        let text = response["result"]["content"][0]["text"].as_str().unwrap();
        assert!(text.contains("did not answer within"), "{text}");
        daemon.abort();
    }
}
