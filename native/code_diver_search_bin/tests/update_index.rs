#![allow(dead_code)]
#[path = "../src/embedding.rs"]
mod embedding;
#[path = "../src/fusion.rs"]
mod fusion;
#[path = "../src/index_net.rs"]
mod index_net;
#[path = "../src/metadata.rs"]
mod metadata;
#[path = "../src/model_store.rs"]
mod model_store;
#[path = "../src/runtime_config.rs"]
mod runtime_config;
#[path = "../src/types.rs"]
mod types;
#[path = "../src/update_index.rs"]
mod update_index;

use runtime_config::{
    FileSecretStore, Platform, RuntimeConfig, RuntimePaths, SecretRef, SecretStore, SecretValue,
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::fs;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use update_index::{UpdateOptions, update, update_with_options, update_with_recorder};

const TOKEN: &str = "synthetic-artifact-secret";
const RANKER: &[u8] = b"synthetic ranker artifact; updater verifies bytes, not model syntax";

fn fixture(data: &[u8]) -> Value {
    let mut metadata: Value =
        serde_json::from_slice(include_bytes!("fixtures/shared-index-metadata.json")).unwrap();
    metadata["files"] = json!({"context/catalog.jsonl": {"sha256": format!("{:x}", Sha256::digest(data)), "bytes": data.len()}});
    let ranker = metadata["meta_ranker"]["file"]
        .as_str()
        .unwrap()
        .to_string();
    metadata["files"][&ranker] =
        json!({"sha256": format!("{:x}", Sha256::digest(RANKER)), "bytes": RANKER.len()});
    metadata
}

fn setup() -> (tempfile::TempDir, RuntimePaths, RuntimeConfig) {
    let temp = tempfile::tempdir().unwrap();
    let paths = RuntimePaths::from_env(Platform::MacOs, |key| {
        (key == "CODE_DIVER_HOME").then(|| temp.path().display().to_string())
    })
    .unwrap();
    FileSecretStore::new(&paths)
        .put("artifacts", &SecretValue::new(TOKEN.into()).unwrap())
        .unwrap();
    let mut config = RuntimeConfig::default();
    config.profile.index_name = Some("test".into());
    config
        .secrets
        .insert("artifacts".into(), SecretRef::File("artifacts".into()));
    (temp, paths, config)
}

struct Reply {
    path: &'static str,
    response: Vec<u8>,
    range: Option<&'static str>,
}

fn metadata_reply(value: &Value) -> Reply {
    reply(
        "/base/test/index-metadata.json",
        &serde_json::to_vec(value).unwrap(),
    )
}
fn reply(path: &'static str, data: &[u8]) -> Reply {
    let mut response = format!(
        "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        data.len()
    )
    .into_bytes();
    response.extend_from_slice(data);
    Reply {
        path,
        response,
        range: None,
    }
}

async fn server(replies: Vec<Reply>) -> (String, tokio::task::JoinHandle<()>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}/base", listener.local_addr().unwrap());
    let task = tokio::spawn(async move {
        for reply in replies {
            loop {
                let (mut stream, _) =
                    tokio::time::timeout(std::time::Duration::from_secs(5), listener.accept())
                        .await
                        .unwrap()
                        .unwrap();
                let mut request = Vec::new();
                while !request.ends_with(b"\r\n\r\n") {
                    request.push(stream.read_u8().await.unwrap());
                }
                let request = String::from_utf8(request).unwrap();
                if request.starts_with(
                    "GET /base/test/artifacts/ce_meta_ranker/ce_meta_ranker.lgb.txt HTTP/1.1",
                ) {
                    assert!(request.contains(&format!("Bearer {TOKEN}")));
                    stream
                        .write_all(&self::reply("", RANKER).response)
                        .await
                        .unwrap();
                    stream.shutdown().await.unwrap();
                    continue;
                }
                assert!(
                    request.starts_with(&format!("GET {} HTTP/1.1", reply.path)),
                    "unexpected request path"
                );
                if reply.path == "/manifest" {
                    assert!(!request.to_lowercase().contains("authorization:"));
                    assert!(!request.contains(TOKEN));
                } else {
                    assert!(request.contains(&format!("Bearer {TOKEN}")));
                }
                if let Some(range) = reply.range {
                    assert!(request.to_lowercase().contains(range));
                }
                stream.write_all(&reply.response).await.unwrap();
                stream.shutdown().await.unwrap();
                break;
            }
        }
    });
    (url, task)
}

#[tokio::test]
async fn updater_atomic_snapshot_previous_idempotence_and_corruption() {
    let (_temp, paths, mut config) = setup();
    let first = fixture(b"oldold");
    let second = fixture(b"abcdef");
    let (url, task) = server(vec![
        metadata_reply(&first),
        reply("/base/test/context/catalog.jsonl", b"oldold"),
        metadata_reply(&second),
        reply("/base/test/context/catalog.jsonl", b"badbad"),
        metadata_reply(&second),
        reply("/base/test/context/catalog.jsonl", b"abcdef"),
        metadata_reply(&second),
    ])
    .await;
    config.profile.artifact_url = Some(url);
    let old = update(&config, &paths).await.unwrap();
    let pointer = paths.data.join("test");
    assert_eq!(
        fs::read(pointer.join("context/catalog.jsonl")).unwrap(),
        b"oldold"
    );
    let error = update(&config, &paths).await.unwrap_err();
    assert!(!format!("{error:#}").contains(TOKEN));
    assert_eq!(fs::read_link(&pointer).unwrap(), old.snapshot);
    let new = update(&config, &paths).await.unwrap();
    assert_eq!(new.previous.as_ref(), Some(&old.snapshot));
    assert!(!new.created_artifacts.iter().any(|v| v.path == pointer));
    assert!(
        new.created_artifacts
            .iter()
            .any(|v| v.path == paths.data.join(".test-previous"))
    );
    assert!(!new.created_artifacts.iter().any(|v| v.path == old.snapshot));
    assert_eq!(
        fs::read_link(paths.data.join(".test-previous")).unwrap(),
        old.snapshot
    );
    assert_eq!(
        fs::read(old.snapshot.join("context/catalog.jsonl")).unwrap(),
        b"oldold"
    );
    assert_eq!(
        fs::read(pointer.join("context/catalog.jsonl")).unwrap(),
        b"abcdef"
    );
    assert_eq!(
        fs::read(new.snapshot.join("index-metadata.json")).unwrap(),
        serde_json::to_vec(&second).unwrap()
    );
    let same = update(&config, &paths).await.unwrap();
    assert!(!same.changed);
    assert_eq!(same.downloaded_files, 0);
    task.await.unwrap();
}

#[tokio::test]
async fn updater_interrupted_resume_bad_range_and_ignored_range() {
    let (_temp, paths, mut config) = setup();
    let metadata = fixture(b"abcdef");
    let interrupted = Reply {
        path: "/base/test/context/catalog.jsonl",
        range: None,
        response: b"HTTP/1.1 200 OK\r\nContent-Length: 6\r\nConnection: close\r\n\r\nabc".to_vec(),
    };
    let bad = Reply { path: interrupted.path, range: Some("range: bytes=3-"),
        response: b"HTTP/1.1 206 Partial Content\r\nContent-Length: 3\r\nContent-Range: bytes 0-2/6\r\nConnection: close\r\n\r\ndef".to_vec() };
    let resumed = Reply { path: interrupted.path, range: Some("range: bytes=3-"),
        response: b"HTTP/1.1 206 Partial Content\r\nContent-Length: 3\r\nContent-Range: bytes 3-5/6\r\nConnection: close\r\n\r\ndef".to_vec() };
    let (url, task) = server(vec![
        metadata_reply(&metadata),
        interrupted,
        metadata_reply(&metadata),
        bad,
        metadata_reply(&metadata),
        resumed,
    ])
    .await;
    config.profile.artifact_url = Some(url);
    assert!(update(&config, &paths).await.is_err());
    assert!(!paths.data.join("test").exists());
    assert!(update(&config, &paths).await.is_err());
    let result = update(&config, &paths).await.unwrap();
    assert_eq!(result.resumed_bytes, 3);
    assert_eq!(
        fs::read(result.snapshot.join("context/catalog.jsonl")).unwrap(),
        b"abcdef"
    );
    task.await.unwrap();

    let (_temp, paths, mut config) = setup();
    let (url, task) = server(vec![
        metadata_reply(&metadata),
        Reply {
            path: "/base/test/context/catalog.jsonl",
            range: None,
            response: b"HTTP/1.1 200 OK\r\nContent-Length: 6\r\nConnection: close\r\n\r\nabc"
                .to_vec(),
        },
        metadata_reply(&metadata),
        reply("/base/test/context/catalog.jsonl", b"abcdef"),
    ])
    .await;
    config.profile.artifact_url = Some(url);
    assert!(update(&config, &paths).await.is_err());
    assert_eq!(update(&config, &paths).await.unwrap().resumed_bytes, 0);
    task.await.unwrap();
}

#[tokio::test]
async fn updater_rejects_model_schema_size_hash_and_unsafe_paths_before_writes() {
    let (_temp, paths, mut config) = setup();
    let original = fixture(b"abcdef");
    let mut cases = Vec::new();
    for (key, value) in [
        ("model", json!("other")),
        ("dimensions", json!(17)),
        ("sha256", json!("0".repeat(64))),
        ("model_repo", json!("wrong")),
        ("model_file", json!("wrong")),
        ("max_input_chars", json!(1)),
        ("max_input_tokens", json!(1)),
        ("token_safety_margin", json!(1)),
    ] {
        let mut bad = original.clone();
        bad["embedding"][key] = value;
        cases.push(bad);
    }
    for name in [
        "../escape",
        "/absolute",
        "a//b",
        "a/./b",
        "a/../b",
        "a\\b",
        "a%2fb",
        "a?b",
        "a#b",
        "index-metadata.json",
        "a/",
    ] {
        let mut bad = original.clone();
        bad["files"] = json!({name: original["files"]["context/catalog.jsonl"]});
        cases.push(bad);
    }
    let mut bad = original.clone();
    bad["schema"] = json!(1);
    cases.push(bad);
    let mut bad = original.clone();
    bad["files"]["context/catalog.jsonl"]["bytes"] = json!(-1);
    cases.push(bad);
    let mut bad = original.clone();
    bad["files"]["context/catalog.jsonl"]["sha256"] = json!("nope");
    cases.push(bad);
    let mut bad = original.clone();
    bad["files"]["context"] = original["files"]["context/catalog.jsonl"].clone();
    cases.push(bad);
    let (url, task) = server(cases.iter().map(metadata_reply).collect()).await;
    config.profile.artifact_url = Some(url);
    for _ in cases {
        let error = update(&config, &paths).await.unwrap_err();
        assert!(!format!("{error:#}").contains(TOKEN));
        assert!(!paths.data.exists());
    }
    task.await.unwrap();
}

#[tokio::test]
async fn updater_dryrun_override_and_transport_policy() {
    let (temp, paths, mut config) = setup();
    let mut manifest: Value = serde_json::from_str(model_store::EMBEDDED_MANIFEST).unwrap();
    for (key, value) in [
        ("max_input_chars", 2000),
        ("max_input_tokens", 512),
        ("token_safety_margin", 32),
    ] {
        manifest["models"]["embedder"][key] = json!(value);
    }
    let manifest_path = temp.path().join("manifest.json");
    fs::write(&manifest_path, serde_json::to_vec(&manifest).unwrap()).unwrap();
    let metadata = fixture(b"abcdef");
    let (url, task) = server(vec![metadata_reply(&metadata)]).await;
    config.profile.artifact_url = Some(url);
    let outcome = update_with_options(
        &config,
        &paths,
        UpdateOptions {
            dry_run: true,
            model_manifest: Some(&manifest_path),
            keychain: None,
        },
    )
    .await
    .unwrap();
    assert!(outcome.changed && outcome.dry_run);
    assert!(!paths.data.exists());
    task.await.unwrap();
    for url in [
        "http://example.com/base",
        "https://user:secret@example.com",
        "https://example.com?secret",
    ] {
        config.profile.artifact_url = Some(url.into());
        assert!(update(&config, &paths).await.is_err());
    }
}

#[tokio::test]
async fn updater_preserves_unmanaged_directory_and_rejects_symlinks() {
    let (_temp, paths, mut config) = setup();
    fs::create_dir_all(paths.data.join("test")).unwrap();
    fs::write(paths.data.join("test/old"), b"preserved").unwrap();
    let (url, task) = server(vec![metadata_reply(&fixture(b"abcdef"))]).await;
    config.profile.artifact_url = Some(url);
    assert!(update(&config, &paths).await.is_err());
    assert_eq!(fs::read(paths.data.join("test/old")).unwrap(), b"preserved");
    task.await.unwrap();
    #[cfg(unix)]
    {
        fs::remove_file(paths.data.join("test/old")).unwrap();
        fs::remove_dir(paths.data.join("test")).unwrap();
        std::os::unix::fs::symlink(&paths.secrets, paths.data.join("test")).unwrap();
        let (url, task) = server(vec![metadata_reply(&fixture(b"abcdef"))]).await;
        config.profile.artifact_url = Some(url);
        assert!(update(&config, &paths).await.is_err());
        task.await.unwrap();
    }
}

#[tokio::test]
async fn updater_multiple_files_empty_artifact_staging_recovery_and_lock() {
    let (_temp, paths, mut config) = setup();
    let mut metadata = fixture(b"abcdef");
    metadata["files"]["graph.json"] =
        json!({"sha256": format!("{:x}", Sha256::digest(b"graph")), "bytes": 5});
    metadata["files"]["empty.jsonl"] =
        json!({"sha256": format!("{:x}", Sha256::digest([])), "bytes": 0});
    let version = format!(
        "{:x}",
        Sha256::digest(serde_json::to_vec(&metadata).unwrap())
    );
    let staging = paths
        .data
        .join(format!(".test-snapshots/{version}.staging"));
    fs::create_dir_all(&staging).unwrap();
    fs::write(staging.join("incomplete"), b"interrupted assembly").unwrap();
    let cache = paths.data.join(format!(
        ".test-downloads/{:x}",
        Sha256::digest(format!(
            "context/catalog.jsonl:{}:6",
            metadata["files"]["context/catalog.jsonl"]["sha256"]
                .as_str()
                .unwrap()
        ))
    ));
    fs::create_dir_all(&cache).unwrap();
    fs::write(cache.join("artifact.lock"), b"stale killed download").unwrap();
    fs::write(cache.join("artifact.part"), b"abc").unwrap();
    let (url, task) = server(vec![metadata_reply(&metadata), metadata_reply(&metadata), Reply {
        path: "/base/test/context/catalog.jsonl", range: Some("range: bytes=3-"),
        response: b"HTTP/1.1 206 Partial Content\r\nContent-Length: 3\r\nContent-Range: bytes 3-5/6\r\nConnection: close\r\n\r\ndef".to_vec(),
    }, reply("/base/test/graph.json", b"graph")]).await;
    config.profile.artifact_url = Some(url);
    let lock = fs::OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(false)
        .open(paths.data.join(".test-update.lock"))
        .unwrap();
    lock.try_lock().unwrap();
    assert!(
        update(&config, &paths)
            .await
            .unwrap_err()
            .to_string()
            .contains("already active")
    );
    lock.unlock().unwrap();
    drop(lock);
    let outcome = update(&config, &paths).await.unwrap();
    assert_eq!(outcome.resumed_bytes, 3);
    assert!(!outcome.snapshot.join("incomplete").exists());
    assert_eq!(
        fs::read(outcome.snapshot.join("context/catalog.jsonl")).unwrap(),
        b"abcdef"
    );
    assert_eq!(
        fs::read(outcome.snapshot.join("graph.json")).unwrap(),
        b"graph"
    );
    assert_eq!(fs::read(outcome.snapshot.join("empty.jsonl")).unwrap(), b"");
    task.await.unwrap();
}

#[tokio::test]
async fn updater_rejects_status_redirect_and_wrong_response_length() {
    let (_temp, paths, mut config) = setup();
    for response in [
        format!(
            "HTTP/1.1 401 Unauthorized\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{TOKEN}",
            TOKEN.len()
        ),
        format!(
            "HTTP/1.1 302 Found\r\nLocation: http://127.0.0.1:1/{TOKEN}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
        ),
    ] {
        let (url, task) = server(vec![Reply {
            path: "/base/test/index-metadata.json",
            range: None,
            response: response.into_bytes(),
        }])
        .await;
        config.profile.artifact_url = Some(url);
        let error = update(&config, &paths).await.unwrap_err();
        assert!(!format!("{error:#}").contains(TOKEN));
        assert!(!paths.data.exists());
        task.await.unwrap();
    }
    let (url, task) = server(vec![
        metadata_reply(&fixture(b"abcdef")),
        reply("/base/test/context/catalog.jsonl", b"short"),
    ])
    .await;
    config.profile.artifact_url = Some(url);
    assert!(update(&config, &paths).await.is_err());
    assert!(!paths.data.join("test").exists());
    task.await.unwrap();
}

#[tokio::test]
async fn updater_https_rejects_untrusted_certificate_without_panic_or_secret() {
    use std::io::{BufRead, BufReader};
    use std::process::{Command, Stdio};
    let (temp, paths, mut config) = setup();
    let output = Command::new("openssl")
        .current_dir(temp.path())
        .args([
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            "key.pem",
            "-out",
            "cert.pem",
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=IP:127.0.0.1",
        ])
        .output()
        .unwrap();
    assert!(output.status.success());
    struct Server(std::process::Child);
    impl Drop for Server {
        fn drop(&mut self) {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }
    let mut server = Server(Command::new("node").current_dir(temp.path()).args(["-e", r#"
        const fs=require('node:fs'), https=require('node:https');
        const server=https.createServer({key:fs.readFileSync('key.pem'),cert:fs.readFileSync('cert.pem')},(req,res)=>{
            fs.writeFileSync('unexpected-request','request');res.end('{}');
        });
        server.listen(0,'127.0.0.1',()=>console.log('https://127.0.0.1:'+server.address().port));
    "#]).stdout(Stdio::piped()).spawn().unwrap());
    let mut url = String::new();
    BufReader::new(server.0.stdout.take().unwrap())
        .read_line(&mut url)
        .unwrap();
    config.profile.artifact_url = Some(url.trim().into());
    let error = update(&config, &paths).await.unwrap_err();
    assert!(!format!("{error:#}").contains(TOKEN));
    assert!(!temp.path().join("unexpected-request").exists());
    assert!(!paths.data.exists());
}

#[tokio::test]
async fn updater_profile_local_manifest_and_fail_closed_limits() {
    let (temp, paths, mut config) = setup();
    let manifest_path = temp.path().join("model-manifest.json");
    let mut manifest: Value = serde_json::from_str(model_store::EMBEDDED_MANIFEST).unwrap();
    manifest["models"]["embedder"]["model"] = json!("local-model");
    for (key, value) in [
        ("max_input_chars", 2000),
        ("max_input_tokens", 512),
        ("token_safety_margin", 32),
    ] {
        manifest["models"]["embedder"][key] = json!(value);
    }
    fs::write(&manifest_path, serde_json::to_vec(&manifest).unwrap()).unwrap();
    config.profile.model_manifest_path = Some(manifest_path.clone());
    let mut metadata = fixture(b"abcdef");
    metadata["embedding"]["model"] = json!("local-model");
    let (url, task) = server(vec![
        metadata_reply(&metadata),
        metadata_reply(&metadata),
        metadata_reply(&metadata),
    ])
    .await;
    config.profile.artifact_url = Some(url);
    assert!(
        update_with_options(
            &config,
            &paths,
            UpdateOptions {
                dry_run: true,
                ..Default::default()
            }
        )
        .await
        .is_ok()
    );
    manifest["models"]["embedder"]
        .as_object_mut()
        .unwrap()
        .remove("max_input_tokens");
    fs::write(&manifest_path, serde_json::to_vec(&manifest).unwrap()).unwrap();
    assert!(update(&config, &paths).await.is_err());
    config.profile.model_manifest_path = None;
    config.profile.model_manifest_url = Some("https://example.invalid/manifest.json".into());
    assert!(update(&config, &paths).await.is_err());
    assert!(!paths.data.exists());
    task.await.unwrap();
}

#[tokio::test]
async fn updater_profile_remote_manifest_identity_and_secret_isolation() {
    let (_temp, paths, mut config) = setup();
    let mut manifest: Value = serde_json::from_str(model_store::EMBEDDED_MANIFEST).unwrap();
    manifest["models"]["embedder"]["repo"] = json!("test/remote-model-GGUF");
    manifest["models"]["embedder"]["model"] = json!("explicit-remote-model");
    for (field, value) in [
        ("max_input_chars", 2000),
        ("max_input_tokens", 512),
        ("token_safety_margin", 32),
    ] {
        manifest["models"]["embedder"][field] = json!(value);
    }
    let mut metadata = fixture(b"abcdef");
    metadata["embedding"]["model"] = json!("explicit-remote-model");
    metadata["embedding"]["model_repo"] = manifest["models"]["embedder"]["repo"].clone();
    let (manifest_url, manifest_task) = server(vec![
        reply("/manifest", &serde_json::to_vec(&manifest).unwrap()),
        reply("/manifest", &serde_json::to_vec(&manifest).unwrap()),
        reply("/manifest", &serde_json::to_vec(&manifest).unwrap()),
    ])
    .await;
    config.profile.model_manifest_url = Some(manifest_url.replace("/base", "/manifest"));
    let mut mismatch = metadata.clone();
    mismatch["embedding"]["model"] = json!("wrong-model");
    let mut limits = metadata.clone();
    limits["embedding"]["max_input_tokens"] = json!(513);
    let (url, task) = server(vec![
        metadata_reply(&metadata),
        metadata_reply(&mismatch),
        metadata_reply(&limits),
    ])
    .await;
    config.profile.artifact_url = Some(url);
    update_with_options(
        &config,
        &paths,
        UpdateOptions {
            dry_run: true,
            ..Default::default()
        },
    )
    .await
    .unwrap();
    let error = update(&config, &paths).await.unwrap_err();
    assert!(error.to_string().contains("mismatch"));
    assert!(!format!("{error:#}").contains(TOKEN));
    let error = update(&config, &paths).await.unwrap_err();
    assert!(error.to_string().contains("input limits"));
    assert!(!paths.data.exists());
    task.await.unwrap();
    manifest_task.await.unwrap();
}

#[tokio::test]
async fn updater_reports_only_new_ownership_before_publication() {
    use update_index::ArtifactKind;
    let (_temp, paths, mut config) = setup();
    fs::create_dir_all(paths.data.join(".test-snapshots")).unwrap();
    fs::create_dir_all(paths.data.join(".test-downloads")).unwrap();
    let metadata = fixture(b"abcdef");
    let (url, task) = server(vec![
        metadata_reply(&metadata),
        reply("/base/test/context/catalog.jsonl", b"abcdef"),
        metadata_reply(&metadata),
    ])
    .await;
    config.profile.artifact_url = Some(url);
    let recorded = std::sync::Mutex::new(Vec::new());
    let record = |created: &[update_index::CreatedArtifact]| {
        assert!(!paths.data.join("test").exists());
        // The lock remains held while the caller durably records ownership.
        let lock = fs::OpenOptions::new()
            .write(true)
            .open(paths.data.join(".test-update.lock"))
            .unwrap();
        assert!(lock.try_lock().is_err());
        *recorded.lock().unwrap() = created.to_vec();
        Ok(())
    };
    let outcome = update_with_recorder(&config, &paths, UpdateOptions::default(), Some(&record))
        .await
        .unwrap();
    assert_eq!(outcome.created_artifacts, *recorded.lock().unwrap());
    for path in [
        &paths.data,
        &paths.data.join(".test-snapshots"),
        &paths.data.join(".test-downloads"),
    ] {
        assert!(!outcome.created_artifacts.iter().any(|v| &v.path == path));
    }
    assert!(
        outcome
            .created_artifacts
            .iter()
            .any(|v| v.path == outcome.snapshot && v.kind == ArtifactKind::Directory)
    );
    assert!(
        outcome
            .created_artifacts
            .iter()
            .any(|v| v.path == outcome.snapshot.join("context/catalog.jsonl")
                && v.kind == ArtifactKind::File)
    );
    assert!(
        outcome
            .created_artifacts
            .iter()
            .any(|v| v.path == paths.data.join("test")
                && v.kind
                    == ArtifactKind::Symlink {
                        target: outcome.snapshot.clone()
                    })
    );
    assert!(
        update(&config, &paths)
            .await
            .unwrap()
            .created_artifacts
            .is_empty()
    );
    task.await.unwrap();
}

#[tokio::test]
async fn updater_ownership_record_failure_prevents_publication() {
    let (_temp, paths, mut config) = setup();
    let metadata = fixture(b"abcdef");
    let (url, task) = server(vec![
        metadata_reply(&metadata),
        reply("/base/test/context/catalog.jsonl", b"abcdef"),
    ])
    .await;
    config.profile.artifact_url = Some(url);
    let record = |created: &[update_index::CreatedArtifact]| {
        assert!(created.iter().any(|v| v.path == paths.data));
        assert!(created.iter().any(|v| v.path == paths.data.join("test")));
        anyhow::bail!("ownership storage unavailable")
    };
    let error = update_with_recorder(&config, &paths, UpdateOptions::default(), Some(&record))
        .await
        .unwrap_err();
    assert!(error.to_string().contains("ownership storage"));
    assert!(!paths.data.join("test").exists());
    task.await.unwrap();
}

#[tokio::test]
async fn updater_records_interrupted_transfer_remnants_not_preexisting_paths() {
    let (_temp, paths, mut config) = setup();
    fs::create_dir_all(&paths.data).unwrap();
    let metadata = fixture(b"abcdef");
    let mut interrupted = reply("/base/test/context/catalog.jsonl", b"abcdef");
    interrupted
        .response
        .truncate(interrupted.response.len() - 3);
    let (url, task) = server(vec![metadata_reply(&metadata), interrupted]).await;
    config.profile.artifact_url = Some(url);
    let recorded = std::sync::Mutex::new(Vec::new());
    let record = |created: &[update_index::CreatedArtifact]| {
        *recorded.lock().unwrap() = created.to_vec();
        Ok(())
    };
    assert!(
        update_with_recorder(&config, &paths, UpdateOptions::default(), Some(&record))
            .await
            .is_err()
    );
    let recorded = recorded.lock().unwrap().clone();
    assert!(!recorded.iter().any(|v| v.path == paths.data));
    assert!(
        recorded
            .iter()
            .any(|v| v.path.file_name().unwrap() == "artifact.part")
    );
    assert!(
        !recorded
            .iter()
            .any(|v| matches!(v.kind, update_index::ArtifactKind::Symlink { .. }))
    );
    assert!(!paths.data.join("test").exists());
    task.await.unwrap();
}
