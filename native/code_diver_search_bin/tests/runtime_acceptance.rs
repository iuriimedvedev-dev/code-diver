#![cfg(unix)]

use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs;
use std::io::{Read, Write};
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Output, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

const KEY: &str = "acceptance-private-key-never-echo";

#[path = "helpers/pty.rs"]
mod pty;
use pty::pty_setup;

#[path = "helpers/helper_executable.rs"]
mod helper_executable;

fn executable(path: &Path, contents: &str) {
    fs::write(path, contents).unwrap();
    fs::set_permissions(path, fs::Permissions::from_mode(0o700)).unwrap();
}

fn hash(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn snapshot(root: &Path) -> BTreeMap<PathBuf, Vec<u8>> {
    let mut result = BTreeMap::new();
    if root.exists() {
        for entry in fs::read_dir(root).unwrap() {
            let path = entry.unwrap().path();
            if fs::symlink_metadata(&path).unwrap().is_dir() {
                result.extend(snapshot(&path));
            } else if path.is_symlink() {
                result.insert(
                    path.clone(),
                    fs::read_link(path)
                        .unwrap()
                        .as_os_str()
                        .as_encoded_bytes()
                        .to_vec(),
                );
            } else {
                result.insert(path.clone(), fs::read(path).unwrap());
            }
        }
    }
    result
}

struct Process(Child);
impl Drop for Process {
    fn drop(&mut self) {
        unsafe extern "C" {
            fn kill(pid: i32, signal: i32) -> i32;
        }
        const SIGTERM: i32 = 15;
        unsafe {
            kill(self.0.id() as i32, SIGTERM);
        }
        let deadline = Instant::now() + Duration::from_secs(5);
        while Instant::now() < deadline {
            if self.0.try_wait().ok().flatten().is_some() {
                return;
            }
            std::thread::sleep(Duration::from_millis(10));
        }
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

struct Gateway {
    url: String,
    files: Arc<Mutex<BTreeMap<String, Vec<u8>>>>,
    requests: Arc<Mutex<Vec<String>>>,
    fail_stored_profile: Arc<AtomicBool>,
    stop: Arc<AtomicBool>,
    thread: Option<std::thread::JoinHandle<()>>,
}
impl Gateway {
    fn new() -> Self {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        listener.set_nonblocking(true).unwrap();
        let url = format!("http://{}", listener.local_addr().unwrap());
        let files = Arc::new(Mutex::new(BTreeMap::<String, Vec<u8>>::new()));
        let requests = Arc::new(Mutex::new(Vec::new()));
        let fail_stored_profile = Arc::new(AtomicBool::new(false));
        let fail = fail_stored_profile.clone();
        let stop = Arc::new(AtomicBool::new(false));
        let (f, r, s) = (files.clone(), requests.clone(), stop.clone());
        let thread = std::thread::spawn(move || {
            while !s.load(Ordering::Relaxed) {
                let Ok((mut stream, _)) = listener.accept() else {
                    std::thread::sleep(Duration::from_millis(5));
                    continue;
                };
                stream.set_nonblocking(false).unwrap();
                stream
                    .set_read_timeout(Some(Duration::from_secs(5)))
                    .unwrap();
                let mut bytes = Vec::new();
                while !bytes.ends_with(b"\r\n\r\n") {
                    let mut byte = [0];
                    if stream.read_exact(&mut byte).is_err() {
                        break;
                    }
                    bytes.push(byte[0]);
                }
                let head = String::from_utf8_lossy(&bytes).to_lowercase();
                let path = head.split_whitespace().nth(1).unwrap_or("").to_string();
                let length = head
                    .lines()
                    .find_map(|line| line.strip_prefix("content-length:"))
                    .and_then(|v| v.trim().parse().ok())
                    .unwrap_or(0);
                let mut body = vec![0; length];
                let _ = stream.read_exact(&mut body);
                r.lock().unwrap().push(path.clone());
                let authorized = path.starts_with("/models/")
                    || head.contains(&format!("bearer {KEY}"))
                    || head.contains(&format!("api-key: {KEY}"));
                let (status, response) = if !authorized {
                    (401, json!({"error":KEY}).to_string().into_bytes())
                } else if path == "/collections" {
                    (
                        200,
                        json!({"result":{"collections":[{"name":"acceptance"}]}})
                            .to_string()
                            .into_bytes(),
                    )
                } else if path.ends_with("/points/scroll") && fail.load(Ordering::Relaxed) {
                    (503, json!({"error":"unavailable"}).to_string().into_bytes())
                } else if path.ends_with("/points/scroll") {
                    (200, json!({"result":{"points":[{"id":"health", "payload":{"model":"test/embedder","dimensions":2}}],"next_page_offset":null}}).to_string().into_bytes())
                } else if path.ends_with("/points/search") || path.ends_with("/points/query") {
                    (200, json!({"result":[{"id":"scratch","score":0.9,"payload":{"path":"scratch.rs","item_id":"scratch"}}]}).to_string().into_bytes())
                } else if path == "/collections/acceptance" {
                    (200, json!({"result":{"config":{"params":{"vectors":{"size":2,"distance":"Cosine"}}}}}).to_string().into_bytes())
                } else if let Some(bytes) = f.lock().unwrap().get(&path) {
                    (200, bytes.clone())
                } else {
                    (
                        404,
                        json!({"error":"unknown fixture route"})
                            .to_string()
                            .into_bytes(),
                    )
                };
                let _ = write!(
                    stream,
                    "HTTP/1.1 {status} Response\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                    response.len()
                );
                let _ = stream.write_all(&response);
            }
        });
        Self {
            url,
            files,
            requests,
            fail_stored_profile,
            stop,
            thread: Some(thread),
        }
    }
}
impl Drop for Gateway {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        self.thread.take().unwrap().join().unwrap();
    }
}

struct Fixture {
    temp: tempfile::TempDir,
    home: PathBuf,
    bin: PathBuf,
    profile: PathBuf,
    gateway: Gateway,
    stop: Arc<AtomicBool>,
    manager: Option<std::thread::JoinHandle<()>>,
}
impl Fixture {
    fn command(&self) -> Command {
        let mut command = Command::new(env!("CARGO_BIN_EXE_code-diver"));
        command.env_clear();
        for key in ["HOME", "TMPDIR", "SYSTEMROOT"] {
            if let Some(value) = std::env::var_os(key) {
                command.env(key, value);
            }
        }
        command
            .env(
                "PATH",
                format!(
                    "{}:/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
                    self.bin.display()
                ),
            )
            .env("CODE_DIVER_HOME", &self.home)
            .current_dir(self.temp.path());
        command
    }

    fn checked(&self, args: &[&str]) -> Output {
        let output = self.command().args(args).output().unwrap();
        assert_redacted(&output);
        assert!(
            output.status.success(),
            "{args:?}: stdout={} stderr={}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
        output
    }

    fn new() -> Self {
        let temp = tempfile::tempdir().unwrap();
        let root = temp.path().canonicalize().unwrap();
        let home = root.join("runtime");
        let bin = root.join("bin");
        fs::create_dir(&home).unwrap();
        fs::create_dir(&bin).unwrap();
        let gateway = Gateway::new();
        fs::copy(helper_executable::executable(), bin.join("llama-server")).unwrap();
        let manager_script = "#!/bin/sh\nprintf '%s\\n' \"$@\" >> \"$CODE_DIVER_HOME/manager-args\"\ncase \"$*\" in\n*is-active*|print*) test -f \"$CODE_DIVER_HOME/ready\";;\n*disable*|bootout*) touch \"$CODE_DIVER_HOME/stop-service\";;\n*enable*|bootstrap*) touch \"$CODE_DIVER_HOME/start-service\"; i=0; while ! test -f \"$CODE_DIVER_HOME/ready\"; do i=$((i+1)); test $i -lt 300 || exit 1; sleep 0.1; done;;\n*) exit 0;;\nesac\n";
        for name in ["launchctl", "systemctl"] {
            executable(&bin.join(name), manager_script);
        }
        for name in ["brew", "security"] {
            executable(&bin.join(name), "#!/bin/sh\nexit 44\n");
        }
        fs::copy(helper_executable::executable(), bin.join("claude")).unwrap();
        let mut manifest: Value =
            serde_json::from_str(include_str!("../src/runtime_models.json")).unwrap();
        for role in ["embedder", "reranker"] {
            let bytes = format!("tiny-{role}").into_bytes();
            manifest["models"][role]["file"] = json!(format!("{role}.gguf"));
            manifest["models"][role]["repo"] = json!(format!("test/{role}"));
            manifest["models"][role]["url"] = json!(format!("{}/models/{role}", gateway.url));
            manifest["models"][role]["size"] = json!(bytes.len());
            manifest["models"][role]["sha256"] = json!(hash(&bytes));
            gateway
                .files
                .lock()
                .unwrap()
                .insert(format!("/models/{role}"), bytes);
        }
        manifest["models"]["embedder"]["dimensions"] = json!(2);
        for (name, value) in [
            ("max_input_chars", 2000),
            ("max_input_tokens", 512),
            ("token_safety_margin", 32),
        ] {
            manifest["models"]["embedder"][name] = json!(value);
        }
        let manifest_path = root.join("manifest.json");
        fs::write(&manifest_path, manifest.to_string()).unwrap();
        let ranker = b"tree\nversion=v4\nTree=0\nnum_leaves=1\nleaf_value=0.5\n";
        let catalog = format!(
            "{}\n",
            json!({"id":"scratch", "path":"scratch.rs", "name":"scratch", "item_type":"file", "content":"fn scratch_health() {}", "tokenized_name":["scratch"], "tokenized_content":["scratch","health"]})
        );
        let artifacts = [
            ("rust_catalog.jsonl", catalog.as_bytes()),
            ("rust_graph.jsonl", b"".as_slice()),
            ("ranker.txt", ranker.as_slice()),
        ];
        let mut metadata: Value =
            serde_json::from_str(include_str!("fixtures/shared-index-metadata.json")).unwrap();
        metadata["name"] = json!("acceptance");
        metadata["qdrant"]["collection"] = json!("acceptance");
        metadata["embedding"]["model"] = json!("test/embedder");
        metadata["embedding"]["model_repo"] = json!("test/embedder");
        metadata["embedding"]["bytes"] = manifest["models"]["embedder"]["size"].clone();
        metadata["embedding"]["dimensions"] = json!(2);
        metadata["embedding"]["model_file"] = manifest["models"]["embedder"]["file"].clone();
        metadata["embedding"]["sha256"] = manifest["models"]["embedder"]["sha256"].clone();
        metadata["reranker"]["gguf"] = manifest["models"]["reranker"]["file"].clone();
        metadata["reranker"]["sha256"] = manifest["models"]["reranker"]["sha256"].clone();
        metadata["meta_ranker"] = json!({"file":"ranker.txt", "sha256":hash(ranker)});
        metadata["generated_at"] = json!(
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_secs()
        );
        metadata["files"] = json!({});
        for (name, bytes) in artifacts {
            metadata["files"][name] = json!({"sha256":hash(bytes), "bytes":bytes.len()});
            gateway
                .files
                .lock()
                .unwrap()
                .insert(format!("/artifacts/acceptance/{name}"), bytes.to_vec());
        }
        gateway.files.lock().unwrap().insert(
            "/artifacts/acceptance/index-metadata.json".into(),
            metadata.to_string().into_bytes(),
        );
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        drop(listener);
        let profile = root.join("profile.toml");
        fs::write(&profile, format!("[profile]\nindex_name='acceptance'\nartifact_url='{}/artifacts'\nqdrant_url='{}'\ncollection='acceptance'\nmodel_manifest_path='{}'\nembedding_model='test/embedder'\nembedding_dimensions=2\n", gateway.url, gateway.url, manifest_path.display())).unwrap();
        let stop = Arc::new(AtomicBool::new(false));
        let mut fixture = Self {
            temp,
            home,
            bin,
            profile,
            gateway,
            stop: stop.clone(),
            manager: None,
        };
        let home = fixture.home.clone();
        let mut daemon_command = fixture.command();
        daemon_command.args(["daemon", "--foreground"]);
        fixture.manager = Some(std::thread::spawn(move || {
            let mut daemon = None;
            let mut started = false;
            let runtime = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
                .unwrap();
            let client = reqwest::Client::builder()
                .no_proxy()
                .timeout(Duration::from_millis(200))
                .build()
                .unwrap();
            while !stop.load(Ordering::Relaxed) {
                if home.join("start-service").exists() && !started {
                    started = true;
                    daemon = Some(Process(
                        daemon_command
                            .stdout(Stdio::null())
                            .stderr(Stdio::null())
                            .spawn()
                            .unwrap(),
                    ));
                    let deadline = Instant::now() + Duration::from_secs(10);
                    while !runtime.block_on(async {
                        client
                            .get(format!("http://127.0.0.1:{port}/health"))
                            .send()
                            .await
                            .is_ok()
                    }) {
                        assert!(
                            Instant::now() < deadline,
                            "foreground service readiness timeout"
                        );
                        std::thread::sleep(Duration::from_millis(20));
                    }
                    fs::write(home.join("ready"), "ready").unwrap();
                }
                if home.join("stop-service").exists() {
                    daemon.take();
                }
                std::thread::sleep(Duration::from_millis(10));
            }
        }));
        // Port and executable are CLI overrides, not preseeded runtime configuration.
        fs::write(fixture.temp.path().join("port"), port.to_string()).unwrap();
        fixture
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        self.manager.take().unwrap().join().unwrap();
    }
}

fn assert_redacted(output: &Output) {
    assert!(!String::from_utf8_lossy(&output.stdout).contains(KEY));
    assert!(!String::from_utf8_lossy(&output.stderr).contains(KEY));
}

#[test]
fn no_register_setup_skips_only_registration_checks() {
    let fixture = Fixture::new();
    let port = fs::read_to_string(fixture.temp.path().join("port")).unwrap();
    let llama = fixture.bin.join("llama-server");
    let output = fixture
        .command()
        .env("QDRANT_API_KEY", KEY)
        .args([
            "setup",
            "--yes",
            "--no-register",
            "--profile",
            fixture.profile.to_str().unwrap(),
            "--llama-server",
            llama.to_str().unwrap(),
            "--daemon-port",
            &port,
        ])
        .output()
        .unwrap();
    assert_redacted(&output);
    assert!(
        output.status.success(),
        "stdout={} stderr={}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(String::from_utf8_lossy(&output.stdout).contains("Skipped by setup --no-register"));
    assert!(!fixture.home.join("hosts/.claude.json").exists());
    let doctor = fixture
        .command()
        .args(["doctor", "--json"])
        .output()
        .unwrap();
    assert_redacted(&doctor);
    assert!(doctor.status.success());
    let report: Value = serde_json::from_slice(&doctor.stdout).unwrap();
    assert!(report["checks"].as_array().unwrap().iter().any(|check| {
        check["name"] == "mcp_hosts"
            && check["status"] == "SKIP"
            && check.to_string().contains("Skipped by setup --no-register")
    }));
    let config_path = fixture.home.join("config/config.toml");
    let original_config = fs::read_to_string(&config_path).unwrap();
    let mut config: toml::Value = toml::from_str(&original_config).unwrap();
    config["mcp_registration_opt_out"] = toml::Value::Boolean(false);
    fs::write(&config_path, toml::to_string(&config).unwrap()).unwrap();
    let doctor = fixture
        .command()
        .args(["doctor", "--json"])
        .output()
        .unwrap();
    assert_redacted(&doctor);
    assert_eq!(doctor.status.code(), Some(1));
    let report: Value = serde_json::from_slice(&doctor.stdout).unwrap();
    let failures: Vec<_> = report["checks"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|check| check["status"] == "FAIL")
        .collect();
    assert!(!failures.is_empty());
    assert!(
        failures
            .iter()
            .all(|check| check["name"].as_str().unwrap().starts_with("mcp_")),
        "{failures:?}"
    );
    fs::write(config_path, original_config).unwrap();
    fixture
        .gateway
        .fail_stored_profile
        .store(true, Ordering::Relaxed);
    let output = fixture
        .command()
        .args(["setup", "--yes", "--no-register"])
        .output()
        .unwrap();
    assert_redacted(&output);
    assert_eq!(output.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&output.stdout).contains("FAIL stored_embedding_profile"));
    assert!(String::from_utf8_lossy(&output.stderr).contains("doctor failed"));
    fixture.checked(&["setup", "--uninstall", "--purge", "--yes"]);
}

#[test]
fn setup_doctor_registered_mcp_search_and_owned_purge() {
    let fixture = Fixture::new();
    assert!(snapshot(&fixture.home).is_empty());
    fixture.checked(&["setup", "--dry-run"]);
    assert!(snapshot(&fixture.home).is_empty());
    assert!(fixture.gateway.requests.lock().unwrap().is_empty());
    let port = fs::read_to_string(fixture.temp.path().join("port")).unwrap();
    let llama = fixture.bin.join("llama-server");
    let args = [
        "setup",
        "--yes",
        "--profile",
        fixture.profile.to_str().unwrap(),
        "--llama-server",
        llama.to_str().unwrap(),
        "--daemon-port",
        &port,
    ];
    let output = fixture
        .command()
        .env("QDRANT_API_KEY", KEY)
        .args(args)
        .output()
        .unwrap();
    assert_redacted(&output);
    if !output.status.success() {
        let diagnosis = fixture.command().args(["update-index"]).output().unwrap();
        assert_redacted(&diagnosis);
        eprintln!(
            "updater diagnosis: {} routes: {:?}",
            String::from_utf8_lossy(&diagnosis.stderr),
            fixture.gateway.requests.lock().unwrap()
        );
        let diagnosis = fixture
            .command()
            .args(["doctor", "--json"])
            .output()
            .unwrap();
        assert_redacted(&diagnosis);
        let report: Value = serde_json::from_slice(&diagnosis.stdout).unwrap();
        for check in report["checks"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|v| v["status"] == "FAIL")
        {
            eprintln!("doctor diagnosis: {check}");
        }
    }
    assert!(
        output.status.success(),
        "stdout={} stderr={}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    let doctor = fixture.checked(&["doctor", "--json"]);
    assert_eq!(
        serde_json::from_slice::<Value>(&doctor.stdout).unwrap()["passed"],
        true
    );
    fixture.checked(&["config", "show"]);
    assert!(
        !fs::read_to_string(fixture.home.join("config/config.toml"))
            .unwrap()
            .contains(KEY)
    );
    let host_path = fixture.home.join("hosts/.claude.json");
    let mut host: Value = serde_json::from_slice(&fs::read(&host_path).unwrap()).unwrap();
    let registration = &host["mcpServers"]["code-diver"];
    assert_eq!(
        registration["env"]["CODE_DIVER_HOME"],
        fixture.home.to_str().unwrap()
    );
    assert_eq!(registration["command"], env!("CARGO_BIN_EXE_code-diver"));
    let mut command = fixture.command();
    let mut child = command
        .args(
            registration["args"]
                .as_array()
                .unwrap()
                .iter()
                .map(|v| v.as_str().unwrap()),
        )
        .envs(
            registration["env"]
                .as_object()
                .unwrap()
                .iter()
                .map(|(k, v)| (k, v.as_str().unwrap())),
        )
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    child.stdin.take().unwrap().write_all(b"{\"jsonrpc\":\"2.0\",\"id\":0,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2024-11-05\",\"capabilities\":{},\"clientInfo\":{\"name\":\"acceptance\",\"version\":\"1\"}}}\n{\"jsonrpc\":\"2.0\",\"method\":\"notifications/initialized\"}\n{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}\n").unwrap();
    let output = child.wait_with_output().unwrap();
    assert_redacted(&output);
    assert!(output.status.success());
    let response = String::from_utf8(output.stdout)
        .unwrap()
        .lines()
        .map(|line| serde_json::from_str::<Value>(line).unwrap())
        .find(|v| v["id"] == 1)
        .unwrap();
    assert_eq!(response["result"]["tools"].as_array().unwrap().len(), 6);
    fs::write(
        fixture.temp.path().join("scratch.rs"),
        "fn scratch_health() {}\n",
    )
    .unwrap();
    let output = fixture.checked(&["search", "scratch health"]);
    let search: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(search["rerank_applied"], true);
    assert_eq!(search["meta_ranker_applied"], true);
    assert!(
        String::from_utf8_lossy(&output.stdout).contains("scratch.rs"),
        "search stdout={} stderr={}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    let before = snapshot(&fixture.home);
    fixture.checked(&["setup", "--dry-run"]);
    assert_eq!(snapshot(&fixture.home), before);
    let downloads = fixture
        .gateway
        .requests
        .lock()
        .unwrap()
        .iter()
        .filter(|p| {
            p.starts_with("/models/")
                || (p.starts_with("/artifacts/") && !p.ends_with("index-metadata.json"))
        })
        .count();
    let config_before = fs::read(fixture.home.join("config/config.toml")).unwrap();
    let hosts_before = fs::read(&host_path).unwrap();
    fixture.checked(&args);
    assert_eq!(
        fs::read(fixture.home.join("config/config.toml")).unwrap(),
        config_before
    );
    assert_eq!(fs::read(&host_path).unwrap(), hosts_before);
    assert_eq!(
        fixture
            .gateway
            .requests
            .lock()
            .unwrap()
            .iter()
            .filter(|p| p.starts_with("/models/")
                || (p.starts_with("/artifacts/") && !p.ends_with("index-metadata.json")))
            .count(),
        downloads
    );
    assert!(
        !snapshot(&fixture.home)
            .keys()
            .any(|p| p.to_string_lossy().contains(".bak"))
    );
    let pointer = fixture.home.join("data/acceptance");
    let previous = fs::read_link(&pointer).unwrap();
    let previous_files = snapshot(&previous);
    let mut files = fixture.gateway.files.lock().unwrap();
    let mut metadata: Value =
        serde_json::from_slice(&files["/artifacts/acceptance/index-metadata.json"]).unwrap();
    metadata["files"]["rust_catalog.jsonl"]["sha256"] = json!(hash(b"expected replacement"));
    metadata["files"]["rust_catalog.jsonl"]["bytes"] = json!(20);
    files.insert(
        "/artifacts/acceptance/index-metadata.json".into(),
        metadata.to_string().into_bytes(),
    );
    files.insert(
        "/artifacts/acceptance/rust_catalog.jsonl".into(),
        b"corrupt replacement!".to_vec(),
    );
    drop(files);
    let output = fixture.command().args(["update-index"]).output().unwrap();
    assert!(!output.status.success());
    assert_redacted(&output);
    assert_eq!(fs::read_link(&pointer).unwrap(), previous);
    assert_eq!(snapshot(&previous), previous_files);
    let output = fixture
        .command()
        .env("QDRANT_API_KEY", "wrong-key")
        .args(["doctor", "--json"])
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(1));
    assert_redacted(&output);
    assert!(!String::from_utf8_lossy(&output.stdout).contains("wrong-key"));
    fixture.checked(&["doctor", "--json"]);
    host["mcpServers"]["unrelated"] = json!({"command":"preserve-me"});
    fs::write(&host_path, host.to_string()).unwrap();
    fs::write(fixture.home.join("cache/models/unrelated.gguf"), "preserve").unwrap();
    fixture.checked(&["setup", "--uninstall", "--purge", "--yes"]);
    let host: Value = serde_json::from_slice(&fs::read(host_path).unwrap()).unwrap();
    assert_eq!(host["mcpServers"]["unrelated"]["command"], "preserve-me");
    assert!(host["mcpServers"].get("code-diver").is_none());
    assert!(!fixture.home.join("cache/models/embedder.gguf").exists());
    assert!(!fixture.home.join("cache/models/reranker.gguf").exists());
    assert!(fixture.home.join("cache/models/unrelated.gguf").exists());
    assert!(!fixture.home.join("config/secrets/qdrant").exists());
    assert!(!fixture.home.join("config/config.toml").exists());
    assert!(!pointer.exists());
    for (path, bytes) in snapshot(&fixture.home) {
        if path
            .file_name()
            .is_some_and(|name| name == "manager-args" || name == "llama-args")
        {
            assert!(!String::from_utf8_lossy(&bytes).contains(KEY));
        }
    }
}

#[test]
fn piped_installer_prompts_profile_and_hidden_key_once_via_controlling_tty() {
    let fixture = Fixture::new();
    let port = fs::read_to_string(fixture.temp.path().join("port")).unwrap();
    let mut command = fixture.command();
    command.args(["setup", "--daemon-port", &port]);
    let output = pty_setup(command, fixture.profile.to_str().unwrap(), KEY);
    assert_redacted(&output);
    assert!(
        output.status.success(),
        "stdout={} stderr={}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    let transcript = String::from_utf8_lossy(&output.stdout);
    assert_eq!(transcript.matches("Team profile URL or file: ").count(), 1);
    assert_eq!(transcript.matches("Read-only Qdrant key: ").count(), 1);
    let config: toml::Value =
        toml::from_str(&fs::read_to_string(fixture.home.join("config/config.toml")).unwrap())
            .unwrap();
    for role in ["qdrant", "artifacts"] {
        assert_eq!(config["secrets"][role], config["secrets"]["qdrant"]);
    }
    assert_eq!(config["secrets"]["qdrant"]["source"].as_str(), Some("file"));
    assert_eq!(
        fs::read_to_string(fixture.home.join("config/secrets/qdrant")).unwrap(),
        KEY
    );
    fixture.checked(&["doctor", "--json"]);
    fixture.checked(&["setup", "--uninstall", "--purge", "--yes"]);
}
