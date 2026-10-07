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
    config.validate()?;
    if !paths.data.is_absolute() {
        bail!(
            "artifact data directory must be absolute; set CODE_DIVER_HOME or XDG_DATA_HOME to an absolute directory"
        );
    }
    let name = config
        .profile
        .index_name
        .as_deref()
        .ok_or_else(|| anyhow::anyhow!("index name is required; set profile.index_name to the published artifact directory name"))?;
    let current = paths.index_dir(name)?;
    let mut base = runtime_config::validate_url(
        config
            .profile
            .artifact_url
            .as_deref()
            .ok_or_else(|| anyhow::anyhow!("artifact URL is required; set profile.artifact_url to the base URL containing index_name/index-metadata.json"))?,
    )?;
    base.set_path(&format!("{}/{name}/", base.path().trim_end_matches('/')));
    let reference = config
        .secrets
        .get("artifacts")
        .ok_or_else(|| anyhow::anyhow!("artifacts SecretRef is required; run code-diver setup --key-file PATH or configure secrets.artifacts with a read-only key reference"))?;
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
        .map_err(|_| anyhow::anyhow!("cannot initialize verified artifact client: HTTP client setup failed; check system TLS configuration and retry"))?;
    let mut authorization =
        reqwest::header::HeaderValue::from_str(&format!("Bearer {}", token.expose()))
            .map_err(|_| anyhow::anyhow!("invalid artifact authentication: key cannot form an HTTP header; replace secrets.artifacts with a valid read-only key"))?;
    authorization.set_sensitive(true);
    let requested = base.join("index-metadata.json").unwrap();
    let mut response = client
        .get(requested.clone())
        .header(reqwest::header::AUTHORIZATION, authorization)
        .send()
        .await
        .map_err(|_| anyhow::anyhow!("artifact metadata request failed: {requested}; check connectivity, TLS trust and artifact_url + index_name directory containing index-metadata.json"))?;
    if response.status() != reqwest::StatusCode::OK {
        bail!(
            "artifact metadata request rejected: {requested} HTTP {}; artifact_url + index_name must identify the directory containing index-metadata.json; check corrected profile values and artifact read credentials",
            response.status().as_u16()
        );
    }
    let mut bytes = Vec::new();
    while let Some(chunk) = response
        .chunk()
        .await
        .map_err(|_| anyhow::anyhow!("artifact metadata transfer interrupted: {requested}; check connectivity and retry code-diver update-index"))?
    {
        if bytes.len() + chunk.len() > METADATA_MAX_BYTES {
            bail!("artifact metadata exceeds {METADATA_MAX_BYTES} byte limit: {requested}; ask the index owner to publish a bounded index-metadata.json manifest");
        }
        bytes.extend_from_slice(&chunk);
    }
    let metadata = metadata::decode(&bytes).map_err(|cause| anyhow::anyhow!("invalid index metadata at {requested}: {cause}; ask the index owner to republish valid schema 2 index-metadata.json"))?;
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
            Err(cause) => bail!(
                "cannot inspect artifact ownership at {}: {cause}; check directory permissions before retrying",
                path.display()
            ),
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
                    .map_err(|cause| anyhow::anyhow!("cannot clear interrupted artifact lock {}: {cause}; check directory permissions and retry", download_lock.display()))?,
                Ok(_) => bail!("unsafe artifact download lock {}; expected a regular file; preserve the object and repair the cache path", download_lock.display()),
                Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
                Err(cause) => bail!("cannot inspect artifact download lock {}: {cause}; check cache permissions", download_lock.display()),
            }
            let path = directory.join(&spec.file);
            if spec.size == 0 {
                if verify_artifact(&path, spec)? != Verification::Valid {
                    let file = fs::OpenOptions::new()
                        .write(true)
                        .create_new(true)
                        .open(&path)
                        .map_err(|cause| anyhow::anyhow!("cannot create empty artifact {}: {cause}; check cache permissions and conflicting files", path.display()))?;
                    file.sync_all()
                        .map_err(|cause| anyhow::anyhow!("cannot sync empty artifact {}: {cause}; check free space and storage health", path.display()))?;
                    sync(&directory)?;
                    outcome.downloaded_files += 1;
                }
                downloaded.push((relative, path));
            } else {
                use std::io::IsTerminal;
                let mut progress = crate::model_store::ProgressWriter::new(
                    std::io::stderr(),
                    std::io::stderr().is_terminal(),
                    relative,
                );
                let result = ModelStore::new(&directory)?
                    .download(spec, Some(token.expose()), |p| {
                        let _ = progress.update(p);
                    })
                    .await.map_err(|error| {
                        if relative == metadata.ranker_file() {
                            anyhow::anyhow!("{} Transfer failed: {error}", metadata.ranker_publication_error())
                        } else {
                            anyhow::anyhow!("artifact {relative} transfer failed: {error}; check artifact read credentials, connectivity and the published files manifest")
                        }
                    })?;
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
                    .map_err(|cause| anyhow::anyhow!("cannot clear interrupted snapshot staging {}: {cause}; check permissions and retry", staging.display()))?;
            }
            safe_directory(&staging)?;
            for (relative, source) in downloaded {
                let destination = staging.join(relative);
                safe_directory(destination.parent().unwrap())?;
                fs::copy(source, &destination)
                    .map_err(|cause| anyhow::anyhow!("cannot assemble snapshot {}: {cause}; check free space and directory permissions", destination.display()))?;
                sync(&destination)?;
            }
            let mut file = fs::File::create(staging.join("index-metadata.json"))
                .map_err(|cause| anyhow::anyhow!("cannot write snapshot metadata in {}: {cause}; check free space and directory permissions", staging.display()))?;
            file.write_all(&bytes)
                .map_err(|cause| anyhow::anyhow!("cannot write snapshot metadata in {}: {cause}; check free space and storage health", staging.display()))?;
            file.sync_all()
                .map_err(|cause| anyhow::anyhow!("cannot sync snapshot metadata in {}: {cause}; check storage health before retrying", staging.display()))?;
            validate_snapshot(&staging, &bytes, &files)?;
            sync_tree(&staging)?;
            fs::rename(&staging, &snapshot)
                .map_err(|cause| anyhow::anyhow!("cannot finalize snapshot {}: {cause}; check directory permissions and free space; the current snapshot is unchanged", snapshot.display()))?;
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
                target: fs::read_link(path).map_err(|cause| {
                    anyhow::anyhow!(
                        "cannot inspect owned pointer {}: {cause}; check directory permissions",
                        path.display()
                    )
                })?,
            },
            Ok(meta) if meta.is_dir() => ArtifactKind::Directory,
            Ok(meta) if meta.is_file() => ArtifactKind::File,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => continue,
            Ok(_) => bail!(
                "cannot inspect artifact ownership at {}: unsupported object type; preserve the object and inspect the cache",
                path.display()
            ),
            Err(cause) => bail!(
                "cannot inspect artifact ownership at {}: {cause}; check directory permissions",
                path.display()
            ),
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
        bail!(
            "unsupported index metadata schema {}; ask the index owner to republish schema {} index-metadata.json",
            metadata.schema_version,
            metadata::SCHEMA_VERSION
        );
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
            bail!(
                "model manifest override must be local; supply a filesystem path with --model-manifest, or configure the remote source in the profile"
            );
        }
        let file = fs::File::open(path)
            .map_err(|cause| anyhow::anyhow!("cannot open local model manifest {}: {cause}; correct --model-manifest and check read permissions", path.display()))?;
        let mut bytes = Vec::new();
        file.take((crate::model_store::MANIFEST_MAX_BYTES + 1) as u64)
            .read_to_end(&mut bytes)
            .map_err(|cause| anyhow::anyhow!("cannot read local model manifest {}: {cause}; check storage health and read permissions", path.display()))?;
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
        bail!(
            "index embedding model, dimensions or collection mismatch; select a profile and model manifest matching index-metadata.json, or ask the owner to reindex into a new collection"
        );
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
                bail!(
                    "index embedding {field} identity or hash mismatch; select the model manifest used to produce this index or ask the owner to republish matching metadata"
                );
            }
        }
    }
    if embedding
        .extra
        .get("bytes")
        .is_some_and(|v| v.as_u64() != Some(model.size))
    {
        bail!(
            "index embedding size mismatch; select the model manifest used to produce this index or ask the owner to republish matching bytes metadata"
        );
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
                bail!(
                    "index embedding input limits mismatch or unspecified locally; select the matching model manifest with explicit max_input_chars, max_input_tokens and token_safety_margin"
                );
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
        .ok_or_else(|| anyhow::anyhow!("artifact files manifest is required; ask the index owner to publish files with bytes and SHA-256 in index-metadata.json"))?;
    if metadata.schema_version == metadata::SCHEMA_VERSION
        && !files.contains_key(metadata.ranker_file())
    {
        bail!("{}", metadata.ranker_publication_error());
    }
    if files.is_empty() || files.len() > MAX_FILES {
        bail!(
            "invalid artifact file count {}; ask the index owner to publish between 1 and {MAX_FILES} files in index-metadata.json",
            files.len()
        );
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
            bail!(
                "unsafe artifact filename; ask the index owner to publish relative paths without traversal, separators inside components or reserved index-metadata.json paths"
            );
        }
        let spec = ModelSpec {
            label: String::new(),
            repo: String::new(),
            file: "artifact".into(),
            url: base
                .join(name)
                .map_err(|_| anyhow::anyhow!("invalid artifact path for {name}; ask the index owner to publish valid relative filenames"))?
                .to_string(),
            sha256: value
                .get("sha256")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string(),
            size: value
                .get("bytes")
                .and_then(|v| v.as_u64())
                .ok_or_else(|| anyhow::anyhow!("invalid artifact byte count for {name}; ask the index owner to publish a nonnegative integer bytes field in index-metadata.json"))?,
            dimensions: None,
        };
        let mut validation = spec.clone();
        validation.size = spec.size.max(1);
        validation
            .validate()
            .map_err(|_| anyhow::anyhow!("invalid artifact size or SHA256 for {name}; ask the index owner to publish the exact byte count and 64-digit SHA-256 in index-metadata.json"))?;
        if spec.size == 0
            && !spec
                .sha256
                .eq_ignore_ascii_case(&format!("{:x}", Sha256::digest([])))
        {
            bail!(
                "empty artifact SHA256 mismatch; ask the index owner to publish the SHA-256 of zero bytes for empty files"
            );
        }
        result.insert(name.clone(), spec);
    }
    for name in result.keys() {
        for (index, _) in name.match_indices('/') {
            if result.contains_key(&name[..index]) {
                bail!(
                    "conflicting artifact paths; ask the index owner to remove file/directory prefix collisions from the files manifest"
                );
            }
        }
    }
    Ok(result)
}

fn safe_directory(path: &Path) -> Result<bool> {
    match fs::symlink_metadata(path) {
        Ok(meta) if meta.is_dir() => Ok(false),
        Ok(_) => bail!(
            "unsafe artifact directory {}; expected a real directory, not a file or symlink; preserve the object and choose a safe runtime data path",
            path.display()
        ),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            if let Some(parent) = path.parent().filter(|p| !p.as_os_str().is_empty()) {
                safe_directory(parent)?;
            }
            fs::create_dir(path)
                .map_err(|cause| anyhow::anyhow!("cannot create artifact directory {}: {cause}; check parent permissions and free space", path.display()))?;
            Ok(true)
        }
        Err(cause) => bail!(
            "cannot inspect artifact directory {}: {cause}; check parent permissions",
            path.display()
        ),
    }
}

fn current_snapshot(current: &Path, snapshots: &Path) -> Result<Option<PathBuf>> {
    match fs::symlink_metadata(current) {
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Ok(meta) if meta.is_symlink() => {
            let target = fs::read_link(current).map_err(|cause| {
                anyhow::anyhow!(
                    "cannot read snapshot pointer {}: {cause}; check directory permissions",
                    current.display()
                )
            })?;
            if target.parent() != Some(snapshots)
                || !target.file_name().is_some_and(|v| {
                    v.to_str()
                        .is_some_and(|s| s.len() == 64 && s.bytes().all(|b| b.is_ascii_hexdigit()))
                })
            {
                bail!(
                    "unsafe snapshot pointer {}; target must be a SHA-256 directory directly inside {}; preserve the pointer and restore a valid managed snapshot",
                    current.display(),
                    snapshots.display()
                );
            }
            validate_tree(&target)?;
            Ok(Some(target))
        }
        Ok(_) => {
            bail!("existing index must be a managed snapshot; migrate directory before updating")
        }
        Err(cause) => bail!(
            "cannot inspect current index {}: {cause}; check directory permissions",
            current.display()
        ),
    }
}

fn validate_tree(path: &Path) -> Result<()> {
    let meta =
        fs::symlink_metadata(path).map_err(|cause| anyhow::anyhow!("cannot inspect snapshot {}: {cause}; check snapshot existence and directory permissions", path.display()))?;
    if meta.is_dir() {
        for entry in fs::read_dir(path).map_err(|cause| {
            anyhow::anyhow!(
                "cannot inspect snapshot {}: {cause}; check directory permissions",
                path.display()
            )
        })? {
            validate_tree(
                &entry
                    .map_err(|cause| {
                        anyhow::anyhow!(
                            "cannot inspect snapshot entry in {}: {cause}; check storage health",
                            path.display()
                        )
                    })?
                    .path(),
            )?;
        }
    } else if !meta.is_file() {
        bail!(
            "unsafe snapshot path {}; only regular files and real directories are allowed; preserve the object and restore a verified snapshot",
            path.display()
        );
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
        bail!(
            "snapshot metadata mismatch at {}; preserve the current index and restore or republish the matching index-metadata.json",
            path.display()
        );
    }
    for (relative, spec) in files {
        if verify_artifact(&path.join(relative), spec)? != Verification::Valid {
            bail!(
                "snapshot artifact verification failed for {}: size or SHA-256 mismatch; ask the owner to republish matching files and metadata",
                path.join(relative).display()
            );
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
        Ok(_) => bail!(
            "unsafe empty artifact path {}; expected a regular file; preserve the object and repair the cache path",
            path.display()
        ),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(Verification::Missing),
        Err(cause) => bail!(
            "cannot inspect empty artifact {}: {cause}; check cache permissions",
            path.display()
        ),
    }
}

fn sync(path: &Path) -> Result<()> {
    fs::File::open(path)
        .and_then(|file| file.sync_all())
        .map_err(|cause| anyhow::anyhow!("cannot sync artifact snapshot {}: {cause}; check storage health and free space before retrying", path.display()))
}
fn sync_tree(path: &Path) -> Result<()> {
    for entry in fs::read_dir(path).map_err(|cause| {
        anyhow::anyhow!(
            "cannot read snapshot directory {}: {cause}; check directory permissions",
            path.display()
        )
    })? {
        let path = entry
            .map_err(|cause| {
                anyhow::anyhow!(
                    "cannot read snapshot directory entry in {}: {cause}; check storage health",
                    path.display()
                )
            })?
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
                bail!(
                    "unsafe temporary snapshot pointer {}; expected a symlink; preserve the object and resolve the conflicting path before retrying",
                    temp.display()
                );
            }
            fs::remove_file(&temp).map_err(|cause| {
                anyhow::anyhow!(
                    "cannot clear snapshot pointer {}: {cause}; check directory permissions",
                    temp.display()
                )
            })?;
        }
        std::os::unix::fs::symlink(target, &temp)
            .map_err(|cause| anyhow::anyhow!("cannot prepare snapshot pointer {}: {cause}; check directory permissions and symlink support", temp.display()))?;
        fs::rename(&temp, path)
            .map_err(|cause| anyhow::anyhow!("cannot atomically publish snapshot {}: {cause}; check directory permissions and retry", path.display()))?;
        Ok(())
    }
    #[cfg(not(unix))]
    {
        let _ = (path, target);
        bail!(
            "artifact snapshots require macOS or Linux; run code-diver update-index on a supported Unix host"
        );
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
            Ok(_) => bail!(
                "unsafe index update lock {}; expected a regular file; preserve the object and repair the runtime data path",
                path.display()
            ),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
            Err(cause) => bail!(
                "cannot inspect index update lock {}: {cause}; check directory permissions",
                path.display()
            ),
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
                    .map_err(|cause| anyhow::anyhow!("cannot open index update lock {}: {cause}; check write permissions; do not delete an active lock", path.display()))?,
                false,
            ),
            Err(cause) => bail!("cannot open index update lock {}: {cause}; check directory permissions and free space", path.display()),
        };
        loop {
            match file.try_lock() {
                Ok(()) => break,
                Err(fs::TryLockError::WouldBlock) => bail!(
                    "index update already active; wait for the current update or purge to finish and retry code-diver update-index; do not delete the lock file"
                ),
                Err(fs::TryLockError::Error(error))
                    if error.kind() == std::io::ErrorKind::Interrupted => {}
                Err(fs::TryLockError::Error(cause)) => bail!(
                    "cannot acquire index update lock {}: {cause}; check filesystem locking support; do not delete the lock file",
                    path.display()
                ),
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
    fn unsafe_directory_and_snapshot_errors_name_path_and_repair() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("conflict");
        fs::write(&path, "owned-by-user").unwrap();
        let error = safe_directory(&path).unwrap_err().to_string();
        assert!(
            error.contains("conflict") && error.contains("preserve"),
            "{error}"
        );
        let missing = temp.path().join("missing-snapshot");
        let error = validate_tree(&missing).unwrap_err().to_string();
        assert!(
            error.contains("missing-snapshot") && error.contains("permissions"),
            "{error}"
        );
        assert_eq!(fs::read_to_string(path).unwrap(), "owned-by-user");
    }

    #[tokio::test]
    async fn missing_configuration_names_actionable_fields_without_writes() {
        use crate::runtime_config::Platform;
        let temp = tempfile::tempdir().unwrap();
        let paths = RuntimePaths::from_env(Platform::MacOs, |key| {
            (key == "CODE_DIVER_HOME").then(|| temp.path().display().to_string())
        })
        .unwrap();
        let mut config = RuntimeConfig::default();
        let error = update(&config, &paths).await.unwrap_err().to_string();
        assert!(error.contains("profile.index_name"), "{error}");
        config.profile.index_name = Some("test".into());
        let error = update(&config, &paths).await.unwrap_err().to_string();
        assert!(error.contains("profile.artifact_url"), "{error}");
        config.profile.artifact_url = Some("https://example.invalid/base".into());
        let error = update(&config, &paths).await.unwrap_err().to_string();
        assert!(error.contains("secrets.artifacts"), "{error}");
        assert!(error.contains("read-only"), "{error}");
        assert!(!paths.data.exists());
    }

    #[tokio::test]
    async fn m5c_updater_missing_published_ranker_has_guidance() {
        use crate::runtime_config::{Platform, SecretStore, SecretValue};
        let mut value: serde_json::Value = serde_json::from_slice(include_bytes!(
            "../tests/fixtures/shared-index-metadata.json"
        ))
        .unwrap();
        let name = value["meta_ranker"]["file"].as_str().unwrap().to_string();
        let ranker = serde_json::json!({"bytes":1, "sha256":"a".repeat(64)});
        value["files"] = serde_json::json!({name.clone(): ranker});
        let body = value.to_string();
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        listener.set_nonblocking(true).unwrap();
        let server = std::thread::spawn(move || {
            for status in [200, 404] {
                let deadline = std::time::Instant::now() + Duration::from_secs(5);
                let (mut stream, _) = loop {
                    match listener.accept() {
                        Ok(stream) => break stream,
                        Err(error)
                            if error.kind() == std::io::ErrorKind::WouldBlock
                                && std::time::Instant::now() < deadline =>
                        {
                            std::thread::sleep(Duration::from_millis(10))
                        }
                        Err(error) => panic!("local fixture did not receive request: {error}"),
                    }
                };
                stream.set_nonblocking(false).unwrap();
                stream
                    .set_read_timeout(Some(Duration::from_secs(5)))
                    .unwrap();
                let mut request = Vec::new();
                while !request.ends_with(b"\r\n\r\n") {
                    let mut byte = [0];
                    stream.read_exact(&mut byte).unwrap();
                    request.push(byte[0]);
                }
                let content = if status == 200 { body.as_str() } else { "" };
                write!(stream, "HTTP/1.1 {status} Test\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{content}", content.len()).unwrap();
            }
        });
        let temp = tempfile::tempdir().unwrap();
        let paths = RuntimePaths::from_env(Platform::MacOs, |key| {
            (key == "CODE_DIVER_HOME").then(|| temp.path().display().to_string())
        })
        .unwrap();
        FileSecretStore::new(&paths)
            .put(
                "artifacts",
                &SecretValue::new("synthetic-private-token".into()).unwrap(),
            )
            .unwrap();
        let mut config = RuntimeConfig::default();
        config.profile.index_name = Some("pier".into());
        config.profile.artifact_url = Some(format!("http://{address}"));
        config.secrets.insert(
            "artifacts".into(),
            runtime_config::SecretRef::File("artifacts".into()),
        );
        let error = update(&config, &paths).await.unwrap_err().to_string();
        server.join().unwrap();
        for expected in [&name, "owner", "SHA-256", "index-metadata.json"] {
            assert!(error.contains(expected), "{error}");
        }
        assert!(!error.contains("synthetic-private-token"));
    }

    #[test]
    fn m5c_updater_missing_ranker_names_publication() {
        let mut metadata = metadata::decode(include_bytes!(
            "../tests/fixtures/shared-index-metadata.json"
        ))
        .unwrap();
        let name = metadata.extra["meta_ranker"]["file"]
            .as_str()
            .unwrap()
            .to_string();
        metadata
            .extra
            .get_mut("files")
            .unwrap()
            .as_object_mut()
            .unwrap()
            .remove(&name);
        let base = reqwest::Url::parse("https://example.invalid/pier/").unwrap();
        let error = artifact_specs(&metadata, &base).unwrap_err().to_string();
        for expected in [&name, "owner", "SHA-256", "index-metadata.json"] {
            assert!(error.contains(expected), "{error}");
        }
    }

    #[tokio::test]
    async fn m5c_bare_index_http_failure_preserves_url_status_and_hint() {
        use crate::runtime_config::{Platform, SecretStore, SecretValue};
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut request = [0; 4096];
            let size = stream.read(&mut request).unwrap();
            let request = String::from_utf8_lossy(&request[..size]);
            assert!(request.starts_with("GET /shared/pier/index-metadata.json "));
            stream
                .write_all(
                    b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
                )
                .unwrap();
        });
        let temp = tempfile::tempdir().unwrap();
        let paths = RuntimePaths::from_env(Platform::MacOs, |name| {
            (name == "CODE_DIVER_HOME").then(|| temp.path().display().to_string())
        })
        .unwrap();
        let secret = "m5c-private-artifact-token";
        FileSecretStore::new(&paths)
            .put("artifacts", &SecretValue::new(secret.into()).unwrap())
            .unwrap();
        let mut config = RuntimeConfig::default();
        config.profile.index_name = Some("pier".into());
        config.profile.artifact_url = Some(format!("http://{address}/shared"));
        config.secrets.insert(
            "artifacts".into(),
            runtime_config::SecretRef::File("artifacts".into()),
        );
        let error = update(&config, &paths).await.unwrap_err().to_string();
        server.join().unwrap();
        assert!(error.contains(&format!("http://{address}/shared/pier/index-metadata.json")));
        assert!(error.contains("HTTP 404"));
        assert!(error.contains("artifact_url + index_name"));
        assert!(!error.contains(secret));
    }

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
