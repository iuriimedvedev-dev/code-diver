use crate::model_store::{self, ModelManifest, ModelStore};
use crate::runtime_config::{
    self, FileSecretStore, MacSecurity, Platform, RuntimeConfig, RuntimePaths, SecretRef,
    SecretStore, SecretValue,
};
use crate::service_manager::{self, CommandPlan, ServiceOptions};
use anyhow::{Result, bail};
use std::collections::BTreeMap;
use std::fs;
use std::io::{Read, Write};
use std::path::PathBuf;
use std::process::{Command, Stdio};

pub const LINUX_INSTALL_INSTRUCTION: &str = "git clone https://github.com/ggml-org/llama.cpp.git && cmake -S llama.cpp -B llama.cpp/build -DLLAMA_BUILD_SERVER=ON && cmake --build llama.cpp/build --config Release --target llama-server -j2 && code-diver setup --llama-server \"$PWD/llama.cpp/build/bin/llama-server\"";

pub struct SetupOptions {
    pub uninstall: bool,
    pub purge: bool,
    pub profile: Option<String>,
    pub no_register: bool,
    pub yes: bool,
    pub dry_run: bool,
    pub key_file: Option<PathBuf>,
    pub llama_server: Option<PathBuf>,
    pub paths: RuntimePaths,
    pub config: PathBuf,
    pub executable: PathBuf,
    pub platform: Platform,
    pub manager: PathBuf,
    pub brew: PathBuf,
    pub security: Option<PathBuf>,
    pub claude_cli: Option<PathBuf>,
    pub uid: u32,
    pub search_path: Vec<PathBuf>,
    pub environment: BTreeMap<String, String>,
    pub flags: toml::Table,
}
impl SetupOptions {
    pub fn new(paths: RuntimePaths, executable: PathBuf, platform: Platform, uid: u32) -> Self {
        Self {
            config: paths.config_file(),
            paths,
            executable,
            platform,
            uid,
            uninstall: false,
            purge: false,
            profile: None,
            no_register: false,
            yes: false,
            dry_run: false,
            key_file: None,
            llama_server: None,
            manager: match platform {
                Platform::MacOs => "launchctl",
                Platform::Linux => "systemctl",
            }
            .into(),
            brew: "brew".into(),
            security: (platform == Platform::MacOs).then(|| PathBuf::from("/usr/bin/security")),
            claude_cli: None,
            search_path: Vec::new(),
            environment: BTreeMap::new(),
            flags: toml::Table::new(),
        }
    }
}
#[derive(Debug)]
pub struct SetupReport {
    pub actions: Vec<String>,
    pub doctor_passed: Option<bool>,
}
pub fn plan(options: &SetupOptions) -> Result<Vec<String>> {
    if options.purge && !options.uninstall {
        bail!("--purge requires --uninstall");
    }
    for p in [
        &options.config,
        &options.executable,
        &options.paths.config,
        &options.paths.models,
        &options.paths.state,
        &options.paths.data,
        &options.paths.cache,
        &options.paths.hosts,
        &options.paths.secrets,
    ] {
        service_manager::validate_path(p)?;
    }
    if options.uninstall {
        return Ok(vec![
            "Stop and remove owned user service".into(),
            if options.no_register {
                "Skip MCP removal"
            } else {
                "Remove owned MCP entries"
            }
            .into(),
            "Remove unchanged owned config and secret".into(),
            if options.purge {
                "Purge unchanged owned model/cache artifacts"
            } else {
                "Preserve models and cache"
            }
            .into(),
        ]);
    }
    Ok(vec!["1 Check platform".into(), "2 Check llama-server build; macOS brew install llama.cpp requires consent; Linux prints install command".into(), "3 Load manifest and verify/download both models (HF_TOKEN optional)".into(), "4 Load profile, resolve config, acquire key once privately and save references only".into(), "5 Install and start owned user service".into(), "6 Update shared index artifacts".into(), if options.no_register { "7 Skip MCP registration" } else { "7 Register detected MCP hosts additively" }.into(), "8 Run doctor last".into()])
}

pub trait Interaction {
    fn confirm_brew(&mut self) -> Result<bool>;
    fn read_key(&mut self) -> Result<SecretValue>;
}
pub struct TerminalInteraction;
impl Interaction for TerminalInteraction {
    fn confirm_brew(&mut self) -> Result<bool> {
        let mut tty = fs::OpenOptions::new()
            .read(true)
            .write(true)
            .open("/dev/tty")
            .map_err(|_| anyhow::anyhow!("consent unavailable; use --yes or --llama-server"))?;
        tty.write_all(b"Install llama.cpp with brew? [y/N] ")?;
        let mut line = String::new();
        std::io::BufRead::read_line(&mut std::io::BufReader::new(tty), &mut line)?;
        Ok(matches!(line.trim(), "y" | "Y" | "yes"))
    }
    fn read_key(&mut self) -> Result<SecretValue> {
        let mut tty = fs::OpenOptions::new()
            .read(true)
            .write(true)
            .open("/dev/tty")
            .map_err(|_| anyhow::anyhow!("key unavailable; set QDRANT_API_KEY or --key-file"))?;
        let state = Command::new("stty")
            .arg("-g")
            .stdin(tty.try_clone()?)
            .output()?;
        if !state.status.success() {
            bail!("cannot secure key prompt");
        }
        let state = String::from_utf8(state.stdout)
            .map_err(|_| anyhow::anyhow!("cannot secure key prompt"))?;
        struct Restore(fs::File, String);
        impl Drop for Restore {
            fn drop(&mut self) {
                if let Ok(tty) = self.0.try_clone() {
                    let _ = Command::new("stty")
                        .arg(self.1.trim())
                        .stdin(tty)
                        .stdout(Stdio::null())
                        .stderr(Stdio::null())
                        .status();
                }
            }
        }
        let _restore = Restore(tty.try_clone()?, state);
        if !Command::new("stty")
            .arg("-echo")
            .stdin(tty.try_clone()?)
            .status()?
            .success()
        {
            bail!("cannot hide key prompt");
        }
        tty.write_all(b"Read-only Qdrant key: ")?;
        let mut value = String::new();
        std::io::BufRead::read_line(
            &mut std::io::BufReader::new(tty.try_clone()?).take(16386),
            &mut value,
        )?;
        tty.write_all(b"\n")?;
        SecretValue::new(value.trim_end_matches(['\r', '\n']).to_string())
    }
}

/// CLI lookup/deletion; writes use the native framework, never CLI password arguments.
pub struct SecurityStore {
    pub executable: PathBuf,
}
impl SecretStore for SecurityStore {
    fn get(&self, name: &str) -> Result<Option<SecretValue>> {
        runtime_config::validate_name(name)?;
        let out = Command::new(&self.executable)
            .args([
                "find-generic-password",
                "-s",
                "code-diver",
                "-a",
                name,
                "-w",
            ])
            .stdin(Stdio::null())
            .stderr(Stdio::null())
            .output()
            .map_err(|_| anyhow::anyhow!("keychain lookup failed"))?;
        if out.status.code() == Some(44) {
            return Ok(None);
        }
        if !out.status.success() {
            bail!("keychain lookup failed");
        }
        let value =
            String::from_utf8(out.stdout).map_err(|_| anyhow::anyhow!("invalid keychain value"))?;
        Ok(Some(SecretValue::new(
            value.trim_end_matches(['\r', '\n']).into(),
        )?))
    }
    fn put(&self, name: &str, value: &SecretValue) -> Result<()> {
        runtime_config::validate_name(name)?;
        if self.executable != std::path::Path::new("/usr/bin/security") {
            bail!("native keychain writes disabled for injected CLI; use file fallback");
        }
        runtime_config::NativeMacSecurity
            .put(name, value)
            .map_err(|_| anyhow::anyhow!("keychain write failed"))
    }
    fn delete(&self, name: &str) -> Result<()> {
        runtime_config::validate_name(name)?;
        let out = Command::new(&self.executable)
            .args(["delete-generic-password", "-s", "code-diver", "-a", name])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map_err(|_| anyhow::anyhow!("keychain deletion failed"))?;
        if !out.success() && out.code() != Some(44) {
            bail!("keychain deletion failed");
        }
        Ok(())
    }
}
impl MacSecurity for SecurityStore {}

pub trait SetupHooks {
    fn registration(&mut self, options: &SetupOptions, uninstall: bool) -> Result<()> {
        registration(options, uninstall).map(|_| ())
    }
    fn update_index<'a>(
        &'a mut self,
        config: &'a RuntimeConfig,
        paths: &'a RuntimePaths,
    ) -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<()>> + 'a>>;
    fn doctor(&mut self, command: &CommandPlan) -> Result<bool> {
        command.execute()
    }
}
/// Compatibility helper: caller must authoritatively report exclusive creation.
/// Prefer `track_created_artifacts` for updater reports, including directories and pointers.
pub fn track_owned_artifact(options: &SetupOptions, path: &std::path::Path) -> Result<()> {
    track_created_artifacts(options, &[CreatedArtifact { path: path.into() }])
}

/// An updater's authoritative creation receipt, NOT a before/after existence guess.
/// Construct only after exclusive creation under the updater's serialization lock.
/// Never report pre-existing objects, even if updated or replaced by this invocation.
pub struct CreatedArtifact {
    pub path: PathBuf,
}

/// Record an authoritative, not-yet-published pointer under the updater lock.
/// The destination must be absent; purge compares link text without following it.
pub fn track_created_pointer(
    options: &SetupOptions,
    path: &std::path::Path,
    target: &std::path::Path,
) -> Result<()> {
    if options.dry_run {
        return Ok(());
    }
    let _lock = ownership_lock(options)?;
    artifact_path(options, path)?;
    match fs::symlink_metadata(path) {
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => (),
        _ => bail!("new pointer destination must be absent"),
    }
    let mut owned = load_owned(options)?;
    let receipt = ArtifactIdentity {
        device: 0,
        inode: 0,
        kind: ArtifactKind::Symlink(target.into()),
    };
    if owned
        .artifacts
        .get(path)
        .is_some_and(|previous| previous != &receipt)
    {
        bail!("pointer already has a conflicting ownership receipt");
    }
    owned.artifacts.insert(path.into(), receipt);
    save_owned(options, &owned)
}

pub fn track_created_artifacts(options: &SetupOptions, created: &[CreatedArtifact]) -> Result<()> {
    if options.dry_run {
        return Ok(());
    }
    let _lock = ownership_lock(options)?;
    let mut owned = load_owned(options)?;
    for artifact in created {
        let path = &artifact.path;
        artifact_path(options, path)?;
        let receipt = artifact_identity(path)?;
        if let Some(previous) = owned.artifacts.get(path)
            && previous != &receipt
            && !(previous.device == 0 && previous.inode == 0 && previous.kind == receipt.kind)
        {
            bail!("artifact creation receipt conflicts with existing ownership");
        }
        owned.artifacts.insert(path.clone(), receipt);
    }
    save_owned(options, &owned)
}

fn artifact_path(options: &SetupOptions, path: &std::path::Path) -> Result<()> {
    service_manager::validate_path(path)?;
    if ![&options.paths.data, &options.paths.cache]
        .iter()
        .any(|root| path != *root && path.starts_with(root))
    {
        bail!("artifact must be strictly inside runtime data or cache");
    }
    service_manager::safe_path(
        path.parent()
            .ok_or_else(|| anyhow::anyhow!("missing artifact parent"))?,
    )
}

#[derive(serde::Serialize, serde::Deserialize, PartialEq, Eq)]
struct ArtifactIdentity {
    device: u64,
    inode: u64,
    kind: ArtifactKind,
}
#[derive(serde::Serialize, serde::Deserialize, PartialEq, Eq)]
enum ArtifactKind {
    File(String),
    Directory,
    Symlink(PathBuf),
}
fn artifact_identity(path: &std::path::Path) -> Result<ArtifactIdentity> {
    use std::os::unix::fs::MetadataExt;
    let metadata = fs::symlink_metadata(path)?;
    let kind = if metadata.file_type().is_symlink() {
        ArtifactKind::Symlink(fs::read_link(path)?)
    } else if metadata.is_dir() {
        ArtifactKind::Directory
    } else if metadata.is_file() {
        ArtifactKind::File(hash_file(path)?)
    } else {
        bail!("unsupported owned artifact type");
    };
    Ok(ArtifactIdentity {
        device: metadata.dev(),
        inode: metadata.ino(),
        kind,
    })
}

struct SetupLock(fs::File);
impl Drop for SetupLock {
    fn drop(&mut self) {
        let _ = self.0.unlock();
    }
}
fn ownership_lock(options: &SetupOptions) -> Result<SetupLock> {
    setup_lock(options, "setup-owned.lock")
}
fn setup_lock(options: &SetupOptions, name: &str) -> Result<SetupLock> {
    use std::os::unix::fs::OpenOptionsExt;
    let path = options.paths.state.join(name);
    service_manager::safe_path(&path)?;
    fs::create_dir_all(&options.paths.state)?;
    let file = fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .mode(0o600)
        .open(path)?;
    file.try_lock().map_err(|_| {
        anyhow::anyhow!("setup ownership is busy; retry after the current operation")
    })?;
    Ok(SetupLock(file))
}

fn updater_locks(options: &SetupOptions) -> Result<Vec<fs::File>> {
    let entries = match fs::read_dir(&options.paths.data) {
        Ok(entries) => entries,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(Vec::new()),
        Err(e) => return Err(e.into()),
    };
    let mut locks = Vec::new();
    for entry in entries {
        let path = entry?.path();
        if is_update_lock(&path) {
            service_manager::safe_path(&path)?;
            let file = fs::OpenOptions::new().write(true).open(path)?;
            file.try_lock()
                .map_err(|_| anyhow::anyhow!("index update is active; retry purge later"))?;
            locks.push(file);
        }
    }
    Ok(locks)
}
fn is_update_lock(path: &std::path::Path) -> bool {
    path.file_name()
        .and_then(|name| name.to_str())
        .is_some_and(|name| name.starts_with('.') && name.ends_with("-update.lock"))
}
pub fn parse_llama_build(text: &str) -> Option<u32> {
    text.split_whitespace()
        .collect::<Vec<_>>()
        .windows(2)
        .find_map(|pair| {
            if pair[0] == "version:" || pair[0] == "build:" {
                pair[1].trim_start_matches('b').parse().ok()
            } else {
                None
            }
        })
}
fn llama_valid(binary: &PathBuf, minimum: u32) -> bool {
    Command::new(binary)
        .arg("--version")
        .stdin(Stdio::null())
        .output()
        .is_ok_and(|o| {
            let text = format!(
                "{}\n{}",
                String::from_utf8_lossy(&o.stdout),
                String::from_utf8_lossy(&o.stderr)
            );
            o.status.success() && parse_llama_build(&text).is_some_and(|b| b >= minimum)
        })
}
#[derive(serde::Serialize, serde::Deserialize, Default)]
struct Ownership {
    files: BTreeMap<PathBuf, String>,
    #[serde(default)]
    artifacts: BTreeMap<PathBuf, ArtifactIdentity>,
    key: Option<SecretRef>,
    #[serde(default)]
    key_hash: Option<String>,
}
fn hash(bytes: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    format!("{:x}", Sha256::digest(bytes))
}
fn hash_file(path: &std::path::Path) -> Result<String> {
    use sha2::{Digest, Sha256};
    let mut file =
        fs::File::open(path).map_err(|_| anyhow::anyhow!("cannot read owned artifact"))?;
    let mut digest = Sha256::new();
    let mut buffer = [0u8; 65536];
    loop {
        let len = file
            .read(&mut buffer)
            .map_err(|_| anyhow::anyhow!("cannot hash owned artifact"))?;
        if len == 0 {
            break;
        }
        digest.update(&buffer[..len]);
    }
    Ok(format!("{:x}", digest.finalize()))
}
fn record(owned: &mut Ownership, path: PathBuf) -> Result<()> {
    owned.files.insert(path.clone(), hash_file(&path)?);
    Ok(())
}
fn ledger(options: &SetupOptions) -> PathBuf {
    options.paths.state.join("setup-owned.json")
}
fn save_owned(options: &SetupOptions, owned: &Ownership) -> Result<()> {
    service_manager::write_private(&ledger(options), &serde_json::to_vec(owned)?)
}
fn load_owned(options: &SetupOptions) -> Result<Ownership> {
    let path = ledger(options);
    service_manager::safe_path(&path)?;
    match fs::read(path) {
        Ok(b) => serde_json::from_slice(&b)
            .map_err(|_| anyhow::anyhow!("invalid setup ownership record")),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(Ownership::default()),
        Err(_) => bail!("cannot read setup ownership record"),
    }
}
pub async fn run(
    options: &SetupOptions,
    interaction: &mut dyn Interaction,
    hooks: &mut dyn SetupHooks,
) -> Result<SetupReport> {
    let actions = plan(options)?;
    for action in &actions {
        eprintln!("{action}");
    }
    if options.dry_run {
        return Ok(SetupReport {
            actions,
            doctor_passed: None,
        });
    }
    for path in [
        &options.config,
        &options.paths.config,
        &options.paths.models,
        &options.paths.state,
        &options.paths.data,
        &options.paths.cache,
        &options.paths.hosts,
        &options.paths.secrets,
        &options.paths.logs,
        &options.paths.services,
    ] {
        service_manager::safe_path(path)?;
    }
    let _operation_guard = setup_lock(options, "setup-operation.lock")?;
    let service = service_manager::plan(&ServiceOptions {
        platform: options.platform,
        paths: options.paths.clone(),
        executable: options.executable.clone(),
        config: options.config.clone(),
        manager: options.manager.clone(),
        uid: options.uid,
    })?;
    // Same lock order as the updater callback: updater first, ownership second.
    let _updater_guards = if options.uninstall && options.purge {
        updater_locks(options)?
    } else {
        Vec::new()
    };
    let ownership_guard = ownership_lock(options)?;
    let mut owned = load_owned(options)?;
    let files = FileSecretStore::new(&options.paths);
    let keychain = options.security.as_ref().map(|p| SecurityStore {
        executable: p.clone(),
    });
    if options.uninstall {
        let config_modified = owned.files.get(&options.config).is_some_and(|expected| {
            options.config.exists()
                && hash_file(&options.config).is_ok_and(|actual| actual != *expected)
        });
        service_manager::apply(&service, true, false)?;
        if !options.no_register {
            hooks.registration(options, true).map_err(|_| {
                anyhow::anyhow!("MCP unregister failed; repair detected host configuration")
            })?;
        }
        for (path, digest) in &owned.files {
            let allowed = path == &options.config
                || path.starts_with(&options.paths.models)
                || path.starts_with(&options.paths.data)
                || path.starts_with(&options.paths.cache);
            if !allowed {
                bail!("unsafe setup ownership record");
            }
            if path != &options.config && !options.purge {
                continue;
            }
            service_manager::safe_path(path)?;
            if hash_file(path).is_ok_and(|actual| actual == *digest) {
                fs::remove_file(path)?;
            }
        }
        if options.purge {
            let mut paths: Vec<_> = owned.artifacts.keys().collect();
            paths.sort_by_key(|path| std::cmp::Reverse(path.components().count()));
            for path in paths {
                artifact_path(options, path)?;
                // Keep lock inodes stable; unlinking them permits two simultaneous owners.
                if is_update_lock(path) {
                    continue;
                }
                let expected = &owned.artifacts[path];
                if artifact_identity(path).is_ok_and(|actual| {
                    actual == *expected
                        || (expected.device == 0
                            && expected.inode == 0
                            && matches!(expected.kind, ArtifactKind::Symlink(_))
                            && actual.kind == expected.kind)
                }) {
                    match owned.artifacts[path].kind {
                        ArtifactKind::Directory => {
                            // Never recurse: unreported or changed children preserve their parent.
                            match fs::remove_dir(path) {
                                Ok(()) => (),
                                Err(e) if e.kind() == std::io::ErrorKind::DirectoryNotEmpty => (),
                                Err(e) => return Err(e.into()),
                            }
                        }
                        _ => fs::remove_file(path)?,
                    }
                }
            }
        }
        if let Some(reference) = &owned.key
            && !config_modified
        {
            let current = runtime_config::resolve_secret(
                reference,
                |_| None,
                &files,
                keychain.as_ref().map(|k| k as &dyn MacSecurity),
            )
            .ok();
            if current.as_ref().is_some_and(|v| {
                owned
                    .key_hash
                    .as_ref()
                    .is_some_and(|digest| hash(v.expose().as_bytes()) == *digest)
            }) {
                match reference {
                    SecretRef::File(name) => files.delete(name)?,
                    SecretRef::Keychain(name) => keychain
                        .as_ref()
                        .ok_or_else(|| anyhow::anyhow!("keychain required for uninstall"))?
                        .delete(name)?,
                    SecretRef::Env(_) => (),
                }
            }
        }
        if options.purge {
            let _ = fs::remove_file(ledger(options));
        } else {
            owned.files.retain(|p, _| p != &options.config);
            owned.key = None;
            owned.key_hash = None;
            if owned.files.is_empty() && owned.artifacts.is_empty() {
                let _ = fs::remove_file(ledger(options));
            } else {
                save_owned(options, &owned)?;
            }
        }
        return Ok(SetupReport {
            actions,
            doctor_passed: None,
        });
    }
    let config_exists = options.config.exists();
    let mut config = runtime_config::load_config(&options.config)?;
    if let Some(source) = &options.profile {
        config.profile = runtime_config::load_profile(source).await?;
    }
    config = runtime_config::effective_config(
        config,
        &runtime_config::environment_overrides(|k| options.environment.get(k).cloned())?,
        &options.flags,
    )?;
    let manifest = match config.profile.model_manifest_source()? {
        Some(source) => model_store::load_manifest(source).await?,
        None => ModelManifest::embedded()?,
    };
    let candidate = options
        .llama_server
        .clone()
        .or_else(|| {
            config
                .llama_server
                .clone()
                .filter(|p| llama_valid(p, manifest.llama_cpp.min_build))
        })
        .or_else(|| {
            options
                .search_path
                .iter()
                .map(|p| p.join("llama-server"))
                .find(|p| llama_valid(p, manifest.llama_cpp.min_build))
        });
    let binary = if let Some(p) = candidate {
        if !llama_valid(&p, manifest.llama_cpp.min_build) {
            bail!("llama-server build too old or unavailable; supply a supported --llama-server");
        }
        p
    } else {
        if options.platform == Platform::Linux {
            bail!("llama-server unavailable; install: {LINUX_INSTALL_INSTRUCTION}");
        }
        if !options.yes && !interaction.confirm_brew()? {
            bail!("installation declined; supply --llama-server");
        }
        if !(CommandPlan {
            program: options.brew.clone(),
            args: vec!["install".into(), "llama.cpp".into()],
            env: BTreeMap::new(),
        })
        .execute()?
        {
            bail!("brew install llama.cpp failed");
        }
        options
            .search_path
            .iter()
            .map(|p| p.join("llama-server"))
            .find(|p| llama_valid(p, manifest.llama_cpp.min_build))
            .ok_or_else(|| {
                anyhow::anyhow!("installed llama-server unavailable; supply --llama-server")
            })?
    };
    config.llama_server = Some(binary);
    if !config.llama_server.as_ref().unwrap().is_absolute() {
        bail!("llama-server path must be absolute");
    }
    options.paths.ensure_dirs()?;
    let store = ModelStore::new(&options.paths.models)?;
    for spec in [&manifest.models.embedder, &manifest.models.reranker] {
        let path = store.model_path(spec)?;
        let previously_owned = owned.files.get(&path).is_some_and(|expected| {
            fs::symlink_metadata(&path).is_ok_and(|meta| meta.is_file())
                && hash_file(&path).is_ok_and(|actual| &actual == expected)
        });
        if !previously_owned && owned.files.remove(&path).is_some() {
            save_owned(options, &owned)?;
        }
        store
            .download_with_receipt(
                spec,
                options.environment.get("HF_TOKEN").map(String::as_str),
                |p| eprintln!("model bytes {}/{}", p.downloaded, p.total),
                |receipt| {
                    owned
                        .files
                        .insert(receipt.path.clone(), receipt.sha256.to_ascii_lowercase());
                    save_owned(options, &owned)
                },
            )
            .await?;
    }
    if options.key_file.is_some()
        || options.environment.contains_key("QDRANT_API_KEY")
        || !config.secrets.contains_key("qdrant")
    {
        let value = if let Some(path) = &options.key_file {
            service_manager::safe_path(path)?;
            let mut bytes = String::new();
            fs::File::open(path)
                .map_err(|_| anyhow::anyhow!("cannot open key file"))?
                .take(16386)
                .read_to_string(&mut bytes)
                .map_err(|_| anyhow::anyhow!("cannot read key file"))?;
            SecretValue::new(bytes.trim_end_matches(['\r', '\n']).into())?
        } else if let Some(value) = options.environment.get("QDRANT_API_KEY") {
            SecretValue::new(value.clone())?
        } else {
            interaction
                .read_key()
                .map_err(|_| anyhow::anyhow!("private key prompt failed"))?
        };
        let reference = if !options.paths.isolated
            && keychain.as_ref().is_some_and(|s| {
                (owned.key == Some(SecretRef::Keychain("qdrant".into()))
                    || matches!(s.get("qdrant"), Ok(None)))
                    && s.put("qdrant", &value).is_ok()
            }) {
            SecretRef::Keychain("qdrant".into())
        } else {
            service_manager::safe_path(&options.paths.secrets.join("qdrant"))?;
            let previous = files.get("qdrant")?;
            if previous.is_some() && owned.key != Some(SecretRef::File("qdrant".into())) {
                bail!("existing secret is not setup-owned; configure its reference instead");
            }
            if previous
                .as_ref()
                .is_none_or(|v| v.expose() != value.expose())
            {
                files.put("qdrant", &value)?;
            }
            SecretRef::File("qdrant".into())
        };
        owned.key = Some(reference.clone());
        owned.key_hash = Some(hash(value.expose().as_bytes()));
        config.secrets.insert("qdrant".into(), reference);
        save_owned(options, &owned)?;
    } else {
        runtime_config::resolve_secret(
            config.secrets.get("qdrant").unwrap(),
            |k| options.environment.get(k).cloned(),
            &files,
            keychain.as_ref().map(|k| k as &dyn MacSecurity),
        )?;
    }
    config
        .secrets
        .insert("artifacts".into(), config.secrets["qdrant"].clone());
    config.validate()?;
    if runtime_config::load_config(&options.config)? != config || !config_exists {
        runtime_config::save_config(&options.config, &config)?;
    }
    if !config_exists || owned.files.contains_key(&options.config) {
        record(&mut owned, options.config.clone())?;
        save_owned(options, &owned)?;
    }
    service_manager::apply(&service, false, false)?;
    drop(ownership_guard);
    hooks
        .update_index(&config, &options.paths)
        .await
        .map_err(|_| anyhow::anyhow!("shared index update failed"))?;
    if !options.no_register {
        hooks.registration(options, false).map_err(|_| {
            anyhow::anyhow!("MCP registration failed; repair detected host configuration")
        })?;
    }
    let mut env = BTreeMap::new();
    if options.paths.isolated {
        env.insert(
            "CODE_DIVER_HOME".into(),
            options.paths.config.parent().unwrap().display().to_string(),
        );
    }
    let passed = hooks
        .doctor(&CommandPlan {
            program: options.executable.clone(),
            args: vec![
                "doctor".into(),
                "--config".into(),
                options.config.display().to_string(),
            ],
            env,
        })
        .map_err(|_| anyhow::anyhow!("doctor invocation failed"))?;
    eprintln!("doctor: {}", if passed { "PASS" } else { "FAIL" });
    if !passed {
        bail!("doctor failed; run doctor for repair instructions");
    }
    Ok(SetupReport {
        actions,
        doctor_passed: Some(passed),
    })
}
pub fn registration(
    options: &SetupOptions,
    uninstall: bool,
) -> Result<crate::mcp_registration::RegistrationReport> {
    let mut reg = crate::mcp_registration::Registration::new(
        &options.paths.hosts,
        &options.executable,
        &options.config,
        options.dry_run,
    )?;
    reg.claude_cli = options.claude_cli.clone();
    reg.runtime_root = registration_environment(options)?
        .get("CODE_DIVER_HOME")
        .map(PathBuf::from);
    let report = if uninstall {
        reg.unregister()?
    } else {
        reg.register()?
    };
    if report
        .hosts
        .iter()
        .any(|h| h.detected && h.problem.is_some())
    {
        bail!("MCP registration incomplete; repair detected host configuration");
    }
    Ok(report)
}

/// Environment for a registration adapter that separates host home from runtime root.
/// Host discovery must still use `options.paths.hosts`, never this runtime root.
pub fn registration_environment(options: &SetupOptions) -> Result<BTreeMap<String, String>> {
    let mut environment = BTreeMap::new();
    environment.insert(
        "CODE_DIVER_CONFIG".into(),
        options.config.display().to_string(),
    );
    if options.paths.isolated {
        let root = options
            .paths
            .config
            .parent()
            .ok_or_else(|| anyhow::anyhow!("isolated config has no parent"))?;
        service_manager::validate_path(root)?;
        environment.insert("CODE_DIVER_HOME".into(), root.display().to_string());
    }
    Ok(environment)
}
