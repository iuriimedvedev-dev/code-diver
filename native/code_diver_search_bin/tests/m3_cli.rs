use serde_json::{Value, json};
use std::io::{Read, Write};
use std::process::Command;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

#[derive(Default)]
struct State {
    size: Option<usize>,
    points: Vec<Value>,
    requests: Vec<(String, String, Value)>,
    fail_next: Option<u16>,
    delay_ms: u64,
    context_limit: Option<usize>,
}

struct Mock {
    url: String,
    state: Arc<Mutex<State>>,
    stop: Arc<AtomicBool>,
    thread: Option<std::thread::JoinHandle<()>>,
}

impl Mock {
    fn start() -> Self {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let url = format!("http://{}", listener.local_addr().unwrap());
        listener.set_nonblocking(true).unwrap();
        let state = Arc::new(Mutex::new(State::default()));
        let stop = Arc::new(AtomicBool::new(false));
        let shared = state.clone();
        let stopping = stop.clone();
        let thread = std::thread::spawn(move || {
            let mut handlers = Vec::new();
            while !stopping.load(Ordering::Relaxed) {
                let Ok((mut stream, _)) = listener.accept() else {
                    std::thread::sleep(std::time::Duration::from_millis(2));
                    continue;
                };
                let shared = shared.clone();
                handlers.push(std::thread::spawn(move || {
                // macOS inherits O_NONBLOCK from the listener on accepted sockets.
                stream.set_nonblocking(false).unwrap();
                stream
                    .set_read_timeout(Some(std::time::Duration::from_secs(5)))
                    .unwrap();
                stream.set_write_timeout(Some(std::time::Duration::from_secs(5))).unwrap();
                let mut bytes = Vec::new();
                let mut buffer = [0; 4096];
                let (end, length) = loop {
                    let Ok(n) = stream.read(&mut buffer) else { return; };
                    if n == 0 {
                        return;
                    }
                    bytes.extend_from_slice(&buffer[..n]);
                    if let Some(end) = bytes.windows(4).position(|w| w == b"\r\n\r\n") {
                        let head = String::from_utf8_lossy(&bytes[..end]).to_lowercase();
                        let length = head
                            .lines()
                            .find_map(|l| l.strip_prefix("content-length:"))
                            .and_then(|n| n.trim().parse::<usize>().ok())
                            .unwrap_or(0);
                        break (end + 4, length);
                    }
                };
                while bytes.len() < end + length {
                    let Ok(n) = stream.read(&mut buffer) else { return; };
                    if n == 0 {
                        return;
                    }
                    bytes.extend_from_slice(&buffer[..n]);
                }
                let head = String::from_utf8_lossy(&bytes[..end]).to_string();
                let first = head.lines().next().unwrap().to_string();
                let body: Value =
                    serde_json::from_slice(&bytes[end..end + length]).unwrap_or(Value::Null);
                let mut state = shared.lock().unwrap();
                state.requests.push((first.clone(), head, body.clone()));
                let (status, response) = if let Some(status) = state.fail_next.take() {
                    (status, json!({"error": "DO-NOT-ECHO-secret"}))
                } else if first.starts_with("GET ") {
                    if let Some(size) = state.size {
                        (
                            200,
                            json!({"result": {"config": {"params": {"vectors": {"size": size}}}}}),
                        )
                    } else {
                        (404, json!({}))
                    }
                } else if first.contains("/embeddings ") {
                    let inputs = body["input"].as_array().cloned().unwrap_or_else(|| vec![body["input"].clone()]);
                    if state.context_limit.is_some_and(|limit| inputs.iter().any(|text| text.as_str().unwrap().chars().count() > limit)) {
                        let response = json!({"error": {"message": "maximum context length exceeded DO-NOT-ECHO-secret"}}).to_string();
                        write!(stream, "HTTP/1.1 400 Bad Request\r\ncontent-type: application/json\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{}", response.len(), response).unwrap();
                        return;
                    }
                    let data: Vec<_> = inputs
                        .iter()
                        .enumerate()
                        .map(|(i, _)| json!({"index": i, "embedding": [1., 2., 3., 4.]}))
                        .collect();
                    (200, json!({"data": data}))
                } else if first.contains("/points/search ") {
                    (200, json!({"result": []}))
                } else if first.contains("/rerank ") {
                    let results: Vec<_> = body["documents"].as_array().unwrap().iter().enumerate().map(|(index, _)| json!({"index": index, "relevance_score": 0.8})).collect();
                    (200, json!({"results": results}))
                } else if first.contains("/scroll ") {
                    (
                        200,
                        json!({"result": {"points": state.points, "next_page_offset": null}}),
                    )
                } else if first.contains("/delete?") {
                    let ids = body["points"].as_array().unwrap();
                    state.points.retain(|p| !ids.contains(&p["id"]));
                    (200, json!({"result": {"status": "completed"}}))
                } else if first.contains("/points?") {
                    for point in body["points"].as_array().unwrap() {
                        state.points.retain(|p| p["id"] != point["id"]);
                        state.points.push(point.clone());
                    }
                    (200, json!({"result": {"status": "completed"}}))
                } else {
                    state.size = body["vectors"]["size"].as_u64().map(|n| n as usize);
                    assert_eq!(body["vectors"]["distance"], "Cosine");
                    (200, json!({"result": true}))
                };
                let delay = state.delay_ms;
                drop(state);
                std::thread::sleep(std::time::Duration::from_millis(delay));
                let body = response.to_string();
                let _ = write!(stream, "HTTP/1.1 {status} X\r\ncontent-type: application/json\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{body}", body.len());
                }));
            }
            for handler in handlers {
                handler.join().unwrap();
            }
        });
        Self {
            url,
            state,
            stop,
            thread: Some(thread),
        }
    }

    fn run(&self, root: &std::path::Path, flags: &[&str]) -> std::process::Output {
        Command::new(env!("CARGO_BIN_EXE_code-diver"))
            .args(["index", "--root"])
            .arg(root)
            .args([
                "--collection",
                "zz_synthetic",
                "--qdrant-url",
                &self.url,
                "--embedding-url",
                &format!("{}/embeddings", self.url),
                "--qdrant-api-key",
                "q-secret",
                "--embedding-api-key",
                "e-secret",
            ])
            .args(flags)
            .args(if flags.contains(&"--batch-size") {
                vec![]
            } else {
                vec!["--batch-size", "2"]
            })
            .output()
            .unwrap()
    }
}

impl Drop for Mock {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        self.thread.take().unwrap().join().unwrap();
    }
}

fn success(output: std::process::Output) -> String {
    let stderr = String::from_utf8_lossy(&output.stderr).into_owned();
    assert!(output.status.success(), "{stderr}");
    assert!(!stderr.contains("q-secret") && !stderr.contains("e-secret"));
    stderr
}

#[test]
fn mock_keeps_accepted_connection_alive_until_headers_arrive() {
    let server = Mock::start();
    let mut stream =
        std::net::TcpStream::connect(server.url.strip_prefix("http://").unwrap()).unwrap();
    stream
        .set_read_timeout(Some(std::time::Duration::from_secs(2)))
        .unwrap();
    std::thread::sleep(std::time::Duration::from_millis(50));
    stream.write_all(b"GET /collections/zz_synthetic HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n").unwrap();
    let mut response = String::new();
    stream.read_to_string(&mut response).unwrap();
    assert!(response.starts_with("HTTP/1.1 404"), "{response}");
    assert_eq!(server.state.lock().unwrap().requests.len(), 1);
}

#[test]
fn context_overflow_splits_batch_and_shrinks_with_bounded_retries() {
    let server = Mock::start();
    server.state.lock().unwrap().context_limit = Some(80);
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(
        dir.path().join("a.md"),
        format!("# Alpha\n{}", "x".repeat(200)),
    )
    .unwrap();
    success(server.run(dir.path(), &["--apply", "--max-input-chars", "256"]));
    let state = server.state.lock().unwrap();
    assert_eq!(state.points.len(), 2);
    let requests: Vec<_> = state
        .requests
        .iter()
        .filter(|(first, _, _)| first.contains("/embeddings "))
        .collect();
    assert!(requests.len() > 1 && requests.len() <= 7);
    assert!(
        requests
            .iter()
            .any(|(_, _, body)| body["input"].as_array().unwrap().len() == 1)
    );
}

#[test]
fn context_overflow_exhaustion_does_not_upsert_or_echo_body() {
    let server = Mock::start();
    server.state.lock().unwrap().context_limit = Some(0);
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(dir.path().join("a.md"), "# Alpha\nText").unwrap();
    let output = server.run(dir.path(), &["--apply"]);
    assert!(!output.status.success());
    assert!(!String::from_utf8_lossy(&output.stderr).contains("DO-NOT-ECHO-secret"));
    let state = server.state.lock().unwrap();
    assert!(state.points.is_empty());
    assert_eq!(
        state
            .requests
            .iter()
            .filter(|(first, _, _)| first.contains("/embeddings "))
            .count(),
        4
    );
}

#[test]
fn search_shared_config_env_cli_model_prefix_and_isolated_auth() {
    let server = Mock::start();
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(dir.path().join("a.md"), "# Alpha\nSearch text").unwrap();
    success(server.run(dir.path(), &["--apply"]));
    server.state.lock().unwrap().requests.clear();
    let config = dir.path().join("services.toml");
    std::fs::write(&config, format!("catalog = '.code-diver/rust_catalog.jsonl'\ngraph_path = '.code-diver/rust_graph.jsonl'\n[storage.qdrant]\nurl = '{}'\ncollection = 'zz_synthetic'\napi_key = 'q-secret'\n[embedding]\nurl = '{}/embeddings'\nmodel = 'config-model'\nquery_prefix = 'query: '\napi_key = 'e-secret'\n", server.url, server.url)).unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_code-diver"))
        .args(["search", "--config"])
        .arg(&config)
        .args([
            "--query",
            "Alpha",
            "--ce-url",
            &format!("{}/rerank", server.url),
            "--embedding-model",
            "cli-model",
        ])
        .env("CODE_DIVER_EMBEDDING_MODEL", "env-model")
        .env("CODE_DIVER_EMBEDDING_QUERY_PREFIX", "env-query: ")
        .output()
        .unwrap();
    success(output);
    let state = server.state.lock().unwrap();
    let (_, headers, body) = state
        .requests
        .iter()
        .find(|(first, _, _)| first.contains("/embeddings "))
        .unwrap();
    assert_eq!(body["model"], "cli-model");
    assert_eq!(body["input"], "env-query: Alpha");
    assert!(headers.contains("Bearer e-secret") && !headers.contains("q-secret"));
    let (_, headers, _) = state
        .requests
        .iter()
        .find(|(first, _, _)| first.contains("/collections/zz_synthetic/points/search "))
        .unwrap();
    assert!(headers.contains("q-secret") && !headers.contains("e-secret"));
    for (_, headers, _) in state
        .requests
        .iter()
        .filter(|(first, _, _)| first.contains("/rerank "))
    {
        assert!(!headers.contains("q-secret") && !headers.contains("e-secret"));
    }
    drop(state);
    server.state.lock().unwrap().requests.clear();
    success(
        Command::new(env!("CARGO_BIN_EXE_code-diver"))
            .args([
                "search",
                "--query",
                "Alpha",
                "--ce-url",
                &format!("{}/rerank", server.url),
            ])
            .env("CODE_DIVER_CONFIG", &config)
            .output()
            .unwrap(),
    );
    let state = server.state.lock().unwrap();
    let (_, _, body) = state
        .requests
        .iter()
        .find(|(first, _, _)| first.contains("/embeddings "))
        .unwrap();
    assert_eq!(body["model"], "config-model");
    assert_eq!(body["input"], "query: Alpha");
}

#[test]
fn audit_reports_measurable_estimated_candidates_without_exact_parity_claim() {
    let server = Mock::start();
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(
        dir.path().join("a.md"),
        format!("# Alpha\n{}", "x".repeat(200)),
    )
    .unwrap();
    let stderr = success(server.run(
        dir.path(),
        &[
            "--audit-embed-text",
            "--max-input-tokens",
            "16",
            "--token-safety-margin",
            "0",
        ],
    ));
    assert!(stderr.contains("estimated_threshold_candidates=2"));
    assert!(stderr.contains("would_differ_from_python=unknown"));
    assert!(stderr.contains("NOT exact token counts"));
    assert_eq!(server.state.lock().unwrap().requests.len(), 1);
}

#[test]
fn full_incremental_dry_run_edit_and_prune_with_auth_and_retry() {
    let server = Mock::start();
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(dir.path().join("a.md"), "# Alpha\nOriginal").unwrap();
    std::fs::write(dir.path().join("b.md"), "# Beta\nOriginal").unwrap();
    assert!(success(server.run(dir.path(), &[])).contains("added=4 changed=0 deleted=0"));
    assert_eq!(server.state.lock().unwrap().requests.len(), 1);
    server.state.lock().unwrap().fail_next = Some(503);
    success(server.run(dir.path(), &["--apply"]));
    {
        let state = server.state.lock().unwrap();
        assert_eq!(state.points.len(), 4);
        assert_eq!(state.size, Some(4));
        for (first, headers, body) in &state.requests {
            if first.contains("/embeddings ") {
                assert!(headers.contains("Bearer e-secret"));
                assert!(!headers.contains("q-secret"));
                assert_eq!(body["encoding_format"], "float");
                assert!(body["input"].as_array().unwrap().len() <= 2);
            } else {
                assert!(headers.contains("q-secret"));
                assert!(!headers.contains("e-secret"));
            }
        }
        for point in &state.points {
            assert_eq!(
                point["payload"]["root"],
                dir.path()
                    .canonicalize()
                    .unwrap()
                    .to_string_lossy()
                    .as_ref()
            );
            assert_eq!(point["payload"]["dimensions"], 4);
            assert_eq!(point["payload"]["item"]["metadata"], json!({}));
        }
    }
    server.state.lock().unwrap().requests.clear();
    let catalog = dir.path().join(".code-diver/rust_catalog.jsonl");
    let modified = std::fs::metadata(&catalog).unwrap().modified().unwrap();
    assert!(success(server.run(dir.path(), &["--apply"])).contains("added=0 changed=0 deleted=0"));
    assert_eq!(server.state.lock().unwrap().requests.len(), 2);
    assert_eq!(
        std::fs::metadata(catalog).unwrap().modified().unwrap(),
        modified
    );
    std::fs::write(dir.path().join("a.md"), "# Alpha Changed\nNew content").unwrap();
    assert!(success(server.run(dir.path(), &["--apply"])).contains("added=0 changed=2 deleted=0"));
    std::fs::remove_file(dir.path().join("b.md")).unwrap();
    assert!(success(server.run(dir.path(), &["--apply"])).contains("deleted=2"));
    assert_eq!(server.state.lock().unwrap().points.len(), 4);
    success(server.run(dir.path(), &["--apply", "--prune"]));
    assert_eq!(server.state.lock().unwrap().points.len(), 2);
    assert!(dir.path().join(".code-diver/rust_graph.jsonl").exists());
}

#[test]
fn profile_changes_require_explicit_migration() {
    let server = Mock::start();
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(dir.path().join("a.md"), "# Alpha").unwrap();
    success(server.run(dir.path(), &["--apply", "--embedding-dimensions", "4"]));
    for flags in [
        vec!["--embedding-model", "different-model"],
        vec!["--embedding-document-prefix", "different-prefix"],
        vec!["--max-input-chars", "100"],
        vec!["--max-input-tokens", "256"],
        vec!["--token-safety-margin", "64"],
    ] {
        server.state.lock().unwrap().requests.clear();
        let mut flags = flags;
        flags.extend(["--apply", "--embedding-dimensions", "4"]);
        let output = server.run(dir.path(), &flags);
        assert!(
            !output.status.success(),
            "profile change silently accepted: {flags:?}"
        );
        assert!(String::from_utf8_lossy(&output.stderr).contains("profile"));
        assert!(
            server
                .state
                .lock()
                .unwrap()
                .requests
                .iter()
                .all(|(first, _, _)| first.starts_with("GET ") || first.contains("/scroll "))
        );
    }
    let profile = dir
        .path()
        .join(".code-diver/rust_catalog.jsonl.embedding-profile.json");
    for field in ["model", "provider"] {
        server.state.lock().unwrap().points[0]["payload"][field] = json!("wrong-profile");
        let output = server.run(dir.path(), &["--apply", "--embedding-dimensions", "4"]);
        assert!(!output.status.success());
        assert!(String::from_utf8_lossy(&output.stderr).contains("profile"));
        let mut state = server.state.lock().unwrap();
        state.points[0]["payload"][field] = state.points[1]["payload"][field].clone();
    }
    std::fs::remove_file(profile).unwrap();
    let output = server.run(dir.path(), &["--apply"]);
    assert!(!output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("profile"));
}

#[test]
fn default_request_omits_optional_dimensions() {
    let server = Mock::start();
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(dir.path().join("a.md"), "# Alpha").unwrap();
    success(server.run(dir.path(), &["--apply", "--embedding-dimensions", "4"]));
    assert!(
        server
            .state
            .lock()
            .unwrap()
            .requests
            .iter()
            .filter(|(first, _, _)| first.contains("/embeddings "))
            .all(|(_, _, body)| body.get("dimensions").is_none())
    );
}

#[test]
fn dimension_and_4xx_errors_do_not_write_or_echo_response() {
    let server = Mock::start();
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(dir.path().join("a.md"), "# Alpha").unwrap();
    server.state.lock().unwrap().size = Some(8);
    let output = server.run(dir.path(), &["--apply"]);
    assert!(!output.status.success());
    assert!(
        String::from_utf8_lossy(&output.stderr).contains("dimension mismatch"),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(server.state.lock().unwrap().points.is_empty());
    server.state.lock().unwrap().requests.clear();
    server.state.lock().unwrap().fail_next = Some(401);
    let output = server.run(dir.path(), &["--apply"]);
    assert!(!output.status.success());
    assert!(!String::from_utf8_lossy(&output.stderr).contains("DO-NOT-ECHO"));
    assert_eq!(server.state.lock().unwrap().requests.len(), 1);
}

#[test]
fn timeout_is_bounded_and_large_batches_are_complete() {
    let server = Mock::start();
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(dir.path().join("a.md"), "# Alpha").unwrap();
    server.state.lock().unwrap().delay_ms = 500;
    let start = std::time::Instant::now();
    let output = server.run(dir.path(), &["--apply", "--timeout-ms", "100"]);
    assert!(!output.status.success());
    assert!(
        String::from_utf8_lossy(&output.stderr).contains("timed out"),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(start.elapsed() < std::time::Duration::from_secs(5));
    assert!(server.state.lock().unwrap().points.is_empty());
    server.state.lock().unwrap().delay_ms = 0;
    for i in 0..149 {
        std::fs::write(
            dir.path().join(format!("file{i}.md")),
            format!("# Heading {i}"),
        )
        .unwrap();
    }
    success(server.run(
        dir.path(),
        &["--apply", "--batch-size", "128", "--workers", "3"],
    ));
    let state = server.state.lock().unwrap();
    assert_eq!(state.points.len(), 300);
    let batches: Vec<_> = state
        .requests
        .iter()
        .filter(|(first, _, _)| first.contains("/points?"))
        .map(|(_, _, body)| body["points"].as_array().unwrap().len())
        .collect();
    assert_eq!(batches, vec![128, 128, 44]);
}

#[test]
fn apply_requires_explicit_collection_before_scanning() {
    let output = Command::new(env!("CARGO_BIN_EXE_code-diver"))
        .args(["index", "--apply", "--root", "/nonexistent-m3-root"])
        .output()
        .unwrap();
    assert!(!output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("--collection"));
}
