use std::process::Command;

fn command(home: &std::path::Path) -> Command {
    let mut command = Command::new(env!("CARGO_BIN_EXE_code-diver"));
    command
        .env("CODE_DIVER_HOME", home.canonicalize().unwrap())
        .env_remove("CODE_DIVER_CONFIG");
    command
}

#[test]
fn runtime_config_precedence_and_secret_redaction() {
    let home = tempfile::tempdir().unwrap();
    std::fs::create_dir(home.path().join("config")).unwrap();
    std::fs::write(home.path().join("config/config.toml"),
        "schema=1\n[daemon]\nport=8091\n[secrets.qdrant]\nsource='env'\nname='SYNTHETIC_RUNTIME_KEY'\n").unwrap();
    let output = command(home.path())
        .env("CODE_DIVER_DAEMON_PORT", "8092")
        .env("SYNTHETIC_RUNTIME_KEY", "never-print-this-token")
        .args(["config", "show", "--daemon-port", "8093"])
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let text = String::from_utf8(output.stdout).unwrap();
    assert!(text.contains("port = 8093"), "{text}");
    assert!(text.contains("REDACTED"));
    assert!(!text.contains("never-print-this-token"));
    assert!(!text.contains("SYNTHETIC_RUNTIME_KEY"));
}

#[test]
fn runtime_credentials_reject_argv() {
    let home = tempfile::tempdir().unwrap();
    std::fs::create_dir(home.path().join("config")).unwrap();
    std::fs::write(home.path().join("config/config.toml"), "schema=1\n").unwrap();
    let output = command(home.path())
        .args([
            "config",
            "show",
            "--qdrant-api-key",
            "never-print-this-token",
        ])
        .output()
        .unwrap();
    assert!(!output.status.success());
    assert!(!String::from_utf8_lossy(&output.stderr).contains("never-print-this-token"));
}

#[test]
fn mcp_before_setup_preserves_legacy_stdio_without_creating_runtime() {
    let home = tempfile::tempdir().unwrap();
    let output = command(home.path()).args(["mcp"]).output().unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(std::fs::read_dir(home.path()).unwrap().next().is_none());
}

#[test]
fn runtime_mcp_reports_autostart_failure_before_serving() {
    let home = tempfile::tempdir().unwrap();
    std::fs::create_dir(home.path().join("config")).unwrap();
    std::fs::write(home.path().join("config/config.toml"),
        "schema=1\n[daemon]\nport=1\nautostart=true\n[profile]\nmodel_manifest_path='/nonexistent/synthetic-runtime-manifest.json'\n").unwrap();
    let output = command(home.path()).args(["mcp"]).output().unwrap();
    assert!(
        !output.status.success(),
        "MCP must not silently serve with a failed runtime autostart"
    );
    assert!(
        String::from_utf8_lossy(&output.stderr).contains("daemon"),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
}

#[test]
fn setup_dry_run_and_new_commands_reject_tokens() {
    let home = tempfile::tempdir().unwrap();
    let output = command(home.path())
        .args(["setup", "--dry-run", "--no-register"])
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(std::fs::read_dir(home.path()).unwrap().next().is_none());
    for subcommand in ["setup", "daemon", "update-index"] {
        let output = command(home.path())
            .args([subcommand, "--api-key", "SYNTHETIC_TOKEN"])
            .output()
            .unwrap();
        assert!(!output.status.success());
        assert!(!String::from_utf8_lossy(&output.stderr).contains("SYNTHETIC_TOKEN"));
    }
}

struct Process(std::process::Child);

#[test]
fn unconfigured_doctor_is_actionable_and_dry_run_does_not_fetch_profile() {
    let home = tempfile::tempdir().unwrap();
    let output = command(home.path())
        .args(["doctor", "--json"])
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(1));
    let report: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(report["checks"][0]["name"], "configuration");
    assert!(
        report["checks"][0]["message"]
            .as_str()
            .unwrap()
            .contains("setup --profile")
    );
    let output = command(home.path())
        .args([
            "setup",
            "--dry-run",
            "--profile",
            "http://127.0.0.1:1/profile",
        ])
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(String::from_utf8_lossy(&output.stdout).contains("Configuration required"));
    assert!(std::fs::read_dir(home.path()).unwrap().next().is_none());
}

#[test]
fn doctor_missing_snapshot_selection_fails_without_guessing_collection() {
    let home = tempfile::tempdir().unwrap();
    std::fs::create_dir(home.path().join("config")).unwrap();
    std::fs::write(
        home.path().join("config/config.toml"),
        "schema=1\n[profile]\ncollection='not-a-snapshot'\n",
    )
    .unwrap();
    let output = command(home.path())
        .args(["doctor", "--json", "--ce-timeout-ms", "100"])
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(1));
    let report: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(report["checks"][0]["status"], "FAIL");
    assert!(
        report["checks"][0]["message"]
            .as_str()
            .unwrap()
            .contains("index_name")
    );
}

#[test]
fn setup_requires_selected_index_before_side_effects() {
    let home = tempfile::tempdir().unwrap();
    let output = command(home.path())
        .args(["setup", "--no-register", "--yes"])
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&output.stderr).contains("--profile"));
    assert!(std::fs::read_dir(home.path()).unwrap().next().is_none());
}

#[test]
fn doctor_discovers_explicit_runtime_snapshot_metadata() {
    let home = tempfile::tempdir().unwrap();
    std::fs::create_dir(home.path().join("config")).unwrap();
    std::fs::write(home.path().join("config/config.toml"), "schema=1\nllama_server='/nonexistent/synthetic-llama'\n[daemon]\nport=1\nautostart=false\n[profile]\nindex_name='default'\nqdrant_url='http://127.0.0.1:1'\n").unwrap();
    let directory = home.path().join("data/default");
    std::fs::create_dir_all(&directory).unwrap();
    let mut metadata: serde_json::Value =
        serde_json::from_str(include_str!("fixtures/shared-index-metadata.json")).unwrap();
    let model = metadata["meta_ranker"]["file"].as_str().unwrap().to_owned();
    metadata["files"][model] = serde_json::json!({});
    metadata["generated_at"] = serde_json::json!(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_secs()
    );
    std::fs::write(directory.join("index-metadata.json"), metadata.to_string()).unwrap();
    let output = command(home.path())
        .args(["doctor", "--json", "--ce-timeout-ms", "100"])
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(1));
    let report: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    let checks = report["checks"].as_array().unwrap();
    let metadata = checks
        .iter()
        .find(|check| check["name"] == "metadata")
        .unwrap();
    assert_eq!(metadata["status"], "PASS", "{report}");
    assert!(
        checks.iter().any(|check| check["name"] == "daemon"),
        "{report}"
    );
}

#[test]
fn mcp_waits_for_service_holding_pid_lock_before_health_is_ready() {
    use std::io::{Read, Write};
    use std::os::fd::AsRawFd;
    unsafe extern "C" {
        fn flock(fd: i32, operation: i32) -> i32;
    }
    let home = tempfile::tempdir().unwrap();
    std::fs::create_dir(home.path().join("config")).unwrap();
    std::fs::create_dir(home.path().join("state")).unwrap();
    let lock = std::fs::File::create(home.path().join("state/daemon.pid")).unwrap();
    assert_eq!(unsafe { flock(lock.as_raw_fd(), 2 | 4) }, 0);
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port();
    listener.set_nonblocking(true).unwrap();
    std::fs::write(home.path().join("config/config.toml"), format!(
        "schema=1\nllama_server='/nonexistent/race-llama'\n[daemon]\nport={port}\nstartup_timeout_secs=3\n[profile]\nindex_name='test'\n"
    )).unwrap();
    let server = std::thread::spawn(move || {
        std::thread::sleep(std::time::Duration::from_millis(1400));
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(4);
        while std::time::Instant::now() < deadline {
            if let Ok((mut stream, _)) = listener.accept() {
                stream
                    .set_read_timeout(Some(std::time::Duration::from_millis(100)))
                    .unwrap();
                let _ = stream.read(&mut [0; 4096]);
                let _ = stream.write_all(
                    b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}",
                );
            }
            std::thread::sleep(std::time::Duration::from_millis(10));
        }
    });
    let output = command(home.path())
        .env("CODE_DIVER_AUTOSTART", "true")
        .env("CODE_DIVER_DAEMON_PORT", port.to_string())
        .args(["mcp"])
        .output()
        .unwrap();
    server.join().unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
}

#[test]
fn runtime_doctor_json_reports_local_runtime_failures() {
    let home = tempfile::tempdir().unwrap();
    std::fs::create_dir(home.path().join("config")).unwrap();
    std::fs::write(home.path().join("config/config.toml"), "schema=1\nllama_server='/nonexistent/synthetic-llama'\n[daemon]\nport=1\nautostart=false\n[profile]\nindex_name='test'\nqdrant_url='http://127.0.0.1:1'\ncollection='zz_synthetic_runtime'\n").unwrap();
    let output = command(home.path())
        .args(["doctor", "--json", "--ce-timeout-ms", "100"])
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(1));
    let report: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    let checks = report["checks"].as_array().unwrap();
    for name in [
        "daemon",
        "runtime_embedding_model_file",
        "runtime_reranker_model_file",
        "qdrant",
    ] {
        let check = checks
            .iter()
            .find(|check| check["name"] == name)
            .unwrap_or_else(|| panic!("Missing {name}: {report}"));
        assert_eq!(check["status"], "FAIL");
        assert!(!check["fix"].as_str().unwrap().is_empty());
    }
}
impl Drop for Process {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

#[tokio::test]
async fn foreground_daemon_health_models_and_mcp_protocol() {
    use std::io::Write;
    let home = tempfile::tempdir().unwrap();
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port();
    drop(listener);
    std::fs::create_dir(home.path().join("config")).unwrap();
    std::fs::write(
        home.path().join("config/config.toml"),
        format!("schema=1\n[daemon]\nport={port}\nautostart=false\n[profile]\nindex_name='test'\n"),
    )
    .unwrap();
    let mut daemon = Process(
        command(home.path())
            .args(["daemon", "--foreground"])
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::inherit())
            .spawn()
            .unwrap(),
    );
    let client = reqwest::Client::builder()
        .no_proxy()
        .timeout(std::time::Duration::from_millis(200))
        .build()
        .unwrap();
    let base = format!("http://127.0.0.1:{port}");
    let deadline = tokio::time::Instant::now() + std::time::Duration::from_secs(5);
    loop {
        if let Ok(response) = client.get(format!("{base}/health")).send().await {
            let health: serde_json::Value = response.json().await.unwrap();
            assert_eq!(health["status"], "ok");
            assert_eq!(health["children"][0]["loaded"], false);
            break;
        }
        assert!(daemon.0.try_wait().unwrap().is_none());
        assert!(
            tokio::time::Instant::now() < deadline,
            "Daemon readiness timeout"
        );
        tokio::time::sleep(std::time::Duration::from_millis(25)).await;
    }
    let models: serde_json::Value = client
        .get(format!("{base}/v1/models"))
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(models["data"].as_array().unwrap().len(), 2);
    let duplicate = command(home.path())
        .args(["daemon", "--foreground", "--port", "1"])
        .output()
        .unwrap();
    assert!(!duplicate.status.success());
    assert!(String::from_utf8_lossy(&duplicate.stderr).contains("process lock"));
    assert_eq!(
        std::fs::read_to_string(home.path().join("state/daemon.pid"))
            .unwrap()
            .trim(),
        daemon.0.id().to_string()
    );
    let mut mcp = command(home.path())
        .args(["mcp"])
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .spawn()
        .unwrap();
    mcp.stdin.take().unwrap().write_all(b"{\"jsonrpc\":\"2.0\",\"id\":0,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2024-11-05\",\"capabilities\":{},\"clientInfo\":{\"name\":\"runtime-test\",\"version\":\"1\"}}}\n{\"jsonrpc\":\"2.0\",\"method\":\"notifications/initialized\"}\n{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}\n").unwrap();
    let output = mcp.wait_with_output().unwrap();
    assert!(output.status.success());
    let response: serde_json::Value = String::from_utf8(output.stdout)
        .unwrap()
        .lines()
        .map(|line| serde_json::from_str::<serde_json::Value>(line).unwrap())
        .find(|response| response["id"] == 1)
        .unwrap();
    assert_eq!(response["result"]["tools"].as_array().unwrap().len(), 6);
}
