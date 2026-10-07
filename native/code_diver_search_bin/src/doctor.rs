use std::path::Path;
use std::time::Instant;

use serde::Serialize;
use serde_json::json;

use crate::{SearchArgs, index_net};

const NORM_TOLERANCE: f64 = 0.01;
const LONG_PAIR_WORDS: usize = 2100;
const METADATA_MAX_AGE_SECONDS: u64 = 30 * 24 * 60 * 60;
const MIN_DISK_BYTES: u64 = 2 * 1024 * 1024 * 1024;
const MIN_RAM_BYTES: u64 = 8 * 1024 * 1024 * 1024;
const MIN_LLAMA_BUILD: u64 = 9430;

#[derive(Serialize)]
struct Check {
    name: String,
    status: &'static str,
    message: String,
    fix: String,
    elapsed_ms: f64,
}

#[derive(Default, Serialize)]
struct Report {
    checks: Vec<Check>,
}

impl Report {
    fn warning(&mut self, name: &str, start: Instant, message: String, fix: &str) {
        self.record(name, start, Ok(message), fix);
        self.checks.last_mut().unwrap().status = "WARN";
    }
    fn record(&mut self, name: &str, start: Instant, result: Result<String, String>, fix: &str) {
        let (status, message) = match result {
            Ok(message) => ("PASS", message),
            Err(message) => ("FAIL", message),
        };
        self.checks.push(Check {
            name: name.into(),
            status,
            message,
            fix: fix.into(),
            elapsed_ms: start.elapsed().as_secs_f64() * 1000.0,
        });
    }

    fn output(&self, json_output: bool) -> Result<(), String> {
        let passed = !self.checks.iter().any(|check| check.status == "FAIL");
        if json_output {
            println!(
                "{}",
                serde_json::to_string_pretty(&json!({"passed":passed,"checks":self.checks}))
                    .map_err(|_| "Cannot serialize doctor report")?
            );
        } else {
            for check in &self.checks {
                println!(
                    "{} {} ({:.1}ms): {}\n  fix: {}",
                    check.status, check.name, check.elapsed_ms, check.message, check.fix
                );
            }
        }
        if passed {
            Ok(())
        } else {
            Err("Doctor found failures; follow the reported fix hints".into())
        }
    }
}

pub async fn run(args: &SearchArgs, json_output: bool) -> Result<(), String> {
    run_checks(args, json_output, false).await
}

pub(crate) async fn run_for_setup(args: &SearchArgs) -> Result<(), String> {
    run_checks(args, false, true).await
}

async fn run_checks(
    args: &SearchArgs,
    json_output: bool,
    skip_registration: bool,
) -> Result<(), String> {
    let mut report = Report::default();
    let start = Instant::now();
    if args.config.is_none()
        && std::env::var_os("CODE_DIVER_CONFIG").is_none()
        && args.root.is_none()
        && args.catalog.is_none()
        && args.graph.is_none()
        && args.index_metadata.is_none()
        && args.qdrant_collection.is_empty()
        && args.qdrant_url.is_none()
        && crate::runtime_for_args(args)?.is_none()
    {
        report.record("configuration", start, Err("Runtime snapshot is not configured; run code-diver setup --profile URL-or-file with explicit index_name".into()), "Run code-diver setup, or supply explicit legacy artifact and collection configuration");
        return report.output(json_output);
    }
    let config = match crate::build_search_config_default(args, false, true) {
        Ok((config, _)) => config,
        Err(error) => {
            report.record(
                "configuration",
                start,
                Err(error),
                "Correct --config, service URLs and credential references; for metadata mismatch select matching --index-metadata, embedding model/dimensions and Qdrant collection",
            );
            return report.output(json_output);
        }
    };
    report.record(
        "configuration",
        start,
        Ok("Effective configuration loaded".into()),
        "No action required",
    );
    let runtime = crate::runtime_for_args(args)?;
    if let Some((runtime, paths)) = &runtime {
        runtime_checks(&mut report, args, runtime, paths, skip_registration).await;
    }
    let start = Instant::now();
    let metadata = config
        .index_metadata
        .as_deref()
        .ok_or("Index metadata missing; use --index-metadata".to_string())
        .and_then(crate::metadata::load);
    let metadata_result = metadata
        .as_ref()
        .map_err(Clone::clone)
        .and_then(|metadata| {
            metadata.validate(&config)?;
            let now = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map_err(|_| "Invalid system clock")?
                .as_secs();
            let age = now
                .checked_sub(metadata.generated_at)
                .ok_or("Index generated_at is in the future")?;
            if age > METADATA_MAX_AGE_SECONDS {
                return Err("Index metadata is older than 30 days".into());
            }
            Ok("Compatible schema 2 metadata; generated_at fresh".into())
        });
    report.record(
        "metadata",
        start,
        metadata_result,
        "Fetch current matching index artifacts, or regenerate metadata with index --apply",
    );
    let platform = matches!(std::env::consts::OS, "macos" | "linux")
        && matches!(std::env::consts::ARCH, "aarch64" | "x86_64");
    report.record(
        "platform",
        Instant::now(),
        if platform {
            Ok(format!(
                "{} {}",
                std::env::consts::OS,
                std::env::consts::ARCH
            ))
        } else {
            Err("Unsupported platform".into())
        },
        "Use macOS or Linux on arm64/x86_64",
    );
    for (name, minimum, fix) in [
        (
            "disk",
            MIN_DISK_BYTES,
            "Free at least 2 GiB on the artifact filesystem",
        ),
        (
            "ram",
            MIN_RAM_BYTES,
            "Use a host with at least 8 GiB physical RAM; reduce model concurrency if memory constrained",
        ),
    ] {
        let start = Instant::now();
        let result = if name == "disk" {
            disk_bytes(Path::new(&config.catalog_path))
        } else {
            ram_bytes()
        };
        match result {
            Ok(bytes) if bytes >= minimum => report.record(
                name,
                start,
                Ok(format!("{bytes} bytes; minimum {minimum}")),
                "No action required",
            ),
            Ok(bytes) => report.warning(
                name,
                start,
                format!("{bytes} bytes below recommended {minimum}"),
                fix,
            ),
            Err(error) => report.warning(name, start, error, fix),
        }
    }
    let start = Instant::now();
    let llama_path = args
        .llama_server
        .clone()
        .or_else(|| std::env::var_os("CODE_DIVER_LLAMA_SERVER").map(Into::into))
        .or_else(|| {
            runtime
                .as_ref()
                .and_then(|(config, _)| config.llama_server.clone())
        })
        .unwrap_or_else(|| "llama-server".into());
    let llama = command_text(&llama_path, &["--version"]).and_then(|version| {
        let build = regex::Regex::new(r"(?m)(?:version:\s*|build:\s*|\bb)(\d+)")
            .unwrap()
            .captures(&version)
            .and_then(|c| c[1].parse::<u64>().ok())
            .ok_or("Cannot identify llama-server build".to_string())?;
        if build < MIN_LLAMA_BUILD {
            return Err(format!(
                "llama-server build {build} older than {MIN_LLAMA_BUILD}"
            ));
        }
        Ok(format!("llama-server build {build}"))
    });
    report.record(
        "llama_server",
        start,
        llama,
        "Install a current llama.cpp build; use --llama-server PATH if not on PATH",
    );
    if let Ok(metadata) = &metadata {
        let models_dir = args
            .models_dir
            .clone()
            .or_else(|| std::env::var_os("CODE_DIVER_MODELS_DIR").map(Into::into))
            .or_else(|| runtime.as_ref().map(|(_, paths)| paths.models.clone()))
            .or_else(|| {
                std::env::var_os("HOME")
                    .map(|home| std::path::PathBuf::from(home).join(".cache/code-diver/models"))
            });
        if let Some(warning) = metadata.prefix_warning(&config) {
            report.warning(
                "embedding_prefixes",
                Instant::now(),
                warning,
                "Remove explicit prefix overrides for production searches",
            );
        }
        for (name, model, hash) in [
            (
                "embedding_model_file",
                metadata.embedding.extra.get("model_file"),
                metadata.embedding.extra.get("sha256"),
            ),
            (
                "reranker_model_file",
                metadata.extra.get("reranker").and_then(|v| v.get("gguf")),
                metadata.extra.get("reranker").and_then(|v| v.get("sha256")),
            ),
        ] {
            let start = Instant::now();
            if let (Some(file), Some(hash)) = (
                model.and_then(|v| v.as_str()),
                hash.and_then(|v| v.as_str()),
            ) {
                let result = models_dir
                    .as_ref()
                    .ok_or("Model cache unavailable".into())
                    .and_then(|directory| {
                        let filename = Path::new(file);
                        if filename.components().count() != 1 {
                            return Err("Invalid model manifest filename".into());
                        }
                        verify_hash(&directory.join(filename), hash, None)
                    });
                report.record(name, start, result, "Place the manifest model in ~/.cache/code-diver/models/ and verify its SHA-256");
            } else {
                report.warning(
                    name,
                    start,
                    "Model filename/hash absent from index metadata; cannot verify local model"
                        .into(),
                    "Supply a complete model manifest in index metadata",
                );
            }
        }
    }
    for (name, path, load) in [
        ("catalog", config.catalog_path.as_str(), 0),
        ("graph", config.graph_path.as_str(), 1),
        ("meta_ranker", config.ce_meta_model_path.as_str(), 2),
    ] {
        let start = Instant::now();
        let result = match load {
            0 => crate::catalog::load_catalog(Path::new(path))
                .map(|c| format!("{} items", c.items.len())),
            1 => crate::graph::load_graph_adjacency(Path::new(path))
                .map(|g| format!("{} nodes", g.edges.len())),
            _ => crate::lightgbm::load_lightgbm_txt(Path::new(path))
                .map(|m| format!("{} trees", m.num_trees)),
        }
        .map_err(|_| format!("{name} is missing or cannot be loaded"));
        report.record(
            name,
            start,
            result,
            "Supply a valid artifact via --catalog, --graph or --model",
        );
        if let Ok(metadata) = &metadata {
            let manifest = if name == "meta_ranker" {
                metadata.extra.get("meta_ranker")
            } else {
                metadata.extra.get("files").and_then(|files| {
                    Path::new(path)
                        .file_name()
                        .and_then(|filename| filename.to_str())
                        .and_then(|filename| files.get(filename))
                })
            };
            if let Some(manifest) = manifest {
                let start = Instant::now();
                let result = manifest["sha256"]
                    .as_str()
                    .ok_or("Artifact manifest has no SHA-256".to_string())
                    .and_then(|hash| {
                        verify_hash(Path::new(path), hash, manifest["bytes"].as_u64())
                    });
                report.record(
                    &format!("{name}_integrity"),
                    start,
                    result,
                    "Fetch artifacts matching index-metadata.json; do not mix snapshots",
                );
            }
        }
    }
    let start = Instant::now();
    let clients = (|| {
        let q = index_net::client(
            &config.qdrant_api_key,
            &config.qdrant_bearer,
            config.ca_bundle.as_deref(),
            config.insecure_skip_verify,
            config.ce_timeout_ms,
        )?;
        let e = index_net::client(
            &Default::default(),
            &config.embedding_api_key,
            config.ca_bundle.as_deref(),
            config.insecure_skip_verify,
            config.ce_timeout_ms,
        )?;
        let ce = index_net::client(
            &Default::default(),
            &config.ce_api_key,
            config.ca_bundle.as_deref(),
            config.insecure_skip_verify,
            config.ce_timeout_ms,
        )?;
        Ok::<_, String>((q, e, ce))
    })();
    let (q, e, ce) = match clients {
        Ok(clients) => clients,
        Err(error) => {
            report.record(
                "transport",
                start,
                Err(error),
                "Check credential headers and --ca-bundle",
            );
            return report.output(json_output);
        }
    };
    let base = config.qdrant_url.trim_end_matches('/');
    let start = Instant::now();
    let reachable = async {
        index_net::json(
            index_net::request(
                &q,
                reqwest::Method::GET,
                &format!("{base}/collections"),
                None,
            )
            .await?,
        )
        .await?;
        Ok("Qdrant accepted configured credentials".into())
    }
    .await;
    report.record(
        "qdrant",
        start,
        reachable,
        "Check Qdrant endpoint, read-only key and TLS trust",
    );
    let start = Instant::now();
    let dimensions =
        crate::index_update::collection_dimensions(&q, base, &config.qdrant_collection).await;
    report.record(
        "collection",
        start,
        dimensions
            .as_ref()
            .map_err(|_| "Collection missing or vector schema invalid".to_string())
            .and_then(|n| {
                if config
                    .embedding_dimensions
                    .is_some_and(|expected| expected != *n)
                {
                    Err("Collection vector size differs from configured metadata".into())
                } else {
                    Ok(format!("{n} dimensions"))
                }
            }),
        "Set --qdrant-collection to an existing compatible collection",
    );
    let start = Instant::now();
    let stored = async {
        let data = index_net::json(
            index_net::request(
                &q,
                reqwest::Method::POST,
                &format!(
                    "{base}/collections/{}/points/scroll",
                    config.qdrant_collection
                ),
                Some(&json!({"limit":1,"with_payload":true,"with_vector":false})),
            )
            .await?,
        )
        .await?;
        let point = data["result"]["points"]
            .as_array()
            .and_then(|points| points.first())
            .ok_or("Collection has no stored model payload to verify")?;
        if point["payload"]["model"].as_str() != Some(config.embedding_model.as_str()) {
            return Err("Stored payload embedding model mismatch".into());
        }
        if let Ok(size) = dimensions
            && point["payload"]["dimensions"].as_u64() != Some(size as u64)
        {
            return Err("Stored payload dimensions mismatch".into());
        }
        Ok("Stored model and dimensions match".into())
    }
    .await;
    report.record(
        "stored_embedding_profile",
        start,
        stored,
        "Select the matching model/index; reindex into a new collection for migration",
    );
    let start = Instant::now();
    let vector = async {
        let (input, _) =
            crate::pipeline::prepare_embedding_query(&config, "code search health probe")?;
        let data = index_net::embedding_request(
            &e,
            &config.embedding_url,
            &json!({"model":config.embedding_model,"input":input,"encoding_format":"float"}),
        )
        .await?;
        let vector: Vec<f64> = data["data"][0]["embedding"]
            .as_array()
            .ok_or("Missing embedding vector")?
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
        let norm = vector.iter().map(|v| v * v).sum::<f64>().sqrt();
        if (norm - 1.0).abs() > NORM_TOLERANCE {
            return Err("Embedding is not unit normalized".into());
        }
        if let Ok(size) = dimensions
            && size != vector.len()
        {
            return Err(format!(
                "Embedder dimension {} differs from collection {size}",
                vector.len()
            ));
        }
        let expected = config
            .embedding_dimensions
            .or_else(|| metadata.as_ref().ok().map(|m| m.embedding.dimensions));
        if expected.is_some_and(|size| size != vector.len()) {
            return Err("Embedder dimensions differ from configured metadata".into());
        }
        Ok(format!("{} dimensions; unit norm", vector.len()))
    }
    .await;
    report.record(
        "embedding",
        start,
        vector,
        "Use the index embedding model/dimension and enable normalization",
    );
    let options = crate::embedding::CeOptions {
        route_mode: config.ce_route.clone(),
        timeout_ms: config.ce_timeout_ms,
        model: config.ce_model.clone(),
    };
    for (name, document) in [
        ("rerank_short", "fn health() {}".into()),
        ("rerank_long", "token ".repeat(LONG_PAIR_WORDS)),
    ] {
        let start = Instant::now();
        let result = crate::embedding::ce_rerank_with_options(
            &ce,
            &config.ce_url,
            &options,
            "find health",
            &[document],
        )
        .await
        .map(|_| "Reranker returned a valid score".into());
        report.record(name, start, result, "Check reranker; llama-server: --embedding --reranking --pooling rank --ctx-size 4096 --batch-size 4096 --ubatch-size 4096 (physical batch and ubatch must both be >=4096); retain the model manifest's tested serving/parallel settings");
        if !config.require_rerank
            && let Some(check) = report.checks.last_mut()
            && check.status == "FAIL"
        {
            check.status = "WARN";
        }
    }
    report.output(json_output)
}

async fn runtime_checks(
    report: &mut Report,
    args: &SearchArgs,
    config: &crate::runtime_config::RuntimeConfig,
    paths: &crate::runtime_config::RuntimePaths,
    skip_registration: bool,
) {
    let start = Instant::now();
    let source = config.profile.model_manifest_source();
    let manifest = match source {
        Err(error) => Err(error),
        Ok(source) => match args.model_manifest.as_deref().or(source) {
            Some(source) => crate::model_store::load_manifest(source).await,
            None => crate::model_store::ModelManifest::embedded(),
        },
    };
    report.record(
        "model_manifest",
        start,
        manifest
            .as_ref()
            .map(|_| "Model manifest valid".into())
            .map_err(|e| e.to_string()),
        "Use setup or --model-manifest with a valid model manifest",
    );
    if let Ok(manifest) = manifest {
        let directory = args
            .models_dir
            .clone()
            .or_else(|| std::env::var_os("CODE_DIVER_MODELS_DIR").map(Into::into))
            .unwrap_or_else(|| paths.models.clone());
        for (name, spec) in [
            ("runtime_embedding_model_file", &manifest.models.embedder),
            ("runtime_reranker_model_file", &manifest.models.reranker),
        ] {
            let start = Instant::now();
            let result = crate::model_store::verify_model(&directory.join(&spec.file), spec)
                .map_err(|e| e.to_string())
                .and_then(|verification| {
                    if verification == crate::model_store::Verification::Valid {
                        Ok("Model size and SHA-256 verified".into())
                    } else {
                        Err("Model missing or integrity verification failed".into())
                    }
                });
            report.record(
                name,
                start,
                result,
                "Run code-diver setup to repair the model cache",
            );
        }
    } else {
        for name in [
            "runtime_embedding_model_file",
            "runtime_reranker_model_file",
        ] {
            report.record(
                name,
                Instant::now(),
                Err("Cannot verify model without a valid manifest".into()),
                "Repair the model manifest and run code-diver setup",
            );
        }
    }
    let start = Instant::now();
    let health = async {
        let client = reqwest::Client::builder()
            .no_proxy()
            .timeout(std::time::Duration::from_secs(5))
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .map_err(|_| "Cannot initialize daemon health client".to_string())?;
        let response = client
            .get(format!("{}/health", config.daemon_url()))
            .send()
            .await
            .map_err(|_| "Local daemon unreachable".to_string())?;
        if !response.status().is_success() {
            return Err("Local daemon health check failed".into());
        }
        let health: serde_json::Value = response
            .json()
            .await
            .map_err(|_| "Invalid daemon health response".to_string())?;
        if health
            .get("status")
            .and_then(|v| v.as_str())
            .is_some_and(|s| !matches!(s, "ok" | "healthy" | "ready"))
            || health.get("healthy").and_then(|v| v.as_bool()) == Some(false)
        {
            return Err("Local daemon reports unhealthy".into());
        }
        Ok("Local daemon reachable".into())
    }
    .await;
    report.record(
        "daemon",
        start,
        health,
        "Run code-diver daemon or re-run setup",
    );
    if skip_registration {
        report.record(
            "mcp_hosts",
            Instant::now(),
            Ok("Skipped by setup --no-register".into()),
            "Run code-diver setup without --no-register to register detected MCP hosts",
        );
        report.checks.last_mut().unwrap().status = "SKIP";
        return;
    }
    let start = Instant::now();
    let registration = std::env::current_exe()
        .map_err(|_| "Cannot locate code-diver binary".to_string())
        .and_then(|binary| {
            let config_path = args
                .config
                .clone()
                .or_else(|| std::env::var_os("CODE_DIVER_CONFIG").map(Into::into))
                .unwrap_or_else(|| paths.config_file());
            let config_path = if config_path.is_absolute() {
                config_path
            } else {
                std::env::current_dir()
                    .map_err(|_| "Cannot resolve MCP config path".to_string())?
                    .join(config_path)
            };
            crate::runtime_registration(paths, &binary, &config_path, true)
                .and_then(|registration| registration.doctor())
                .map_err(|_| "Cannot inspect MCP host registrations".to_string())
        });
    match registration {
        Ok(registration) => {
            for host in registration.hosts.iter().filter(|host| host.detected) {
                report.record(
                    &format!("mcp_{:?}", host.host),
                    start,
                    if host.registered && host.problem.is_none() {
                        Ok("MCP registration present".into())
                    } else {
                        Err("MCP registration missing or invalid".into())
                    },
                    "Run code-diver setup to register detected MCP hosts",
                );
            }
            if registration.detected_hosts().is_empty() {
                report.warning(
                    "mcp_hosts",
                    start,
                    "No MCP hosts detected".into(),
                    "Install an MCP host then re-run setup",
                );
            }
        }
        Err(error) => report.record(
            "mcp_hosts",
            start,
            Err(error),
            "Check MCP host configuration permissions",
        ),
    }
}

fn command_text(path: &Path, args: &[&str]) -> Result<String, String> {
    let output = std::process::Command::new(path)
        .args(args)
        .output()
        .map_err(|_| "Health probe command unavailable".to_string())?;
    if !output.status.success() {
        return Err("Health probe command failed".into());
    }
    Ok(format!(
        "{}{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    ))
}

fn disk_bytes(path: &Path) -> Result<u64, String> {
    let mut parent = path;
    while !parent.exists() {
        parent = parent
            .parent()
            .filter(|p| !p.as_os_str().is_empty())
            .unwrap_or_else(|| Path::new("."));
    }
    let output = command_text(
        Path::new("df"),
        &["-Pk", parent.to_str().ok_or("Invalid artifact path")?],
    )?;
    output
        .lines()
        .last()
        .and_then(|line| line.split_whitespace().nth(3))
        .and_then(|value| value.parse::<u64>().ok())
        .and_then(|n| n.checked_mul(1024))
        .ok_or("Cannot determine free disk space".into())
}

fn ram_bytes() -> Result<u64, String> {
    if cfg!(target_os = "macos") {
        command_text(Path::new("sysctl"), &["-n", "hw.memsize"])?
            .trim()
            .parse()
            .map_err(|_| "Cannot determine physical RAM".into())
    } else {
        std::fs::read_to_string("/proc/meminfo")
            .ok()
            .and_then(|text| {
                text.lines()
                    .find(|line| line.starts_with("MemTotal:"))
                    .map(str::to_owned)
            })
            .and_then(|line| line.split_whitespace().nth(1)?.parse::<u64>().ok())
            .and_then(|n| n.checked_mul(1024))
            .ok_or("Cannot determine physical RAM".into())
    }
}

fn verify_hash(path: &Path, expected: &str, bytes: Option<u64>) -> Result<String, String> {
    use sha2::{Digest, Sha256};
    use std::io::Read;
    let mut file = std::fs::File::open(path).map_err(|_| "Manifest file missing or unreadable")?;
    if let Some(bytes) = bytes
        && file.metadata().map_err(|_| "Cannot read file size")?.len() != bytes
    {
        return Err("Manifest file size mismatch".into());
    }
    let mut hasher = Sha256::new();
    let mut buffer = [0u8; 65536];
    loop {
        let count = file
            .read(&mut buffer)
            .map_err(|_| "Cannot read manifest file")?;
        if count == 0 {
            break;
        }
        hasher.update(&buffer[..count]);
    }
    if format!("{:x}", hasher.finalize()).eq_ignore_ascii_case(expected) {
        Ok("Manifest SHA-256 verified".into())
    } else {
        Err("Manifest SHA-256 mismatch".into())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn integrity_checks_reject_corruption_wrong_size_and_missing_files() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("artifact");
        let hash = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";
        assert!(verify_hash(&path, hash, None).is_err());
        std::fs::write(&path, "abc").unwrap();
        assert!(verify_hash(&path, hash, Some(3)).is_ok());
        assert!(
            verify_hash(&path, hash, Some(4))
                .unwrap_err()
                .contains("size mismatch")
        );
        std::fs::write(&path, "abd").unwrap();
        assert!(
            verify_hash(&path, hash, Some(3))
                .unwrap_err()
                .contains("SHA-256 mismatch")
        );
    }
}
