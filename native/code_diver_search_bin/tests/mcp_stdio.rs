use serde_json::{Value, json};
use std::process::Stdio;
use std::time::Duration;
use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, ChildStdin, ChildStdout, Command};

#[tokio::test]
async fn long_query_preview_and_degraded_search_are_caller_visible() {
    let root = tempfile::tempdir().unwrap();
    let catalog = root.path().join("catalog.jsonl");
    let graph = root.path().join("graph.jsonl");
    std::fs::write(&catalog, "{\"id\":\"hello\",\"path\":\"hello.rs\",\"name\":\"Hello\",\"content\":\"first\\nsecond\\n\"}\n").unwrap();
    std::fs::write(&graph, "").unwrap();
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}", listener.local_addr().unwrap());
    let mock = tokio::spawn(async move {
        for request in 0..6 {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut bytes = Vec::new();
            let (headers, body) = loop {
                let mut buffer = [0; 4096];
                let n = socket.read(&mut buffer).await.unwrap();
                assert!(n > 0);
                bytes.extend_from_slice(&buffer[..n]);
                if let Some(end) = bytes.windows(4).position(|w| w == b"\r\n\r\n") {
                    let headers = String::from_utf8(bytes[..end].to_vec()).unwrap();
                    let size: usize = headers
                        .lines()
                        .find_map(|l| {
                            l.to_lowercase()
                                .strip_prefix("content-length:")
                                .map(|v| v.trim().parse().unwrap())
                        })
                        .unwrap();
                    if bytes.len() >= end + 4 + size {
                        break (
                            headers,
                            serde_json::from_slice::<Value>(&bytes[end + 4..end + 4 + size])
                                .unwrap(),
                        );
                    }
                }
            };
            let mut status = "200 OK";
            let payload = if headers.starts_with("POST /embed ") {
                assert_eq!(body["input"].as_str().unwrap().len(), 96);
                json!({"data":[{"embedding":[1.0,0.0]}]})
            } else if headers.contains("/points/search ") {
                json!({"result":[{"id":"hello","score":0.9,"payload":{"item_id":"hello","path":"hello.rs"}}]})
            } else {
                assert_eq!(body["query"].as_str().unwrap().len(), 10_000);
                if request == 5 { status = "503 Unavailable"; }
                json!({"results":[{"index":0,"relevance_score":0.8}]})
            }.to_string();
            socket.write_all(format!("HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{payload}", payload.len()).as_bytes()).await.unwrap();
        }
    });
    let mut s = Session::start(
        root.path(),
        &[
            "--catalog",
            catalog.to_str().unwrap(),
            "--graph",
            graph.to_str().unwrap(),
            "--embedding-url",
            &format!("{url}/embed"),
            "--qdrant-url",
            &url,
            "--ce-url",
            &format!("{url}/v1/rerank"),
            "--second-pass-disable",
            "--embedding-query-token-budget",
            "96",
            "--embed-cache-size",
            "0",
        ],
    );
    s.initialize().await;
    for degraded in [false, true] {
        let result = s
            .call(
                1,
                "code_diver_search",
                json!({"query":"x".repeat(10_000),"preview_chars":if degraded {5} else {0}}),
            )
            .await;
        assert_eq!(result["result"]["isError"], false, "{result}");
        let content = result["result"]["content"].as_array().unwrap();
        assert_eq!(content.len(), 2);
        let warning = content[1]["text"].as_str().unwrap();
        assert!(warning.starts_with("WARNING"));
        assert!(warning.contains("truncated"));
        assert!(warning.contains("Meta-ranker"));
        assert_eq!(warning.contains("CE reranking unavailable"), degraded);
        let results: Value = serde_json::from_str(content[0]["text"].as_str().unwrap()).unwrap();
        assert_eq!(results.as_array().unwrap().len(), 1);
        for field in [
            "path",
            "title",
            "start_line",
            "end_line",
            "score",
            "ce_score",
        ] {
            assert!(results[0].get(field).is_some(), "{results}");
        }
        if degraded {
            assert_eq!(results[0]["preview"], "first");
            assert!(results[0]["ce_score"].is_null());
        } else {
            assert!(results[0].get("preview").is_none());
            assert!(results[0]["ce_score"].is_number());
        }
    }
    let invalid = s
        .call(2, "code_diver_search", json!({"query":"x","limit":35}))
        .await;
    assert_eq!(invalid["result"]["isError"], true);
    assert!(
        invalid["result"]["content"][0]["text"]
            .as_str()
            .unwrap()
            .contains("1..=34")
    );
    s.stop().await;
    mock.await.unwrap();
}

struct Session {
    child: Child,
    stdin: ChildStdin,
    stdout: BufReader<ChildStdout>,
}

#[tokio::test]
async fn configured_maximum_and_direct_info_credentials() {
    let root = tempfile::tempdir().unwrap();
    let config = root.path().join("config.toml");
    std::fs::write(&config, "[search]\ncandidate_limit = 40\n[storage.qdrant]\ncollection = 'mock_private'\napi_key = 'wrong-config-secret'\n").unwrap();
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}", listener.local_addr().unwrap());
    let mock = tokio::spawn(async move {
        for expected in ["/", "/collections/mock_private"] {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut bytes = Vec::new();
            loop {
                let mut buffer = [0; 4096];
                let count = socket.read(&mut buffer).await.unwrap();
                assert!(count > 0);
                bytes.extend_from_slice(&buffer[..count]);
                if bytes.windows(4).any(|w| w == b"\r\n\r\n") {
                    break;
                }
            }
            let request = String::from_utf8(bytes).unwrap().to_lowercase();
            assert!(request.starts_with(&format!("get {expected} ")));
            assert!(request.contains("api-key: direct-secret\r\n"));
            assert!(request.contains("authorization: bearer direct-bearer\r\n"));
            assert!(!request.contains("wrong-config-secret"));
            let body = "{\"result\":{\"points_count\":9}}";
            socket.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len()).as_bytes()).await.unwrap();
        }
    });
    let mut s = Session::start(
        root.path(),
        &[
            "--config",
            config.to_str().unwrap(),
            "--qdrant-url",
            &url,
            "--qdrant-api-key",
            "direct-secret",
            "--qdrant-bearer",
            "direct-bearer",
            "--insecure-skip-verify",
        ],
    );
    s.initialize().await;
    s.send(json!({"jsonrpc":"2.0","id":5,"method":"tools/list"}))
        .await;
    let tools = s.receive().await;
    assert_eq!(
        tools["result"]["tools"][0]["inputSchema"]["properties"]["limit"]["maximum"],
        40
    );
    let result = s.call(6, "code_diver_info", json!({})).await;
    assert_eq!(result["result"]["isError"], false, "{result}");
    let info: Value =
        serde_json::from_str(result["result"]["content"][0]["text"].as_str().unwrap()).unwrap();
    assert_eq!(info["qdrant_collection_points"], 9);
    assert!(!result.to_string().contains("direct-secret"));
    s.stop().await;
    mock.await.unwrap();
}

impl Session {
    fn start(root: &std::path::Path, extra: &[&str]) -> Self {
        let mut child = Command::new(env!("CARGO_BIN_EXE_code-diver"))
            .args(["mcp", "--root", root.to_str().unwrap()])
            .args(extra)
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
        let n = tokio::time::timeout(Duration::from_secs(5), self.stdout.read_line(&mut line))
            .await
            .unwrap()
            .unwrap();
        assert!(n > 0, "server exited");
        serde_json::from_str(&line).unwrap()
    }

    async fn initialize(&mut self) {
        self.send(json!({"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1"}}})).await;
        let result = self.receive().await;
        assert_eq!(result["result"]["protocolVersion"], "2024-11-05");
        assert_eq!(
            result["result"]["serverInfo"]["version"],
            env!("CARGO_PKG_VERSION")
        );
        self.send(json!({"jsonrpc":"2.0","method":"notifications/initialized"}))
            .await;
    }

    async fn call(&mut self, id: i64, name: &str, args: Value) -> Value {
        self.send(json!({"jsonrpc":"2.0","id":id,"method":"tools/call","params":{"name":name,"arguments":args}})).await;
        let result = self.receive().await;
        assert_eq!(result["id"], id);
        result
    }

    async fn stop(mut self) {
        self.child.kill().await.unwrap();
        self.child.wait().await.unwrap();
    }
}

#[tokio::test]
async fn initialize_negotiation_and_lifecycle() {
    let root = tempfile::tempdir().unwrap();
    let mut s = Session::start(root.path(), &[]);
    s.send(json!({"jsonrpc":"2.0","id":1,"method":"ping"}))
        .await;
    assert_eq!(s.receive().await["result"], json!({}));
    s.send(json!({"jsonrpc":"2.0","id":2,"method":"tools/list"}))
        .await;
    assert_eq!(s.receive().await["error"]["code"], -32600);
    s.send(json!({"jsonrpc":"2.0","id":3,"method":"initialize","params":{}}))
        .await;
    assert_eq!(s.receive().await["error"]["code"], -32602);
    s.send(json!({"jsonrpc":"2.0","id":4,"method":"initialize","params":{"protocolVersion":"unsupported","capabilities":{},"clientInfo":{"name":"test","version":"1"}}})).await;
    assert_eq!(s.receive().await["result"]["protocolVersion"], "2025-11-25");
    s.send(json!({"jsonrpc":"2.0","id":5,"method":"tools/list"}))
        .await;
    assert_eq!(s.receive().await["error"]["code"], -32600);
    s.send(json!({"jsonrpc":"2.0","method":"notifications/initialized"}))
        .await;
    s.send(json!({"jsonrpc":"2.0","id":6,"method":"unknown"}))
        .await;
    assert_eq!(s.receive().await["error"]["code"], -32601);
    s.send(json!({"jsonrpc":"2.0","id":7,"method":"ping","params":[]}))
        .await;
    assert_eq!(s.receive().await["error"]["code"], -32602);
    s.stop().await;
}

#[tokio::test]
async fn protocol_and_hostile_arguments_without_catalog() {
    let root = tempfile::tempdir().unwrap();
    std::fs::write(root.path().join("hello.rs"), "fn hello() {}\n").unwrap();
    std::fs::write(root.path().join("binary"), b"a\0b").unwrap();
    std::fs::write(root.path().join("nonutf8"), [255u8]).unwrap();
    let mut s = Session::start(
        root.path(),
        &[
            "--qdrant-url",
            "http://127.0.0.1:0",
            "--qdrant-collection",
            "zz_synthetic_info",
        ],
    );
    s.initialize().await;
    for (id, method, field) in [
        (1, "tools/list", "tools"),
        (2, "resources/list", "resources"),
        (3, "prompts/list", "prompts"),
    ] {
        s.send(json!({"jsonrpc":"2.0","id":id,"method":method}))
            .await;
        let result = s.receive().await;
        let values = result["result"][field].as_array().unwrap();
        if field == "tools" {
            assert_eq!(values.len(), 6);
            let symbols = values
                .iter()
                .find(|tool| tool["name"] == "code_diver_symbols")
                .unwrap();
            assert_eq!(
                symbols["inputSchema"]["properties"]["limit"]["default"],
                100
            );
            let tree = values
                .iter()
                .find(|tool| tool["name"] == "code_diver_tree")
                .unwrap();
            assert_eq!(tree["inputSchema"]["properties"]["depth"]["minimum"], 1);
            assert!(
                values
                    .iter()
                    .all(|t| !t["name"].as_str().unwrap().contains("find_files"))
            );
        } else {
            assert!(values.is_empty());
        }
    }
    for (name, args) in [
        ("code_diver_read", json!({"file":"hello.rs"})),
        ("code_diver_grep", json!({"pattern":"hello"})),
        ("code_diver_tree", json!({})),
        ("code_diver_symbols", json!({"path":"hello.rs"})),
    ] {
        let result = s.call(10, name, args).await;
        assert_eq!(result["result"]["isError"], false, "{result}");
    }
    for args in [
        json!({"file":"../.."}),
        json!({"file":root.path().join("hello.rs")}),
        json!({"file":"binary"}),
        json!({"file":"nonutf8"}),
        json!({"file":"hello.rs","lines":"100"}),
        json!({"file":42}),
    ] {
        let result = s.call(11, "code_diver_read", args).await;
        assert!(result.get("error").is_none(), "{result}");
        assert_eq!(result["result"]["isError"], true, "{result}");
    }
    std::fs::write(
        root.path().join("many.rs"),
        "// bounded line\n".repeat(1000),
    )
    .unwrap();
    let capped = s
        .call(
            11,
            "code_diver_read",
            json!({"file":"many.rs","lines":u64::MAX}),
        )
        .await;
    assert_eq!(capped["result"]["isError"], false);
    let text = capped["result"]["content"][0]["text"].as_str().unwrap();
    assert!(text.contains("400 |"));
    assert!(!text.contains("401 |"));
    assert!(text.chars().count() <= 40_000);
    for args in [
        json!({"query":""}),
        json!({"query":"  "}),
        json!({"query":1}),
        json!({"query":"x","limit":-1}),
        json!({"query":"x","preview_chars":1.5}),
    ] {
        assert_eq!(
            s.call(12, "code_diver_search", args).await["result"]["isError"],
            true
        );
    }
    let info = s.call(12, "code_diver_info", json!({})).await;
    assert_eq!(info["result"]["isError"], false);
    let info: Value =
        serde_json::from_str(info["result"]["content"][0]["text"].as_str().unwrap()).unwrap();
    assert_eq!(info["qdrant_collection"], "zz_synthetic_info");
    for (name, args) in [
        ("code_diver_grep", json!({"pattern":"[","regex":true})),
        ("code_diver_grep", json!({"pattern":"x","path":"../.."})),
        ("code_diver_tree", json!({"depth":"three"})),
        ("code_diver_tree", json!({"path":"../.."})),
        ("code_diver_symbols", json!({"limit":-1})),
        ("code_diver_symbols", json!({"path":"../.."})),
        ("code_diver_info", json!({"unexpected":true})),
    ] {
        let result = s.call(12, name, args).await;
        assert_eq!(result["result"]["isError"], true, "{result}");
    }
    assert_eq!(
        s.call(13, "does_not_exist", json!({})).await["result"]["isError"],
        true
    );
    s.send(json!({"jsonrpc":"2.0","id":14,"method":"tools/call","params":{"name":"code_diver_read","arguments":[]}})).await;
    assert_eq!(s.receive().await["error"]["code"], -32602);
    for value in [
        json!([]),
        json!({"jsonrpc":"1.0","id":15,"method":"ping"}),
        json!({"jsonrpc":"2.0","id":true,"method":"ping"}),
        json!({"jsonrpc":"2.0","id":null,"method":"ping"}),
    ] {
        s.send(value).await;
        assert_eq!(s.receive().await["error"]["code"], -32600);
    }
    s.stdin.write_all(b"{broken\n").await.unwrap();
    let result = s.receive().await;
    assert_eq!(result["id"], Value::Null);
    assert_eq!(result["error"]["code"], -32700);
    s.stdin.write_all(&vec![b'x'; 1_100_000]).await.unwrap();
    s.stdin.write_all(b"\n").await.unwrap();
    assert_eq!(s.receive().await["error"]["code"], -32700);
    s.send(json!({"jsonrpc":"2.0","method":"ping"})).await;
    s.send(json!({"jsonrpc":"2.0","id":"alive","method":"ping"}))
        .await;
    assert_eq!(
        s.receive().await,
        json!({"jsonrpc":"2.0","id":"alive","result":{}})
    );
    s.stop().await;
}

#[cfg(unix)]
#[tokio::test]
async fn symlink_escape_is_tool_error() {
    let root = tempfile::tempdir().unwrap();
    let outside = tempfile::tempdir().unwrap();
    std::fs::write(outside.path().join("secret"), "not readable").unwrap();
    std::os::unix::fs::symlink(outside.path().join("secret"), root.path().join("escape")).unwrap();
    let mut s = Session::start(root.path(), &[]);
    s.initialize().await;
    assert_eq!(
        s.call(1, "code_diver_read", json!({"file":"escape"})).await["result"]["isError"],
        true
    );
    s.stop().await;
}

#[tokio::test]
async fn slow_search_does_not_block_read_and_can_be_cancelled() {
    let root = tempfile::tempdir().unwrap();
    std::fs::write(root.path().join("hello"), "fast read").unwrap();
    let catalog = root.path().join("catalog.jsonl");
    let graph = root.path().join("graph.jsonl");
    std::fs::write(
        &catalog,
        "{\"id\":\"hello::file_summary\",\"path\":\"hello\",\"content\":\"fast read\"}\n",
    )
    .unwrap();
    std::fs::write(&graph, "").unwrap();
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}/v1/embeddings", listener.local_addr().unwrap());
    let (tx, mut rx) = tokio::sync::mpsc::channel(4);
    let mock = tokio::spawn(async move {
        loop {
            let (mut socket, _) = listener.accept().await.unwrap();
            let tx = tx.clone();
            tokio::spawn(async move {
                let mut bytes = [0u8; 4096];
                assert!(socket.read(&mut bytes).await.unwrap() > 0);
                tx.send(()).await.unwrap();
                tokio::time::sleep(Duration::from_secs(30)).await;
                let _ = socket
                    .write_all(b"HTTP/1.1 500 Error\r\nContent-Length: 0\r\n\r\n")
                    .await;
            });
        }
    });
    let mut s = Session::start(
        root.path(),
        &[
            "--catalog",
            catalog.to_str().unwrap(),
            "--graph",
            graph.to_str().unwrap(),
            "--embedding-url",
            &url,
            "--max-concurrent-searches",
            "1",
        ],
    );
    s.initialize().await;
    s.send(json!({"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"code_diver_search","arguments":{"query":"slow"}}})).await;
    tokio::time::timeout(Duration::from_secs(5), rx.recv())
        .await
        .unwrap()
        .unwrap();
    s.send(json!({"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"code_diver_search","arguments":{"query":"queued"}}})).await;
    assert!(
        tokio::time::timeout(Duration::from_millis(200), rx.recv())
            .await
            .is_err()
    );
    assert_eq!(
        s.call(3, "code_diver_read", json!({"file":"hello"})).await["result"]["isError"],
        false
    );
    s.send(json!({"jsonrpc":"2.0","method":"notifications/cancelled","params":{"requestId":1,"reason":"test"}})).await;
    tokio::time::timeout(Duration::from_secs(5), rx.recv())
        .await
        .unwrap()
        .unwrap();
    s.send(json!({"jsonrpc":"2.0","method":"notifications/cancelled","params":{"requestId":2}}))
        .await;
    s.send(json!({"jsonrpc":"2.0","id":4,"method":"ping"}))
        .await;
    assert_eq!(s.receive().await["id"], 4);
    s.stop().await;
    mock.abort();
}
