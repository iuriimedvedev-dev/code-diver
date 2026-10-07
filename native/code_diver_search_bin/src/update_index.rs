use anyhow::{Result, bail};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::time::Duration;

use crate::metadata::{self, Metadata};
use crate::model_store::{ModelManifest, ModelSpec, ModelStore, Verification, verify_model};
use crate::runtime_config::{self, FileSecretStore, MacSecurity, RuntimeConfig, RuntimePaths};

const METADATA_MAX_BYTES: usize = 1024 * 1024;
const MAX_FILES: usize = 4096;

#[derive(Default)]
pub struct UpdateOptions<'a> {
    /// Fetch and validate metadata, but do not create directories or download files.
    pub dry_run: bool,
    /// Local manifest only: updates must not trust a manifest from the artifact server.
    /// Optional `models.embedder.model` declares identity; otherwise the repo's
    /// `-GGUF` suffix is removed. Input limits specified by index metadata must
    /// be declared in an override; the embedded manifest uses indexer defaults.
    pub model_manifest: Option<&'a Path>,
    pub keychain: Option<&'a dyn MacSecurity>,
}

pub type OwnershipRecorder<'a> = dyn Fn(&[CreatedArtifact]) -> Result<()> + Send + Sync + 'a;

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ArtifactKind {
    File,
    Directory,
    Symlink { target: PathBuf },
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CreatedArtifact {
    pub path: PathBuf,
    pub kind: ArtifactKind,
}

#[derive(Debug)]
pub struct UpdateOutcome {
    /// Resolve this directory once before opening multiple files to pin a snapshot.
    pub snapshot: PathBuf,
    pub previous: Option<PathBuf>,
    pub changed: bool,
    pub dry_run: bool,
    pub downloaded_files: usize,
    pub resumed_bytes: u64,
    /// Only paths newly created by this call, never preexisting containers.
    pub created_artifacts: Vec<CreatedArtifact>,
}

/// Fetch `artifact_url/index_name/index-metadata.json` using `secrets["artifacts"]`.
/// Publishes a verified snapshot through `paths.data/index_name`; retains all
/// prior snapshots and points `.index_name-previous` at the preceding version.
/// Existing unmanaged directories are refused without modification.
pub async fn update(config: &RuntimeConfig, paths: &RuntimePaths) -> Result<UpdateOutcome> {
    update_with_options(config, paths, UpdateOptions::default()).await
}

pub async fn update_with_options(
    config: &RuntimeConfig,
    paths: &RuntimePaths,
    options: UpdateOptions<'_>,
) -> Result<UpdateOutcome> {
    update_with_recorder(config, paths, options, None).await
}

/// The recorder must durably merge records before returning. Called under the
/// update lock, including on transfer failure; new publication links are recorded
/// before installation. An error prevents publication. Do not reenter the updater
/// or acquire its lock from the callback. Purge must hold the same update lock.
pub async fn update_with_recorder(
    config: &RuntimeConfig,
    paths: &RuntimePaths,
    options: UpdateOptions<'_>,
    recorder: Option<&OwnershipRecorder<'_>>,
) -> Result<UpdateOutcome> {
    if !paths.data.is_absolute() {
        bail!("artifact data directory must be absolute");
    }
    let name = config
        .profile
        .index_name
        .as_deref()
        .ok_or_else(|| anyhow::anyhow!("index name is required"))?;
    let current = paths.index_dir(name)?;
    let mut base = runtime_config::validate_url(
        config
            .profile
            .artifact_url
            .as_deref()
            .ok_or_else(|| anyhow::anyhow!("artifact URL is required"))?,
    )?;
    base.set_path(&format!("{}/{name}/", base.path().trim_end_matches('/')));
    let reference = config
        .secrets
        .get("artifacts")
        .ok_or_else(|| anyhow::anyhow!("artifacts SecretRef is required"))?;
    let token = runtime_config::resolve_secret(
        reference,
        |key| std::env::var(key).ok(),
        &FileSecretStore::new(paths),
        options.keychain,
    )?;
    let client = reqwest::Client::builder()
        .no_proxy()
        .timeout(Duration::from_secs(30))
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .map_err(|_| anyhow::anyhow!("cannot initialize verified artifact client"))?;
    let mut authorization =
        reqwest::header::HeaderValue::from_str(&format!("Bearer {}", token.expose()))
            .map_err(|_| anyhow::anyhow!("invalid artifact authentication"))?;
    authorization.set_sensitive(true);
    let mut response = client
        .get(base.join("index-metadata.json").unwrap())
        .header(reqwest::header::AUTHORIZATION, authorization)
        .send()
        .await
        .map_err(|_| anyhow::anyhow!("artifact metadata request failed"))?;
    if response.status() != reqwest::StatusCode::OK {
        bail!("artifact metadata request rejected");
    }
    let mut bytes = Vec::new();
    while let Some(chunk) = response
        .chunk()
        .await
        .map_err(|_| anyhow::anyhow!("artifact metadata transfer interrupted"))?
    {
        if bytes.len() + chunk.len() > METADATA_MAX_BYTES {
            bail!("artifact metadata exceeds size limit");
        }
        bytes.extend_from_slice(&chunk);
    }
    let metadata =
        metadata::decode(&bytes).map_err(|_| anyhow::anyhow!("invalid index metadata"))?;
    validate_embedding(&metadata, config, options.model_manifest).await?;
    let files = artifact_specs(&metadata, &base)?;
    let version = format!("{:x}", Sha256::digest(&bytes));
    let snapshots = paths.data.join(format!(".{name}-snapshots"));
    let snapshot = snapshots.join(&version);
    let previous = current_snapshot(&current, &snapshots)?;
    let mut outcome = UpdateOutcome {
        changed: previous.as_ref() != Some(&snapshot),
        snapshot: snapshot.clone(),
        previous,
        dry_run: options.dry_run,
        downloaded_files: 0,
        resumed_bytes: 0,
        created_artifacts: Vec::new(),
    };
    if options.dry_run {
        return Ok(outcome);
    }
    let data_created = safe_directory(&paths.data)?;
    let lock_path = paths.data.join(format!(".{name}-update.lock"));
    let lock = UpdateLock::acquire(lock_path.clone())?;
    outcome.previous = current_snapshot(&current, &snapshots)?;
    outcome.changed = outcome.previous.as_ref() != Some(&snapshot);
    let cache = paths.data.join(format!(".{name}-downloads"));
    let staging = snapshots.join(format!("{version}.staging"));
    let previous_link = paths.data.join(format!(".{name}-previous"));
    let mut candidates = BTreeSet::new();
    for path in [
        &snapshots,
        &snapshot,
        &staging,
        &cache,
        &current,
        &previous_link,
    ] {
        candidates.insert(path.clone());
    }
    for root in [&snapshot, &staging] {
        candidates.insert(root.join("index-metadata.json"));
        for relative in files.keys() {
            let mut path = root.join(relative);
            while path != *root {
                candidates.insert(path.clone());
                path = path.parent().unwrap().to_path_buf();
            }
        }
    }
    for (relative, spec) in &files {
        let directory = download_directory(&cache, relative, spec);
        candidates.insert(directory.clone());
        for file in ["artifact", "artifact.part", "artifact.lock"] {
            candidates.insert(directory.join(file));
        }
    }
    let mut absent = BTreeSet::new();
    for path in candidates {
        match fs::symlink_metadata(&path) {
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
                absent.insert(path);
            }
            Err(_) => bail!("cannot inspect artifact ownership"),
            Ok(_) => {}
        }
    }
    if data_created {
        absent.insert(paths.data.clone());
    }
    if lock.created {
        absent.insert(lock_path);
    }
    let assembly: Result<()> = async {
        safe_directory(&snapshots)?;
        safe_directory(&cache)?;
        let mut downloaded = Vec::new();
        for (relative, spec) in &files {
            let directory = download_directory(&cache, relative, spec);
            safe_directory(&directory)?;
            // This cache is exclusively owned by the OS-locked updater. ModelStore's
            // create-new lock may survive a killed process; no live owner exists here.
            let download_lock = directory.join("artifact.lock");
            match fs::symlink_metadata(&download_lock) {
                Ok(meta) if meta.is_file() => fs::remove_file(&download_lock)
                    .map_err(|_| anyhow::anyhow!("cannot clear interrupted artifact lock"))?,
                Ok(_) => bail!("unsafe artifact download lock"),
                Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
                Err(_) => bail!("cannot inspect artifact download lock"),
            }
            let path = directory.join(&spec.file);
            if spec.size == 0 {
                if verify_artifact(&path, spec)? != Verification::Valid {
                    let file = fs::OpenOptions::new()
                        .write(true)
                        .create_new(true)
                        .open(&path)
                        .map_err(|_| anyhow::anyhow!("cannot create empty artifact"))?;
                    file.sync_all()
                        .map_err(|_| anyhow::anyhow!("cannot sync empty artifact"))?;
                    sync(&directory)?;
                    outcome.downloaded_files += 1;
                }
                downloaded.push((relative, path));
            } else {
                let result = ModelStore::new(&directory)?
                    .download(spec, Some(token.expose()), |_| {})
                    .await?;
                outcome.downloaded_files += usize::from(result.downloaded);
                outcome.resumed_bytes += result.resumed_from;
                downloaded.push((relative, result.path));
            }
        }
        if snapshot.exists() {
            validate_snapshot(&snapshot, &bytes, &files)?;
        } else {
            if fs::symlink_metadata(&staging).is_ok() {
                validate_tree(&staging)?;
                fs::remove_dir_all(&staging)
                    .map_err(|_| anyhow::anyhow!("cannot clear interrupted snapshot staging"))?;
            }
            safe_directory(&staging)?;
            for (relative, source) in downloaded {
                let destination = staging.join(relative);
                safe_directory(destination.parent().unwrap())?;
                fs::copy(source, &destination)
                    .map_err(|_| anyhow::anyhow!("cannot assemble snapshot"))?;
                sync(&destination)?;
            }
            let mut file = fs::File::create(staging.join("index-metadata.json"))
                .map_err(|_| anyhow::anyhow!("cannot write snapshot metadata"))?;
            file.write_all(&bytes)
                .map_err(|_| anyhow::anyhow!("cannot write snapshot metadata"))?;
            file.sync_all()
                .map_err(|_| anyhow::anyhow!("cannot sync snapshot metadata"))?;
            validate_snapshot(&staging, &bytes, &files)?;
            sync_tree(&staging)?;
            fs::rename(&staging, &snapshot)
                .map_err(|_| anyhow::anyhow!("cannot finalize snapshot"))?;
            sync(&snapshots)?;
        }
        Ok(())
    }
    .await;
    let mut created = created_artifacts(&absent)?;
    if assembly.is_ok() && outcome.changed {
        for (path, target) in [
            (&previous_link, outcome.previous.as_ref()),
            (&current, Some(&snapshot)),
        ] {
            if absent.contains(path)
                && let Some(target) = target
            {
                created.push(CreatedArtifact {
                    path: path.clone(),
                    kind: ArtifactKind::Symlink {
                        target: target.clone(),
                    },
                });
            }
        }
    }
    if let Some(record) = recorder {
        record(&created)?;
    }
    assembly?;
    if outcome.changed {
        if let Some(previous) = &outcome.previous {
            replace_link(&paths.data.join(format!(".{name}-previous")), previous)?;
        }
        replace_link(&current, &snapshot)?;
        sync(&paths.data)?;
    }
    outcome.created_artifacts = created_artifacts(&absent)?;
    Ok(outcome)
}

fn download_directory(cache: &Path, relative: &str, spec: &ModelSpec) -> PathBuf {
    cache.join(format!(
        "{:x}",
        Sha256::digest(format!("{relative}:{}:{}", spec.sha256, spec.size))
    ))
}

fn created_artifacts(absent: &BTreeSet<PathBuf>) -> Result<Vec<CreatedArtifact>> {
    let mut result = Vec::new();
    for path in absent {
        let kind = match fs::symlink_metadata(path) {
            Ok(meta) if meta.is_symlink() => ArtifactKind::Symlink {
                target: fs::read_link(path)
                    .map_err(|_| anyhow::anyhow!("cannot inspect owned pointer"))?,
            },
            Ok(meta) if meta.is_dir() => ArtifactKind::Directory,
            Ok(meta) if meta.is_file() => ArtifactKind::File,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => continue,
            _ => bail!("cannot inspect artifact ownership"),
        };
        result.push(CreatedArtifact {
            path: path.clone(),
            kind,
        });
    }
    Ok(result)
}

async fn validate_embedding(
    metadata: &Metadata,
    config: &RuntimeConfig,
    override_path: Option<&Path>,
) -> Result<()> {
    if metadata.schema_version != metadata::SCHEMA_VERSION {
        bail!("unsupported index metadata schema");
    }
    let profile_source = config.profile.model_manifest_source()?;
    let remote_source = override_path
        .is_none()
        .then_some(profile_source)
        .flatten()
        .filter(|source| source.contains("://"));
    let source = match override_path {
        Some(path) => Some(path),
        None => profile_source
            .filter(|_| remote_source.is_none())
            .map(Path::new),
    };
    let bytes = if let Some(remote) = remote_source {
        // The foundation enforces transport/redirect policy without artifact credentials.
        crate::model_store::load_manifest_bytes(Some(remote)).await?
    } else if let Some(path) = source {
        if path.to_string_lossy().contains("://") {
            bail!("model manifest override must be local");
        }
        let file = fs::File::open(path)
            .map_err(|_| anyhow::anyhow!("cannot open local model manifest"))?;
        let mut bytes = Vec::new();
        file.take((crate::model_store::MANIFEST_MAX_BYTES + 1) as u64)
            .read_to_end(&mut bytes)
            .map_err(|_| anyhow::anyhow!("cannot read local model manifest"))?;
        bytes
    } else {
        crate::model_store::EMBEDDED_MANIFEST.as_bytes().to_vec()
    };
    let manifest = ModelManifest::parse(&bytes)?;
    let raw: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
    let model = manifest.models.embedder;
    let embedding = &metadata.embedding;
    let identity = raw["models"]["embedder"]["model"]
        .as_str()
        .unwrap_or_else(|| model.repo.strip_suffix("-GGUF").unwrap_or(&model.repo));
    if embedding.model != identity
        || model.dimensions != Some(embedding.dimensions)
        || embedding.dimensions == 0
        || config
            .profile
            .embedding_model
            .as_ref()
            .is_some_and(|v| v != &embedding.model)
        || config
            .profile
            .embedding_dimensions
            .is_some_and(|v| v != embedding.dimensions)
        || config
            .profile
            .collection
            .as_ref()
            .is_some_and(|v| v != &metadata.collection)
    {
        bail!("index embedding model, dimensions or collection mismatch");
    }
    for (field, expected) in [
        ("model_repo", model.repo.as_str()),
        ("model_file", model.file.as_str()),
        ("sha256", model.sha256.as_str()),
    ] {
        if let Some(value) = embedding.extra.get(field) {
            let valid = value.as_str().is_some_and(|v| {
                if field == "sha256" {
                    v.eq_ignore_ascii_case(expected)
                } else {
                    v == expected
                }
            });
            if !valid {
                bail!("index embedding identity or hash mismatch");
            }
        }
    }
    if embedding
        .extra
        .get("bytes")
        .is_some_and(|v| v.as_u64() != Some(model.size))
    {
        bail!("index embedding size mismatch");
    }
    // These are the native indexer's input defaults, not GGUF context sizes.
    for (field, default) in [
        ("max_input_chars", 2000),
        ("max_input_tokens", 512),
        ("token_safety_margin", 32),
    ] {
        if let Some(value) = embedding.extra.get(field) {
            let local = raw["models"]["embedder"].get(field).cloned().or_else(|| {
                (source.is_none() && remote_source.is_none()).then(|| serde_json::json!(default))
            });
            if local.as_ref() != Some(value) {
                bail!("index embedding input limits mismatch or unspecified locally");
            }
        }
    }
    Ok(())
}

fn artifact_specs(metadata: &Metadata, base: &reqwest::Url) -> Result<BTreeMap<String, ModelSpec>> {
    let files = metadata
        .extra
        .get("files")
        .and_then(|v| v.as_object())
        .ok_or_else(|| anyhow::anyhow!("artifact files manifest is required"))?;
    if files.is_empty() || files.len() > MAX_FILES {
        bail!("invalid artifact file count");
    }
    let mut result = BTreeMap::new();
    for (name, value) in files {
        if name.len() > 1024
            || name.split('/').any(|part| {
                part.is_empty()
                    || part == "."
                    || part == ".."
                    || part.len() > 255
                    || !part
                        .bytes()
                        .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'-' | b'_'))
            })
            || name == "index-metadata.json"
            || name.starts_with("index-metadata.json/")
        {
            bail!("unsafe artifact filename");
        }
        let spec = ModelSpec {
            label: String::new(),
            repo: String::new(),
            file: "artifact".into(),
            url: base
                .join(name)
                .map_err(|_| anyhow::anyhow!("invalid artifact path"))?
                .to_string(),
            sha256: value
                .get("sha256")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string(),
            size: value
                .get("bytes")
                .and_then(|v| v.as_u64())
                .ok_or_else(|| anyhow::anyhow!("invalid artifact byte count"))?,
            dimensions: None,
        };
        let mut validation = spec.clone();
        validation.size = spec.size.max(1);
        validation
            .validate()
            .map_err(|_| anyhow::anyhow!("invalid artifact size or SHA256"))?;
        if spec.size == 0
            && !spec
                .sha256
                .eq_ignore_ascii_case(&format!("{:x}", Sha256::digest([])))
        {
            bail!("empty artifact SHA256 mismatch");
        }
        result.insert(name.clone(), spec);
    }
    for name in result.keys() {
        for (index, _) in name.match_indices('/') {
            if result.contains_key(&name[..index]) {
                bail!("conflicting artifact paths");
            }
        }
    }
    Ok(result)
}

fn safe_directory(path: &Path) -> Result<bool> {
    match fs::symlink_metadata(path) {
        Ok(meta) if meta.is_dir() => Ok(false),
        Ok(_) => bail!("unsafe artifact directory"),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            if let Some(parent) = path.parent().filter(|p| !p.as_os_str().is_empty()) {
                safe_directory(parent)?;
            }
            fs::create_dir(path)
                .map_err(|_| anyhow::anyhow!("cannot create artifact directory"))?;
            Ok(true)
        }
        Err(_) => bail!("cannot inspect artifact directory"),
    }
}

fn current_snapshot(current: &Path, snapshots: &Path) -> Result<Option<PathBuf>> {
    match fs::symlink_metadata(current) {
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Ok(meta) if meta.is_symlink() => {
            let target = fs::read_link(current)
                .map_err(|_| anyhow::anyhow!("cannot read snapshot pointer"))?;
            if target.parent() != Some(snapshots)
                || !target.file_name().is_some_and(|v| {
                    v.to_str()
                        .is_some_and(|s| s.len() == 64 && s.bytes().all(|b| b.is_ascii_hexdigit()))
                })
            {
                bail!("unsafe snapshot pointer");
            }
            validate_tree(&target)?;
            Ok(Some(target))
        }
        Ok(_) => {
            bail!("existing index must be a managed snapshot; migrate directory before updating")
        }
        Err(_) => bail!("cannot inspect current index"),
    }
}

fn validate_tree(path: &Path) -> Result<()> {
    let meta =
        fs::symlink_metadata(path).map_err(|_| anyhow::anyhow!("cannot inspect snapshot"))?;
    if meta.is_dir() {
        for entry in fs::read_dir(path).map_err(|_| anyhow::anyhow!("cannot inspect snapshot"))? {
            validate_tree(
                &entry
                    .map_err(|_| anyhow::anyhow!("cannot inspect snapshot"))?
                    .path(),
            )?;
        }
    } else if !meta.is_file() {
        bail!("unsafe snapshot path");
    }
    Ok(())
}

fn validate_snapshot(
    path: &Path,
    metadata: &[u8],
    files: &BTreeMap<String, ModelSpec>,
) -> Result<()> {
    validate_tree(path)?;
    if fs::read(path.join("index-metadata.json")).ok().as_deref() != Some(metadata) {
        bail!("snapshot metadata mismatch");
    }
    for (relative, spec) in files {
        if verify_artifact(&path.join(relative), spec)? != Verification::Valid {
            bail!("snapshot artifact verification failed");
        }
    }
    Ok(())
}

fn verify_artifact(path: &Path, spec: &ModelSpec) -> Result<Verification> {
    if spec.size != 0 {
        return verify_model(path, spec);
    }
    match fs::symlink_metadata(path) {
        Ok(meta) if meta.is_file() && meta.len() == 0 => Ok(Verification::Valid),
        Ok(meta) if meta.is_file() => Ok(Verification::Invalid),
        Ok(_) => bail!("unsafe empty artifact path"),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(Verification::Missing),
        Err(_) => bail!("cannot inspect empty artifact"),
    }
}

fn sync(path: &Path) -> Result<()> {
    fs::File::open(path)
        .and_then(|file| file.sync_all())
        .map_err(|_| anyhow::anyhow!("cannot sync artifact snapshot"))
}
fn sync_tree(path: &Path) -> Result<()> {
    for entry in
        fs::read_dir(path).map_err(|_| anyhow::anyhow!("cannot read snapshot directory"))?
    {
        let path = entry
            .map_err(|_| anyhow::anyhow!("cannot read snapshot directory"))?
            .path();
        if path.is_dir() {
            sync_tree(&path)?;
        }
    }
    sync(path)
}

fn replace_link(path: &Path, target: &Path) -> Result<()> {
    #[cfg(unix)]
    {
        let temp = path.with_extension("next");
        if let Ok(meta) = fs::symlink_metadata(&temp) {
            if !meta.is_symlink() {
                bail!("unsafe temporary snapshot pointer");
            }
            fs::remove_file(&temp).map_err(|_| anyhow::anyhow!("cannot clear snapshot pointer"))?;
        }
        std::os::unix::fs::symlink(target, &temp)
            .map_err(|_| anyhow::anyhow!("cannot prepare snapshot pointer"))?;
        fs::rename(&temp, path)
            .map_err(|_| anyhow::anyhow!("cannot atomically publish snapshot"))?;
        Ok(())
    }
    #[cfg(not(unix))]
    {
        let _ = (path, target);
        bail!("artifact snapshots require macOS or Linux");
    }
}

struct UpdateLock {
    _file: fs::File,
    created: bool,
}
impl Drop for UpdateLock {
    fn drop(&mut self) {
        let _ = self._file.unlock();
    }
}
impl UpdateLock {
    fn acquire(path: PathBuf) -> Result<Self> {
        match fs::symlink_metadata(&path) {
            Ok(meta) if meta.is_file() => {}
            Ok(_) => bail!("unsafe index update lock"),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
            Err(_) => bail!("cannot inspect index update lock"),
        }
        let (file, created) = match fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&path)
        {
            Ok(file) => (file, true),
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => (
                fs::OpenOptions::new()
                    .write(true)
                    .open(&path)
                    .map_err(|_| anyhow::anyhow!("cannot open index update lock"))?,
                false,
            ),
            Err(_) => bail!("cannot open index update lock"),
        };
        loop {
            match file.try_lock() {
                Ok(()) => break,
                Err(fs::TryLockError::WouldBlock) => bail!("index update already active"),
                Err(fs::TryLockError::Error(error))
                    if error.kind() == std::io::ErrorKind::Interrupted => {}
                Err(fs::TryLockError::Error(_)) => bail!("cannot acquire index update lock"),
            }
        }
        Ok(Self {
            _file: file,
            created,
        })
    }
}

#[cfg(test)]
mod lock_tests {
    use super::*;

    #[test]
    fn completed_update_releases_lock_with_inherited_descriptor() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("update.lock");
        let lock = UpdateLock::acquire(path.clone()).unwrap();
        // A clone retains the same open-file description as a descriptor inherited by fork.
        let inherited = lock._file.try_clone().unwrap();
        assert!(UpdateLock::acquire(path.clone()).is_err());
        drop(lock);
        let next = UpdateLock::acquire(path.clone())
            .unwrap_or_else(|error| panic!("completed update retained its lock: {error}"));
        drop(inherited);
        assert!(UpdateLock::acquire(path.clone()).is_err());
        drop(next);
        assert!(UpdateLock::acquire(path).is_ok());
    }
}
