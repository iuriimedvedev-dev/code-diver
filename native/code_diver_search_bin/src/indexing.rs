use std::fs::{File, OpenOptions};
use std::path::{Path, PathBuf};

use clap::Args;
use reqwest::Method;
use serde_json::{Value, json};

use crate::index_net::{self, Secret};
use crate::index_update::{
    delete_points, diff_catalog, embed_text, scroll_indexed_profile, upsert_points,
};
use crate::types::CatalogItem;

#[derive(Args, Debug, Clone, Default)]
pub struct IndexOptions {
    #[arg(long, alias = "qdrant-collection")]
    pub collection: Option<String>,
    #[arg(long, conflicts_with = "dry_run")]
    pub apply: bool,
    #[arg(long)]
    pub dry_run: bool,
    #[arg(long, requires = "apply")]
    pub prune: bool,
    #[arg(long)]
    pub graph: Option<PathBuf>,
    #[arg(long)]
    pub qdrant_url: Option<String>,
    #[arg(long, hide_default_value = true)]
    pub qdrant_api_key: Option<Secret>,
    #[arg(long, hide_default_value = true)]
    pub qdrant_bearer: Option<Secret>,
    #[arg(long)]
    pub embedding_url: Option<String>,
    #[arg(long)]
    pub embedding_model: Option<String>,
    #[arg(long)]
    pub embedding_dimensions: Option<usize>,
    #[arg(long, hide_default_value = true)]
    pub embedding_api_key: Option<Secret>,
    #[arg(long)]
    pub embedding_document_prefix: Option<String>,
    #[arg(long)]
    pub embedding_query_prefix: Option<String>,
    #[arg(long)]
    pub max_input_chars: Option<usize>,
    #[arg(long)]
    pub max_input_tokens: Option<usize>,
    #[arg(long)]
    pub token_safety_margin: Option<usize>,
    #[arg(long)]
    pub batch_size: Option<usize>,
    #[arg(long)]
    pub workers: Option<usize>,
    #[arg(long)]
    pub timeout_ms: Option<u64>,
    #[arg(long)]
    pub ca_bundle: Option<String>,
    #[arg(long)]
    pub insecure_skip_verify: bool,
    #[arg(long)]
    pub audit_embed_text: bool,
}

pub struct CatalogLock {
    path: PathBuf,
    _file: File,
}
impl CatalogLock {
    pub fn acquire(catalog: &Path) -> Result<Self, String> {
        let parent = catalog
            .parent()
            .filter(|p| !p.as_os_str().is_empty())
            .unwrap_or_else(|| Path::new("."));
        let parent = parent
            .canonicalize()
            .map_err(|_| "Cannot resolve catalog directory for lock")?;
        let catalog = parent.join(
            catalog
                .file_name()
                .ok_or("Catalog path lacks a file name")?,
        );
        let mut name = catalog.as_os_str().to_os_string();
        name.push(".lock");
        let path = PathBuf::from(name);
        let file = OpenOptions::new().write(true).create_new(true).open(&path)
            .map_err(|_| "Catalog lock unavailable; another indexer may be running (remove stale .lock only after checking)")?;
        Ok(Self { path, _file: file })
    }
}
impl Drop for CatalogLock {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.path);
    }
}

pub(crate) fn remote_config(path: Option<&Path>) -> Result<Value, String> {
    let Some(path) = path else {
        return Ok(json!({}));
    };
    let raw = std::fs::read_to_string(path).map_err(|_| "Cannot read index configuration")?;
    if path.extension().is_some_and(|ext| ext == "toml") {
        let mut config = crate::catalog_builder::config::parse(&raw, true)?;
        apply_profile(&mut config)?;
        return Ok(config);
    }
    // Reuse the scanner's scalar/list reader for the supported service mappings.
    let mut result = json!({});
    for line in raw.lines().filter(|line| !line.starts_with([' ', '\t'])) {
        if let Some((key, _)) = line.split_once(':')
            && matches!(
                key,
                "root"
                    | "catalog"
                    | "graph_path"
                    | "model"
                    | "index_metadata"
                    | "ca_bundle"
                    | "insecure_skip_verify"
            )
        {
            result[key] = crate::catalog_builder::config::parse(
                &format!("scanner:\n  {line}\n"),
                false,
            )?["scanner"][key]
                .clone();
        }
    }
    for section in [
        "embedding",
        "indexing",
        "search",
        "cross_encoder_rerank",
        "profile",
    ] {
        let mut active = false;
        let mut block = String::from("scanner:\n");
        for line in raw.lines() {
            if !line.starts_with(' ')
                && !line.trim().is_empty()
                && !line.trim_start().starts_with('#')
            {
                active = line.trim() == format!("{section}:");
                continue;
            }
            if active {
                block.push_str(line);
                block.push('\n');
            }
        }
        result[section] = crate::catalog_builder::config::parse(&block, false)?["scanner"].clone();
    }
    let mut storage = false;
    let mut qdrant = false;
    let mut block = String::from("scanner:\n");
    for line in raw.lines() {
        if !line.starts_with(' ') && !line.trim().is_empty() && !line.trim_start().starts_with('#')
        {
            storage = line.trim() == "storage:";
            qdrant = false;
            continue;
        }
        if storage && line.starts_with("  ") && !line.starts_with("    ") {
            qdrant = line.trim() == "qdrant:";
            continue;
        }
        if storage
            && qdrant
            && let Some(line) = line.strip_prefix("  ")
        {
            block.push_str(line);
            block.push('\n');
        }
    }
    result["storage"] =
        json!({"qdrant": crate::catalog_builder::config::parse(&block, false)?["scanner"]});
    apply_profile(&mut result)?;
    Ok(result)
}

fn apply_profile(config: &mut Value) -> Result<(), String> {
    let profile = config["profile"].clone();
    for (key, path) in [
        ("qdrant_url", &["storage", "qdrant", "url"][..]),
        (
            "qdrant_collection",
            &["storage", "qdrant", "collection"][..],
        ),
        ("embedding_url", &["embedding", "url"][..]),
        ("embedding_model", &["embedding", "model"][..]),
        ("embedding_dimensions", &["embedding", "dimensions"][..]),
        ("embedding_query_prefix", &["embedding", "query_prefix"][..]),
        (
            "embedding_document_prefix",
            &["embedding", "document_prefix"][..],
        ),
        ("ce_url", &["cross_encoder_rerank", "url"][..]),
        ("ce_model", &["cross_encoder_rerank", "model"][..]),
        ("catalog", &["catalog"][..]),
        ("graph_path", &["graph_path"][..]),
        ("model", &["model"][..]),
        ("index_metadata", &["index_metadata"][..]),
    ] {
        if profile[key].is_null() {
            continue;
        }
        let mut target = &mut *config;
        for key in path {
            if !target.is_null() && !target.is_object() {
                return Err("Invalid configuration mapping; expected a table".into());
            }
            target = &mut target[*key];
        }
        if target.is_null() {
            *target = profile[key].clone();
        }
    }
    Ok(())
}

pub(crate) fn setting(
    cli: Option<&str>,
    env: &str,
    alias: Option<&str>,
    config: &Value,
    default: &str,
) -> String {
    cli.map(str::to_string)
        .or_else(|| std::env::var(format!("CODE_DIVER_{env}")).ok())
        .or_else(|| alias.and_then(|name| std::env::var(name).ok()))
        .or_else(|| config.as_str().map(str::to_string))
        .or_else(|| {
            if config.is_number() || config.is_boolean() {
                Some(config.to_string())
            } else {
                None
            }
        })
        .unwrap_or_else(|| default.into())
}

pub(crate) fn configured_path(
    cli: Option<&Path>,
    env: &str,
    config: &Value,
    config_file: Option<&Path>,
    default: &Path,
) -> PathBuf {
    let (value, from_config) = if let Some(cli) = cli {
        (cli.to_path_buf(), false)
    } else if let Ok(value) = std::env::var(format!("CODE_DIVER_{env}")) {
        (PathBuf::from(value), false)
    } else if let Some(value) = config.as_str() {
        (PathBuf::from(value), true)
    } else {
        (default.to_path_buf(), false)
    };
    let value = if let Some(rest) = value.to_str().and_then(|v| v.strip_prefix("~/")) {
        std::env::var_os("HOME")
            .map(|home| PathBuf::from(home).join(rest))
            .unwrap_or(value)
    } else {
        value
    };
    if from_config && value.is_relative() {
        config_file
            .and_then(Path::parent)
            .unwrap_or_else(|| Path::new("."))
            .join(value)
    } else {
        value
    }
}

pub(crate) fn validate_config(config: &Value) -> Result<(), String> {
    if !config["search"]["require_rerank"].is_null()
        && !config["search"]["require_rerank"].is_boolean()
    {
        return Err("Invalid search.require_rerank; expected a boolean".into());
    }
    for (section, fields) in [
        (
            "embedding",
            &[
                "provider",
                "model",
                "dimensions",
                "url",
                "api_key",
                "api_key_env",
                "batch_size",
                "workers",
                "max_input_chars",
                "max_input_tokens",
                "token_safety_margin",
                "document_prefix",
                "query_prefix",
                "send_dimensions",
            ][..],
        ),
        ("indexing", &["mode", "timeout_ms"][..]),
    ] {
        if let Some(values) = config[section].as_object() {
            for (key, value) in values {
                if !fields.contains(&key.as_str()) {
                    eprintln!("WARNING: unknown {section} configuration key ignored");
                    continue;
                }
                if value.is_null() {
                    continue;
                }
                let valid = if matches!(
                    key.as_str(),
                    "dimensions"
                        | "batch_size"
                        | "workers"
                        | "max_input_chars"
                        | "max_input_tokens"
                        | "token_safety_margin"
                        | "timeout_ms"
                ) {
                    value.as_u64().is_some()
                } else if key == "send_dimensions" {
                    value.is_boolean()
                } else {
                    value.is_string()
                };
                if !valid {
                    return Err(format!("Invalid {section} setting type"));
                }
            }
        }
    }
    Ok(())
}

fn number<T: std::str::FromStr>(
    cli: Option<T>,
    env: &str,
    value: &Value,
    default: &str,
) -> Result<T, String> {
    cli.map(Ok).unwrap_or_else(|| {
        setting(None, env, None, value, default)
            .parse()
            .map_err(|_| format!("Invalid {env} setting"))
    })
}

pub fn document_text(
    item: &CatalogItem,
    prefix: &str,
    chars: usize,
    tokens: usize,
    margin: usize,
) -> String {
    let budget = tokens.saturating_sub(margin).max(1).saturating_mul(3);
    let cap = if chars == 0 {
        budget
    } else {
        chars.min(budget)
    };
    let prepared = embed_text(item, if chars == 0 { 0 } else { cap });
    format!("{prefix}{prepared}").chars().take(cap).collect()
}

fn embedding_body(model: &str, texts: &[String], dimensions: Option<usize>) -> Value {
    let mut body = json!({"model": model, "input": texts, "encoding_format": "float"});
    if let Some(dimensions) = dimensions {
        body["dimensions"] = json!(dimensions);
    }
    body
}

fn vectors(data: Value, count: usize) -> Result<Vec<Vec<f64>>, String> {
    let rows = data["data"]
        .as_array()
        .ok_or("Embedding response lacks data")?;
    if rows.len() != count {
        return Err("Embedding response count mismatch".into());
    }
    let mut output = vec![None; count];
    for row in rows {
        let index = row["index"]
            .as_u64()
            .and_then(|n| usize::try_from(n).ok())
            .ok_or("Embedding response lacks index")?;
        if index >= count || output[index].is_some() {
            return Err("Embedding response index mismatch".into());
        }
        let vector: Vec<f64> = row["embedding"]
            .as_array()
            .ok_or("Embedding response lacks vector")?
            .iter()
            .map(|v| {
                v.as_f64()
                    .filter(|n| n.is_finite())
                    .ok_or("Invalid embedding value".to_string())
            })
            .collect::<Result<_, _>>()?;
        if vector.is_empty() {
            return Err("Empty embedding vector".into());
        }
        output[index] = Some(vector);
    }
    output
        .into_iter()
        .map(|v| v.ok_or("Missing embedding vector".into()))
        .collect()
}

pub async fn run(
    items: &[CatalogItem],
    root: &Path,
    catalog: &Path,
    options: &IndexOptions,
    config_path: Option<&Path>,
) -> Result<(), String> {
    let config = remote_config(config_path)?;
    validate_config(&config)?;
    let embedding = &config["embedding"];
    let qdrant = &config["storage"]["qdrant"];
    let collection = setting(
        options.collection.as_deref(),
        "COLLECTION",
        Some("CODE_DIVER_QDRANT_COLLECTION"),
        &qdrant["collection"],
        "",
    );
    if collection.is_empty() {
        return Err("Set --collection to compare an index (required explicitly on --apply)".into());
    }
    if !collection
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || matches!(c, '_' | '-' | '.'))
    {
        return Err(
            "Invalid collection name; use letters, digits, underscores, hyphens or dots".into(),
        );
    }
    let qurl = setting(
        options.qdrant_url.as_deref(),
        "QDRANT_URL",
        None,
        &qdrant["url"],
        "http://localhost:6333",
    );
    let eurl = setting(
        options.embedding_url.as_deref(),
        "EMBEDDING_URL",
        None,
        &embedding["url"],
        "http://localhost:8001/v1/embeddings",
    );
    for url in [&qurl, &eurl] {
        let url = reqwest::Url::parse(url).map_err(|_| "Invalid service URL")?;
        if !matches!(url.scheme(), "http" | "https")
            || !url.username().is_empty()
            || url.password().is_some()
            || url.query().is_some()
            || url.fragment().is_some()
        {
            return Err(
                "Service URL must be HTTP(S) without credentials, query or fragment".into(),
            );
        }
    }
    let model = setting(
        options.embedding_model.as_deref(),
        "EMBEDDING_MODEL",
        None,
        &embedding["model"],
        crate::embedding::EMBED_MODEL,
    );
    let provider = setting(
        None,
        "EMBEDDING_PROVIDER",
        None,
        &embedding["provider"],
        "openai_compatible",
    );
    if provider != "openai_compatible" {
        return Err(
            "Unsupported embedding provider; profile migration requires a new collection".into(),
        );
    }
    let prefix = setting(
        options.embedding_document_prefix.as_deref(),
        "EMBEDDING_DOCUMENT_PREFIX",
        None,
        &embedding["document_prefix"],
        "",
    );
    let chars = number(
        options.max_input_chars,
        "MAX_INPUT_CHARS",
        &embedding["max_input_chars"],
        "2000",
    )?;
    let tokens = number(
        options.max_input_tokens,
        "MAX_INPUT_TOKENS",
        &embedding["max_input_tokens"],
        "512",
    )?;
    let margin = number(
        options.token_safety_margin,
        "TOKEN_SAFETY_MARGIN",
        &embedding["token_safety_margin"],
        "32",
    )?;
    let batch: usize = number(
        options.batch_size,
        "BATCH_SIZE",
        &embedding["batch_size"],
        "32",
    )?;
    let timeout = number(
        options.timeout_ms,
        "TIMEOUT_MS",
        &config["indexing"]["timeout_ms"],
        "60000",
    )?;
    if batch == 0 || batch > 4096 || timeout == 0 || tokens == 0 {
        return Err("Batch size must be 1..4096; timeout and token window must be positive".into());
    }
    let dimensions: usize = number(
        options.embedding_dimensions,
        "EMBEDDING_DIMENSIONS",
        &embedding["dimensions"],
        "0",
    )?;
    let dimensions = if dimensions == 0 {
        None
    } else {
        Some(dimensions)
    };
    let send_dimensions: bool = number(
        None,
        "EMBEDDING_SEND_DIMENSIONS",
        &embedding["send_dimensions"],
        "false",
    )?;
    let qkey = Secret(setting(
        options.qdrant_api_key.as_ref().map(|s| s.0.as_str()),
        "QDRANT_API_KEY",
        Some(qdrant["api_key_env"].as_str().unwrap_or("QDRANT_API_KEY")),
        &qdrant["api_key"],
        "",
    ));
    let qbearer = Secret(setting(
        options.qdrant_bearer.as_ref().map(|s| s.0.as_str()),
        "QDRANT_BEARER",
        None,
        &qdrant["bearer"],
        "",
    ));
    let ekey = Secret(setting(
        options.embedding_api_key.as_ref().map(|s| s.0.as_str()),
        "EMBEDDING_API_KEY",
        Some(
            embedding["api_key_env"]
                .as_str()
                .unwrap_or("EMBEDDING_API_KEY"),
        ),
        &embedding["api_key"],
        "",
    ));
    let ca = setting(
        options.ca_bundle.as_deref(),
        "CA_BUNDLE",
        Some("SSL_CERT_FILE"),
        &config["ca_bundle"],
        "",
    );
    let ca = if options.ca_bundle.is_none()
        && std::env::var_os("CODE_DIVER_CA_BUNDLE").is_none()
        && std::env::var_os("SSL_CERT_FILE").is_none()
        && !ca.is_empty()
    {
        configured_path(
            None,
            "CA_BUNDLE",
            &config["ca_bundle"],
            config_path,
            Path::new(&ca),
        )
        .to_string_lossy()
        .into_owned()
    } else if ca.starts_with("~/") {
        configured_path(
            Some(Path::new(&ca)),
            "CA_BUNDLE",
            &Value::Null,
            None,
            Path::new(""),
        )
        .to_string_lossy()
        .into_owned()
    } else {
        ca
    };
    let insecure = options.insecure_skip_verify
        || setting(
            None,
            "INSECURE_SKIP_VERIFY",
            None,
            &config["insecure_skip_verify"],
            "false",
        )
        .parse::<bool>()
        .map_err(|_| "Invalid TLS verification setting")?;
    let ca = if ca.is_empty() {
        None
    } else {
        Some(ca.as_str())
    };
    let qclient = index_net::client(&qkey, &qbearer, ca, insecure, timeout)?;
    let eclient = index_net::client(&Secret::default(), &ekey, ca, insecure, timeout)?;
    let collection_url = format!("{}/collections/{collection}", qurl.trim_end_matches('/'));
    let response = index_net::request(&qclient, Method::GET, &collection_url, None).await?;
    let mut existing_dimensions = if response.status() == reqwest::StatusCode::NOT_FOUND {
        None
    } else {
        Some(
            index_net::json(response).await?["result"]["config"]["params"]["vectors"]["size"]
                .as_u64()
                .filter(|n| *n > 0)
                .ok_or("Cannot read collection vector size (named vectors unsupported)")?
                as usize,
        )
    };
    let indexed = if existing_dimensions.is_some() {
        scroll_indexed_profile(
            &qclient,
            &qurl,
            &collection,
            if options.apply {
                Some((&provider, &model))
            } else {
                None
            },
        )
        .await?
    } else {
        Default::default()
    };
    let query_prefix = setting(
        options.embedding_query_prefix.as_deref(),
        "EMBEDDING_QUERY_PREFIX",
        None,
        &embedding["query_prefix"],
        "",
    );
    let profile = json!({
        "version": 1, "text_preparation": "unicode-character-fallback-v1",
        "qdrant_url": qurl, "collection": collection, "root": root.to_string_lossy(),
        "embedding_url": eurl, "provider": provider, "model": model,
        "document_prefix": prefix, "query_prefix": query_prefix, "max_input_chars": chars,
        "max_input_tokens": tokens, "token_safety_margin": margin,
        "dimensions": dimensions, "send_dimensions": send_dimensions
    });
    let mut profile_name = catalog.as_os_str().to_os_string();
    profile_name.push(".embedding-profile.json");
    let profile_path = PathBuf::from(profile_name);
    let saved_profile =
        match std::fs::read(&profile_path) {
            Ok(bytes) => Some(serde_json::from_slice::<Value>(&bytes).map_err(
                |_| "Invalid embedding profile sidecar; use a new collection and catalog",
            )?),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => None,
            Err(_) => return Err("Cannot read embedding profile sidecar".into()),
        };
    if !indexed.is_empty() && saved_profile.as_ref() != Some(&profile) {
        let message = "Embedding profile changed or unverified; use a new collection and catalog for explicit migration (no remote writes)";
        if options.apply {
            return Err(message.into());
        }
        eprintln!("WARNING: {message}; content diff below does not imply embedding compatibility");
    }
    if options.apply && !items.is_empty() && saved_profile.as_ref() != Some(&profile) {
        // Persist before mutations so partial applies can be safely resumed with the same profile.
        std::fs::write(
            &profile_path,
            serde_json::to_vec_pretty(&profile).map_err(|_| "Cannot encode embedding profile")?,
        )
        .map_err(|_| "Cannot persist embedding profile before remote writes")?;
    }
    let diff = diff_catalog(items, &indexed);
    eprintln!(
        "Diff: added={} changed={} deleted={}",
        diff.added.len(),
        diff.changed.len(),
        diff.deleted.len()
    );
    if options.audit_embed_text {
        let counts: Vec<_> = items
            .iter()
            .map(|item| {
                document_text(item, &prefix, chars, tokens, margin)
                    .chars()
                    .count()
            })
            .collect();
        eprintln!(
            "embed-text audit: items={} total_chars={} max_chars={} token_budget={} estimated_threshold_candidates={} tokenizer=unavailable would_differ_from_python=unknown; char/3 estimates are NOT exact token counts",
            counts.len(),
            counts.iter().sum::<usize>(),
            counts.iter().max().unwrap_or(&0),
            tokens.saturating_sub(margin).max(1),
            items
                .iter()
                .filter(|item| format!("{prefix}{}", embed_text(item, chars))
                    .chars()
                    .count()
                    > tokens.saturating_sub(margin).max(1).saturating_mul(3))
                .count()
        );
    }
    if !options.apply {
        eprintln!("Dry run: no remote writes; use --apply (--prune permits deletions)");
        return Ok(());
    }
    let dirty: Vec<_> = diff
        .added
        .iter()
        .chain(&diff.changed)
        .map(|i| &items[*i])
        .collect();
    let workers: usize = number(options.workers, "WORKERS", &embedding["workers"], "2")?;
    if workers == 0 || workers > 32 {
        return Err("Workers must be 1..32".into());
    }
    let mut done = 0;
    for wave in dirty.chunks(batch * workers) {
        let chunks: Vec<_> = wave.chunks(batch).collect();
        let mut tasks = tokio::task::JoinSet::new();
        for (index, chunk) in chunks.iter().enumerate() {
            let texts: Vec<_> = chunk
                .iter()
                .map(|item| document_text(item, &prefix, chars, tokens, margin))
                .collect();
            let body = embedding_body(
                &model,
                &texts,
                if send_dimensions { dimensions } else { None },
            );
            let client = eclient.clone();
            let url = eurl.clone();
            tasks.spawn(async move {
                let response = index_net::embedding_request(&client, &url, &body).await?;
                vectors(response, texts.len()).map(|vectors| (index, vectors))
            });
        }
        let mut completed = Vec::new();
        while let Some(result) = tasks.join_next().await {
            completed.push(result.map_err(|_| "Embedding worker failed")??);
        }
        completed.sort_by_key(|(index, _)| *index);
        for (index, vectors) in completed {
            let chunk = chunks[index];
            let size = vectors[0].len();
            if vectors.iter().any(|v| v.len() != size)
                || dimensions.is_some_and(|n| n != size)
                || existing_dimensions.is_some_and(|n| n != size)
            {
                return Err("Embedding dimension mismatch; no batch upserted".into());
            }
            if existing_dimensions.is_none() {
                index_net::json(
                    index_net::request(
                        &qclient,
                        Method::PUT,
                        &collection_url,
                        Some(&json!({"vectors": {"size": size, "distance": "Cosine"}})),
                    )
                    .await?,
                )
                .await?;
                existing_dimensions = Some(size);
            }
            done += upsert_points(
                &qclient,
                &qurl,
                &collection,
                chunk,
                &vectors,
                &root.to_string_lossy(),
                "openai_compatible",
                &model,
                size,
            )
            .await?;
            eprintln!("Upserted {done}/{}", dirty.len());
        }
    }
    if options.prune {
        eprintln!("Pruning {} points", diff.deleted.len());
        delete_points(&qclient, &qurl, &collection, &diff.deleted).await?;
    } else if !diff.deleted.is_empty() {
        eprintln!(
            "Retained {} removed points; pass --apply --prune to delete",
            diff.deleted.len()
        );
    }
    if let Some(dimensions) = existing_dimensions {
        let path = crate::metadata::sidecar(catalog);
        let metadata = crate::metadata::Metadata {
            schema_version: crate::metadata::SCHEMA_VERSION,
            generated_at: std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map_err(|_| "System clock precedes Unix epoch")?
                .as_secs(),
            collection,
            extra: Default::default(),
            embedding: crate::metadata::Embedding {
                model,
                dimensions,
                query_prefix,
                document_prefix: prefix,
                extra: [
                    ("max_input_chars".into(), json!(chars)),
                    ("max_input_tokens".into(), json!(tokens)),
                    ("token_safety_margin".into(), json!(margin)),
                ]
                .into(),
            },
        };
        let should_write =
            !path.exists() || !dirty.is_empty() || (options.prune && !diff.deleted.is_empty());
        if should_write {
            std::fs::write(
                path,
                serde_json::to_vec_pretty(&metadata).map_err(|_| "Cannot encode index metadata")?,
            )
            .map_err(|_| "Cannot persist index metadata")?;
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn config_paths_and_types_are_explicit() {
        assert_eq!(
            configured_path(
                None,
                "M3_TEST_UNUSED_PATH",
                &json!("repo"),
                Some(Path::new("configs/config.toml")),
                Path::new(".")
            ),
            Path::new("configs/repo")
        );
        assert_eq!(
            configured_path(
                Some(Path::new("explicit")),
                "M3_TEST_UNUSED_PATH",
                &json!("repo"),
                Some(Path::new("configs/config.toml")),
                Path::new(".")
            ),
            Path::new("explicit")
        );
        assert!(validate_config(&json!({"embedding": {"workers": "bad"}})).is_err());
        assert!(validate_config(&json!({"embedding": {"max_input_tokens": -1}})).is_err());
    }

    #[test]
    fn synthetic_python_request_body_parity() {
        let item = crate::catalog_builder::build_records(
            "docs/example.md",
            "# Example",
            &Default::default(),
        )
        .remove(0);
        let item = CatalogItem {
            content: "File: docs/example.md".into(),
            ..item
        };
        let texts = vec![document_text(
            &item,
            "Represent this code file metadata for retrieval: ",
            2000,
            512,
            32,
        )];
        let expected: Value =
            serde_json::from_str(include_str!("../tests/fixtures/m3_embedding_request.json"))
                .unwrap();
        assert_eq!(embedding_body("synthetic-model", &texts, Some(4)), expected);
    }

    #[test]
    fn prefix_is_inside_unicode_budget() {
        let item = crate::catalog_builder::build_records("x.md", "# Example", &Default::default())
            .remove(0);
        assert_eq!(document_text(&item, "文档: ", 6, 512, 32), "文档: ti");
        assert_eq!(
            document_text(&item, "x".repeat(2000).as_str(), 2000, 512, 32)
                .chars()
                .count(),
            1440
        );
    }

    #[test]
    fn validates_all_vectors_and_response_indices() {
        assert_eq!(
            vectors(
                json!({"data": [{"index": 1, "embedding": [2.]}, {"index": 0, "embedding": [1.]}]}),
                2
            )
            .unwrap(),
            vec![vec![1.], vec![2.]]
        );
        for value in [
            json!({"data": []}),
            json!({"data": [{"index": 0, "embedding": []}]}),
            json!({"data": [{"index": 0, "embedding": ["bad"]}]}),
        ] {
            assert!(vectors(value, 1).is_err());
        }
    }

    #[test]
    fn catalog_lock_is_exclusive_and_released() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("catalog.jsonl");
        let lock = CatalogLock::acquire(&path).unwrap();
        assert!(CatalogLock::acquire(&path).is_err());
        drop(lock);
        assert!(CatalogLock::acquire(&path).is_ok());
    }

    #[test]
    fn reads_service_yaml_without_echoing_secrets() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("config.yml");
        std::fs::write(&path, "storage:\n  backend: qdrant\n  qdrant:\n    url: http://localhost:6333\n    api_key: secret\nembedding:\n  model: synthetic\n  dimensions: 4\n  document_prefix: 'Represent: '\n").unwrap();
        let config = remote_config(Some(&path)).unwrap();
        assert_eq!(config["storage"]["qdrant"]["api_key"], "secret");
        assert_eq!(config["embedding"]["dimensions"], 4);
        assert_eq!(config["embedding"]["document_prefix"], "Represent: ");
    }
}
