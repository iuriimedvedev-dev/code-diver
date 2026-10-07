use anyhow::{Result, bail};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fs;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::time::Duration;

pub const EMBEDDED_MANIFEST: &str = include_str!("runtime_models.json");
pub const MANIFEST_MAX_BYTES: usize = 1024 * 1024;
pub const DOWNLOAD_TIMEOUT_SECS: u64 = 3600;

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LlamaCpp {
    pub min_build: u32,
    pub install_hint: String,
}
#[derive(Clone, Serialize, Deserialize)]
pub struct ModelSpec {
    pub label: String,
    pub repo: String,
    pub file: String,
    pub url: String,
    pub sha256: String,
    pub size: u64,
    pub dimensions: Option<usize>,
}
impl std::fmt::Debug for ModelSpec {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("ModelSpec")
            .field("size", &self.size)
            .field("sha256", &self.sha256)
            .field("dimensions", &self.dimensions)
            .finish_non_exhaustive()
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Models {
    pub embedder: ModelSpec,
    pub reranker: ModelSpec,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ModelManifest {
    pub schema: u32,
    pub llama_cpp: LlamaCpp,
    pub models: Models,
}
impl ModelManifest {
    pub fn embedded() -> Result<Self> {
        Self::parse(EMBEDDED_MANIFEST.as_bytes())
    }
    pub fn parse(bytes: &[u8]) -> Result<Self> {
        if bytes.len() > MANIFEST_MAX_BYTES {
            bail!("model manifest exceeds size limit");
        }
        let manifest: Self = serde_json::from_slice(bytes)
            .map_err(|_| anyhow::anyhow!("invalid model manifest JSON"))?;
        if manifest.schema != 1 || manifest.llama_cpp.min_build == 0 {
            bail!("unsupported model manifest schema or build requirement");
        }
        manifest.models.embedder.validate()?;
        manifest.models.reranker.validate()?;
        if manifest.models.embedder.file == manifest.models.reranker.file {
            bail!("model filenames must be distinct");
        }
        Ok(manifest)
    }
}
impl ModelSpec {
    pub fn validate(&self) -> Result<()> {
        if self.file.is_empty()
            || self.file.len() > 255
            || self.file == "."
            || self.file == ".."
            || !self
                .file
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'-' | b'_'))
        {
            bail!("invalid model filename; use a single safe filename");
        }
        if self.size == 0
            || self.sha256.len() != 64
            || !self.sha256.bytes().all(|b| b.is_ascii_hexdigit())
            || self.dimensions == Some(0)
        {
            bail!("invalid model size, SHA256 or dimensions");
        }
        download_url(&self.url)?;
        Ok(())
    }
}
fn download_url(raw: &str) -> Result<reqwest::Url> {
    let url = reqwest::Url::parse(raw).map_err(|_| anyhow::anyhow!("invalid download URL"))?;
    let local = url
        .host_str()
        .is_some_and(|h| matches!(h, "localhost" | "127.0.0.1" | "[::1]" | "::1"));
    if !(url.scheme() == "https" || url.scheme() == "http" && local)
        || !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
    {
        bail!(
            "download requires HTTPS (HTTP only for loopback), without credentials, query or fragment"
        );
    }
    Ok(url)
}
fn client(timeout: Duration) -> Result<reqwest::Client> {
    if timeout.is_zero() {
        bail!("download timeout must be positive");
    }
    reqwest::Client::builder()
        .no_proxy()
        .timeout(timeout)
        .connect_timeout(Duration::from_secs(15))
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .map_err(|_| anyhow::anyhow!("cannot initialize verified download client"))
}
const MAX_REDIRECTS: usize = 5;
fn public_address(ip: std::net::IpAddr) -> bool {
    match ip {
        std::net::IpAddr::V4(ip) => {
            !ip.is_private()
                && !ip.is_loopback()
                && !ip.is_link_local()
                && !ip.is_unspecified()
                && !ip.is_multicast()
                && !ip.is_broadcast()
                && ip.octets()[0] != 0
                && !(ip.octets()[0] == 100 && (64..=127).contains(&ip.octets()[1]))
                && !(ip.octets()[0] == 198 && matches!(ip.octets()[1], 18 | 19))
                && ip.octets()[0] < 240
        }
        std::net::IpAddr::V6(ip) => {
            ip.to_ipv4_mapped()
                .map(public_address_v4)
                .unwrap_or_else(|| {
                    let segments = ip.segments();
                    segments[0] & 0xe000 == 0x2000
                        && segments[0] != 0x2002
                        && !(segments[0] == 0x2001 && segments[1] == 0)
                })
        }
    }
}
fn public_address_v4(ip: std::net::Ipv4Addr) -> bool {
    public_address(std::net::IpAddr::V4(ip))
}
fn redirect_url(current: &reqwest::Url, location: &str) -> Result<reqwest::Url> {
    let next = current
        .join(location)
        .map_err(|_| anyhow::anyhow!("invalid model redirect"))?;
    let local_test = current.scheme() == "http"
        && next.scheme() == "http"
        && next
            .host_str()
            .is_some_and(|h| matches!(h, "localhost" | "127.0.0.1" | "[::1]"));
    if !(next.scheme() == "https" || local_test)
        || !next.username().is_empty()
        || next.password().is_some()
        || next.fragment().is_some()
    {
        bail!("unsafe model redirect");
    }
    Ok(next)
}
async fn model_request(
    timeout: Duration,
    original: reqwest::Url,
    token: Option<&str>,
    offset: u64,
) -> Result<reqwest::Response> {
    let deadline = tokio::time::Instant::now() + timeout;
    let operation = async {
        let mut url = original.clone();
        let mut credentials_allowed = true;
        for hop in 0..=MAX_REDIRECTS {
            let remaining = deadline.saturating_duration_since(tokio::time::Instant::now());
            let client = if url.scheme() == "https" {
                let host = url
                    .host_str()
                    .ok_or_else(|| anyhow::anyhow!("download host missing"))?;
                let addresses: Vec<_> = tokio::net::lookup_host((
                    host.trim_matches(['[', ']']),
                    url.port_or_known_default().unwrap_or(443),
                ))
                .await
                .map_err(|_| anyhow::anyhow!("download host resolution failed"))?
                .collect();
                if addresses.is_empty() || addresses.iter().any(|a| !public_address(a.ip())) {
                    bail!("download host resolves to a non-public address");
                }
                reqwest::Client::builder()
                    .no_proxy()
                    .timeout(remaining)
                    .redirect(reqwest::redirect::Policy::none())
                    .resolve_to_addrs(host, &addresses)
                    .build()
                    .map_err(|_| anyhow::anyhow!("cannot initialize model client"))?
            } else {
                client(remaining)?
            };
            let mut request = client
                .get(url.clone())
                .header(reqwest::header::ACCEPT_ENCODING, "identity");
            if offset > 0 {
                request = request.header(reqwest::header::RANGE, format!("bytes={offset}-"));
            }
            if let Some(token) = token.filter(|_| credentials_allowed) {
                let mut header = reqwest::header::HeaderValue::from_str(&format!("Bearer {token}"))
                    .map_err(|_| anyhow::anyhow!("invalid model download token"))?;
                header.set_sensitive(true);
                request = request.header(reqwest::header::AUTHORIZATION, header);
            }
            let response = request
                .send()
                .await
                .map_err(|_| anyhow::anyhow!("model request failed; retry to resume"))?;
            if !matches!(response.status().as_u16(), 301 | 302 | 303 | 307 | 308) {
                return Ok(response);
            }
            if hop == MAX_REDIRECTS {
                bail!("too many model redirects");
            }
            let location = response
                .headers()
                .get(reqwest::header::LOCATION)
                .and_then(|h| h.to_str().ok())
                .ok_or_else(|| anyhow::anyhow!("model redirect missing location"))?;
            let next = redirect_url(&url, location)?;
            credentials_allowed &= next.origin() == original.origin();
            url = next;
        }
        unreachable!()
    };
    tokio::time::timeout(timeout, operation)
        .await
        .map_err(|_| anyhow::anyhow!("model request timed out"))?
}
pub async fn load_manifest(source: &str) -> Result<ModelManifest> {
    ModelManifest::parse(&load_manifest_bytes(Some(source)).await?)
}
/// Validated bytes preserve identity extensions for updater compatibility checks.
/// None selects the embedded manifest; Some selects a configured file or remote URL.
pub async fn load_manifest_bytes(source: Option<&str>) -> Result<Vec<u8>> {
    let Some(source) = source else {
        ModelManifest::embedded()?;
        return Ok(EMBEDDED_MANIFEST.as_bytes().to_vec());
    };
    let bytes = if source.contains("://") {
        let mut response =
            model_request(Duration::from_secs(30), download_url(source)?, None, 0).await?;
        if !response.status().is_success() {
            bail!("manifest request rejected");
        }
        let mut bytes = Vec::new();
        while let Some(chunk) = response
            .chunk()
            .await
            .map_err(|_| anyhow::anyhow!("manifest transfer interrupted"))?
        {
            if bytes.len() + chunk.len() > MANIFEST_MAX_BYTES {
                bail!("model manifest exceeds size limit");
            }
            bytes.extend_from_slice(&chunk);
        }
        bytes
    } else {
        let file =
            fs::File::open(source).map_err(|_| anyhow::anyhow!("cannot open model manifest"))?;
        let mut bytes = Vec::new();
        file.take((MANIFEST_MAX_BYTES + 1) as u64)
            .read_to_end(&mut bytes)
            .map_err(|_| anyhow::anyhow!("cannot read model manifest"))?;
        bytes
    };
    ModelManifest::parse(&bytes)?;
    Ok(bytes)
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Verification {
    Missing,
    Invalid,
    Valid,
}
pub fn verify_model(path: &Path, spec: &ModelSpec) -> Result<Verification> {
    spec.validate()?;
    let meta = match fs::symlink_metadata(path) {
        Ok(meta) => meta,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(Verification::Missing),
        Err(_) => bail!("cannot inspect model file"),
    };
    if !meta.is_file() {
        bail!("unsafe model path; expected a regular file");
    }
    if meta.len() != spec.size {
        return Ok(Verification::Invalid);
    }
    let mut file = fs::File::open(path).map_err(|_| anyhow::anyhow!("cannot read model file"))?;
    let mut hash = Sha256::new();
    let mut buffer = [0u8; 65536];
    loop {
        let len = file
            .read(&mut buffer)
            .map_err(|_| anyhow::anyhow!("model verification read failed"))?;
        if len == 0 {
            break;
        }
        hash.update(&buffer[..len]);
    }
    Ok(
        if format!("{:x}", hash.finalize()).eq_ignore_ascii_case(&spec.sha256) {
            Verification::Valid
        } else {
            Verification::Invalid
        },
    )
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct DownloadProgress {
    pub downloaded: u64,
    pub total: u64,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ModelCreationReceipt {
    pub path: PathBuf,
    pub sha256: String,
    pub size: u64,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DownloadOutcome {
    pub path: PathBuf,
    pub downloaded: bool,
    pub resumed_from: u64,
    pub newly_created: bool,
    pub receipt: Option<ModelCreationReceipt>,
}
pub struct ModelStore {
    directory: PathBuf,
    timeout: Duration,
}
impl ModelStore {
    pub fn new(directory: impl Into<PathBuf>) -> Result<Self> {
        Self::with_timeout(directory, Duration::from_secs(DOWNLOAD_TIMEOUT_SECS))
    }
    pub fn with_timeout(directory: impl Into<PathBuf>, timeout: Duration) -> Result<Self> {
        if timeout.is_zero() {
            bail!("download timeout must be positive");
        }
        Ok(Self {
            directory: directory.into(),
            timeout,
        })
    }
    pub fn model_path(&self, spec: &ModelSpec) -> Result<PathBuf> {
        spec.validate()?;
        Ok(self.directory.join(&spec.file))
    }
    /// Caller supplies HF token only for this model request; never stored or logged.
    pub async fn download(
        &self,
        spec: &ModelSpec,
        token: Option<&str>,
        progress: impl FnMut(DownloadProgress),
    ) -> Result<DownloadOutcome> {
        self.download_with_receipt(spec, token, progress, |_| Ok(()))
            .await
    }
    /// Records only verified final models absent when this download acquired its lock.
    /// The callback must durably persist the receipt before returning. It runs under
    /// the lock after finalization; failure leaves the model intact and returns an error.
    /// Cache directories, partial files and lock files are never granted purge ownership.
    pub async fn download_with_receipt(
        &self,
        spec: &ModelSpec,
        token: Option<&str>,
        mut progress: impl FnMut(DownloadProgress),
        mut record: impl FnMut(&ModelCreationReceipt) -> Result<()>,
    ) -> Result<DownloadOutcome> {
        let path = self.model_path(spec)?;
        fs::create_dir_all(&self.directory)
            .map_err(|_| anyhow::anyhow!("cannot create model cache; check permissions"))?;
        let lock_path = self.directory.join(format!("{}.lock", spec.file));
        let _lock = DownloadLock::acquire(lock_path)?;
        let newly_created = match fs::symlink_metadata(&path) {
            Ok(_) => false,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => true,
            Err(_) => bail!("cannot inspect model ownership"),
        };
        if verify_model(&path, spec)? == Verification::Valid {
            progress(DownloadProgress {
                downloaded: spec.size,
                total: spec.size,
            });
            return Ok(DownloadOutcome {
                path,
                downloaded: false,
                resumed_from: 0,
                newly_created: false,
                receipt: None,
            });
        }
        let partial = self.directory.join(format!("{}.part", spec.file));
        let mut offset = match fs::symlink_metadata(&partial) {
            Ok(meta) if meta.is_file() => meta.len(),
            Ok(_) => bail!("unsafe partial model path"),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => 0,
            Err(_) => bail!("cannot inspect partial model"),
        };
        if offset == spec.size && verify_model(&partial, spec)? == Verification::Valid {
            finalize(&partial, &path, &self.directory)?;
            progress(DownloadProgress {
                downloaded: spec.size,
                total: spec.size,
            });
            return Ok(DownloadOutcome {
                receipt: creation_receipt(&path, spec, newly_created, &mut record)?,
                path,
                downloaded: true,
                resumed_from: offset,
                newly_created,
            });
        }
        if offset >= spec.size {
            fs::remove_file(&partial)
                .map_err(|_| anyhow::anyhow!("cannot discard invalid partial model"))?;
            offset = 0;
        }
        let mut response =
            model_request(self.timeout, download_url(&spec.url)?, token, offset).await?;
        if response.status() == reqwest::StatusCode::PARTIAL_CONTENT {
            let range = response
                .headers()
                .get(reqwest::header::CONTENT_RANGE)
                .and_then(|v| v.to_str().ok())
                .ok_or_else(|| anyhow::anyhow!("resumed download missing Content-Range"))?;
            let expected = format!("bytes {offset}-{}/{}", spec.size - 1, spec.size);
            if range != expected {
                bail!("resumed download has incompatible Content-Range");
            }
        } else if response.status() == reqwest::StatusCode::OK {
            offset = 0;
        } else {
            bail!("model download rejected; check access or retry later");
        }
        if response
            .content_length()
            .is_some_and(|len| len != spec.size - offset)
        {
            bail!("model response length differs from manifest");
        }
        let resumed_from = offset;
        let mut options = fs::OpenOptions::new();
        options.write(true).create(true);
        if offset == 0 {
            options.truncate(true);
        } else {
            options.append(true);
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut output = options
            .open(&partial)
            .map_err(|_| anyhow::anyhow!("cannot write partial model"))?;
        progress(DownloadProgress {
            downloaded: offset,
            total: spec.size,
        });
        while let Some(chunk) = response
            .chunk()
            .await
            .map_err(|_| anyhow::anyhow!("model transfer interrupted; retry to resume"))?
        {
            if chunk.len() as u64 > spec.size - offset {
                bail!("model download exceeds manifest size");
            }
            output
                .write_all(&chunk)
                .map_err(|_| anyhow::anyhow!("cannot write model; check disk space"))?;
            offset += chunk.len() as u64;
            progress(DownloadProgress {
                downloaded: offset,
                total: spec.size,
            });
        }
        output
            .sync_all()
            .map_err(|_| anyhow::anyhow!("cannot sync downloaded model"))?;
        drop(output);
        if verify_model(&partial, spec)? != Verification::Valid {
            if offset == spec.size {
                fs::remove_file(&partial)
                    .map_err(|_| anyhow::anyhow!("cannot discard corrupt model"))?;
            }
            bail!("model verification failed (size or SHA256); retry download");
        }
        finalize(&partial, &path, &self.directory)?;
        Ok(DownloadOutcome {
            receipt: creation_receipt(&path, spec, newly_created, &mut record)?,
            path,
            downloaded: true,
            resumed_from,
            newly_created,
        })
    }
}
fn creation_receipt(
    path: &Path,
    spec: &ModelSpec,
    newly_created: bool,
    record: &mut impl FnMut(&ModelCreationReceipt) -> Result<()>,
) -> Result<Option<ModelCreationReceipt>> {
    if !newly_created {
        return Ok(None);
    }
    let receipt = ModelCreationReceipt {
        path: path.to_path_buf(),
        sha256: spec.sha256.to_ascii_lowercase(),
        size: spec.size,
    };
    record(&receipt).map_err(|_| anyhow::anyhow!("cannot record model creation receipt"))?;
    Ok(Some(receipt))
}
fn finalize(partial: &Path, path: &Path, directory: &Path) -> Result<()> {
    fs::rename(partial, path)
        .map_err(|_| anyhow::anyhow!("cannot atomically finalize verified model"))?;
    fs::File::open(directory)
        .and_then(|file| file.sync_all())
        .map_err(|_| anyhow::anyhow!("cannot sync model directory"))
}
struct DownloadLock(PathBuf);
impl DownloadLock {
    fn acquire(path: PathBuf) -> Result<Self> {
        fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&path)
            .map_err(|_| {
                anyhow::anyhow!(
                    "model download locked; check for an active download before removing stale lock"
                )
            })?;
        Ok(Self(path))
    }
}
impl Drop for DownloadLock {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;
    #[tokio::test]
    async fn ownership_receipts_are_recorded_under_lock() {
        let temp = tempfile::tempdir().unwrap();
        let store = ModelStore::new(temp.path()).unwrap();
        let model = spec("https://example.invalid/model".into());
        fs::write(temp.path().join("model.gguf.part"), b"abcdef").unwrap();
        let mut receipts = Vec::new();
        let outcome = store
            .download_with_receipt(
                &model,
                None,
                |_| {},
                |receipt| {
                    assert!(temp.path().join("model.gguf.lock").exists());
                    assert!(DownloadLock::acquire(temp.path().join("model.gguf.lock")).is_err());
                    assert_eq!(verify_model(&receipt.path, &model)?, Verification::Valid);
                    assert_eq!(
                        serde_json::from_slice::<ModelCreationReceipt>(&serde_json::to_vec(
                            receipt
                        )?)?,
                        *receipt
                    );
                    receipts.push(receipt.clone());
                    Ok(())
                },
            )
            .await
            .unwrap();
        assert!(outcome.newly_created);
        assert_eq!(receipts.len(), 1);
        assert_eq!(receipts[0].size, model.size);
        assert_eq!(receipts[0].sha256, model.sha256);
        assert_eq!(outcome.receipt.as_ref(), receipts.first());
        let existing = store.download(&model, None, |_| {}).await.unwrap();
        assert!(!existing.newly_created);
        assert!(existing.receipt.is_none());
        fs::write(&outcome.path, b"invalid").unwrap();
        fs::write(temp.path().join("model.gguf.part"), b"abcdef").unwrap();
        let repaired = store
            .download_with_receipt(&model, None, |_| {}, |_| panic!("unowned repair"))
            .await
            .unwrap();
        assert!(!repaired.newly_created);
        assert!(repaired.receipt.is_none());
    }
    #[tokio::test]
    async fn concurrent_download_cannot_claim_another_download() {
        let temp = tempfile::tempdir().unwrap();
        let (url, task) = mock(
            "HTTP/1.1 200 OK\r\nContent-Length: 6\r\nConnection: close\r\n\r\nabcdef".into(),
            |_| {},
        );
        let model = spec(url);
        let first = ModelStore::new(temp.path()).unwrap();
        let second = ModelStore::new(temp.path()).unwrap();
        let mut receipts = Vec::new();
        let (created, competing) = tokio::join!(
            first.download_with_receipt(
                &model,
                None,
                |_| {},
                |receipt| {
                    receipts.push(receipt.clone());
                    Ok(())
                }
            ),
            second.download_with_receipt(&model, None, |_| {}, |_| panic!("competing ownership"))
        );
        task.join().unwrap();
        assert!(created.unwrap().newly_created);
        assert!(competing.unwrap_err().to_string().contains("locked"));
        assert_eq!(receipts.len(), 1);
        assert!(
            !second
                .download(&model, None, |_| {})
                .await
                .unwrap()
                .newly_created
        );
    }
    #[tokio::test]
    async fn failed_download_and_receipt_recording_never_claim_unverified_models() {
        let temp = tempfile::tempdir().unwrap();
        let store = ModelStore::new(temp.path()).unwrap();
        let (url, task) = mock(
            "HTTP/1.1 200 OK\r\nContent-Length: 6\r\nConnection: close\r\n\r\nbadbad".into(),
            |_| {},
        );
        assert!(
            store
                .download_with_receipt(&spec(url), None, |_| {}, |_| panic!("unverified receipt"))
                .await
                .is_err()
        );
        task.join().unwrap();
        assert!(!temp.path().join("model.gguf").exists());
        fs::write(temp.path().join("model.gguf.part"), b"abcdef").unwrap();
        let model = spec("https://example.invalid/model".into());
        let error = store
            .download_with_receipt(&model, None, |_| {}, |_| bail!("synthetic-secret"))
            .await
            .unwrap_err();
        assert!(!error.to_string().contains("synthetic-secret"));
        assert_eq!(
            verify_model(&temp.path().join("model.gguf"), &model).unwrap(),
            Verification::Valid
        );
        assert!(!temp.path().join("model.gguf.lock").exists());
        assert!(
            !store
                .download(&model, None, |_| {})
                .await
                .unwrap()
                .newly_created
        );
    }
    #[tokio::test]
    async fn manifest_bytes_preserve_identity_for_all_sources() {
        assert_eq!(
            load_manifest_bytes(None).await.unwrap(),
            EMBEDDED_MANIFEST.as_bytes()
        );
        let mut value: serde_json::Value = serde_json::from_str(EMBEDDED_MANIFEST).unwrap();
        value["models"]["embedder"]["model"] = "custom/embedding-identity".into();
        let bytes = serde_json::to_vec(&value).unwrap();
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("manifest.json");
        fs::write(&path, &bytes).unwrap();
        assert_eq!(load_manifest_bytes(path.to_str()).await.unwrap(), bytes);
        let (url, task) = mock(
            format!(
                "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                bytes.len(),
                String::from_utf8(bytes.clone()).unwrap()
            ),
            |_| {},
        );
        assert_eq!(load_manifest_bytes(Some(&url)).await.unwrap(), bytes);
        task.join().unwrap();
    }
    #[test]
    fn redirect_security_policy() {
        let source = reqwest::Url::parse("https://huggingface.co/model").unwrap();
        assert!(redirect_url(&source, "https://cdn.example/model?signature=secret").is_ok());
        assert!(redirect_url(&source, "http://127.0.0.1/model").is_err());
        assert!(redirect_url(&source, "https://user:secret@cdn.example/model").is_err());
        for address in [
            "127.0.0.1",
            "10.0.0.1",
            "169.254.169.254",
            "100.64.0.1",
            "::1",
            "fc00::1",
            "::ffff:127.0.0.1",
        ] {
            assert!(!public_address(address.parse().unwrap()), "{address}");
        }
        assert!(public_address("1.1.1.1".parse().unwrap()));
    }
    #[tokio::test]
    async fn same_origin_redirect_keeps_sensitive_header() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let task = std::thread::spawn(move || {
            for hop in 0..2 {
                let (mut stream, _) = listener.accept().unwrap();
                stream
                    .set_read_timeout(Some(Duration::from_secs(5)))
                    .unwrap();
                let mut request = Vec::new();
                let mut byte = [0];
                while !request.ends_with(b"\r\n\r\n") {
                    stream.read_exact(&mut byte).unwrap();
                    request.push(byte[0]);
                }
                assert!(
                    String::from_utf8(request)
                        .unwrap()
                        .contains("Bearer synthetic-token")
                );
                let response = if hop == 0 {
                    "HTTP/1.1 307 Temporary Redirect\r\nLocation: /cdn?signature=secret\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                } else {
                    "HTTP/1.1 200 OK\r\nContent-Length: 6\r\nConnection: close\r\n\r\nabcdef"
                };
                stream.write_all(response.as_bytes()).unwrap();
            }
        });
        let temp = tempfile::tempdir().unwrap();
        ModelStore::new(temp.path())
            .unwrap()
            .download(
                &spec(format!("http://{address}/model")),
                Some("synthetic-token"),
                |_| {},
            )
            .await
            .unwrap();
        task.join().unwrap();
    }
    #[tokio::test]
    async fn cdn_redirect_strips_token_and_preserves_resume() {
        for (status, body, expected_offset) in [
            (
                "206 Partial Content\r\nContent-Range: bytes 3-5/6",
                "def",
                3,
            ),
            ("200 OK", "abcdef", 0),
        ] {
            let temp = tempfile::tempdir().unwrap();
            fs::write(temp.path().join("model.gguf.part"), b"abc").unwrap();
            let (cdn, cdn_task) = mock(
                format!(
                    "HTTP/1.1 {status}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                    body.len()
                ),
                |request| {
                    assert!(!request.to_lowercase().contains("authorization:"));
                    assert!(!request.contains("synthetic-token"));
                    assert!(request.to_lowercase().contains("range: bytes=3-"));
                    assert!(request.contains("?signature=synthetic-signed-secret"));
                },
            );
            let (source, source_task) = mock(
                format!(
                    "HTTP/1.1 302 Found\r\nLocation: {cdn}?signature=synthetic-signed-secret\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                ),
                |request| {
                    assert!(request.contains("Bearer synthetic-token"));
                },
            );
            let result = ModelStore::new(temp.path())
                .unwrap()
                .download(&spec(source), Some("synthetic-token"), |_| {})
                .await
                .unwrap();
            source_task.join().unwrap();
            cdn_task.join().unwrap();
            assert_eq!(result.resumed_from, expected_offset);
            assert!(result.newly_created);
            assert_eq!(result.receipt.as_ref().unwrap().size, 6);
            assert_eq!(fs::read(result.path).unwrap(), b"abcdef");
        }
    }
    #[tokio::test]
    async fn private_https_redirect_is_rejected_without_url() {
        let (source, task) = mock("HTTP/1.1 302 Found\r\nLocation: https://127.0.0.1/model?signature=synthetic-signed-secret\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".into(), |_| {});
        let temp = tempfile::tempdir().unwrap();
        let error = ModelStore::new(temp.path())
            .unwrap()
            .download(&spec(source), None, |_| {})
            .await
            .unwrap_err();
        task.join().unwrap();
        assert!(!format!("{error:#}").contains("synthetic-signed-secret"));
        assert!(format!("{error:#}").contains("non-public"));
    }
    #[tokio::test]
    async fn stalled_request_times_out_without_finalizing() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let task = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            stream.set_nonblocking(false).unwrap();
            stream
                .set_read_timeout(Some(Duration::from_secs(5)))
                .unwrap();
            let mut request = Vec::new();
            let mut byte = [0];
            while !request.ends_with(b"\r\n\r\n") {
                stream.read_exact(&mut byte).unwrap();
                request.push(byte[0]);
            }
            std::thread::sleep(Duration::from_millis(500));
        });
        let temp = tempfile::tempdir().unwrap();
        let store = ModelStore::with_timeout(temp.path(), Duration::from_millis(100)).unwrap();
        let started = std::time::Instant::now();
        assert!(
            store
                .download(&spec(format!("http://{address}/model")), None, |_| {})
                .await
                .is_err()
        );
        assert!(started.elapsed() < Duration::from_secs(2));
        task.join().unwrap();
        assert!(!temp.path().join("model.gguf").exists());
        assert!(!temp.path().join("model.gguf.lock").exists());
    }
    #[tokio::test]
    async fn complete_partial_lock_and_unsafe_paths() {
        let temp = tempfile::tempdir().unwrap();
        let model = spec("https://example.invalid/model".into());
        let store = ModelStore::new(temp.path()).unwrap();
        fs::write(temp.path().join("model.gguf.part"), b"abcdef").unwrap();
        assert_eq!(
            store
                .download(&model, None, |_| {})
                .await
                .unwrap()
                .resumed_from,
            6
        );
        fs::write(temp.path().join("model.gguf.lock"), b"").unwrap();
        assert!(store.download(&model, None, |_| {}).await.is_err());
        assert!(temp.path().join("model.gguf.lock").exists());
        fs::remove_file(temp.path().join("model.gguf.lock")).unwrap();
        #[cfg(unix)]
        {
            fs::remove_file(temp.path().join("model.gguf")).unwrap();
            std::os::unix::fs::symlink(
                temp.path().join("model.gguf.part"),
                temp.path().join("model.gguf"),
            )
            .unwrap();
            assert!(store.download(&model, None, |_| {}).await.is_err());
        }
    }
    #[tokio::test]
    async fn wrong_length_status_and_manifest_url() {
        let temp = tempfile::tempdir().unwrap();
        let store = ModelStore::new(temp.path()).unwrap();
        for response in [
            "HTTP/1.1 200 OK\r\nContent-Length: 7\r\nConnection: close\r\n\r\nabcdefg",
            "HTTP/1.1 401 Unauthorized\r\nContent-Length: 6\r\nConnection: close\r\n\r\nsecret",
        ] {
            let (url, task) = mock(response.into(), |_| {});
            let error = store
                .download(&spec(url), Some("synthetic-secret"), |_| {})
                .await
                .unwrap_err();
            task.join().unwrap();
            assert!(!format!("{error:#}").contains("synthetic-secret"));
            assert!(!temp.path().join("model.gguf").exists());
        }
        let response = format!(
            "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
            EMBEDDED_MANIFEST.len(),
            EMBEDDED_MANIFEST
        );
        let (url, task) = mock(response, |_| {});
        assert!(load_manifest(&url).await.is_ok());
        task.join().unwrap();
    }
    fn mock(
        response: String,
        check: impl FnOnce(String) + Send + 'static,
    ) -> (String, std::thread::JoinHandle<()>) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let task = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            stream.set_nonblocking(false).unwrap();
            stream
                .set_read_timeout(Some(Duration::from_secs(5)))
                .unwrap();
            stream
                .set_write_timeout(Some(Duration::from_secs(5)))
                .unwrap();
            let mut request = Vec::new();
            let mut byte = [0];
            while !request.ends_with(b"\r\n\r\n") {
                stream.read_exact(&mut byte).unwrap();
                request.push(byte[0]);
            }
            check(String::from_utf8(request).unwrap());
            stream.write_all(response.as_bytes()).unwrap();
        });
        (format!("http://{address}/model"), task)
    }
    fn spec(url: String) -> ModelSpec {
        ModelSpec {
            label: "synthetic".into(),
            repo: "synthetic".into(),
            file: "model.gguf".into(),
            url,
            size: 6,
            sha256: format!("{:x}", Sha256::digest(b"abcdef")),
            dimensions: Some(1024),
        }
    }
    #[test]
    fn embedded_and_manifest_validation() {
        let manifest = ModelManifest::embedded().unwrap();
        assert_eq!(manifest.llama_cpp.min_build, 9430);
        assert_eq!(manifest.models.embedder.size, 639150592);
        assert_eq!(
            manifest.models.reranker.sha256,
            "c04f5f5657c52e04538c455e8c62817db3d3b795b39e9f547f8581510445f075"
        );
        let mut model = spec("https://example.invalid/model".into());
        model.file = "../escape".into();
        assert!(model.validate().is_err());
        assert!(ModelManifest::parse(b"not JSON synthetic-secret").is_err());
    }
    #[tokio::test]
    async fn download_resume_and_idempotence() {
        let temp = tempfile::tempdir().unwrap();
        fs::write(temp.path().join("model.gguf.part"), b"abc").unwrap();
        let (url, task) = mock("HTTP/1.1 206 Partial Content\r\nContent-Length: 3\r\nContent-Range: bytes 3-5/6\r\nConnection: close\r\n\r\ndef".into(), |request| {
            assert!(request.to_lowercase().contains("range: bytes=3-")); assert!(request.contains("Bearer synthetic-token"));
        });
        let model = spec(url);
        let store = ModelStore::new(temp.path()).unwrap();
        let mut progress = Vec::new();
        let outcome = store
            .download(&model, Some("synthetic-token"), |p| progress.push(p))
            .await
            .unwrap();
        task.join().unwrap();
        assert_eq!(outcome.resumed_from, 3);
        assert_eq!(progress.last().unwrap().downloaded, 6);
        assert_eq!(fs::read(&outcome.path).unwrap(), b"abcdef");
        assert!(!temp.path().join("model.gguf.part").exists());
        assert!(
            !store
                .download(&model, None, |_| {})
                .await
                .unwrap()
                .downloaded
        );
        assert_eq!(
            verify_model(&outcome.path, &model).unwrap(),
            Verification::Valid
        );
    }
    #[tokio::test]
    async fn ignored_range_restarts_and_corruption_never_finalizes() {
        let temp = tempfile::tempdir().unwrap();
        let store = ModelStore::new(temp.path()).unwrap();
        fs::write(temp.path().join("model.gguf.part"), b"abc").unwrap();
        let (url, task) = mock(
            "HTTP/1.1 200 OK\r\nContent-Length: 6\r\nConnection: close\r\n\r\nabcdef".into(),
            |_| {},
        );
        let outcome = store.download(&spec(url), None, |_| {}).await.unwrap();
        task.join().unwrap();
        assert_eq!(outcome.resumed_from, 0);
        fs::write(&outcome.path, b"oldbad").unwrap();
        let (url, task) = mock(
            "HTTP/1.1 200 OK\r\nContent-Length: 6\r\nConnection: close\r\n\r\nbadbad".into(),
            |_| {},
        );
        assert!(store.download(&spec(url), None, |_| {}).await.is_err());
        task.join().unwrap();
        assert_eq!(fs::read(&outcome.path).unwrap(), b"oldbad");
        assert!(!temp.path().join("model.gguf.part").exists());
    }
    #[tokio::test]
    async fn interrupted_then_resume_and_bad_range() {
        let temp = tempfile::tempdir().unwrap();
        let store = ModelStore::new(temp.path()).unwrap();
        let (url, task) = mock(
            "HTTP/1.1 200 OK\r\nContent-Length: 6\r\nConnection: close\r\n\r\nabc".into(),
            |_| {},
        );
        assert!(store.download(&spec(url), None, |_| {}).await.is_err());
        task.join().unwrap();
        assert_eq!(
            fs::read(temp.path().join("model.gguf.part")).unwrap(),
            b"abc"
        );
        let (url, task) = mock("HTTP/1.1 206 Partial Content\r\nContent-Length: 3\r\nContent-Range: bytes 0-2/6\r\nConnection: close\r\n\r\ndef".into(), |_| {});
        assert!(store.download(&spec(url), None, |_| {}).await.is_err());
        task.join().unwrap();
        assert_eq!(
            fs::read(temp.path().join("model.gguf.part")).unwrap(),
            b"abc"
        );
        let (url, task) = mock("HTTP/1.1 206 Partial Content\r\nContent-Length: 3\r\nContent-Range: bytes 3-5/6\r\nConnection: close\r\n\r\ndef".into(), |_| {});
        store.download(&spec(url), None, |_| {}).await.unwrap();
        task.join().unwrap();
    }
    #[tokio::test]
    async fn redirect_and_status_errors_are_sanitized() {
        let temp = tempfile::tempdir().unwrap();
        let store = ModelStore::new(temp.path()).unwrap();
        let (url, task) = mock("HTTP/1.1 302 Found\r\nLocation: http://127.0.0.1:1/synthetic-token\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".into(), |_| {});
        let error = store
            .download(&spec(url), Some("synthetic-token"), |_| {})
            .await
            .unwrap_err();
        task.join().unwrap();
        assert!(!format!("{error:#}").contains("synthetic-token"));
        assert!(ModelStore::with_timeout(temp.path(), Duration::ZERO).is_err());
        let path = temp.path().join("manifest.json");
        fs::write(&path, EMBEDDED_MANIFEST).unwrap();
        assert_eq!(
            load_manifest(path.to_str().unwrap())
                .await
                .unwrap()
                .models
                .embedder
                .dimensions,
            Some(1024)
        );
    }
}
