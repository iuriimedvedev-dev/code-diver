use anyhow::{Result, bail};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};

pub const RUNTIME_SCHEMA: u32 = 1;
pub const PROFILE_MAX_BYTES: usize = 1024 * 1024;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Platform {
    MacOs,
    Linux,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RuntimePaths {
    pub config: PathBuf,
    pub cache: PathBuf,
    pub data: PathBuf,
    pub state: PathBuf,
    pub models: PathBuf,
    pub secrets: PathBuf,
    pub logs: PathBuf,
    pub hosts: PathBuf,
    pub services: PathBuf,
    pub isolated: bool,
}

impl RuntimePaths {
    pub fn discover() -> Result<Self> {
        let platform = if cfg!(target_os = "macos") {
            Platform::MacOs
        } else if cfg!(target_os = "linux") {
            Platform::Linux
        } else {
            bail!("unsupported runtime platform; use macOS or Linux");
        };
        Self::from_env(platform, |name| std::env::var(name).ok())
    }

    pub fn from_env(platform: Platform, env: impl Fn(&str) -> Option<String>) -> Result<Self> {
        if let Some(base) = env("CODE_DIVER_HOME") {
            let base = absolute_dir(&base)?;
            return Ok(Self::new(
                [
                    base.join("config"),
                    base.join("cache"),
                    base.join("data"),
                    base.join("state"),
                    base.join("hosts"),
                    base.join("services"),
                ],
                true,
            ));
        }
        let home = absolute_dir(
            &env("HOME").ok_or_else(|| anyhow::anyhow!("HOME unavailable; set CODE_DIVER_HOME"))?,
        )?;
        let xdg = |key: &str, fallback: PathBuf| -> Result<PathBuf> {
            Ok(match env(key) {
                Some(value) => absolute_dir(&value)?,
                None => fallback,
            }
            .join("code-diver"))
        };
        match platform {
            Platform::Linux => {
                let config = xdg("XDG_CONFIG_HOME", home.join(".config"))?;
                let services = config.parent().unwrap().join("systemd/user");
                Ok(Self::new(
                    [
                        config,
                        xdg("XDG_CACHE_HOME", home.join(".cache"))?,
                        xdg("XDG_DATA_HOME", home.join(".local/share"))?,
                        xdg("XDG_STATE_HOME", home.join(".local/state"))?,
                        home,
                        services,
                    ],
                    false,
                ))
            }
            Platform::MacOs => Ok(Self::new(
                [
                    home.join("Library/Application Support/code-diver"),
                    home.join("Library/Caches/code-diver"),
                    home.join("Library/Application Support/code-diver/data"),
                    home.join("Library/Application Support/code-diver/state"),
                    home.clone(),
                    home.join("Library/LaunchAgents"),
                ],
                false,
            )),
        }
    }

    fn new([config, cache, data, state, hosts, services]: [PathBuf; 6], isolated: bool) -> Self {
        Self {
            models: cache.join("models"),
            secrets: config.join("secrets"),
            logs: state.join("logs"),
            config,
            cache,
            data,
            state,
            hosts,
            services,
            isolated,
        }
    }
    pub fn config_file(&self) -> PathBuf {
        self.config.join("config.toml")
    }
    pub fn index_dir(&self, name: &str) -> Result<PathBuf> {
        validate_name(name)?;
        Ok(self.data.join(name))
    }
    pub fn ensure_dirs(&self) -> Result<()> {
        for path in [
            &self.config,
            &self.cache,
            &self.data,
            &self.state,
            &self.models,
            &self.secrets,
            &self.logs,
        ] {
            fs::create_dir_all(path).map_err(|_| {
                anyhow::anyhow!("cannot create runtime directory; check permissions")
            })?;
        }
        secure_directory(&self.secrets)
    }
}

fn absolute_dir(value: &str) -> Result<PathBuf> {
    let path = PathBuf::from(value);
    if !path.is_absolute()
        || path
            .components()
            .any(|p| matches!(p, std::path::Component::ParentDir))
    {
        bail!("runtime directory must be absolute without parent traversal");
    }
    Ok(path)
}
pub fn validate_name(value: &str) -> Result<()> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
    {
        bail!("invalid runtime name; use letters, digits, hyphen or underscore");
    }
    Ok(())
}
fn secure_directory(path: &Path) -> Result<()> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(path, fs::Permissions::from_mode(0o700))
            .map_err(|_| anyhow::anyhow!("cannot secure secret directory"))?;
    }
    Ok(())
}

#[derive(Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(tag = "source", content = "name", rename_all = "snake_case")]
pub enum SecretRef {
    Env(String),
    File(String),
    Keychain(String),
}
impl std::fmt::Debug for SecretRef {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("SecretRef([REDACTED])")
    }
}
pub struct SecretValue(String);
impl SecretValue {
    pub fn new(value: String) -> Result<Self> {
        if value.is_empty() || value.len() > 16384 || value.chars().any(char::is_control) {
            bail!("invalid secret value");
        }
        Ok(Self(value))
    }
    pub fn expose(&self) -> &str {
        &self.0
    }
}
impl std::fmt::Debug for SecretValue {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("[REDACTED]")
    }
}
/// Implementations must not pass secret values through process arguments.
pub trait SecretStore {
    fn get(&self, name: &str) -> Result<Option<SecretValue>>;
    fn put(&self, name: &str, value: &SecretValue) -> Result<()>;
    fn delete(&self, name: &str) -> Result<()>;
}
pub struct FileSecretStore {
    directory: PathBuf,
}
impl FileSecretStore {
    pub fn new(paths: &RuntimePaths) -> Self {
        Self {
            directory: paths.secrets.clone(),
        }
    }
}
impl SecretStore for FileSecretStore {
    fn get(&self, name: &str) -> Result<Option<SecretValue>> {
        validate_name(name)?;
        let path = self.directory.join(name);
        let meta = match fs::symlink_metadata(&path) {
            Ok(meta) => meta,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(_) => bail!("cannot inspect secret file"),
        };
        if !meta.is_file() || meta.len() > 16384 {
            bail!("unsafe secret file");
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            if meta.permissions().mode() & 0o777 != 0o600 {
                bail!("secret file must have mode 0600");
            }
        }
        let value =
            fs::read_to_string(path).map_err(|_| anyhow::anyhow!("cannot read secret file"))?;
        Ok(Some(SecretValue::new(value)?))
    }
    fn put(&self, name: &str, value: &SecretValue) -> Result<()> {
        validate_name(name)?;
        fs::create_dir_all(&self.directory)
            .map_err(|_| anyhow::anyhow!("cannot create secret directory"))?;
        secure_directory(&self.directory)?;
        atomic_write(&self.directory.join(name), value.expose().as_bytes())
    }
    fn delete(&self, name: &str) -> Result<()> {
        validate_name(name)?;
        match fs::remove_file(self.directory.join(name)) {
            Ok(()) => Ok(()),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(()),
            Err(_) => bail!("cannot delete secret file"),
        }
    }
}
/// Fakeable keychain interface. Stores use service `code-diver`, account = secret name.
pub trait MacSecurity: SecretStore {}
#[derive(Default)]
pub struct NativeMacSecurity;
impl MacSecurity for NativeMacSecurity {}
#[cfg(target_os = "macos")]
mod native_keychain {
    use super::*;
    use std::ffi::c_void;
    const SERVICE: &[u8] = b"code-diver";
    const NOT_FOUND: i32 = -25300;
    #[link(name = "Security", kind = "framework")]
    unsafe extern "C" {
        fn SecKeychainFindGenericPassword(
            keychain: *const c_void,
            service_len: u32,
            service: *const u8,
            account_len: u32,
            account: *const u8,
            length: *mut u32,
            data: *mut *mut c_void,
            item: *mut *mut c_void,
        ) -> i32;
        fn SecKeychainAddGenericPassword(
            keychain: *const c_void,
            service_len: u32,
            service: *const u8,
            account_len: u32,
            account: *const u8,
            length: u32,
            data: *const c_void,
            item: *mut *mut c_void,
        ) -> i32;
        fn SecKeychainItemModifyAttributesAndData(
            item: *mut c_void,
            attributes: *const c_void,
            length: u32,
            data: *const c_void,
        ) -> i32;
        fn SecKeychainItemDelete(item: *mut c_void) -> i32;
    }
    #[link(name = "CoreFoundation", kind = "framework")]
    unsafe extern "C" {
        fn CFRelease(value: *const c_void);
    }
    struct Item(*mut c_void);
    impl Drop for Item {
        fn drop(&mut self) {
            if !self.0.is_null() {
                unsafe {
                    CFRelease(self.0);
                }
            }
        }
    }
    fn find(name: &str) -> Result<Option<Item>> {
        validate_name(name)?;
        let mut item = Item(std::ptr::null_mut());
        let status = unsafe {
            SecKeychainFindGenericPassword(
                std::ptr::null(),
                SERVICE.len() as u32,
                SERVICE.as_ptr(),
                name.len() as u32,
                name.as_ptr(),
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                &mut item.0,
            )
        };
        match status {
            0 => Ok(Some(item)),
            NOT_FOUND => Ok(None),
            _ => bail!("keychain lookup failed"),
        }
    }
    impl SecretStore for NativeMacSecurity {
        fn get(&self, name: &str) -> Result<Option<SecretValue>> {
            validate_name(name)?;
            let output = std::process::Command::new("/usr/bin/security")
                .args([
                    "find-generic-password",
                    "-s",
                    "code-diver",
                    "-a",
                    name,
                    "-w",
                ])
                .stdin(std::process::Stdio::null())
                .stderr(std::process::Stdio::null())
                .output()
                .map_err(|_| anyhow::anyhow!("keychain lookup failed"))?;
            if output.status.code() == Some(44) {
                return Ok(None);
            }
            if !output.status.success() {
                bail!("keychain lookup failed");
            }
            let value = String::from_utf8(output.stdout)
                .map_err(|_| anyhow::anyhow!("invalid keychain secret"))?;
            let value = value.strip_suffix('\n').unwrap_or(&value);
            Ok(Some(SecretValue::new(value.to_owned())?))
        }
        fn put(&self, name: &str, value: &SecretValue) -> Result<()> {
            let item = find(name)?;
            let bytes = value.expose().as_bytes();
            let status = unsafe {
                if let Some(item) = &item {
                    SecKeychainItemModifyAttributesAndData(
                        item.0,
                        std::ptr::null(),
                        bytes.len() as u32,
                        bytes.as_ptr().cast(),
                    )
                } else {
                    SecKeychainAddGenericPassword(
                        std::ptr::null(),
                        SERVICE.len() as u32,
                        SERVICE.as_ptr(),
                        name.len() as u32,
                        name.as_ptr(),
                        bytes.len() as u32,
                        bytes.as_ptr().cast(),
                        std::ptr::null_mut(),
                    )
                }
            };
            if status != 0 {
                bail!("keychain write failed");
            }
            Ok(())
        }
        fn delete(&self, name: &str) -> Result<()> {
            if let Some(item) = find(name)? {
                let status = unsafe { SecKeychainItemDelete(item.0) };
                if status != 0 && status != NOT_FOUND {
                    bail!("keychain delete failed");
                }
            }
            Ok(())
        }
    }
}
#[cfg(not(target_os = "macos"))]
impl SecretStore for NativeMacSecurity {
    fn get(&self, _: &str) -> Result<Option<SecretValue>> {
        bail!("native keychain requires macOS")
    }
    fn put(&self, _: &str, _: &SecretValue) -> Result<()> {
        bail!("native keychain requires macOS")
    }
    fn delete(&self, _: &str) -> Result<()> {
        bail!("native keychain requires macOS")
    }
}
pub fn resolve_secret(
    reference: &SecretRef,
    env: impl Fn(&str) -> Option<String>,
    files: &dyn SecretStore,
    keychain: Option<&dyn MacSecurity>,
) -> Result<SecretValue> {
    let value = match reference {
        SecretRef::Env(name) => {
            if name.is_empty() || !name.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_') {
                bail!("invalid secret environment reference");
            }
            env(name).map(SecretValue::new).transpose()?
        }
        SecretRef::File(name) => files
            .get(name)
            .map_err(|_| anyhow::anyhow!("secret store lookup failed"))?,
        SecretRef::Keychain(name) => {
            validate_name(name)?;
            keychain
                .ok_or_else(|| {
                    anyhow::anyhow!(
                        "keychain unavailable; use an environment reference or private file"
                    )
                })?
                .get(name)
                .map_err(|_| anyhow::anyhow!("keychain lookup failed"))?
        }
    };
    value.ok_or_else(|| {
        anyhow::anyhow!(
            "secret unavailable; configure its named environment variable or secret store"
        )
    })
}

#[derive(Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct RuntimeProfile {
    pub qdrant_url: Option<String>,
    pub collection: Option<String>,
    pub artifact_url: Option<String>,
    pub model_manifest_url: Option<String>,
    pub model_manifest_path: Option<PathBuf>,
    pub index_name: Option<String>,
    pub embedding_model: Option<String>,
    pub embedding_dimensions: Option<usize>,
    pub query_prefix: Option<String>,
    pub document_prefix: Option<String>,
}
impl std::fmt::Debug for RuntimeProfile {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("RuntimeProfile([REDACTED])")
    }
}
impl RuntimeProfile {
    /// None selects the embedded manifest. Paths are resolved when loading the config file.
    pub fn model_manifest_source(&self) -> Result<Option<&str>> {
        if self.model_manifest_path.is_some() && self.model_manifest_url.is_some() {
            bail!("choose a model manifest path or URL, not both");
        }
        if let Some(path) = &self.model_manifest_path {
            return path
                .to_str()
                .map(Some)
                .ok_or_else(|| anyhow::anyhow!("model manifest path must be UTF-8"));
        }
        Ok(self.model_manifest_url.as_deref())
    }
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct DaemonConfig {
    pub bind: String,
    pub port: u16,
    pub autostart: bool,
    pub idle_timeout_secs: u64,
    pub request_timeout_secs: u64,
    pub startup_timeout_secs: u64,
    pub max_concurrency: usize,
    pub threads: Option<usize>,
    pub reranker_ctx: usize,
    /// Reranker batch limits, not embedder batch defaults.
    pub batch: usize,
    pub ubatch: usize,
    pub embedder_ctx: usize,
    pub embedder_batch: usize,
    pub embedder_ubatch: usize,
    pub embedder_pooling: String,
    pub reranker_pooling: String,
    pub flash_attention: bool,
    pub log_max_bytes: u64,
    pub log_retained_files: usize,
}
impl Default for DaemonConfig {
    fn default() -> Self {
        Self {
            bind: "127.0.0.1".into(),
            port: 8090,
            autostart: true,
            idle_timeout_secs: 600,
            request_timeout_secs: 120,
            startup_timeout_secs: 120,
            max_concurrency: 1,
            threads: None,
            reranker_ctx: 16384,
            batch: 4096,
            ubatch: 4096,
            embedder_ctx: 5120,
            embedder_batch: 2560,
            embedder_ubatch: 2560,
            embedder_pooling: "last".into(),
            reranker_pooling: "rank".into(),
            flash_attention: true,
            log_max_bytes: 20 * 1024 * 1024,
            log_retained_files: 3,
        }
    }
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct RuntimeConfig {
    pub schema: u32,
    pub profile: RuntimeProfile,
    pub daemon: DaemonConfig,
    pub llama_server: Option<PathBuf>,
    pub secrets: BTreeMap<String, SecretRef>,
}
impl Default for RuntimeConfig {
    fn default() -> Self {
        Self {
            schema: RUNTIME_SCHEMA,
            profile: RuntimeProfile::default(),
            daemon: DaemonConfig::default(),
            llama_server: None,
            secrets: BTreeMap::new(),
        }
    }
}
impl RuntimeConfig {
    pub fn validate(&self) -> Result<()> {
        if self.schema != RUNTIME_SCHEMA {
            bail!("unsupported runtime config schema");
        }
        if self.daemon.bind != "127.0.0.1" && self.daemon.bind != "::1" {
            bail!("daemon must bind to loopback");
        }
        if self.daemon.port == 0
            || self.daemon.request_timeout_secs == 0
            || self.daemon.startup_timeout_secs == 0
            || self.daemon.max_concurrency == 0
            || self.daemon.embedder_ctx == 0
            || self.daemon.embedder_batch == 0
            || self.daemon.embedder_ubatch == 0
            || self.daemon.embedder_ubatch > self.daemon.embedder_batch
            || self.daemon.embedder_pooling != "last"
            || self.daemon.reranker_pooling != "rank"
            || self.daemon.idle_timeout_secs == 0
            || self.daemon.batch < 4096
            || self.daemon.ubatch < 4096
            || self.daemon.reranker_ctx < 16384
            || self.daemon.threads == Some(0)
            || self.daemon.log_max_bytes == 0
            || self.daemon.log_retained_files == 0
        {
            bail!("invalid runtime limits; reranker requires ctx >=16384 and batch/ubatch >=4096");
        }
        for url in [
            &self.profile.qdrant_url,
            &self.profile.artifact_url,
            &self.profile.model_manifest_url,
        ]
        .into_iter()
        .flatten()
        {
            validate_url(url)?;
        }
        if self.profile.model_manifest_path.is_some() && self.profile.model_manifest_url.is_some() {
            bail!("choose a model manifest path or URL, not both");
        }
        if let Some(name) = &self.profile.index_name {
            validate_name(name)?;
        }
        for reference in self.secrets.values() {
            match reference {
                SecretRef::File(name) | SecretRef::Keychain(name) => validate_name(name)?,
                SecretRef::Env(name)
                    if !name.is_empty()
                        && name.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_') => {}
                _ => bail!("invalid secret reference"),
            }
        }
        Ok(())
    }
    pub fn daemon_url(&self) -> String {
        let host = if self.daemon.bind == "::1" {
            "[::1]"
        } else {
            "127.0.0.1"
        };
        format!("http://{host}:{}", self.daemon.port)
    }
    pub fn redacted_toml(&self) -> Result<String> {
        self.validate()?;
        let mut value = toml::Value::try_from(self)
            .map_err(|_| anyhow::anyhow!("cannot serialize runtime configuration"))?;
        if let Some(table) = value.as_table_mut() {
            table.insert("secrets".into(), toml::Value::String("[REDACTED]".into()));
        }
        toml::to_string_pretty(&value)
            .map_err(|_| anyhow::anyhow!("cannot render runtime configuration"))
    }
}
pub fn validate_url(raw: &str) -> Result<reqwest::Url> {
    let url = reqwest::Url::parse(raw).map_err(|_| anyhow::anyhow!("invalid service URL"))?;
    let loopback = url
        .host_str()
        .is_some_and(|h| matches!(h, "localhost" | "127.0.0.1" | "[::1]" | "::1"));
    if !(url.scheme() == "https" || url.scheme() == "http" && loopback)
        || !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
    {
        bail!(
            "service URL requires HTTPS (HTTP only for loopback), without credentials, query or fragment"
        );
    }
    Ok(url)
}
pub fn load_config(path: &Path) -> Result<RuntimeConfig> {
    let (config, warnings) = load_config_with_warnings(path)?;
    for warning in warnings {
        eprintln!("warning: {warning}");
    }
    Ok(config)
}

pub fn load_config_with_warnings(path: &Path) -> Result<(RuntimeConfig, Vec<String>)> {
    let text = match fs::read_to_string(path) {
        Ok(text) => text,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            return Ok((RuntimeConfig::default(), Vec::new()));
        }
        Err(_) => bail!("cannot read runtime config; check permissions"),
    };
    let parsed: toml::Value = toml::from_str(&text)
        .map_err(|_| anyhow::anyhow!("invalid runtime TOML config; check field types"))?;
    let warnings = unknown_key_warnings(&parsed);
    let mut config: RuntimeConfig = toml::from_str(&text)
        .map_err(|_| anyhow::anyhow!("invalid runtime TOML config; check field types"))?;
    if let Some(binary) = &config.llama_server
        && !binary.is_absolute()
    {
        if let Ok(relative) = binary.strip_prefix("~") {
            let home = std::env::var("CODE_DIVER_HOME")
                .or_else(|_| std::env::var("HOME"))
                .map_err(|_| anyhow::anyhow!("cannot expand runtime path; set CODE_DIVER_HOME"))?;
            config.llama_server = Some(absolute_dir(&home)?.join(relative));
        } else {
            config.llama_server = Some(path.parent().unwrap_or(Path::new(".")).join(binary));
        }
    }
    if let Some(manifest) = &config.profile.model_manifest_path
        && !manifest.is_absolute()
    {
        if let Ok(relative) = manifest.strip_prefix("~") {
            let home = std::env::var("CODE_DIVER_HOME")
                .or_else(|_| std::env::var("HOME"))
                .map_err(|_| anyhow::anyhow!("cannot expand manifest path; set CODE_DIVER_HOME"))?;
            config.profile.model_manifest_path = Some(absolute_dir(&home)?.join(relative));
        } else {
            config.profile.model_manifest_path =
                Some(path.parent().unwrap_or(Path::new(".")).join(manifest));
        }
    }
    config.validate()?;
    Ok((config, warnings))
}

fn unknown_key_warnings(value: &toml::Value) -> Vec<String> {
    let known = [
        (
            "",
            &["schema", "profile", "daemon", "llama_server", "secrets"][..],
        ),
        (
            "profile",
            &[
                "qdrant_url",
                "collection",
                "artifact_url",
                "model_manifest_url",
                "model_manifest_path",
                "index_name",
                "embedding_model",
                "embedding_dimensions",
                "query_prefix",
                "document_prefix",
            ][..],
        ),
        (
            "daemon",
            &[
                "bind",
                "port",
                "autostart",
                "idle_timeout_secs",
                "request_timeout_secs",
                "startup_timeout_secs",
                "max_concurrency",
                "threads",
                "reranker_ctx",
                "batch",
                "ubatch",
                "embedder_ctx",
                "embedder_batch",
                "embedder_ubatch",
                "embedder_pooling",
                "reranker_pooling",
                "flash_attention",
                "log_max_bytes",
                "log_retained_files",
            ][..],
        ),
    ];
    let mut warnings = Vec::new();
    for (section, keys) in known {
        let table = if section.is_empty() {
            value.as_table()
        } else {
            value.get(section).and_then(toml::Value::as_table)
        };
        if table.is_some_and(|table| table.keys().any(|key| !keys.contains(&key.as_str()))) {
            warnings.push(
                "unknown runtime configuration keys ignored; check configuration schema".into(),
            );
        }
    }
    warnings
}

/// Reads named CODE_DIVER variables only; secret values remain unresolved references.
pub fn environment_overrides(env: impl Fn(&str) -> Option<String>) -> Result<toml::Table> {
    let mut result = toml::Table::new();
    for (variable, section, field, kind) in [
        ("CODE_DIVER_QDRANT_URL", "profile", "qdrant_url", "string"),
        (
            "CODE_DIVER_QDRANT_COLLECTION",
            "profile",
            "collection",
            "string",
        ),
        (
            "CODE_DIVER_ARTIFACT_URL",
            "profile",
            "artifact_url",
            "string",
        ),
        (
            "CODE_DIVER_MODEL_MANIFEST_URL",
            "profile",
            "model_manifest_url",
            "string",
        ),
        ("CODE_DIVER_INDEX_NAME", "profile", "index_name", "string"),
        (
            "CODE_DIVER_EMBEDDING_MODEL",
            "profile",
            "embedding_model",
            "string",
        ),
        (
            "CODE_DIVER_EMBEDDING_DIMENSIONS",
            "profile",
            "embedding_dimensions",
            "integer",
        ),
        (
            "CODE_DIVER_EMBEDDING_QUERY_PREFIX",
            "profile",
            "query_prefix",
            "string",
        ),
        (
            "CODE_DIVER_EMBEDDING_DOCUMENT_PREFIX",
            "profile",
            "document_prefix",
            "string",
        ),
        ("CODE_DIVER_DAEMON_PORT", "daemon", "port", "integer"),
        ("CODE_DIVER_AUTOSTART", "daemon", "autostart", "boolean"),
        ("CODE_DIVER_THREADS", "daemon", "threads", "integer"),
        (
            "CODE_DIVER_EMBEDDER_CTX",
            "daemon",
            "embedder_ctx",
            "integer",
        ),
        (
            "CODE_DIVER_EMBEDDER_BATCH",
            "daemon",
            "embedder_batch",
            "integer",
        ),
        (
            "CODE_DIVER_EMBEDDER_UBATCH",
            "daemon",
            "embedder_ubatch",
            "integer",
        ),
        (
            "CODE_DIVER_RERANKER_CTX",
            "daemon",
            "reranker_ctx",
            "integer",
        ),
        ("CODE_DIVER_BATCH", "daemon", "batch", "integer"),
        ("CODE_DIVER_UBATCH", "daemon", "ubatch", "integer"),
        (
            "CODE_DIVER_EMBEDDER_POOLING",
            "daemon",
            "embedder_pooling",
            "string",
        ),
        (
            "CODE_DIVER_RERANKER_POOLING",
            "daemon",
            "reranker_pooling",
            "string",
        ),
        (
            "CODE_DIVER_FLASH_ATTENTION",
            "daemon",
            "flash_attention",
            "boolean",
        ),
        (
            "CODE_DIVER_LOG_RETAINED_FILES",
            "daemon",
            "log_retained_files",
            "integer",
        ),
        (
            "CODE_DIVER_MODEL_MANIFEST_PATH",
            "profile",
            "model_manifest_path",
            "string",
        ),
        (
            "CODE_DIVER_MAX_CONCURRENCY",
            "daemon",
            "max_concurrency",
            "integer",
        ),
        (
            "CODE_DIVER_REQUEST_TIMEOUT_SECS",
            "daemon",
            "request_timeout_secs",
            "integer",
        ),
        (
            "CODE_DIVER_STARTUP_TIMEOUT_SECS",
            "daemon",
            "startup_timeout_secs",
            "integer",
        ),
        (
            "CODE_DIVER_IDLE_TIMEOUT_SECS",
            "daemon",
            "idle_timeout_secs",
            "integer",
        ),
        (
            "CODE_DIVER_LOG_MAX_BYTES",
            "daemon",
            "log_max_bytes",
            "integer",
        ),
    ] {
        if let Some(raw) = env(variable) {
            let value = match kind {
                "integer" => toml::Value::Integer(raw.parse().map_err(|_| {
                    anyhow::anyhow!("invalid numeric runtime environment override")
                })?),
                "boolean" => toml::Value::Boolean(raw.parse().map_err(|_| {
                    anyhow::anyhow!("invalid boolean runtime environment override")
                })?),
                _ => toml::Value::String(raw),
            };
            result
                .entry(section)
                .or_insert_with(|| toml::Value::Table(toml::Table::new()))
                .as_table_mut()
                .unwrap()
                .insert(field.into(), value);
        }
    }
    if let Some(binary) = env("CODE_DIVER_LLAMA_SERVER") {
        result.insert("llama_server".into(), toml::Value::String(binary));
    }
    Ok(result)
}
pub fn save_config(path: &Path, config: &RuntimeConfig) -> Result<()> {
    config.validate()?;
    let text = toml::to_string_pretty(config)
        .map_err(|_| anyhow::anyhow!("cannot serialize runtime config"))?;
    atomic_write(path, text.as_bytes())
}
fn atomic_write(path: &Path, bytes: &[u8]) -> Result<()> {
    let parent = path
        .parent()
        .ok_or_else(|| anyhow::anyhow!("file requires parent directory"))?;
    fs::create_dir_all(parent)
        .map_err(|_| anyhow::anyhow!("cannot create runtime file directory"))?;
    let temp = parent.join(format!(
        ".runtime-{}-{}.tmp",
        std::process::id(),
        uuid::Uuid::new_v5(
            &uuid::Uuid::NAMESPACE_OID,
            format!("{:?}", std::time::SystemTime::now()).as_bytes()
        )
    ));
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let result = (|| -> std::io::Result<()> {
        let mut file = options.open(&temp)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        fs::rename(&temp, path)?;
        fs::File::open(parent)?.sync_all()
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temp);
    }
    result.map_err(|_| {
        anyhow::anyhow!("cannot atomically save runtime file; check permissions and disk space")
    })
}
/// Apply TOML patches in precedence order: flags > environment > file > defaults.
pub fn effective_config(
    file: RuntimeConfig,
    environment: &toml::Table,
    flags: &toml::Table,
) -> Result<RuntimeConfig> {
    fn merge(target: &mut toml::Value, patch: &toml::Table) {
        let table = target.as_table_mut().unwrap();
        // A source selected by a higher layer replaces the other source form.
        if patch.contains_key("model_manifest_url") && !patch.contains_key("model_manifest_path") {
            table.remove("model_manifest_path");
        }
        if patch.contains_key("model_manifest_path") && !patch.contains_key("model_manifest_url") {
            table.remove("model_manifest_url");
        }
        for (key, value) in patch {
            if let (Some(existing), Some(nested)) = (table.get_mut(key), value.as_table())
                && existing.is_table()
            {
                merge(existing, nested);
                continue;
            }
            table.insert(key.clone(), value.clone());
        }
    }
    let mut value = toml::Value::try_from(file)
        .map_err(|_| anyhow::anyhow!("cannot resolve runtime configuration"))?;
    merge(&mut value, environment);
    merge(&mut value, flags);
    let config: RuntimeConfig = value
        .try_into()
        .map_err(|_| anyhow::anyhow!("invalid runtime override type"))?;
    config.validate()?;
    Ok(config)
}
pub async fn load_profile(source: &str) -> Result<RuntimeProfile> {
    let bytes = if source.contains("://") {
        let url = validate_url(source)?;
        let client = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(30))
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .map_err(|_| anyhow::anyhow!("cannot initialize profile client"))?;
        let mut response = client
            .get(url)
            .send()
            .await
            .map_err(|_| anyhow::anyhow!("profile request failed"))?;
        if !response.status().is_success() {
            bail!("profile request rejected; check profile endpoint");
        }
        let mut bytes = Vec::new();
        while let Some(chunk) = response
            .chunk()
            .await
            .map_err(|_| anyhow::anyhow!("profile transfer interrupted"))?
        {
            if bytes.len() + chunk.len() > PROFILE_MAX_BYTES {
                bail!("profile exceeds size limit");
            }
            bytes.extend_from_slice(&chunk);
        }
        bytes
    } else {
        let file =
            fs::File::open(source).map_err(|_| anyhow::anyhow!("cannot open profile file"))?;
        use std::io::Read;
        let mut bytes = Vec::new();
        file.take((PROFILE_MAX_BYTES + 1) as u64)
            .read_to_end(&mut bytes)
            .map_err(|_| anyhow::anyhow!("cannot read profile file"))?;
        if bytes.len() > PROFILE_MAX_BYTES {
            bail!("profile exceeds size limit");
        }
        bytes
    };
    let text =
        std::str::from_utf8(&bytes).map_err(|_| anyhow::anyhow!("profile must be UTF-8 TOML"))?;
    let mut config: RuntimeConfig =
        toml::from_str(text).map_err(|_| anyhow::anyhow!("invalid profile TOML"))?;
    if !config.secrets.is_empty() {
        bail!("published profiles must not contain secret references");
    }
    if source.contains("://") {
        if config.profile.model_manifest_path.is_some() {
            bail!("remote profiles must use a model manifest URL, not a local path");
        }
    } else if let Some(path) = &config.profile.model_manifest_path
        && !path.is_absolute()
    {
        config.profile.model_manifest_path = Some(
            Path::new(source)
                .parent()
                .unwrap_or(Path::new("."))
                .join(path),
        );
    }
    config.validate()?;
    Ok(config.profile)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn runtime_defaults_and_manifest_override_precedence() {
        let defaults = RuntimeConfig::default();
        assert_eq!(defaults.daemon.log_max_bytes, 20 * 1024 * 1024);
        assert_eq!(defaults.daemon.log_retained_files, 3);
        assert_eq!(defaults.daemon.embedder_ctx, 5120);
        assert_eq!(defaults.daemon.embedder_batch, 2560);
        assert_eq!(defaults.daemon.embedder_ubatch, 2560);
        assert_eq!(defaults.daemon.reranker_ctx, 16384);
        assert_eq!(defaults.daemon.batch, 4096);
        assert_eq!(defaults.daemon.ubatch, 4096);
        let mut file = defaults;
        file.profile.model_manifest_path = Some("/tmp/models.json".into());
        let environment =
            toml::from_str("[profile]\nmodel_manifest_url='https://example.invalid/models.json'")
                .unwrap();
        let resolved = effective_config(file.clone(), &environment, &toml::Table::new()).unwrap();
        assert_eq!(
            resolved.profile.model_manifest_source().unwrap(),
            Some("https://example.invalid/models.json")
        );
        let flags =
            toml::from_str("[profile]\nmodel_manifest_path='/tmp/flag-models.json'").unwrap();
        let resolved = effective_config(file, &environment, &flags).unwrap();
        assert_eq!(
            resolved.profile.model_manifest_source().unwrap(),
            Some("/tmp/flag-models.json")
        );
        let ambiguous = toml::from_str("[profile]\nmodel_manifest_url='https://example.invalid/models.json'\nmodel_manifest_path='/tmp/models.json'").unwrap();
        assert!(
            effective_config(RuntimeConfig::default(), &ambiguous, &toml::Table::new()).is_err()
        );
    }
    #[test]
    fn daemon_environment_override_precedence() {
        let environment = environment_overrides(|key| match key {
            "CODE_DIVER_EMBEDDER_CTX" => Some("6144".into()),
            "CODE_DIVER_EMBEDDER_BATCH" | "CODE_DIVER_EMBEDDER_UBATCH" => Some("3072".into()),
            "CODE_DIVER_RERANKER_CTX" => Some("32768".into()),
            "CODE_DIVER_BATCH" | "CODE_DIVER_UBATCH" => Some("8192".into()),
            "CODE_DIVER_THREADS" => Some("8".into()),
            "CODE_DIVER_FLASH_ATTENTION" => Some("false".into()),
            _ => None,
        })
        .unwrap();
        let file: RuntimeConfig =
            toml::from_str("[daemon]\nembedder_ctx=4096\nbatch=4096\nthreads=2").unwrap();
        let flags = toml::from_str("[daemon]\nbatch=6144\nthreads=4").unwrap();
        let config = effective_config(file, &environment, &flags).unwrap();
        assert_eq!(config.daemon.embedder_ctx, 6144);
        assert_eq!(config.daemon.embedder_batch, 3072);
        assert_eq!(config.daemon.embedder_ubatch, 3072);
        assert_eq!(config.daemon.reranker_ctx, 32768);
        assert_eq!(config.daemon.batch, 6144);
        assert_eq!(config.daemon.ubatch, 8192);
        assert_eq!(config.daemon.threads, Some(4));
        assert!(!config.daemon.flash_attention);
    }
    #[test]
    fn consumer_configuration_fields() {
        let config: RuntimeConfig = toml::from_str("[profile]\nmodel_manifest_path='/tmp/models.json'\n[daemon]\nmax_concurrency=2\nstartup_timeout_secs=90\nflash_attention=false\nthreads=4\n").unwrap();
        config.validate().unwrap();
        assert_eq!(config.daemon.max_concurrency, 2);
        assert_eq!(config.daemon.startup_timeout_secs, 90);
        assert!(!config.daemon.flash_attention);
        assert_eq!(config.daemon.threads, Some(4));
        let value = toml::Value::try_from(&config).unwrap();
        assert!(unknown_key_warnings(&value).is_empty());
        assert_eq!(
            config,
            toml::from_str(&toml::to_string(&config).unwrap()).unwrap()
        );
        let mut invalid = config.clone();
        invalid.daemon.max_concurrency = 0;
        assert!(invalid.validate().is_err());
        invalid = config;
        invalid.profile.model_manifest_url = Some("https://example.invalid/models".into());
        assert!(invalid.validate().is_err());
        assert!(NativeMacSecurity.get("../unsafe").is_err());
    }
    #[test]
    fn env_unknown_keys_and_fake_keychain() {
        let environment = environment_overrides(|key| match key {
            "CODE_DIVER_DAEMON_PORT" => Some("8093".into()),
            "CODE_DIVER_AUTOSTART" => Some("false".into()),
            _ => None,
        })
        .unwrap();
        let config =
            effective_config(RuntimeConfig::default(), &environment, &toml::Table::new()).unwrap();
        assert_eq!(config.daemon.port, 8093);
        assert!(!config.daemon.autostart);
        assert!(environment_overrides(|_| Some("synthetic-secret".into())).is_err());
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("config.toml");
        fs::write(
            &path,
            "unknown='synthetic-secret'\nllama_server='bin/llama-server'\n",
        )
        .unwrap();
        let (config, warnings) = load_config_with_warnings(&path).unwrap();
        assert_eq!(
            config.llama_server.unwrap(),
            temp.path().join("bin/llama-server")
        );
        assert_eq!(warnings.len(), 1);
        assert!(!warnings[0].contains("synthetic-secret"));
        struct Fake;
        impl SecretStore for Fake {
            fn get(&self, _: &str) -> Result<Option<SecretValue>> {
                Ok(Some(SecretValue::new("fake-keychain-token".into())?))
            }
            fn put(&self, _: &str, _: &SecretValue) -> Result<()> {
                Ok(())
            }
            fn delete(&self, _: &str) -> Result<()> {
                Ok(())
            }
        }
        impl MacSecurity for Fake {}
        let fake = Fake;
        assert_eq!(
            resolve_secret(
                &SecretRef::Keychain("qdrant".into()),
                |_| None,
                &fake,
                Some(&fake)
            )
            .unwrap()
            .expose(),
            "fake-keychain-token"
        );
        assert!(
            resolve_secret(&SecretRef::Keychain("qdrant".into()), |_| None, &fake, None).is_err()
        );
        let store: &dyn SecretStore = &fake;
        store.delete("qdrant").unwrap();
        assert!(NativeMacSecurity.delete("../unsafe").is_err());
        assert_eq!(
            resolve_secret(
                &SecretRef::Env("QDRANT_API_KEY".into()),
                |_| Some("env-token".into()),
                &fake,
                None
            )
            .unwrap()
            .expose(),
            "env-token"
        );
    }
    #[tokio::test]
    async fn profile_url_and_bounded_response() {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        for (body, valid) in [
            ("[profile]\nindex_name='pier'\n".to_string(), true),
            (
                "[profile]\nmodel_manifest_path='models.json'\n".to_string(),
                false,
            ),
            ("x".repeat(PROFILE_MAX_BYTES + 1), false),
        ] {
            let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
            let address = listener.local_addr().unwrap();
            let task = tokio::spawn(async move {
                let (mut stream, _) = listener.accept().await.unwrap();
                let mut request = Vec::new();
                while !request.ends_with(b"\r\n\r\n") {
                    request.push(stream.read_u8().await.unwrap());
                }
                let header = format!(
                    "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                    body.len()
                );
                stream.write_all(header.as_bytes()).await.unwrap();
                let _ = stream.write_all(body.as_bytes()).await;
            });
            assert_eq!(
                load_profile(&format!("http://{address}/profile"))
                    .await
                    .is_ok(),
                valid
            );
            task.await.unwrap();
        }
    }
    #[test]
    fn isolated_paths_and_defaults() {
        assert!(RuntimePaths::discover().unwrap().config.is_absolute());
        assert_eq!(
            RuntimeConfig::default().daemon_url(),
            "http://127.0.0.1:8090"
        );
        let temp = tempfile::tempdir().unwrap();
        let paths = RuntimePaths::from_env(Platform::MacOs, |key| match key {
            "CODE_DIVER_HOME" => Some(temp.path().display().to_string()),
            _ => panic!("override consulted user paths"),
        })
        .unwrap();
        for path in [
            &paths.config,
            &paths.cache,
            &paths.data,
            &paths.state,
            &paths.hosts,
            &paths.services,
            &paths.secrets,
        ] {
            assert!(path.starts_with(temp.path()));
        }
        assert!(paths.index_dir("../escape").is_err());
        let linux = RuntimePaths::from_env(Platform::Linux, |k| {
            (k == "HOME").then(|| "/synthetic/user".into())
        })
        .unwrap();
        assert_eq!(
            linux.models,
            PathBuf::from("/synthetic/user/.cache/code-diver/models")
        );
    }
    #[test]
    fn precedence_private_secrets_and_roundtrip() {
        let temp = tempfile::tempdir().unwrap();
        let paths = RuntimePaths::from_env(Platform::Linux, |k| {
            (k == "CODE_DIVER_HOME").then(|| temp.path().display().to_string())
        })
        .unwrap();
        paths.ensure_dirs().unwrap();
        let store = FileSecretStore::new(&paths);
        let token = SecretValue::new("synthetic-sensitive-token".into()).unwrap();
        store.put("qdrant", &token).unwrap();
        let secret =
            resolve_secret(&SecretRef::File("qdrant".into()), |_| None, &store, None).unwrap();
        assert_eq!(secret.expose(), token.expose());
        assert!(!format!("{secret:?}").contains(token.expose()));
        let mut config = RuntimeConfig::default();
        config
            .secrets
            .insert("qdrant".into(), SecretRef::File("qdrant".into()));
        save_config(&paths.config_file(), &config).unwrap();
        assert_eq!(load_config(&paths.config_file()).unwrap(), config);
        assert!(!config.redacted_toml().unwrap().contains("source"));
        assert!(
            !fs::read_to_string(paths.config_file())
                .unwrap()
                .contains(token.expose())
        );
        let env = toml::from_str("[daemon]\nport=8091").unwrap();
        let flags = toml::from_str("[daemon]\nport=8092").unwrap();
        assert_eq!(
            effective_config(config, &env, &flags).unwrap().daemon.port,
            8092
        );
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(
                paths.secrets.join("qdrant"),
                fs::Permissions::from_mode(0o644),
            )
            .unwrap();
            assert!(store.get("qdrant").is_err());
        }
    }
    #[tokio::test]
    async fn profile_file_and_sanitized_errors() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("profile.toml");
        fs::write(
            &path,
            "[profile]\nindex_name='pier'\nqdrant_url='https://example.invalid'\n",
        )
        .unwrap();
        assert_eq!(
            load_profile(path.to_str().unwrap())
                .await
                .unwrap()
                .index_name
                .as_deref(),
            Some("pier")
        );
        fs::write(&path, "[profile]\nmodel_manifest_path='models.json'\n").unwrap();
        assert_eq!(
            load_profile(path.to_str().unwrap())
                .await
                .unwrap()
                .model_manifest_path,
            Some(temp.path().join("models.json"))
        );
        fs::write(
            &path,
            "[profile]\nqdrant_url='https://user:synthetic-secret@example.invalid'\n",
        )
        .unwrap();
        let error = load_profile(path.to_str().unwrap()).await.unwrap_err();
        assert!(!format!("{error:#}").contains("synthetic-secret"));
        assert!(validate_url("http://example.invalid").is_err());
        assert!(validate_url("http://127.0.0.1:1234").is_ok());
        let mut config = RuntimeConfig::default();
        config.daemon.ubatch = 512;
        assert!(config.validate().is_err());
    }
}
