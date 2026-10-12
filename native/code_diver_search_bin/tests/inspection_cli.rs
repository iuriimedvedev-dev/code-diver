use std::process::Command;

#[test]
fn symbols_cli_default_limit_matches_python_and_empty_output_is_empty() {
    let root = tempfile::tempdir().unwrap();
    let run = |limit: Option<&str>| {
        let mut command = Command::new(env!("CARGO_BIN_EXE_code-diver"));
        command.args(["symbols", "--root", root.path().to_str().unwrap()]);
        if let Some(limit) = limit {
            command.args(["--limit", limit]);
        }
        let output = command.output().unwrap();
        assert!(output.status.success());
        String::from_utf8(output.stdout).unwrap()
    };
    assert_eq!(run(None), "");
    for file in ["a.rs", "b.rs", "c.rs", "d.rs"] {
        let text = (0..60)
            .map(|i| format!("fn symbol_{i}() {{}}\n"))
            .collect::<String>();
        std::fs::write(root.path().join(file), text).unwrap();
    }
    assert_eq!(run(None).lines().count(), 200);
    assert_eq!(run(Some("100")).lines().count(), 100);
}

#[test]
fn symbols_plain_output_matches_python_rendering_and_json_keeps_mcp_array() {
    let root = tempfile::tempdir().unwrap();
    std::fs::write(root.path().join("hello.rs"), "fn greeting() {}\n").unwrap();
    let run = |json: bool| {
        let mut command = Command::new(env!("CARGO_BIN_EXE_code-diver"));
        command.args([
            "symbols",
            "hello.rs",
            "--root",
            root.path().to_str().unwrap(),
        ]);
        if json {
            command.arg("--json");
        }
        let output = command.output().unwrap();
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        String::from_utf8(output.stdout).unwrap()
    };
    assert_eq!(
        run(false),
        "hello.rs:1: function greeting - fn greeting() {}\n"
    );
    let result: serde_json::Value = serde_json::from_str(&run(true)).unwrap();
    let rows: serde_json::Value =
        serde_json::from_str(result["content"][0]["text"].as_str().unwrap()).unwrap();
    assert_eq!(
        rows,
        serde_json::json!([{
            "path": "hello.rs", "name": "greeting", "kind": "function",
            "signature": "fn greeting() {}", "startLine": 1, "endLine": 1,
            "confidence": 0.7
        }])
    );
}

#[test]
fn cargo_version_and_read_without_catalog() {
    let output = Command::new(env!("CARGO_BIN_EXE_code-diver"))
        .arg("--version")
        .output()
        .unwrap();
    assert!(output.status.success());
    assert!(String::from_utf8_lossy(&output.stdout).contains(env!("CARGO_PKG_VERSION")));
    let root = tempfile::tempdir().unwrap();
    std::fs::write(root.path().join("hello.txt"), "hello\nworld\n").unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_code-diver"))
        .args([
            "read",
            "hello.txt",
            "--root",
            root.path().to_str().unwrap(),
            "--json",
        ])
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let value: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(value["isError"], false);
    assert!(
        value["content"][0]["text"]
            .as_str()
            .unwrap()
            .contains("hello")
    );
}

#[test]
fn inspection_commands_share_root_and_json_contract() {
    let root = tempfile::tempdir().unwrap();
    std::fs::write(root.path().join("hello.rs"), "fn greeting() {}\n").unwrap();
    std::fs::write(root.path().join(".gitignore"), "ignored.rs\n").unwrap();
    std::fs::write(root.path().join("ignored.rs"), "fn greeting() {}\n").unwrap();
    for args in [
        vec!["grep", "greeting"],
        vec!["tree"],
        vec!["symbols", "hello.rs"],
    ] {
        let output = Command::new(env!("CARGO_BIN_EXE_code-diver"))
            .args(args)
            .args(["--root", root.path().to_str().unwrap(), "--json"])
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        let value: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
        assert_eq!(value["isError"], false);
        assert!(
            value["content"][0]["text"]
                .as_str()
                .unwrap()
                .contains("hello.rs")
        );
        assert!(
            !value["content"][0]["text"]
                .as_str()
                .unwrap()
                .contains("ignored.rs")
        );
    }
    for file in ["../outside", "/etc/passwd", "missing"] {
        let output = Command::new(env!("CARGO_BIN_EXE_code-diver"))
            .args(["read", file, "--root", root.path().to_str().unwrap()])
            .output()
            .unwrap();
        assert!(!output.status.success());
        assert!(!output.stderr.is_empty());
    }
    let config = root.path().join("config.toml");
    std::fs::write(&config, "root = '.'\n").unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_code-diver"))
        .args(["read", "hello.rs", "--config", config.to_str().unwrap()])
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(String::from_utf8_lossy(&output.stdout).contains("greeting"));
}

#[tokio::test]
async fn info_uses_configured_collection_and_reports_artifacts() {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let root = tempfile::tempdir().unwrap();
    std::fs::write(root.path().join("catalog.jsonl"), "{}\n{}\n").unwrap();
    std::fs::write(root.path().join("graph.jsonl"), "{}\n").unwrap();
    std::fs::write(root.path().join("model.txt"), "synthetic").unwrap();
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}", listener.local_addr().unwrap());
    let mock = tokio::spawn(async move {
        let mut paths = Vec::new();
        for _ in 0..2 {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut bytes = [0u8; 4096];
            let size = socket.read(&mut bytes).await.unwrap();
            paths.push(
                String::from_utf8_lossy(&bytes[..size])
                    .split_whitespace()
                    .nth(1)
                    .unwrap()
                    .to_string(),
            );
            let body = r#"{"result":{"points_count":7}}"#;
            socket.write_all(format!("HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{body}", body.len()).as_bytes()).await.unwrap();
        }
        paths
    });
    let config = root.path().join("config.toml");
    std::fs::write(&config, format!("catalog = 'catalog.jsonl'\ngraph_path = 'graph.jsonl'\nmodel = 'model.txt'\n[storage.qdrant]\nurl = '{url}'\ncollection = 'zz_synthetic_info'\n")).unwrap();
    let output = tokio::process::Command::new(env!("CARGO_BIN_EXE_code-diver"))
        .args(["info", "--config", config.to_str().unwrap(), "--json"])
        .output()
        .await
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let value: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(value["version"], env!("CARGO_PKG_VERSION"));
    assert_eq!(value["qdrant_collection"], "zz_synthetic_info");
    assert_eq!(value["qdrant_collection_points"], 7);
    assert_eq!(value["catalog_items"], 2);
    for key in ["catalog_present", "graph_present", "model_present"] {
        assert_eq!(value[key], true);
    }
    let paths = tokio::time::timeout(std::time::Duration::from_secs(5), mock)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(paths, ["/", "/collections/zz_synthetic_info"]);
}
