#[path = "../src/embedding.rs"]
pub mod embedding;
#[path = "../src/fusion.rs"]
pub mod fusion;
#[path = "../src/index_net.rs"]
pub mod index_net;
#[path = "../src/mcp_registration.rs"]
pub mod mcp_registration;
#[path = "../src/metadata.rs"]
pub mod metadata;
#[path = "../src/model_store.rs"]
pub mod model_store;
#[path = "../src/runtime_config.rs"]
pub mod runtime_config;
#[path = "../src/service_manager.rs"]
pub mod service_manager;
#[path = "../src/setup.rs"]
pub mod setup;
#[path = "../src/types.rs"]
pub mod types;
#[path = "../src/update_index.rs"]
pub mod update_index;

use runtime_config::{Platform, RuntimePaths, SecretValue};
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;

fn script(path: &Path, body: &str) {
    fs::write(path, format!("#!/bin/sh\n{body}\n")).unwrap();
    fs::set_permissions(path, fs::Permissions::from_mode(0o700)).unwrap();
}
fn options(home: &Path, platform: Platform) -> setup::SetupOptions {
    let paths = RuntimePaths::from_env(platform, |k| {
        (k == "CODE_DIVER_HOME").then(|| home.display().to_string())
    })
    .unwrap();
    let mut options = setup::SetupOptions::new(paths, home.join("code diver"), platform, 501);
    options.manager = home.join("manager");
    options.no_register = true;
    script(
        &options.manager,
        &format!(
            "printf '%s\\n' \"$@\" >> '{}/commands'\ncase \"$*\" in\n*is-active*|print*) test -f '{}/active';;\n*disable*|bootout*) rm -f '{}/active';;\n*enable*|bootstrap*) touch '{}/active';;\n*) exit 0;;\nesac",
            home.display(),
            home.display(),
            home.display(),
            home.display()
        ),
    );
    options
}
struct Interaction(usize);
impl setup::Interaction for Interaction {
    fn confirm_brew(&mut self) -> anyhow::Result<bool> {
        panic!("must not install")
    }
    fn read_key(&mut self) -> anyhow::Result<SecretValue> {
        self.0 += 1;
        SecretValue::new("SECRET_SENTINEL".into())
    }
}
struct Hooks(Vec<&'static str>);
impl setup::SetupHooks for Hooks {
    fn update_index<'a>(
        &'a mut self,
        _: &'a runtime_config::RuntimeConfig,
        _: &'a RuntimePaths,
    ) -> std::pin::Pin<Box<dyn std::future::Future<Output = anyhow::Result<()>> + 'a>> {
        Box::pin(async move {
            self.0.push("update");
            Ok(())
        })
    }
    fn doctor(&mut self, command: &service_manager::CommandPlan) -> anyhow::Result<bool> {
        self.0.push("doctor");
        command.execute()
    }
}
#[tokio::test]
async fn dry_run_no_effects_even_remote_profile_and_key() {
    let temp = tempfile::tempdir().unwrap();
    let home = fs::canonicalize(temp.path()).unwrap();
    let mut o = options(&home, Platform::Linux);
    o.dry_run = true;
    o.profile = Some("https://invalid.invalid/profile".into());
    o.key_file = Some(home.join("missing"));
    let mut i = Interaction(0);
    let mut h = Hooks(Vec::new());
    assert_eq!(
        setup::run(&o, &mut i, &mut h).await.unwrap().actions.len(),
        8
    );
    assert_eq!(i.0, 0);
    assert!(h.0.is_empty());
    assert!(!o.paths.config.exists());
    assert!(!home.join("commands").exists());
    o.uninstall = true;
    o.purge = true;
    setup::run(&o, &mut i, &mut h).await.unwrap();
    assert!(!home.join("commands").exists());
}
#[test]
fn fake_managers_idempotent_repair_uninstall_and_unowned() {
    for platform in [Platform::Linux, Platform::MacOs] {
        let temp = tempfile::tempdir().unwrap();
        let home = fs::canonicalize(temp.path()).unwrap();
        let o = options(&home, platform);
        let p = service_manager::plan(&service_manager::ServiceOptions {
            platform,
            paths: o.paths.clone(),
            executable: o.executable,
            config: o.config,
            manager: o.manager,
            uid: 501,
        })
        .unwrap();
        assert!(p.contents.contains("CODE_DIVER_HOME"));
        assert!(!p.contents.contains("SECRET_SENTINEL"));
        service_manager::apply(&p, false, true).unwrap();
        assert!(!p.path.exists());
        assert!(!home.join("commands").exists());
        assert!(service_manager::apply(&p, false, false).unwrap());
        let meta = fs::metadata(&p.path).unwrap().modified().unwrap();
        assert!(!service_manager::apply(&p, false, false).unwrap());
        assert_eq!(meta, fs::metadata(&p.path).unwrap().modified().unwrap());
        fs::remove_file(home.join("active")).unwrap();
        service_manager::apply(&p, false, false).unwrap();
        assert!(home.join("active").exists());
        service_manager::apply(&p, true, false).unwrap();
        assert!(!p.path.exists());
        assert!(!service_manager::apply(&p, true, false).unwrap());
        fs::write(&p.path, "personal service").unwrap();
        assert!(service_manager::apply(&p, true, false).is_err());
        assert_eq!(fs::read_to_string(&p.path).unwrap(), "personal service");
    }
}
#[tokio::test]
async fn setup_twice_prompt_once_doctor_last_owned_purge() {
    let temp = tempfile::tempdir().unwrap();
    let home = fs::canonicalize(temp.path()).unwrap();
    let mut o = options(&home, Platform::Linux);
    script(
        &o.executable,
        &format!("printf '%s\\n' \"$@\" > '{}/doctor-args'", home.display()),
    );
    let llama = home.join("llama-server");
    script(&llama, "echo 'version: 9430 (test)'");
    o.llama_server = Some(llama);
    let mut manifest = model_store::ModelManifest::embedded().unwrap();
    use sha2::{Digest, Sha256};
    fs::create_dir_all(&o.paths.models).unwrap();
    for (spec, file) in [
        (&mut manifest.models.embedder, "embed.gguf"),
        (&mut manifest.models.reranker, "rank.gguf"),
    ] {
        spec.file = file.into();
        spec.size = 3;
        spec.sha256 = format!("{:x}", Sha256::digest(b"abc"));
        fs::write(o.paths.models.join(file), b"abc").unwrap();
    }
    // Repair a preexisting embedder, but download a new reranker over loopback.
    fs::write(o.paths.models.join("embed.gguf"), b"bad").unwrap();
    fs::write(o.paths.models.join("embed.gguf.part"), b"abc").unwrap();
    fs::remove_file(o.paths.models.join("rank.gguf")).unwrap();
    let manifest_file = home.join("manifest.json");
    let mut local_manifest = serde_json::to_value(&manifest).unwrap();
    local_manifest["models"]["embedder"]["max_input_chars"] = 2000.into();
    local_manifest["models"]["embedder"]["max_input_tokens"] = 512.into();
    local_manifest["models"]["embedder"]["token_safety_margin"] = 32.into();
    fs::write(&manifest_file, serde_json::to_vec(&local_manifest).unwrap()).unwrap();
    // The profile URL contract permits loopback HTTP; use an HTTP manifest fixture.
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    manifest.models.reranker.url = format!("http://{address}/rank.gguf");
    let body = serde_json::to_vec(&manifest).unwrap();
    let server = std::thread::spawn(move || {
        use std::io::{Read, Write};
        for (path, body) in [
            ("/manifest", body.clone()),
            ("/rank.gguf", b"abc".to_vec()),
            ("/manifest", body),
        ] {
            let (mut s, _) = listener.accept().unwrap();
            s.set_nonblocking(false).unwrap();
            s.set_read_timeout(Some(std::time::Duration::from_secs(5)))
                .unwrap();
            let mut header = Vec::new();
            while !header.ends_with(b"\r\n\r\n") {
                assert!(header.len() < 8192);
                let mut byte = [0];
                s.read_exact(&mut byte).unwrap();
                header.push(byte[0]);
            }
            assert!(
                String::from_utf8(header)
                    .unwrap()
                    .starts_with(&format!("GET {path} HTTP/1.1"))
            );
            write!(
                s,
                "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                body.len()
            )
            .unwrap();
            s.write_all(&body).unwrap();
        }
    });
    o.flags = toml::from_str(&format!(
        "[profile]\nmodel_manifest_url='http://{address}/manifest'\n"
    ))
    .unwrap();
    let mut i = Interaction(0);
    let mut h = Hooks(Vec::new());
    setup::run(&o, &mut i, &mut h).await.unwrap();
    let mut config = runtime_config::load_config(&o.config).unwrap();
    assert_eq!(
        config.secrets.get("artifacts"),
        config.secrets.get("qdrant")
    );
    assert!(config.secrets.contains_key("artifacts"));
    // Upgrade an existing qdrant-only config without asking for another key.
    config.secrets.remove("artifacts");
    runtime_config::save_config(&o.config, &config).unwrap();
    setup::run(&o, &mut i, &mut h).await.unwrap();
    let config = runtime_config::load_config(&o.config).unwrap();
    assert_eq!(
        config.secrets.get("artifacts"),
        config.secrets.get("qdrant")
    );
    server.join().unwrap();
    // The real updater must resolve the persisted shared reference and authenticate.
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    let mut metadata: serde_json::Value =
        serde_json::from_slice(include_bytes!("fixtures/shared-index-metadata.json")).unwrap();
    metadata["embedding"]["model_file"] = manifest.models.embedder.file.clone().into();
    metadata["embedding"]["sha256"] = manifest.models.embedder.sha256.clone().into();
    metadata["embedding"]["bytes"] = manifest.models.embedder.size.into();
    metadata["files"] = serde_json::json!({"context/catalog.jsonl": {
        "sha256": format!("{:x}", Sha256::digest(b"catalog")), "bytes": 7
    }});
    let server = std::thread::spawn(move || {
        use std::io::{Read, Write};
        for (path, body) in [
            (
                "/test/index-metadata.json",
                serde_json::to_vec(&metadata).unwrap(),
            ),
            ("/test/context/catalog.jsonl", b"catalog".to_vec()),
        ] {
            let (mut stream, _) = listener.accept().unwrap();
            stream
                .set_read_timeout(Some(std::time::Duration::from_secs(5)))
                .unwrap();
            let mut header = Vec::new();
            while !header.ends_with(b"\r\n\r\n") {
                assert!(header.len() < 8192);
                let mut byte = [0];
                stream.read_exact(&mut byte).unwrap();
                header.push(byte[0]);
            }
            let header = String::from_utf8(header).unwrap();
            assert!(header.starts_with(&format!("GET {path} HTTP/1.1")));
            assert!(header.contains("Bearer SECRET_SENTINEL"));
            write!(
                stream,
                "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                body.len()
            )
            .unwrap();
            stream.write_all(&body).unwrap();
        }
    });
    let mut config = config;
    config.profile.artifact_url = Some(format!("http://{address}"));
    config.profile.index_name = Some("test".into());
    let recorder = |created: &[update_index::CreatedArtifact]| {
        for artifact in created {
            match &artifact.kind {
                update_index::ArtifactKind::Symlink { target } => {
                    setup::track_created_pointer(&o, &artifact.path, target)?
                }
                _ => setup::track_created_artifacts(
                    &o,
                    &[setup::CreatedArtifact {
                        path: artifact.path.clone(),
                    }],
                )?,
            }
        }
        Ok(())
    };
    update_index::update_with_recorder(
        &config,
        &o.paths,
        update_index::UpdateOptions {
            model_manifest: Some(&manifest_file),
            ..Default::default()
        },
        Some(&recorder),
    )
    .await
    .unwrap();
    server.join().unwrap();
    assert_eq!(
        fs::read(o.paths.data.join("test/context/catalog.jsonl")).unwrap(),
        b"catalog"
    );
    assert_eq!(i.0, 1);
    assert_eq!(h.0, vec!["update", "doctor", "update", "doctor"]);
    assert!(
        !fs::read_to_string(&o.config)
            .unwrap()
            .contains("SECRET_SENTINEL")
    );
    assert!(
        !fs::read_to_string(home.join("doctor-args"))
            .unwrap()
            .contains("SECRET_SENTINEL")
    );
    assert_eq!(
        fs::metadata(o.paths.secrets.join("qdrant"))
            .unwrap()
            .permissions()
            .mode()
            & 0o777,
        0o600
    );
    fs::write(o.paths.cache.join("personal"), b"keep").unwrap();
    o.uninstall = true;
    o.purge = true;
    setup::run(&o, &mut i, &mut h).await.unwrap();
    assert!(!o.config.exists());
    assert!(!o.paths.secrets.join("qdrant").exists());
    assert!(!o.paths.data.join("test").exists());
    assert!(!o.paths.data.join(".test-snapshots").exists());
    assert!(o.paths.cache.join("personal").exists());
    // Pre-existing repaired models are never adopted or purged.
    assert!(o.paths.models.join("embed.gguf").exists());
    assert!(!o.paths.models.join("rank.gguf").exists());
}
#[test]
fn paths_build_and_linux_guidance() {
    assert_eq!(setup::parse_llama_build("version: 9430 (abc)"), Some(9430));
    assert_eq!(setup::parse_llama_build("unknown"), None);
    let p = RuntimePaths::from_env(Platform::MacOs, |k| {
        (k == "HOME").then(|| "/synthetic/user".into())
    })
    .unwrap();
    assert_eq!(
        p.services,
        Path::new("/synthetic/user/Library/LaunchAgents")
    );
    assert!(setup::LINUX_INSTALL_INSTRUCTION.contains("--target llama-server"));
}

#[test]
fn registration_mapping_separates_host_home_and_runtime_root() {
    let temp = tempfile::tempdir().unwrap();
    let home = fs::canonicalize(temp.path()).unwrap();
    let isolated = options(&home, Platform::Linux);
    let environment = setup::registration_environment(&isolated).unwrap();
    assert_eq!(environment["CODE_DIVER_HOME"], home.display().to_string());
    assert_ne!(
        environment["CODE_DIVER_HOME"],
        isolated.paths.hosts.display().to_string()
    );
    let paths = RuntimePaths::from_env(Platform::Linux, |key| {
        (key == "HOME").then(|| home.display().to_string())
    })
    .unwrap();
    let regular = setup::SetupOptions::new(paths, home.join("binary"), Platform::Linux, 501);
    assert!(
        !setup::registration_environment(&regular)
            .unwrap()
            .contains_key("CODE_DIVER_HOME")
    );
    assert_eq!(regular.paths.hosts, home);
}

#[test]
fn planners_are_pure_escape_paths_and_bind_ownership_to_config() {
    for platform in [Platform::MacOs, Platform::Linux] {
        let paths = RuntimePaths::from_env(platform, |k| {
            (k == "CODE_DIVER_HOME").then(|| "/nonexistent/setup-planner".into())
        })
        .unwrap();
        let mut options = service_manager::ServiceOptions {
            platform,
            paths,
            executable: "/nonexistent/code & diver%$".into(),
            config: "/nonexistent/config & runtime.toml".into(),
            manager: "never-executed".into(),
            uid: 501,
        };
        let first = service_manager::plan(&options).unwrap();
        assert!(first.contents.contains("--config"));
        assert!(!first.contents.contains("QDRANT_API_KEY"));
        if platform == Platform::MacOs {
            assert!(first.contents.contains("&amp;"));
        } else {
            assert!(first.contents.contains("%%$$"));
        }
        options.config = "/nonexistent/other.toml".into();
        assert_ne!(first.owner, service_manager::plan(&options).unwrap().owner);
        options.config = "/nonexistent/../escape".into();
        assert!(service_manager::plan(&options).is_err());
    }
}

#[test]
fn fake_security_lookup_delete_and_write_fails_closed() {
    use runtime_config::SecretStore;
    let temp = tempfile::tempdir().unwrap();
    let home = fs::canonicalize(temp.path()).unwrap();
    let binary = home.join("security");
    script(
        &binary,
        &format!(
            "printf '%s\\n' \"$@\" >> '{}/argv'\ncase \"$1\" in\n-i) IFS= read -r line; printf '%s' \"$line\" > '{}/input'; touch '{}/key';;\nfind-generic-password) test -f '{}/key' || exit 44; printf '%s' 'SECRET_SENTINEL';;\ndelete-generic-password) rm -f '{}/key';;\nesac",
            home.display(),
            home.display(),
            home.display(),
            home.display(),
            home.display()
        ),
    );
    let store = setup::SecurityStore {
        executable: binary.clone(),
    };
    let key = SecretValue::new("SECRET_SENTINEL".into()).unwrap();
    assert!(store.get("qdrant").unwrap().is_none());
    assert!(store.put("qdrant", &key).is_err());
    assert!(!home.join("input").exists());
    fs::write(home.join("key"), b"fake stored key").unwrap();
    assert_eq!(store.get("qdrant").unwrap().unwrap().expose(), key.expose());
    assert!(
        !fs::read_to_string(home.join("argv"))
            .unwrap()
            .contains(key.expose())
    );
    store.delete("qdrant").unwrap();
    assert!(store.get("qdrant").unwrap().is_none());
    script(&binary, "echo SECRET_SENTINEL >&2; exit 1");
    assert!(!format!("{:#}", store.put("qdrant", &key).unwrap_err()).contains(key.expose()));
}

#[tokio::test]
async fn snapshot_purge_unlinks_pointers_preserves_unowned_children_and_targets() {
    let temp = tempfile::tempdir().unwrap();
    let home = fs::canonicalize(temp.path()).unwrap();
    let mut o = options(&home, Platform::Linux);
    fs::create_dir_all(&o.paths.data).unwrap();
    let snapshots = o.paths.data.join(".shared-snapshots");
    fs::create_dir(&snapshots).unwrap();
    let snapshot = snapshots.join("one");
    fs::create_dir(&snapshot).unwrap();
    let metadata = snapshot.join("metadata.json");
    fs::write(&metadata, b"owned").unwrap();
    let pointer = o.paths.data.join("shared");
    let outside = home.join("outside");
    fs::write(&outside, b"never delete").unwrap();
    std::os::unix::fs::symlink(&outside, &pointer).unwrap();
    let created: Vec<_> = [&snapshots, &snapshot, &metadata, &pointer]
        .into_iter()
        .map(|path| setup::CreatedArtifact { path: path.clone() })
        .collect();
    setup::track_created_artifacts(&o, &created).unwrap();
    fs::write(snapshots.join("personal"), b"keep").unwrap();
    o.uninstall = true;
    o.purge = true;
    setup::run(&o, &mut Interaction(0), &mut Hooks(Vec::new()))
        .await
        .unwrap();
    assert!(fs::symlink_metadata(pointer).is_err());
    assert!(!snapshot.exists());
    assert!(snapshots.join("personal").exists());
    assert_eq!(fs::read(outside).unwrap(), b"never delete");
}

#[test]
fn ownership_serialization_conflicts_and_pointer_parent_rejected() {
    let temp = tempfile::tempdir().unwrap();
    let home = fs::canonicalize(temp.path()).unwrap();
    let o = options(&home, Platform::Linux);
    fs::create_dir_all(&o.paths.state).unwrap();
    fs::create_dir_all(&o.paths.data).unwrap();
    let lock = fs::OpenOptions::new()
        .create(true)
        .truncate(false)
        .write(true)
        .open(o.paths.state.join("setup-owned.lock"))
        .unwrap();
    lock.try_lock().unwrap();
    let path = o.paths.data.join("artifact");
    fs::write(&path, b"first").unwrap();
    assert!(setup::track_owned_artifact(&o, &path).is_err());
    drop(lock);
    setup::track_owned_artifact(&o, &path).unwrap();
    fs::write(&path, b"changed").unwrap();
    assert!(setup::track_owned_artifact(&o, &path).is_err());
    let pointer = o.paths.data.join("pointer");
    std::os::unix::fs::symlink(&home, &pointer).unwrap();
    assert!(setup::track_owned_artifact(&o, &pointer.join("artifact")).is_err());
    assert!(setup::track_owned_artifact(&o, &o.paths.data).is_err());
}

#[tokio::test]
async fn unpublished_pointer_receipt_and_active_update_lock() {
    let temp = tempfile::tempdir().unwrap();
    let home = fs::canonicalize(temp.path()).unwrap();
    let mut o = options(&home, Platform::Linux);
    fs::create_dir_all(&o.paths.data).unwrap();
    let pointer = o.paths.data.join("shared");
    let target = Path::new(".shared-snapshots/one");
    setup::track_created_pointer(&o, &pointer, target).unwrap();
    setup::track_created_pointer(&o, &pointer, target).unwrap();
    std::os::unix::fs::symlink(target, &pointer).unwrap();
    setup::track_owned_artifact(&o, &pointer).unwrap();
    let lock_path = o.paths.data.join(".shared-update.lock");
    let lock = fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&lock_path)
        .unwrap();
    setup::track_owned_artifact(&o, &lock_path).unwrap();
    lock.try_lock().unwrap();
    o.uninstall = true;
    o.purge = true;
    assert!(
        setup::run(&o, &mut Interaction(0), &mut Hooks(Vec::new()))
            .await
            .unwrap_err()
            .to_string()
            .contains("index update is active")
    );
    assert!(fs::symlink_metadata(&pointer).is_ok());
    drop(lock);
    setup::run(&o, &mut Interaction(0), &mut Hooks(Vec::new()))
        .await
        .unwrap();
    assert!(fs::symlink_metadata(pointer).is_err());
    assert!(lock_path.exists());
}
#[tokio::test]
async fn linux_missing_old_build_and_symlink_are_fail_fast() {
    let temp = tempfile::tempdir().unwrap();
    let home = fs::canonicalize(temp.path()).unwrap();
    let mut o = options(&home, Platform::Linux);
    let mut i = Interaction(0);
    let mut h = Hooks(Vec::new());
    let error = setup::run(&o, &mut i, &mut h).await.unwrap_err();
    assert!(error.to_string().contains(setup::LINUX_INSTALL_INSTRUCTION));
    assert!(!o.paths.config.exists());
    let binary = home.join("old");
    script(&binary, "echo 'version: 1'");
    o.llama_server = Some(binary);
    assert!(setup::run(&o, &mut i, &mut h).await.is_err());
    assert_eq!(i.0, 0);
    std::os::unix::fs::symlink(home.join("outside"), &o.paths.config).unwrap();
    assert!(
        setup::run(&o, &mut i, &mut h)
            .await
            .unwrap_err()
            .to_string()
            .contains("symlink")
    );
}
#[tokio::test]
async fn purge_only_unchanged_recorded_artifacts() {
    let temp = tempfile::tempdir().unwrap();
    let home = fs::canonicalize(temp.path()).unwrap();
    let mut o = options(&home, Platform::Linux);
    fs::create_dir_all(&o.paths.data).unwrap();
    let owned = o.paths.data.join("owned");
    let edited = o.paths.data.join("edited");
    let personal = o.paths.data.join("personal");
    for path in [&owned, &edited, &personal] {
        fs::write(path, b"original").unwrap();
    }
    setup::track_owned_artifact(&o, &owned).unwrap();
    setup::track_owned_artifact(&o, &edited).unwrap();
    fs::write(&edited, b"user edit").unwrap();
    o.uninstall = true;
    let mut i = Interaction(0);
    let mut h = Hooks(Vec::new());
    setup::run(&o, &mut i, &mut h).await.unwrap();
    assert!(owned.exists());
    o.purge = true;
    setup::run(&o, &mut i, &mut h).await.unwrap();
    assert!(!owned.exists());
    assert!(edited.exists());
    assert!(personal.exists());
    setup::run(&o, &mut i, &mut h).await.unwrap();
}

fn cached_fixture(home: &Path) -> setup::SetupOptions {
    use sha2::{Digest, Sha256};
    let mut o = options(home, Platform::Linux);
    script(&o.executable, "exit 0");
    let llama = home.join("llama-server");
    script(&llama, "echo 'build: 9430'");
    o.llama_server = Some(llama);
    let mut manifest = model_store::ModelManifest::embedded().unwrap();
    fs::create_dir_all(&o.paths.models).unwrap();
    for (spec, file) in [
        (&mut manifest.models.embedder, "embedding.gguf"),
        (&mut manifest.models.reranker, "reranking.gguf"),
    ] {
        spec.file = file.into();
        spec.size = 3;
        spec.sha256 = format!("{:x}", Sha256::digest(b"abc"));
        fs::write(o.paths.models.join(file), b"abc").unwrap();
    }
    let manifest_path = home.join("models.json");
    fs::write(&manifest_path, serde_json::to_vec(&manifest).unwrap()).unwrap();
    o.flags = toml::from_str(&format!(
        "[profile]\nmodel_manifest_path='{}'",
        manifest_path.display()
    ))
    .unwrap();
    o
}
#[tokio::test]
async fn keyfile_precedes_env_modified_secret_preserved_doctor_failure_last() {
    let temp = tempfile::tempdir().unwrap();
    let home = fs::canonicalize(temp.path()).unwrap();
    let mut o = cached_fixture(&home);
    let key_file = home.join("key");
    fs::write(&key_file, b"FILE_SECRET\n").unwrap();
    o.key_file = Some(key_file);
    o.environment
        .insert("QDRANT_API_KEY".into(), "ENV_SECRET".into());
    let mut i = Interaction(0);
    let mut h = Hooks(Vec::new());
    setup::run(&o, &mut i, &mut h).await.unwrap();
    assert_eq!(i.0, 0);
    assert_eq!(
        fs::read_to_string(o.paths.secrets.join("qdrant")).unwrap(),
        "FILE_SECRET"
    );
    o.key_file = None;
    o.environment.clear();
    script(&o.executable, "echo FILE_SECRET >&2; exit 1");
    let error = setup::run(&o, &mut i, &mut h).await.unwrap_err();
    assert!(error.to_string().contains("doctor failed"));
    assert!(!format!("{error:#}").contains("FILE_SECRET"));
    assert_eq!(h.0.last(), Some(&"doctor"));
    fs::write(o.paths.secrets.join("qdrant"), b"personal replacement").unwrap();
    o.uninstall = true;
    o.purge = true;
    setup::run(&o, &mut i, &mut h).await.unwrap();
    assert!(o.paths.secrets.join("qdrant").exists());
}
#[tokio::test]
async fn brew_consent_decline_and_yes_fake_install_only() {
    struct Decline;
    impl setup::Interaction for Decline {
        fn confirm_brew(&mut self) -> anyhow::Result<bool> {
            Ok(false)
        }
        fn read_key(&mut self) -> anyhow::Result<SecretValue> {
            panic!("key should come from environment")
        }
    }
    let temp = tempfile::tempdir().unwrap();
    let home = fs::canonicalize(temp.path()).unwrap();
    let mut o = cached_fixture(&home);
    o.platform = Platform::MacOs;
    o.security = None;
    o.llama_server = None;
    o.search_path = vec![home.clone()];
    fs::remove_file(home.join("llama-server")).unwrap();
    o.brew = home.join("brew");
    script(
        &o.brew,
        &format!(
            "printf '%s\\n' '#!/bin/sh' \"echo 'version: 9430'\" > '{}/llama-server'; chmod 700 '{}/llama-server'",
            home.display(),
            home.display()
        ),
    );
    let mut h = Hooks(Vec::new());
    let mut i = Decline;
    assert!(
        setup::run(&o, &mut i, &mut h)
            .await
            .unwrap_err()
            .to_string()
            .contains("declined")
    );
    assert!(!home.join("llama-server").exists());
    o.yes = true;
    o.environment
        .insert("QDRANT_API_KEY".into(), "TEST_KEY".into());
    setup::run(&o, &mut i, &mut h).await.unwrap();
    assert_eq!(h.0, vec!["update", "doctor"]);
}
#[tokio::test]
async fn registration_helper_additive_and_uninstall_preserves_other_hosts() {
    let temp = tempfile::tempdir().unwrap();
    let home = fs::canonicalize(temp.path()).unwrap();
    let mut o = cached_fixture(&home);
    o.no_register = false;
    let host = o.paths.hosts.join(".gemini");
    fs::create_dir_all(&host).unwrap();
    fs::write(
        host.join("settings.json"),
        r#"{"mcpServers":{"personal":{"command":"personal-tool"}}}"#,
    )
    .unwrap();
    let mut i = Interaction(0);
    let mut h = Hooks(Vec::new());
    setup::run(&o, &mut i, &mut h).await.unwrap();
    let json: serde_json::Value =
        serde_json::from_slice(&fs::read(host.join("settings.json")).unwrap()).unwrap();
    assert!(json["mcpServers"]["code-diver"].is_object());
    assert_eq!(json["mcpServers"]["personal"]["command"], "personal-tool");
    o.uninstall = true;
    setup::run(&o, &mut i, &mut h).await.unwrap();
    let json: serde_json::Value =
        serde_json::from_slice(&fs::read(host.join("settings.json")).unwrap()).unwrap();
    assert!(json["mcpServers"]["code-diver"].is_null());
    assert!(json["mcpServers"]["personal"].is_object());
}

#[test]
fn registration_runtime_root_is_separate_from_host_discovery() {
    for isolated in [false, true] {
        let temp = tempfile::tempdir().unwrap();
        let home = fs::canonicalize(temp.path()).unwrap();
        let mut o = options(&home, Platform::Linux);
        o.paths.hosts = home.join("host-home");
        o.paths.isolated = isolated;
        o.claude_cli = None;
        let host = o.paths.hosts.join(".gemini/settings.json");
        fs::create_dir_all(host.parent().unwrap()).unwrap();
        fs::write(&host, r#"{"mcpServers":{"personal":{"command":"keep"}}}"#).unwrap();
        setup::registration(&o, false).unwrap();
        let document: serde_json::Value =
            serde_json::from_slice(&fs::read(&host).unwrap()).unwrap();
        let env = &document["mcpServers"]["code-diver"]["env"];
        assert_eq!(env["CODE_DIVER_CONFIG"], o.config.to_str().unwrap());
        if isolated {
            assert_eq!(env["CODE_DIVER_HOME"], home.to_str().unwrap());
        } else {
            assert!(env.get("CODE_DIVER_HOME").is_none());
        }
        setup::registration(&o, true).unwrap();
        let document: serde_json::Value =
            serde_json::from_slice(&fs::read(&host).unwrap()).unwrap();
        assert!(document["mcpServers"].get("code-diver").is_none());
        assert_eq!(document["mcpServers"]["personal"]["command"], "keep");
    }
}

#[tokio::test]
async fn setup_does_not_adopt_models_with_stale_ownership() {
    let temp = tempfile::tempdir().unwrap();
    let home = fs::canonicalize(temp.path()).unwrap();
    let mut o = cached_fixture(&home);
    fs::create_dir_all(&o.paths.state).unwrap();
    let model = o.paths.models.join("embedding.gguf");
    let mut files = std::collections::BTreeMap::new();
    files.insert(model.clone(), "0".repeat(64));
    fs::write(
        o.paths.state.join("setup-owned.json"),
        serde_json::to_vec(&serde_json::json!({"files": files, "key": null})).unwrap(),
    )
    .unwrap();
    let mut i = Interaction(0);
    let mut h = Hooks(Vec::new());
    setup::run(&o, &mut i, &mut h).await.unwrap();
    let ledger: serde_json::Value =
        serde_json::from_slice(&fs::read(o.paths.state.join("setup-owned.json")).unwrap()).unwrap();
    assert!(ledger["files"].get(model.to_str().unwrap()).is_none());
    o.uninstall = true;
    o.purge = true;
    setup::run(&o, &mut i, &mut h).await.unwrap();
    assert_eq!(fs::read(model).unwrap(), b"abc");
    assert_eq!(
        fs::read(o.paths.models.join("reranking.gguf")).unwrap(),
        b"abc"
    );
}
