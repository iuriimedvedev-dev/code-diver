#![cfg(unix)]

use serde_json::{Value, json};
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::time::{Duration, Instant};
use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, ChildStdin, ChildStdout, Command};

const BIN: &str = env!("CARGO_BIN_EXE_code-diver");

fn catalog_rows(ids: &[&str]) -> String {
    ids.iter()
        .map(|id| {
            json!({"id": id, "path": format!("{id}.rs"), "name": id, "content": "fn main() {}\n"})
                .to_string()
                + "\n"
        })
        .collect()
}

/// Replace the file the way an indexer would: write aside, rename over (new inode).
fn replace_file(path: &Path, body: &str) {
    let staged = path.with_extension("next");
    std::fs::write(&staged, body).unwrap();
    std::fs::rename(&staged, path).unwrap();
}

/// Minimal embedding, vector store and reranker so `code_diver_search` can run end to end.
async fn mock_services() -> String {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}", listener.local_addr().unwrap());
    tokio::spawn(async move {
        loop {
            let Ok((mut socket, _)) = listener.accept().await else {
                return;
            };
            tokio::spawn(async move {
                let mut bytes = Vec::new();
                let headers = loop {
                    let mut buffer = [0; 4096];
                    let n = socket.read(&mut buffer).await.unwrap_or(0);
                    if n == 0 {
                        return;
                    }
                    bytes.extend_from_slice(&buffer[..n]);
                    if let Some(end) = bytes.windows(4).position(|w| w == b"\r\n\r\n") {
                        let headers = String::from_utf8_lossy(&bytes[..end]).to_string();
                        let size: usize = headers
                            .lines()
                            .find_map(|l| {
                                l.to_lowercase()
                                    .strip_prefix("content-length:")
                                    .and_then(|v| v.trim().parse().ok())
                            })
                            .unwrap_or(0);
                        if bytes.len() >= end + 4 + size {
                            break headers;
                        }
                    }
                };
                let payload = if headers.starts_with("POST /embed ") {
                    json!({"data":[{"embedding":[1.0,0.0]}]})
                } else if headers.contains("/points/search ") {
                    json!({"result":[{"id":"hello","score":0.9,"payload":{"item_id":"hello","path":"hello.rs"}}]})
                } else {
                    json!({"results":[{"index":0,"relevance_score":0.8}]})
                }
                .to_string();
                let _ = socket
                    .write_all(
                        format!(
                            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{payload}",
                            payload.len()
                        )
                        .as_bytes(),
                    )
                    .await;
            });
        }
    });
    url
}

struct Shim {
    child: Child,
    stdin: ChildStdin,
    stdout: BufReader<ChildStdout>,
}

impl Shim {
    fn start(socket: &Path) -> Self {
        let mut child = Command::new(BIN)
            .args(["shim", "--socket", socket.to_str().unwrap()])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .kill_on_drop(true)
            .spawn()
            .unwrap();
        Self {
            stdin: child.stdin.take().unwrap(),
            stdout: BufReader::new(child.stdout.take().unwrap()),
            child,
        }
    }

    async fn send(&mut self, value: Value) {
        self.stdin
            .write_all(format!("{value}\n").as_bytes())
            .await
            .unwrap();
        self.stdin.flush().await.unwrap();
    }

    async fn receive(&mut self) -> Value {
        let mut line = String::new();
        let n = tokio::time::timeout(Duration::from_secs(30), self.stdout.read_line(&mut line))
            .await
            .expect("shim answered in time")
            .unwrap();
        assert!(n > 0, "shim exited");
        serde_json::from_str(&line).unwrap()
    }

    async fn request(&mut self, id: i64, method: &str, params: Value) -> Value {
        self.send(json!({"jsonrpc":"2.0","id":id,"method":method,"params":params}))
            .await;
        let response = self.receive().await;
        assert_eq!(response["id"], id, "{response}");
        response
    }

    async fn health(&mut self) -> Value {
        let response = self.request(900, "health", json!({})).await;
        response["result"].clone()
    }

    async fn wait_health(&mut self, what: &str, done: impl Fn(&Value) -> bool) -> Value {
        let deadline = Instant::now() + Duration::from_secs(20);
        loop {
            let health = self.health().await;
            if done(&health) {
                return health;
            }
            assert!(
                Instant::now() < deadline,
                "timed out waiting for {what}: {health}"
            );
            tokio::time::sleep(Duration::from_millis(200)).await;
        }
    }
}

fn signal(child: &Child, signal: i32) {
    let pid = child.id().expect("running child") as i32;
    // SAFETY: plain kill(2) on a child process this test spawned.
    assert_eq!(unsafe { libc::kill(pid, signal) }, 0);
}

async fn wait_for_socket(path: &Path, serve: &mut Child) {
    let deadline = Instant::now() + Duration::from_secs(30);
    while !path.exists() {
        assert!(serve.try_wait().unwrap().is_none(), "serve exited early");
        assert!(Instant::now() < deadline, "socket never appeared");
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
}

fn serve_command(root: &Path, socket: &Path, services: &str) -> Command {
    let mut command = Command::new(BIN);
    command
        .args(["serve", "--root", root.to_str().unwrap()])
        .args(["--catalog", root.join("catalog.jsonl").to_str().unwrap()])
        .args(["--graph", root.join("graph.jsonl").to_str().unwrap()])
        .args(["--listen", &format!("unix:{}", socket.display())])
        .args(["--embedding-url", &format!("{services}/embed")])
        .args(["--qdrant-url", services])
        .args(["--ce-url", &format!("{services}/v1/rerank")])
        .arg("--no-require-rerank")
        .args(["--reload-poll-secs", "1", "--reload-debounce-secs", "1"])
        .kill_on_drop(true);
    command
}

fn socket_in(dir: &Path) -> PathBuf {
    dir.join("serve.sock")
}

#[tokio::test]
async fn serve_answers_shim_reloads_and_shuts_down_cleanly() {
    let root = tempfile::tempdir().unwrap();
    let catalog = root.path().join("catalog.jsonl");
    std::fs::write(&catalog, catalog_rows(&["hello"])).unwrap();
    std::fs::write(root.path().join("graph.jsonl"), "").unwrap();
    std::fs::write(root.path().join("hello.rs"), "fn main() {}\n").unwrap();
    let services = mock_services().await;
    let socket = socket_in(root.path());

    let mut serve = serve_command(root.path(), &socket, &services)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .unwrap();
    wait_for_socket(&socket, &mut serve).await;
    assert_eq!(
        std::fs::metadata(&socket).unwrap().permissions().mode() & 0o777,
        0o600,
        "socket must be private to the user"
    );

    // A second daemon on the same live socket must refuse to start and leave the first alone.
    let second = serve_command(root.path(), &socket, &services)
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
        .output()
        .await
        .unwrap();
    assert!(!second.status.success());
    let stderr = String::from_utf8_lossy(&second.stderr);
    assert!(stderr.contains("already serving"), "{stderr}");
    assert!(socket.exists());

    let mut shim = Shim::start(&socket);
    let init = shim
        .request(
            1,
            "initialize",
            json!({"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"t","version":"1"}}),
        )
        .await;
    assert_eq!(init["result"]["serverInfo"]["name"], "code-diver");
    shim.send(json!({"jsonrpc":"2.0","method":"notifications/initialized"}))
        .await;
    assert_eq!(
        shim.request(2, "ping", json!({})).await["result"],
        json!({})
    );

    let list = shim.request(3, "tools/list", json!({})).await;
    let tools = list["result"]["tools"].as_array().unwrap();
    let names: Vec<&str> = tools.iter().map(|t| t["name"].as_str().unwrap()).collect();
    for expected in ["code_diver_search", "code_diver_read", "code_diver_grep"] {
        assert!(names.contains(&expected), "{names:?}");
    }

    let health = shim.health().await;
    assert_eq!(health["items"], 1);
    assert_eq!(health["generation"], 1);
    assert_eq!(health["catalog_stale"], false);
    assert_eq!(health["pid"], serve.id().unwrap());
    assert!(health["last_reload_error"].is_null());

    let search = shim
        .request(
            4,
            "tools/call",
            json!({"name":"code_diver_search","arguments":{"query":"hello"}}),
        )
        .await;
    assert_eq!(search["result"]["isError"], false, "{search}");
    assert!(
        search["result"]["content"][0]["text"]
            .as_str()
            .unwrap()
            .contains("hello.rs")
    );
    let read = shim
        .request(
            5,
            "tools/call",
            json!({"name":"code_diver_read","arguments":{"file":"hello.rs"}}),
        )
        .await;
    assert!(
        read["result"]["content"][0]["text"]
            .as_str()
            .unwrap()
            .contains("fn main")
    );

    // SIGHUP picks up a replaced catalog.
    replace_file(&catalog, &catalog_rows(&["hello", "two"]));
    signal(&serve, libc::SIGHUP);
    let health = shim
        .wait_health("SIGHUP reload", |h| h["generation"] == 2)
        .await;
    assert_eq!(health["items"], 2);
    assert_eq!(health["reload_count"], 1);

    // A changed file is picked up by the watcher without any signal.
    replace_file(&catalog, &catalog_rows(&["hello", "two", "three"]));
    let health = shim
        .wait_health("watcher reload", |h| h["generation"] == 3)
        .await;
    assert_eq!(health["items"], 3);

    // A broken catalog keeps the previous generation serving and is reported, not retried.
    replace_file(&catalog, "this is not json\n");
    let failed = shim
        .wait_health("reload error", |h| !h["last_reload_error"].is_null())
        .await;
    assert_eq!(failed["generation"], 3);
    assert_eq!(failed["items"], 3);
    assert_eq!(failed["catalog_stale"], true);
    let message = failed["last_reload_error"].as_str().unwrap();
    assert!(message.contains("Still serving generation 3"), "{message}");
    let still = shim
        .request(
            6,
            "tools/call",
            json!({"name":"code_diver_search","arguments":{"query":"hello"}}),
        )
        .await;
    assert_eq!(still["result"]["isError"], false, "{still}");
    tokio::time::sleep(Duration::from_secs(4)).await;
    let later = shim.health().await;
    assert_eq!(
        later["last_reload_error_at"], failed["last_reload_error_at"],
        "the failed file state must not be retried while it is unchanged"
    );

    // Fixing the file recovers on its own.
    replace_file(&catalog, &catalog_rows(&["hello", "two", "three", "four"]));
    let health = shim.wait_health("recovery", |h| h["generation"] == 4).await;
    assert_eq!(health["items"], 4);
    assert!(health["last_reload_error"].is_null());

    // SIGTERM stops the daemon and removes the socket file.
    signal(&serve, libc::SIGTERM);
    let status = tokio::time::timeout(Duration::from_secs(20), serve.wait())
        .await
        .expect("serve exits after SIGTERM")
        .unwrap();
    assert!(status.success(), "{status:?}");
    assert!(!socket.exists(), "socket file must be removed on shutdown");
    drop(shim.stdin);
    let _ = shim.child.wait().await;
}

#[tokio::test]
async fn shim_without_a_daemon_still_starts_and_explains_how_to_start_one() {
    let root = tempfile::tempdir().unwrap();
    let socket = socket_in(root.path());
    let mut shim = Shim::start(&socket);
    let init = shim
        .request(
            1,
            "initialize",
            json!({"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"t","version":"1"}}),
        )
        .await;
    assert_eq!(init["result"]["serverInfo"]["name"], "code-diver");
    let list = shim.request(2, "tools/list", json!({})).await;
    assert!(list["result"]["tools"].as_array().unwrap().len() >= 2);
    drop(shim.stdin);
    let _ = shim.child.wait().await;
}

#[tokio::test]
async fn serve_refuses_a_path_that_is_not_a_socket_and_cleans_a_stale_one() {
    let root = tempfile::tempdir().unwrap();
    std::fs::write(root.path().join("catalog.jsonl"), catalog_rows(&["hello"])).unwrap();
    std::fs::write(root.path().join("graph.jsonl"), "").unwrap();
    let socket = socket_in(root.path());
    std::fs::write(&socket, "keep me").unwrap();
    let refused = serve_command(root.path(), &socket, "http://127.0.0.1:9")
        .stderr(Stdio::piped())
        .output()
        .await
        .unwrap();
    assert!(!refused.status.success());
    assert!(String::from_utf8_lossy(&refused.stderr).contains("not a socket"));
    assert_eq!(std::fs::read_to_string(&socket).unwrap(), "keep me");

    std::fs::remove_file(&socket).unwrap();
    drop(std::os::unix::net::UnixListener::bind(&socket).unwrap());
    assert!(socket.exists(), "a dead listener leaves its file behind");
    let mut serve = serve_command(root.path(), &socket, "http://127.0.0.1:9")
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .unwrap();
    let mut shim = Shim::start(&socket);
    let health = shim
        .wait_health("start over a stale socket", |_| true)
        .await;
    assert_eq!(health["items"], 1);
    signal(&serve, libc::SIGTERM);
    assert!(serve.wait().await.unwrap().success());
    assert!(!socket.exists());
}
