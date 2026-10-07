mod bm25;
mod catalog;
mod catalog_builder;
mod daemon;
mod doctor;
mod embedding;
mod features;
mod fusion;
mod graph;
mod index_net;
mod index_update;
mod indexing;
pub mod info;
mod inspection;
mod lightgbm;
pub mod mcp;
pub mod mcp_registration;
mod metadata;
mod model_store;
mod pipeline;
pub mod runtime_config;
mod service_manager;
pub mod setup;
mod types;
pub mod update_index;

use std::fs;
use std::path::{Path, PathBuf};
use std::time::Instant;

use clap::Parser;

use crate::pipeline::{
    SearchTimings, dump_features, dump_features_batch, init_search_context, search,
};
use crate::types::{SearchConfig, resolve_candidate_limit, resolve_second_pass};

#[derive(Parser, Debug)]
#[command(
    name = "code-diver",
    version,
    about = "Pure Rust search pipeline for code-diver",
    args_conflicts_with_subcommands = true
)]
pub struct Cli {
    #[command(subcommand)]
    pub command: Option<Commands>,

    #[command(flatten)]
    pub search: SearchArgs,
}

#[derive(clap::Subcommand, Debug, Clone)]
pub enum Commands {
    /// Configure local models, runtime, shared index and MCP hosts
    Setup(SetupArgs),
    /// Run the loopback-only local model runtime
    Daemon(DaemonArgs),
    /// Fetch and verify shared index artifacts atomically
    UpdateIndex(UpdateIndexArgs),
    /// Print effective configuration with service secrets redacted
    Config {
        #[command(subcommand)]
        command: ConfigCommand,
    },
    /// Read sandboxed numbered lines
    Read(ReadArgs),
    /// Search repository text
    Grep(GrepArgs),
    /// Render a repository tree
    Tree(TreeArgs),
    /// List source symbols
    Symbols(SymbolsArgs),
    /// Build a catalog without contacting any services
    Index(catalog_builder::cli::IndexArgs),

    /// Compare catalogs by ID and content
    CatalogCompare(catalog_builder::cli::CompareArgs),
    /// Pure Rust search pipeline
    Search(SearchArgs),

    /// Display index, graph, and vector store overview
    Info(InfoArgs),

    /// Run dependency health checks (Qdrant, embedding service, CE)
    Doctor(DoctorArgs),

    /// Start Model Context Protocol (MCP) stdio server
    Mcp(McpArgs),
}

#[derive(clap::Args, Debug, Clone)]
pub struct InfoArgs {
    #[arg(long)]
    pub config: Option<PathBuf>,
    #[arg(long)]
    pub root: Option<PathBuf>,
    #[arg(long, default_value = "")]
    pub qdrant_collection: String,
    #[arg(long)]
    pub model: Option<String>,
    #[arg(long)]
    pub json: bool,
    /// Path to catalog JSONL file (defaults to ./artifacts/rust_catalog.jsonl or /tmp/rust_catalog.jsonl)
    #[arg(short = 'c', long)]
    pub catalog: Option<String>,

    /// Path to graph adjacency JSONL file (defaults to ./artifacts/rust_graph.jsonl or /tmp/rust_graph.jsonl)
    #[arg(short = 'g', long)]
    pub graph: Option<String>,

    /// Qdrant service URL
    #[arg(short = 'd', long, default_value = "http://localhost:6333")]
    pub qdrant_url: String,
}

#[derive(clap::Args, Debug, Clone)]
pub struct RuntimeArgs {
    #[arg(long)]
    pub config: Option<PathBuf>,
    #[arg(long)]
    pub llama_server: Option<PathBuf>,
    #[arg(long, alias = "daemon-port")]
    pub port: Option<u16>,
    #[arg(long)]
    pub threads: Option<usize>,
    #[arg(long)]
    pub idle_timeout_secs: Option<u64>,
    #[arg(long)]
    pub request_timeout_secs: Option<u64>,
    #[arg(long)]
    pub reranker_ctx: Option<usize>,
    #[arg(long)]
    pub embedder_ctx: Option<usize>,
    #[arg(long)]
    pub embedder_batch: Option<usize>,
    #[arg(long)]
    pub embedder_ubatch: Option<usize>,
    #[arg(long)]
    pub batch: Option<usize>,
    #[arg(long)]
    pub ubatch: Option<usize>,
    #[arg(long)]
    pub model_manifest: Option<String>,
    #[arg(long)]
    pub qdrant_url: Option<String>,
    #[arg(long)]
    pub collection: Option<String>,
    #[arg(long)]
    pub artifact_url: Option<String>,
    #[arg(long)]
    pub index_name: Option<String>,
}

#[derive(clap::Args, Debug, Clone)]
pub struct SetupArgs {
    #[command(flatten)]
    pub runtime: RuntimeArgs,
    #[arg(long)]
    pub profile: Option<String>,
    #[arg(long)]
    pub no_register: bool,
    #[arg(long)]
    pub uninstall: bool,
    #[arg(long, requires = "uninstall")]
    pub purge: bool,
    #[arg(long)]
    pub yes: bool,
    #[arg(long)]
    pub dry_run: bool,
    #[arg(long)]
    pub key_file: Option<PathBuf>,
}

#[derive(clap::Args, Debug, Clone)]
pub struct DaemonArgs {
    #[command(flatten)]
    pub runtime: RuntimeArgs,
    #[arg(long)]
    pub foreground: bool,
}

#[derive(clap::Args, Debug, Clone)]
pub struct UpdateIndexArgs {
    #[command(flatten)]
    pub runtime: RuntimeArgs,
    #[arg(long)]
    pub dry_run: bool,
}

#[derive(clap::Args, Debug, Clone)]
pub struct DoctorArgs {
    #[command(flatten)]
    pub search: SearchArgs,
    #[arg(long)]
    pub json: bool,
}

#[derive(clap::Subcommand, Debug, Clone)]
pub enum ConfigCommand {
    Show(SearchArgs),
}

#[derive(clap::Args, Debug, Clone)]
pub struct McpArgs {
    #[arg(long, default_value_t = 2)]
    pub max_concurrent_searches: usize,
    #[command(flatten)]
    pub search: SearchArgs,
}

#[derive(clap::Args, Debug, Clone)]
pub struct SearchArgs {
    #[arg(long)]
    pub daemon_port: Option<u16>,
    #[arg(long)]
    pub threads: Option<usize>,
    #[arg(long, num_args = 0..=1, default_missing_value = "true", require_equals = true)]
    pub autostart: Option<bool>,
    /// Override the runtime model manifest (local file or HTTPS URL)
    #[arg(long)]
    pub model_manifest: Option<String>,
    /// Fail rather than return degraded results on any reranker failure
    #[arg(long, num_args = 0..=1, default_missing_value = "true", require_equals = true)]
    pub require_rerank: Option<bool>,
    /// Allow degraded results when reranking is unavailable
    #[arg(long, conflicts_with = "require_rerank")]
    pub no_require_rerank: bool,
    /// llama-server executable used by doctor build checks
    #[arg(long)]
    pub llama_server: Option<PathBuf>,
    /// Local model cache used by doctor (default ~/.cache/code-diver/models)
    #[arg(long)]
    pub models_dir: Option<PathBuf>,
    #[arg(long)]
    pub root: Option<PathBuf>,
    #[arg(long)]
    pub config: Option<PathBuf>,
    #[arg(long)]
    pub embedding_model: Option<String>,
    #[arg(long)]
    pub embedding_query_prefix: Option<String>,
    #[arg(long)]
    pub embedding_document_prefix: Option<String>,
    #[arg(long)]
    pub embedding_dimensions: Option<usize>,
    #[arg(long)]
    pub index_metadata: Option<PathBuf>,
    #[arg(long)]
    pub qdrant_api_key: Option<index_net::Secret>,
    #[arg(long)]
    pub qdrant_bearer: Option<index_net::Secret>,
    #[arg(long)]
    pub embedding_api_key: Option<index_net::Secret>,
    #[arg(long)]
    pub ce_api_key: Option<index_net::Secret>,
    #[arg(long)]
    pub ca_bundle: Option<String>,
    #[arg(long)]
    pub insecure_skip_verify: bool,
    /// Query to search for
    #[arg(short, long)]
    pub query: Option<String>,

    /// Positional query fallback (e.g. `code-diver-search "where is foo"`)
    #[arg(value_name = "QUERY")]
    pub query_pos: Option<String>,

    /// Number of results to return
    #[arg(short, long, default_value = "10")]
    pub limit: usize,

    /// Path to catalog JSONL file (defaults to ./artifacts/rust_catalog.jsonl or /tmp/rust_catalog.jsonl)
    #[arg(short = 'c', long)]
    pub catalog: Option<String>,

    /// Path to graph adjacency JSONL file (defaults to ./artifacts/rust_graph.jsonl or /tmp/rust_graph.jsonl)
    #[arg(short = 'g', long)]
    pub graph: Option<String>,

    /// Path to LightGBM meta-ranker model (TXT format, defaults to ./artifacts/ce_meta_ranker/ce_meta_ranker.lgb.txt)
    #[arg(short = 'm', long)]
    pub model: Option<String>,

    /// Embedding service URL
    #[arg(short = 'e', long)]
    pub embedding_url: Option<String>,

    /// Qdrant service URL
    #[arg(short = 'd', long)]
    pub qdrant_url: Option<String>,

    /// CE rerank service URL
    #[arg(short = 'r', long)]
    pub ce_url: Option<String>,

    /// Optional second-pass CE URL (mixed routing, e.g. vLLM-metal for long
    /// docs). Empty (default) = reuse --ce-url for both passes.
    #[arg(long)]
    pub second_ce_url: Option<String>,

    /// CE rerank route mode: auto (use --ce-url, fall back v1<->legacy on 404/405),
    /// v1 (force .../v1/rerank), legacy (force .../rerank)
    #[arg(long)]
    pub ce_route: Option<String>,

    /// Per-request CE timeout in ms (Python CrossEncoderRerankConfig.timeout_ms parity)
    #[arg(long)]
    pub ce_timeout_ms: Option<u64>,

    /// Optional CE `model` body field (empty = omit; llama.cpp scores with the
    /// loaded model, vLLM-metal pooling with the served one)
    #[arg(long)]
    pub ce_model: Option<String>,

    /// Vector weight in H-91a manual fusion
    #[arg(long, default_value_t = 0.42)]
    pub vector_weight: f64,

    /// Lexical (BM25) weight in H-91a manual fusion
    #[arg(long, default_value_t = 0.26)]
    pub lexical_weight: f64,

    /// Path coverage weight in H-91a manual fusion
    #[arg(long, default_value_t = 0.12)]
    pub path_weight: f64,

    /// Symbol coverage weight in H-91a manual fusion
    #[arg(long, default_value_t = 0.10)]
    pub symbol_weight: f64,

    /// Graph propagation weight in H-91a manual fusion
    #[arg(long, default_value_t = 0.0)]
    pub graph_weight: f64,

    /// Symbol match weight in fusion
    #[arg(long, default_value_t = 0.10)]
    pub symbol_match_weight: f64,

    /// File vote weight in fusion
    #[arg(long, default_value_t = 0.06)]
    pub file_vote_weight: f64,

    /// Max NEW lexical (BM25-only) candidates admitted per query (H-91a: 1000)
    #[arg(long, default_value_t = 1000)]
    pub lexical_candidate_limit: usize,

    /// Rank CE candidates by raw logit instead of provider probability
    /// (Python default: false)
    #[arg(long, action = clap::ArgAction::SetTrue)]
    pub rank_by_raw_logits: bool,

    /// Break near-ties in CE scores by the fused base score (Python default: false)
    #[arg(long, action = clap::ArgAction::SetTrue)]
    pub tie_break_by_fused_score: bool,

    /// Tie width for --tie-break-by-fused-score (Python default: 1e-4)
    #[arg(long, default_value_t = 1e-4)]
    pub tie_break_epsilon: f64,

    /// Candidate limit for CE rerank (first pass window)
    #[arg(long)]
    pub candidate_limit: Option<usize>,

    /// Conservative embedding query token budget, including the prefix
    #[arg(long)]
    pub embedding_query_token_budget: Option<usize>,

    /// Alias for --candidate-limit: first-pass CE window size (1..=512).
    /// When present, wins over --candidate-limit.
    #[arg(long)]
    pub first_pass_cap: Option<usize>,

    /// Second-pass candidate cap (default 24, 0 = uncapped).
    /// Explicit value overrides --preset.
    #[arg(long)]
    pub second_pass_cap: Option<usize>,

    /// Second-pass score floor in [0.0, 1.0] (default 0.3).
    /// Explicit value overrides --preset.
    #[arg(long)]
    pub second_pass_floor: Option<f64>,

    /// Disable the selective second CE pass entirely.
    #[arg(long, default_value_t = false)]
    pub second_pass_disable: bool,

    /// Latency preset. Currently supported: "selective-strict"
    /// (second-pass cap 8, floor 0.15). No preset by default.
    #[arg(long)]
    pub preset: Option<String>,

    /// In-memory embedding cache size (number of query vectors, server mode).
    /// Default is 1024 (0 = disabled).
    #[arg(long, default_value_t = 1024)]
    pub embed_cache_size: usize,

    /// Vector retrieval width before file selection and CE rerank
    #[arg(long, default_value = "360")]
    pub retrieval_limit: usize,

    /// Document truncation character limit for first-pass CE (default: 850)
    #[arg(long, default_value = "850")]
    pub max_document_chars: usize,

    /// Document truncation character limit for second-pass CE (default: 2400)
    #[arg(long, default_value = "2400")]
    pub second_pass_max_document_chars: usize,

    /// Run in server mode (read queries from stdin)
    #[arg(short = 's', long)]
    pub server: bool,

    /// Benchmark mode: run N queries from a file
    #[arg(short = 'b', long)]
    pub bench: Option<String>,

    /// Number of benchmark queries to run
    #[arg(long, default_value = "20")]
    pub bench_n: usize,

    /// Dump features for training (outputs JSONL with 16 features per candidate)
    #[arg(long)]
    pub dump_features: bool,

    /// Expected paths (comma-separated) for label computation in dump_features mode
    #[arg(long)]
    pub expected: Option<String>,

    /// Query ID for dump_features output
    #[arg(long)]
    pub query_id: Option<String>,

    /// Dump features from a JSONL file (batch mode, much faster than per-query)
    #[arg(long)]
    pub dump_features_file: Option<String>,

    /// Quality mode: run queries from a JSONL file and output per-query results
    #[arg(long)]
    pub quality: Option<String>,

    /// Base path for reading file content (default: use catalog content)
    #[arg(long)]
    pub base_path: Option<String>,

    /// Incremental index update: diff --catalog against the Qdrant collection
    /// and report added/changed/deleted counts (dry run by default).
    #[arg(long)]
    pub index_update: bool,

    /// Apply the incremental index update (embed + upsert dirty items,
    /// delete removed points). Without it, --index-update only reports.
    #[arg(long)]
    pub apply: bool,

    /// Qdrant collection (or alias) for --index-update.
    #[arg(long, default_value = "")]
    pub qdrant_collection: String,

    /// Character budget for index-update embed texts (H-66b/H-91a: 500).
    #[arg(long, default_value_t = 500)]
    pub embed_max_chars: usize,

    /// Healthcheck / Doctor mode: checks connection to Qdrant, Embedding, and CE services,
    /// verifies catalog, graph, and model paths, then exits.
    #[arg(long)]
    pub doctor: bool,
}

impl SearchArgs {
    pub fn resolved_query(&self) -> Option<String> {
        self.query.clone().or_else(|| self.query_pos.clone())
    }
}

pub type Args = SearchArgs;

#[derive(clap::Args, Debug, Clone)]
pub struct InspectionArgs {
    #[arg(long)]
    pub root: Option<PathBuf>,
    #[arg(long)]
    pub config: Option<PathBuf>,
    #[arg(long)]
    pub json: bool,
}

#[derive(clap::Args, Debug, Clone)]
pub struct ReadArgs {
    pub file: String,
    #[arg(long, default_value_t = 1)]
    pub start_line: usize,
    #[arg(long, default_value_t = 100)]
    pub lines: usize,
    #[command(flatten)]
    pub common: InspectionArgs,
}

#[derive(clap::Args, Debug, Clone)]
pub struct GrepArgs {
    pub pattern: String,
    #[arg(long)]
    pub path: Option<String>,
    #[arg(long, default_value_t = 50)]
    pub limit: usize,
    #[arg(long)]
    pub regex: bool,
    #[command(flatten)]
    pub common: InspectionArgs,
}

#[derive(clap::Args, Debug, Clone)]
pub struct TreeArgs {
    pub path: Option<String>,
    #[arg(long, default_value_t = 3)]
    pub depth: usize,
    #[arg(long, default_value_t = 100)]
    pub limit: usize,
    #[command(flatten)]
    pub common: InspectionArgs,
}

#[derive(clap::Args, Debug, Clone)]
pub struct SymbolsArgs {
    pub path: Option<String>,
    #[arg(long, default_value_t = 200)]
    pub limit: usize,
    #[command(flatten)]
    pub common: InspectionArgs,
}

fn inspection_root(root: Option<&Path>, config: Option<&Path>) -> Result<PathBuf, String> {
    let config = config
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("CODE_DIVER_CONFIG").map(PathBuf::from));
    let remote = indexing::remote_config(config.as_deref())?;
    Ok(indexing::configured_path(
        root,
        "ROOT",
        &remote["root"],
        config.as_deref(),
        Path::new("."),
    ))
}

fn run_inspection_cli(
    tool: &str,
    common: &InspectionArgs,
    mut args: serde_json::Value,
) -> Result<(), String> {
    if let Some(object) = args.as_object_mut() {
        object.retain(|_, value| !value.is_null());
    }
    let root = inspection_root(common.root.as_deref(), common.config.as_deref())?;
    let result = inspection::call(&root, tool, &args).map_err(|e| e.to_string())?;
    if common.json {
        println!(
            "{}",
            serde_json::to_string_pretty(&result).map_err(|e| e.to_string())?
        );
    } else if let Some(content) = result["content"].as_array() {
        for item in content {
            if let Some(text) = item["text"].as_str() {
                if tool == "code_diver_symbols" {
                    let symbols: Vec<serde_json::Value> =
                        serde_json::from_str(text).map_err(|e| e.to_string())?;
                    for symbol in symbols {
                        println!(
                            "{}:{}: {} {} - {}",
                            symbol["path"].as_str().ok_or("Missing symbol path")?,
                            symbol["startLine"]
                                .as_u64()
                                .ok_or("Missing symbol startLine")?,
                            symbol["kind"].as_str().ok_or("Missing symbol kind")?,
                            symbol["name"].as_str().ok_or("Missing symbol name")?,
                            symbol["signature"]
                                .as_str()
                                .ok_or("Missing symbol signature")?,
                        );
                    }
                } else {
                    println!("{text}");
                }
            }
        }
    }
    Ok(())
}

async fn configured_info(args: &SearchArgs) -> Result<info::NativeInfo, String> {
    collect_configured_info(
        args.config.as_deref(),
        args.catalog.as_deref(),
        args.graph.as_deref(),
        args.model.as_deref(),
        args.qdrant_url.as_deref(),
        &args.qdrant_collection,
        Some(args),
    )
    .await
}

async fn collect_configured_info(
    config: Option<&Path>,
    catalog: Option<&str>,
    graph: Option<&str>,
    model: Option<&str>,
    url: Option<&str>,
    collection: &str,
    overrides: Option<&SearchArgs>,
) -> Result<info::NativeInfo, String> {
    let config = config
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("CODE_DIVER_CONFIG").map(PathBuf::from));
    let remote = indexing::remote_config(config.as_deref())?;
    let artifact =
        |cli: Option<&str>, env: &str, value: &serde_json::Value, candidates: &[&str]| {
            let path = indexing::configured_path(
                cli.map(Path::new),
                env,
                value,
                config.as_deref(),
                Path::new(""),
            );
            resolve_path(path.to_str().filter(|s| !s.is_empty()), candidates)
        };
    let catalog = artifact(
        catalog,
        "CATALOG",
        &remote["catalog"],
        &[
            ".code-diver/rust_catalog.jsonl",
            "artifacts/rust_catalog.jsonl",
        ],
    );
    let graph = artifact(
        graph,
        "GRAPH",
        &remote["graph_path"],
        &[".code-diver/rust_graph.jsonl", "artifacts/rust_graph.jsonl"],
    );
    let model = artifact(
        model,
        "MODEL",
        &remote["model"],
        &[
            ".code-diver/models/ce_meta_ranker.lgb.txt",
            "artifacts/ce_meta_ranker/ce_meta_ranker.lgb.txt",
        ],
    );
    let url = indexing::setting(
        url,
        "QDRANT_URL",
        None,
        &remote["storage"]["qdrant"]["url"],
        "http://localhost:6333",
    );
    let collection = indexing::setting(
        (!collection.is_empty()).then_some(collection),
        "COLLECTION",
        Some("CODE_DIVER_QDRANT_COLLECTION"),
        &remote["storage"]["qdrant"]["collection"],
        "",
    );
    let q = &remote["storage"]["qdrant"];
    let api_key = indexing::setting(
        overrides.and_then(|a| a.qdrant_api_key.as_ref().map(|s| s.0.as_str())),
        "QDRANT_API_KEY",
        Some(q["api_key_env"].as_str().unwrap_or("QDRANT_API_KEY")),
        &q["api_key"],
        "",
    );
    let bearer = indexing::setting(
        overrides.and_then(|a| a.qdrant_bearer.as_ref().map(|s| s.0.as_str())),
        "QDRANT_BEARER",
        None,
        &q["bearer"],
        "",
    );
    let ca = indexing::configured_path(
        overrides.and_then(|a| a.ca_bundle.as_deref().map(Path::new)),
        "CA_BUNDLE",
        &remote["ca_bundle"],
        config.as_deref(),
        Path::new(""),
    );
    let ca = (!ca.as_os_str().is_empty()).then_some(ca);
    let client = index_net::client(
        &index_net::Secret(api_key),
        &index_net::Secret(bearer),
        ca.as_deref().and_then(Path::to_str),
        overrides.is_some_and(|a| a.insecure_skip_verify)
            || indexing::setting(
                None,
                "INSECURE_SKIP_VERIFY",
                None,
                &remote["insecure_skip_verify"],
                "false",
            )
            .parse::<bool>()
            .map_err(|_| "Invalid TLS verification setting")?,
        2000,
    )?;
    Ok(info::collect_info_with_client(
        catalog.as_deref(),
        graph.as_deref(),
        model.as_deref(),
        &url,
        &collection,
        &client,
    )
    .await)
}

#[tokio::main]
async fn main() -> Result<(), String> {
    let cli = Cli::parse();

    match cli.command {
        Some(Commands::Setup(args)) => run_setup(args).await,
        Some(Commands::Daemon(args)) => {
            let (config, paths) = load_runtime(&args.runtime)?;
            let _lock = RuntimeProcessLock::acquire(&paths, "daemon.pid", None).await?;
            daemon::run(config, paths, args.foreground)
                .await
                .map_err(|e| e.to_string())
        }
        Some(Commands::UpdateIndex(args)) => {
            let (config, paths) = load_runtime(&args.runtime)?;
            let keychain = runtime_config::NativeMacSecurity;
            let outcome = update_index::update_with_options(
                &config,
                &paths,
                update_index::UpdateOptions {
                    dry_run: args.dry_run,
                    model_manifest: args.runtime.model_manifest.as_deref().map(Path::new),
                    keychain: (!paths.isolated)
                        .then_some(&keychain as &dyn runtime_config::MacSecurity),
                },
            )
            .await
            .map_err(|e| e.to_string())?;
            println!(
                "{}: {} files downloaded, {} bytes resumed{}",
                if outcome.changed {
                    "Index changed"
                } else {
                    "Index unchanged"
                },
                outcome.downloaded_files,
                outcome.resumed_bytes,
                if outcome.dry_run { " (dry run)" } else { "" }
            );
            Ok(())
        }
        Some(Commands::Read(args)) => run_inspection_cli(
            "code_diver_read",
            &args.common,
            serde_json::json!({"file":args.file,"start_line":args.start_line,"lines":args.lines}),
        ),
        Some(Commands::Grep(args)) => run_inspection_cli(
            "code_diver_grep",
            &args.common,
            serde_json::json!({"pattern":args.pattern,"path":args.path,"limit":args.limit,"regex":args.regex}),
        ),
        Some(Commands::Tree(args)) => run_inspection_cli(
            "code_diver_tree",
            &args.common,
            serde_json::json!({"path":args.path,"depth":args.depth,"limit":args.limit}),
        ),
        Some(Commands::Symbols(args)) => run_inspection_cli(
            "code_diver_symbols",
            &args.common,
            serde_json::json!({"path":args.path,"limit":args.limit}),
        ),
        Some(Commands::Index(args)) => catalog_builder::cli::run_index(args).await,
        Some(Commands::Config {
            command: ConfigCommand::Show(args),
        }) => {
            if let Some((config, _)) = runtime_for_args(&args)? {
                println!("{}", config.redacted_toml().map_err(|e| e.to_string())?);
                return Ok(());
            }
            let (config, _) = build_search_config_for(&args, false)?;
            let mut effective =
                serde_json::to_value(config).map_err(|_| "Cannot encode configuration")?;
            for key in [
                "qdrant_api_key",
                "qdrant_bearer",
                "embedding_api_key",
                "ce_api_key",
            ] {
                effective[key] = serde_json::json!("[redacted]");
            }
            println!(
                "{}",
                serde_json::to_string_pretty(&effective)
                    .map_err(|_| "Cannot encode configuration")?
            );
            Ok(())
        }
        Some(Commands::CatalogCompare(args)) => catalog_builder::cli::run_compare(args),
        Some(Commands::Doctor(args)) => doctor::run(&args.search, args.json).await,
        Some(Commands::Info(args)) => {
            let info = collect_configured_info(
                args.config.as_deref(),
                args.catalog.as_deref(),
                args.graph.as_deref(),
                args.model.as_deref(),
                (args.qdrant_url != "http://localhost:6333").then_some(args.qdrant_url.as_str()),
                &args.qdrant_collection,
                None,
            )
            .await?;
            println!(
                "{}",
                serde_json::to_string_pretty(&info).map_err(|e| e.to_string())?
            );
            Ok(())
        }
        Some(Commands::Mcp(args)) => run_mcp(args).await,
        Some(Commands::Search(args)) => run_search_cli(args).await,
        None => {
            if cli.search.doctor {
                doctor::run(&cli.search, false).await
            } else if cli.search.index_update {
                run_index_update(&cli.search).await
            } else {
                run_search_cli(cli.search).await
            }
        }
    }
}

pub(crate) fn configured_candidate_limit(args: &SearchArgs) -> Result<usize, String> {
    let path = args
        .config
        .clone()
        .or_else(|| std::env::var_os("CODE_DIVER_CONFIG").map(PathBuf::from));
    let remote = indexing::remote_config(path.as_deref())?;
    let value = indexing::setting(
        args.candidate_limit
            .as_ref()
            .map(|n| n.to_string())
            .as_deref(),
        "CANDIDATE_LIMIT",
        None,
        &remote["search"]["candidate_limit"],
        "34",
    );
    let limit = value
        .parse::<usize>()
        .map_err(|_| "Invalid candidate limit")?;
    resolve_candidate_limit(limit, args.first_pass_cap).map_err(|e| e.to_string())
}

pub(crate) fn runtime_for(
    explicit: Option<&Path>,
) -> Result<Option<(runtime_config::RuntimeConfig, runtime_config::RuntimePaths)>, String> {
    let paths = runtime_config::RuntimePaths::discover().map_err(|e| e.to_string())?;
    let path = explicit
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("CODE_DIVER_CONFIG").map(PathBuf::from))
        .unwrap_or_else(|| paths.config_file());
    if !path.is_file() {
        return Ok(None);
    }
    if path.extension().is_none_or(|ext| ext != "toml") {
        return Ok(None);
    }
    let text = fs::read_to_string(&path).map_err(|_| "Cannot read runtime configuration")?;
    let value: toml::Value = toml::from_str(&text).map_err(|_| "Invalid TOML configuration")?;
    if path != paths.config_file()
        && value.get("daemon").is_none()
        && value.get("schema").is_none()
        && value.get("llama_server").is_none()
    {
        return Ok(None);
    }
    let config = runtime_config::load_config(&path).map_err(|e| e.to_string())?;
    let environment = runtime_config::environment_overrides(|key| std::env::var(key).ok())
        .map_err(|e| e.to_string())?;
    let config = runtime_config::effective_config(config, &environment, &toml::Table::new())
        .map_err(|e| e.to_string())?;
    Ok(Some((config, paths)))
}

fn runtime_flags(args: &RuntimeArgs) -> Result<toml::Table, String> {
    let mut flags = toml::Table::new();
    let mut daemon = toml::Table::new();
    for (key, value) in [
        ("port", args.port.map(u64::from)),
        ("threads", args.threads.map(|v| v as u64)),
        ("idle_timeout_secs", args.idle_timeout_secs),
        ("request_timeout_secs", args.request_timeout_secs),
        ("reranker_ctx", args.reranker_ctx.map(|v| v as u64)),
        ("embedder_ctx", args.embedder_ctx.map(|v| v as u64)),
        ("embedder_batch", args.embedder_batch.map(|v| v as u64)),
        ("embedder_ubatch", args.embedder_ubatch.map(|v| v as u64)),
        ("batch", args.batch.map(|v| v as u64)),
        ("ubatch", args.ubatch.map(|v| v as u64)),
    ] {
        if let Some(value) = value {
            daemon.insert(
                key.into(),
                toml::Value::Integer(value.try_into().map_err(|_| "Runtime setting too large")?),
            );
        }
    }
    flags.insert("daemon".into(), toml::Value::Table(daemon));
    let mut profile = toml::Table::new();
    for (key, value) in [
        ("qdrant_url", &args.qdrant_url),
        ("collection", &args.collection),
        ("artifact_url", &args.artifact_url),
        ("index_name", &args.index_name),
    ] {
        if let Some(value) = value {
            profile.insert(key.into(), toml::Value::String(value.clone()));
        }
    }
    if let Some(source) = &args.model_manifest {
        profile.insert(
            if source.contains("://") {
                "model_manifest_url"
            } else {
                "model_manifest_path"
            }
            .into(),
            toml::Value::String(source.clone()),
        );
    }
    flags.insert("profile".into(), toml::Value::Table(profile));
    if let Some(binary) = &args.llama_server {
        flags.insert(
            "llama_server".into(),
            toml::Value::String(binary.to_string_lossy().into_owned()),
        );
    }
    Ok(flags)
}

fn load_runtime(
    args: &RuntimeArgs,
) -> Result<(runtime_config::RuntimeConfig, runtime_config::RuntimePaths), String> {
    let paths = runtime_config::RuntimePaths::discover().map_err(|e| e.to_string())?;
    let path = args
        .config
        .clone()
        .or_else(|| std::env::var_os("CODE_DIVER_CONFIG").map(PathBuf::from))
        .unwrap_or_else(|| paths.config_file());
    let config = runtime_config::load_config(&path).map_err(|e| e.to_string())?;
    let environment = runtime_config::environment_overrides(|key| std::env::var(key).ok())
        .map_err(|e| e.to_string())?;
    let config = runtime_config::effective_config(config, &environment, &runtime_flags(args)?)
        .map_err(|e| e.to_string())?;
    Ok((config, paths))
}

struct RuntimeSetupHooks<'a> {
    options: &'a setup::SetupOptions,
}
pub(crate) fn runtime_registration(
    paths: &runtime_config::RuntimePaths,
    binary: &Path,
    config: &Path,
    dry_run: bool,
) -> anyhow::Result<mcp_registration::Registration> {
    let mut registration =
        mcp_registration::Registration::new(&paths.hosts, binary, config, dry_run)?;
    if paths.isolated {
        registration.runtime_root = Some(
            paths
                .config
                .parent()
                .ok_or_else(|| anyhow::anyhow!("isolated config has no parent"))?
                .to_path_buf(),
        );
    }
    Ok(registration)
}

impl setup::SetupHooks for RuntimeSetupHooks<'_> {
    fn doctor(&mut self, command: &service_manager::CommandPlan) -> anyhow::Result<bool> {
        if !self.options.no_register {
            return command.execute();
        }
        let cli = Cli::try_parse_from(
            std::iter::once(command.program.as_os_str().to_owned())
                .chain(command.args.iter().map(std::ffi::OsString::from)),
        )?;
        let Some(Commands::Doctor(args)) = cli.command else {
            anyhow::bail!("setup doctor command expected");
        };
        std::thread::spawn(move || {
            let runtime = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()?;
            Ok(runtime
                .block_on(doctor::run_for_setup(&args.search))
                .is_ok())
        })
        .join()
        .map_err(|_| anyhow::anyhow!("setup doctor thread failed"))?
    }

    fn update_index<'a>(
        &'a mut self,
        config: &'a runtime_config::RuntimeConfig,
        paths: &'a runtime_config::RuntimePaths,
    ) -> std::pin::Pin<Box<dyn std::future::Future<Output = anyhow::Result<()>> + 'a>> {
        Box::pin(async move {
            let keychain = runtime_config::NativeMacSecurity;
            let recorder = |created: &[update_index::CreatedArtifact]| {
                record_created_artifacts(self.options, created)
            };
            update_index::update_with_recorder(
                config,
                paths,
                update_index::UpdateOptions {
                    keychain: (!paths.isolated)
                        .then_some(&keychain as &dyn runtime_config::MacSecurity),
                    ..Default::default()
                },
                Some(&recorder),
            )
            .await?;
            Ok(())
        })
    }
}

fn record_created_artifacts(
    options: &setup::SetupOptions,
    created: &[update_index::CreatedArtifact],
) -> anyhow::Result<()> {
    let mut artifacts = Vec::new();
    for artifact in created {
        match &artifact.kind {
            update_index::ArtifactKind::File | update_index::ArtifactKind::Directory => {
                artifacts.push(setup::CreatedArtifact {
                    path: artifact.path.clone(),
                });
            }
            update_index::ArtifactKind::Symlink { target } => {
                setup::track_created_pointer(options, &artifact.path, target)?;
            }
        }
    }
    setup::track_created_artifacts(options, &artifacts)
}

fn read_setup_profile(
    reader: &mut impl std::io::BufRead,
    writer: &mut impl std::io::Write,
) -> Result<String, String> {
    writer
        .write_all(b"Team profile URL or file: ")
        .map_err(|_| "Cannot write profile prompt")?;
    writer.flush().map_err(|_| "Cannot write profile prompt")?;
    let mut line = String::new();
    std::io::BufRead::read_line(&mut std::io::Read::take(reader, 4097), &mut line)
        .map_err(|_| "Cannot read team profile")?;
    if line.len() > 4096 || line.trim().is_empty() {
        return Err("Team profile is required; supply --profile URL-or-file".into());
    }
    Ok(line.trim().to_string())
}

fn prompt_setup_profile() -> Result<String, String> {
    let mut tty = fs::OpenOptions::new().read(true).write(true).open("/dev/tty")
        .map_err(|_| "No interactive terminal; supply --profile URL-or-file (including index_name, artifact_url, qdrant_url and collection)")?;
    let input = tty.try_clone().map_err(|_| "Cannot open profile prompt")?;
    read_setup_profile(&mut std::io::BufReader::new(input), &mut tty)
}

async fn run_setup(args: SetupArgs) -> Result<(), String> {
    let paths = runtime_config::RuntimePaths::discover().map_err(|e| e.to_string())?;
    let platform = if cfg!(target_os = "macos") {
        runtime_config::Platform::MacOs
    } else if cfg!(target_os = "linux") {
        runtime_config::Platform::Linux
    } else {
        return Err("Unsupported runtime platform".into());
    };
    let executable = std::env::current_exe().map_err(|_| "Cannot locate code-diver binary")?;
    #[cfg(unix)]
    let uid = {
        unsafe extern "C" {
            fn getuid() -> u32;
        }
        unsafe { getuid() }
    };
    #[cfg(not(unix))]
    let uid = 0;
    let mut options = setup::SetupOptions::new(paths, executable, platform, uid);
    options.config = args
        .runtime
        .config
        .clone()
        .or_else(|| std::env::var_os("CODE_DIVER_CONFIG").map(PathBuf::from))
        .unwrap_or_else(|| options.paths.config_file());
    if !options.config.is_absolute() {
        options.config = std::env::current_dir()
            .map_err(|_| "Cannot resolve config directory")?
            .join(&options.config);
    }
    options.uninstall = args.uninstall;
    options.purge = args.purge;
    options.profile = args.profile;
    options.no_register = args.no_register;
    options.yes = args.yes;
    options.dry_run = args.dry_run;
    options.key_file = args.key_file;
    options.llama_server = args.runtime.llama_server.clone();
    options.flags = runtime_flags(&args.runtime)?;
    options.environment = std::env::vars().collect();
    if !options.uninstall {
        let mut config = runtime_config::load_config(&options.config).map_err(|e| e.to_string())?;
        if let Some(source) = &options.profile
            && !options.dry_run
        {
            config.profile = runtime_config::load_profile(source)
                .await
                .map_err(|e| e.to_string())?;
        }
        let environment =
            runtime_config::environment_overrides(|key| options.environment.get(key).cloned())
                .map_err(|e| e.to_string())?;
        let mut config = runtime_config::effective_config(config, &environment, &options.flags)
            .map_err(|e| e.to_string())?;
        let missing = |config: &runtime_config::RuntimeConfig| {
            let mut fields = Vec::new();
            for (name, value) in [
                ("index_name", &config.profile.index_name),
                ("artifact_url", &config.profile.artifact_url),
                ("qdrant_url", &config.profile.qdrant_url),
                ("collection", &config.profile.collection),
            ] {
                if value.as_deref().is_none_or(|value| value.trim().is_empty()) {
                    fields.push(name);
                }
            }
            fields
        };
        if !missing(&config).is_empty() {
            if options.dry_run {
                println!(
                    "Configuration required: supply --profile URL-or-file containing {} (interactive setup asks for the profile, then a hidden key)",
                    missing(&config).join(", ")
                );
            } else {
                if options.profile.is_some() || options.yes {
                    return Err(format!(
                        "Setup requires {}; supply --profile URL-or-file or explicit configuration; --yes does not supply missing configuration",
                        missing(&config).join(", ")
                    ));
                }
                let source = prompt_setup_profile()?;
                config.profile = runtime_config::load_profile(&source)
                    .await
                    .map_err(|e| e.to_string())?;
                config = runtime_config::effective_config(config, &environment, &options.flags)
                    .map_err(|e| e.to_string())?;
                options.profile = Some(source);
                if !missing(&config).is_empty() {
                    return Err(format!(
                        "Team profile is missing {}; correct --profile before setup",
                        missing(&config).join(", ")
                    ));
                }
            }
        }
        if let Some(name) = config.profile.index_name {
            options
                .flags
                .get_mut("profile")
                .unwrap()
                .as_table_mut()
                .unwrap()
                .insert("index_name".into(), toml::Value::String(name));
        }
    }
    options.search_path = std::env::var_os("PATH")
        .map(|value| std::env::split_paths(&value).collect())
        .unwrap_or_default();
    options.claude_cli = runtime_registration(
        &options.paths,
        &options.executable,
        &options.config,
        options.dry_run,
    )
    .map_err(|e| e.to_string())?
    .claude_cli;
    if options.paths.isolated {
        options.security = None;
    }
    setup::run(
        &options,
        &mut setup::TerminalInteraction,
        &mut RuntimeSetupHooks { options: &options },
    )
    .await
    .map_err(|e| e.to_string())?;
    Ok(())
}

pub(crate) fn runtime_remote(
    config: &runtime_config::RuntimeConfig,
    paths: &runtime_config::RuntimePaths,
) -> Result<serde_json::Value, String> {
    let source = config
        .profile
        .model_manifest_source()
        .map_err(|e| e.to_string())?;
    let manifest = match source {
        Some(source) if !source.contains("://") => {
            let raw = fs::read(source).map_err(|_| "Cannot read runtime model manifest")?;
            Some(model_store::ModelManifest::parse(&raw).map_err(|e| e.to_string())?)
        }
        Some(_) => None,
        None => Some(model_store::ModelManifest::embedded().map_err(|e| e.to_string())?),
    };
    let base = config.daemon_url();
    let mut result = serde_json::json!({
        "storage":{"qdrant":{"url":config.profile.qdrant_url,"collection":config.profile.collection}},
        "embedding":{"url":format!("{base}/v1/embeddings"),
            "model":config.profile.embedding_model.as_deref().or_else(|| manifest.as_ref().map(|manifest| manifest.models.embedder.repo.strip_suffix("-GGUF").unwrap_or(&manifest.models.embedder.repo))),
            "dimensions":config.profile.embedding_dimensions.or_else(|| manifest.as_ref().and_then(|manifest| manifest.models.embedder.dimensions)),
            "query_prefix":config.profile.query_prefix,"document_prefix":config.profile.document_prefix},
        "cross_encoder_rerank":{"url":format!("{base}/v1/rerank")}
    });
    {
        let name = config
            .profile
            .index_name
            .as_deref()
            .ok_or("Runtime snapshot is not configured: set profile.index_name via code-diver setup --profile URL-or-file; collection is not a snapshot selection")?;
        let directory = paths.index_dir(name).map_err(|e| e.to_string())?;
        let directory = directory.canonicalize().unwrap_or(directory);
        let metadata_path = directory.join("index-metadata.json");
        let metadata = if metadata_path.is_file() {
            Some(metadata::load(&metadata_path)?)
        } else {
            None
        };
        for (field, filename) in [
            ("catalog", "rust_catalog.jsonl"),
            ("graph_path", "rust_graph.jsonl"),
            ("model", "ce_meta_ranker.lgb.txt"),
        ] {
            let files = metadata
                .as_ref()
                .and_then(|metadata| metadata.extra.get("files"))
                .and_then(serde_json::Value::as_object);
            let explicit = metadata
                .as_ref()
                .and_then(|metadata| {
                    if field == "model" {
                        metadata
                            .extra
                            .get("meta_ranker")
                            .and_then(|value| value.get("file"))
                    } else {
                        metadata.extra.get(field)
                    }
                })
                .and_then(serde_json::Value::as_str);
            let selected = if let Some(explicit) = explicit {
                if files.is_none_or(|files| !files.contains_key(explicit)) {
                    return Err(format!(
                        "Index metadata {field} is absent from its files manifest"
                    ));
                }
                explicit.to_owned()
            } else if let Some(files) = files {
                let matches: Vec<_> = files
                    .keys()
                    .filter(|path| {
                        Path::new(path)
                            .file_name()
                            .is_some_and(|name| name == filename)
                    })
                    .collect();
                match matches.as_slice() {
                    [path] => (*path).clone(),
                    [] => filename.into(),
                    _ => {
                        return Err(format!(
                            "Ambiguous index metadata {field}; specify its path"
                        ));
                    }
                }
            } else {
                filename.into()
            };
            if Path::new(&selected)
                .components()
                .any(|part| !matches!(part, std::path::Component::Normal(_)))
            {
                return Err("Unsafe index metadata artifact path".into());
            }
            result[field] = serde_json::json!(directory.join(selected));
        }
        if metadata_path.is_file() {
            result["index_metadata"] = serde_json::json!(metadata_path);
        }
    }
    let store = runtime_config::FileSecretStore::new(paths);
    let keychain = runtime_config::NativeMacSecurity;
    for (name, section, field) in [
        ("qdrant", "storage", "api_key"),
        ("embedding", "embedding", "api_key"),
        ("ce", "cross_encoder_rerank", "api_key"),
    ] {
        if let Some(reference) = config.secrets.get(name) {
            let secret = runtime_config::resolve_secret(
                reference,
                |key| std::env::var(key).ok(),
                &store,
                (!paths.isolated).then_some(&keychain as &dyn runtime_config::MacSecurity),
            )
            .map_err(|e| e.to_string())?;
            if section == "storage" {
                result[section]["qdrant"][field] = serde_json::json!(secret.expose());
            } else {
                result[section][field] = serde_json::json!(secret.expose());
            }
        }
    }
    Ok(result)
}

pub(crate) fn runtime_for_args(
    args: &SearchArgs,
) -> Result<Option<(runtime_config::RuntimeConfig, runtime_config::RuntimePaths)>, String> {
    let Some((mut config, paths)) = runtime_for(args.config.as_deref())? else {
        return Ok(None);
    };
    if args.qdrant_api_key.is_some()
        || args.qdrant_bearer.is_some()
        || args.embedding_api_key.is_some()
        || args.ce_api_key.is_some()
    {
        return Err("Runtime credentials must use environment references or the private secret store, not command-line flags".into());
    }
    if let Some(port) = args.daemon_port {
        config.daemon.port = port;
    }
    if let Some(threads) = args.threads {
        config.daemon.threads = Some(threads);
    }
    if let Some(autostart) = args.autostart {
        config.daemon.autostart = autostart;
    }
    if let Some(binary) = &args.llama_server {
        config.llama_server = Some(binary.clone());
    }
    if let Some(source) = &args.model_manifest {
        if source.contains("://") {
            config.profile.model_manifest_url = Some(source.clone());
            config.profile.model_manifest_path = None;
        } else {
            config.profile.model_manifest_path = Some(PathBuf::from(source));
            config.profile.model_manifest_url = None;
        }
    }
    if let Some(url) = &args.qdrant_url {
        config.profile.qdrant_url = Some(url.clone());
    }
    if !args.qdrant_collection.is_empty() {
        config.profile.collection = Some(args.qdrant_collection.clone());
    }
    if let Some(model) = &args.embedding_model {
        config.profile.embedding_model = Some(model.clone());
    }
    if let Some(dimensions) = args.embedding_dimensions {
        config.profile.embedding_dimensions = Some(dimensions);
    }
    if let Some(prefix) = &args.embedding_query_prefix {
        config.profile.query_prefix = Some(prefix.clone());
    }
    if let Some(prefix) = &args.embedding_document_prefix {
        config.profile.document_prefix = Some(prefix.clone());
    }
    config.validate().map_err(|e| e.to_string())?;
    Ok(Some((config, paths)))
}

fn build_search_config(args: &SearchArgs) -> Result<(SearchConfig, PathBuf), String> {
    build_search_config_for(args, true)
}

fn build_search_config_for(
    args: &SearchArgs,
    require_artifacts: bool,
) -> Result<(SearchConfig, PathBuf), String> {
    build_search_config_default(args, require_artifacts, false)
}

fn build_search_config_default(
    args: &SearchArgs,
    require_artifacts: bool,
    default_require_rerank: bool,
) -> Result<(SearchConfig, PathBuf), String> {
    let config_path = args
        .config
        .clone()
        .or_else(|| std::env::var_os("CODE_DIVER_CONFIG").map(PathBuf::from));
    let remote = if let Some((config, paths)) = runtime_for_args(args)? {
        runtime_remote(&config, &paths)?
    } else {
        indexing::remote_config(config_path.as_deref())?
    };
    indexing::validate_config(&remote)?;
    let q = &remote["storage"]["qdrant"];
    let e = &remote["embedding"];
    let value = |cli: Option<&str>, env: &str, config: &serde_json::Value, default: &str| {
        indexing::setting(cli, env, None, config, default)
    };
    let root_path = indexing::configured_path(
        args.root
            .as_deref()
            .or_else(|| args.base_path.as_deref().map(Path::new)),
        "ROOT",
        &remote["root"],
        config_path.as_deref(),
        Path::new("."),
    );
    let artifact = |configured: &Path, defaults: &[&str]| {
        if !configured.as_os_str().is_empty() {
            return Some(configured.to_string_lossy().into_owned());
        }
        defaults
            .iter()
            .map(|p| root_path.join(p))
            .find(|p| p.is_file())
            .map(|p| p.to_string_lossy().into_owned())
    };
    let configured_catalog = indexing::configured_path(
        args.catalog.as_deref().map(Path::new),
        "CATALOG",
        &remote["catalog"],
        config_path.as_deref(),
        Path::new(""),
    );
    let configured_graph = indexing::configured_path(
        args.graph.as_deref().map(Path::new),
        "GRAPH",
        &remote["graph_path"],
        config_path.as_deref(),
        Path::new(""),
    );
    let catalog_path = artifact(
        &configured_catalog,
        &[
            "artifacts/rust_catalog.jsonl",
            ".code-diver/rust_catalog.jsonl",
        ],
    )
    .or_else(|| {
        (!require_artifacts).then(|| {
            root_path
                .join("artifacts/rust_catalog.jsonl")
                .to_string_lossy()
                .into_owned()
        })
    })
    .ok_or_else(|| {
        "Catalog file not found. Pass --catalog PATH or place at artifacts/rust_catalog.jsonl"
            .to_string()
    })?;

    let graph_path = artifact(
        &configured_graph,
        &["artifacts/rust_graph.jsonl", ".code-diver/rust_graph.jsonl"],
    )
    .or_else(|| {
        (!require_artifacts).then(|| {
            root_path
                .join("artifacts/rust_graph.jsonl")
                .to_string_lossy()
                .into_owned()
        })
    })
    .ok_or_else(|| {
        "Graph file not found. Pass --graph PATH or place at artifacts/rust_graph.jsonl".to_string()
    })?;

    let configured_model = indexing::configured_path(
        args.model.as_deref().map(Path::new),
        "MODEL",
        &remote["model"],
        config_path.as_deref(),
        Path::new(""),
    );
    let model_path = artifact(
        &configured_model,
        &[
            "artifacts/ce_meta_ranker/ce_meta_ranker.lgb.txt",
            ".code-diver/models/ce_meta_ranker.lgb.txt",
            "models/ce_meta_ranker.lgb.txt",
        ],
    );

    let meta_ranker_enabled = model_path.is_some();
    let candidate_limit = configured_candidate_limit(args)?;
    let (second_pass_enabled, second_pass_score_floor, second_pass_candidate_cap) =
        resolve_second_pass(
            args.preset.as_deref(),
            args.second_pass_cap,
            args.second_pass_floor,
            args.second_pass_disable,
        )
        .map_err(|e| e.to_string())?;
    if second_pass_enabled && second_pass_candidate_cap > candidate_limit {
        return Err(format!(
            "second-pass cap ({}) must not exceed first-pass window ({})",
            second_pass_candidate_cap, candidate_limit
        ));
    }

    let mut config = SearchConfig {
        catalog_path,
        graph_path,
        ce_url: value(
            args.ce_url.as_deref(),
            "CE_URL",
            &remote["cross_encoder_rerank"]["url"],
            "http://localhost:18081/v1/rerank",
        ),
        second_ce_url: value(
            args.second_ce_url.as_deref(),
            "SECOND_CE_URL",
            &remote["cross_encoder_rerank"]["second_ce_url"],
            "",
        ),
        ce_route: value(
            args.ce_route.as_deref(),
            "CE_ROUTE",
            &remote["cross_encoder_rerank"]["route"],
            "auto",
        ),
        ce_timeout_ms: value(
            args.ce_timeout_ms.map(|n| n.to_string()).as_deref(),
            "CE_TIMEOUT_MS",
            &remote["cross_encoder_rerank"]["timeout_ms"],
            "60000",
        )
        .parse()
        .map_err(|_| "Invalid CE timeout")?,
        ce_model: value(
            args.ce_model.as_deref(),
            "CE_MODEL",
            &remote["cross_encoder_rerank"]["model"],
            "",
        ),
        retrieval_limit: args.retrieval_limit,
        candidate_limit,
        vector_weight: args.vector_weight,
        lexical_weight: args.lexical_weight,
        path_weight: args.path_weight,
        symbol_weight: args.symbol_weight,
        graph_weight: args.graph_weight,
        symbol_match_weight: args.symbol_match_weight,
        file_vote_weight: args.file_vote_weight,
        lexical_candidate_limit: args.lexical_candidate_limit,
        rank_by_raw_logits: args.rank_by_raw_logits,
        tie_break_by_fused_score: args.tie_break_by_fused_score,
        tie_break_epsilon: args.tie_break_epsilon,
        second_pass_enabled,
        second_pass_score_floor,
        second_pass_candidate_cap,
        max_document_chars: args.max_document_chars,
        second_pass_max_document_chars: args.second_pass_max_document_chars,
        qdrant_collection: args.qdrant_collection.clone(),
        ce_meta_model_path: model_path.unwrap_or_default(),
        ce_meta_ranker_enabled: meta_ranker_enabled,
        base_path: root_path.to_string_lossy().into_owned(),
        embed_cache_size: args.embed_cache_size,
        ..SearchConfig::default()
    };

    config.embedding_url = value(
        args.embedding_url.as_deref(),
        "EMBEDDING_URL",
        &e["url"],
        "http://localhost:8001/v1/embeddings",
    );
    config.qdrant_url = value(
        args.qdrant_url.as_deref(),
        "QDRANT_URL",
        &q["url"],
        "http://localhost:6333",
    );
    config.embedding_model = value(
        args.embedding_model.as_deref(),
        "EMBEDDING_MODEL",
        &e["model"],
        embedding::EMBED_MODEL,
    );
    config.embedding_query_prefix = value(
        args.embedding_query_prefix.as_deref(),
        "EMBEDDING_QUERY_PREFIX",
        &e["query_prefix"],
        "",
    );
    config.require_rerank = value(
        (if args.no_require_rerank {
            Some(false)
        } else {
            args.require_rerank
        })
        .map(|v| if v { "true" } else { "false" }),
        "REQUIRE_RERANK",
        &remote["search"]["require_rerank"],
        if default_require_rerank {
            "true"
        } else {
            "false"
        },
    )
    .parse()
    .map_err(|_| "Invalid require_rerank; expected true or false")?;
    config.embedding_document_prefix = value(
        args.embedding_document_prefix.as_deref(),
        "EMBEDDING_DOCUMENT_PREFIX",
        &e["document_prefix"],
        "",
    );
    let dimension = value(
        args.embedding_dimensions.map(|n| n.to_string()).as_deref(),
        "EMBEDDING_DIMENSIONS",
        &e["dimensions"],
        "",
    );
    config.embedding_dimensions = if dimension.is_empty() {
        None
    } else {
        Some(
            dimension
                .parse()
                .map_err(|_| "Invalid embedding dimensions")?,
        )
    };
    if config.embedding_dimensions == Some(0) || config.ce_timeout_ms == 0 {
        return Err("Embedding dimensions and CE timeout must be positive".into());
    }
    let chars = value(None, "MAX_INPUT_CHARS", &e["max_input_chars"], "2000")
        .parse::<usize>()
        .map_err(|_| "Invalid max_input_chars")?;
    let tokens = value(None, "MAX_INPUT_TOKENS", &e["max_input_tokens"], "512")
        .parse::<usize>()
        .map_err(|_| "Invalid max_input_tokens")?;
    let margin = value(None, "TOKEN_SAFETY_MARGIN", &e["token_safety_margin"], "32")
        .parse::<usize>()
        .map_err(|_| "Invalid token_safety_margin")?;
    if tokens == 0 {
        return Err("Token window must be positive".into());
    }
    let token_budget = tokens
        .checked_sub(margin)
        .filter(|n| *n > 0)
        .ok_or("Token safety margin exhausts token window")?;
    config.embedding_query_token_budget = match args.embedding_query_token_budget {
        Some(budget) => budget,
        None => value(
            None,
            "EMBEDDING_QUERY_TOKEN_BUDGET",
            &e["query_token_budget"],
            &token_budget.to_string(),
        )
        .parse::<usize>()
        .map_err(|_| "Invalid embedding query token budget")?,
    };
    if config.embedding_query_token_budget == 0 {
        return Err("Embedding query token budget must be positive".into());
    }
    let budget = token_budget.saturating_mul(3);
    config.embedding_query_char_limit = if chars == 0 {
        budget
    } else {
        chars.min(budget)
    };
    config.qdrant_collection = indexing::setting(
        (!args.qdrant_collection.is_empty()).then_some(args.qdrant_collection.as_str()),
        "COLLECTION",
        Some("CODE_DIVER_QDRANT_COLLECTION"),
        &q["collection"],
        "",
    );
    config.qdrant_api_key = index_net::Secret(indexing::setting(
        args.qdrant_api_key.as_ref().map(|s| s.0.as_str()),
        "QDRANT_API_KEY",
        Some(q["api_key_env"].as_str().unwrap_or("QDRANT_API_KEY")),
        &q["api_key"],
        "",
    ));
    config.qdrant_bearer = index_net::Secret(value(
        args.qdrant_bearer.as_ref().map(|s| s.0.as_str()),
        "QDRANT_BEARER",
        &q["bearer"],
        "",
    ));
    config.embedding_api_key = index_net::Secret(indexing::setting(
        args.embedding_api_key.as_ref().map(|s| s.0.as_str()),
        "EMBEDDING_API_KEY",
        Some(e["api_key_env"].as_str().unwrap_or("EMBEDDING_API_KEY")),
        &e["api_key"],
        "",
    ));
    config.ce_api_key = index_net::Secret(indexing::setting(
        args.ce_api_key.as_ref().map(|s| s.0.as_str()),
        "CE_API_KEY",
        Some(
            remote["cross_encoder_rerank"]["api_key_env"]
                .as_str()
                .unwrap_or("CE_API_KEY"),
        ),
        &remote["cross_encoder_rerank"]["api_key"],
        "",
    ));
    let ca = indexing::setting(
        args.ca_bundle.as_deref(),
        "CA_BUNDLE",
        Some("SSL_CERT_FILE"),
        &remote["ca_bundle"],
        "",
    );
    config.ca_bundle = (!ca.is_empty()).then_some(ca);
    if args.ca_bundle.is_none()
        && std::env::var_os("CODE_DIVER_CA_BUNDLE").is_none()
        && std::env::var_os("SSL_CERT_FILE").is_none()
        && config.ca_bundle.is_some()
    {
        config.ca_bundle = Some(
            indexing::configured_path(
                None,
                "CA_BUNDLE",
                &remote["ca_bundle"],
                config_path.as_deref(),
                Path::new(""),
            )
            .to_string_lossy()
            .into_owned(),
        );
    }
    if let Some(ca) = config
        .ca_bundle
        .as_deref()
        .filter(|ca| ca.starts_with("~/"))
    {
        config.ca_bundle = Some(
            indexing::configured_path(
                Some(Path::new(ca)),
                "CA_BUNDLE",
                &serde_json::Value::Null,
                None,
                Path::new(""),
            )
            .to_string_lossy()
            .into_owned(),
        );
    }
    for url in [&config.embedding_url, &config.qdrant_url, &config.ce_url]
        .into_iter()
        .chain((!config.second_ce_url.is_empty()).then_some(&config.second_ce_url))
    {
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
    config.insecure_skip_verify = args.insecure_skip_verify
        || value(
            None,
            "INSECURE_SKIP_VERIFY",
            &remote["insecure_skip_verify"],
            "false",
        )
        .parse::<bool>()
        .map_err(|_| "Invalid TLS verification setting")?;
    if value(
        None,
        "EMBEDDING_PROVIDER",
        &e["provider"],
        "openai_compatible",
    ) != "openai_compatible"
    {
        return Err("Unsupported embedding provider".into());
    }

    let configured_metadata = indexing::configured_path(
        args.index_metadata.as_deref(),
        "INDEX_METADATA",
        &remote["index_metadata"],
        config_path.as_deref(),
        Path::new(""),
    );
    config.index_metadata =
        metadata::discover(&configured_metadata, Path::new(&config.catalog_path));
    if let Some(path) = &config.index_metadata {
        let metadata = metadata::load(path)?;
        let explicit = |cli: bool, env: &str, field: &serde_json::Value| {
            cli || std::env::var_os(format!("CODE_DIVER_{env}")).is_some() || !field.is_null()
        };
        if !explicit(
            args.embedding_model.is_some(),
            "EMBEDDING_MODEL",
            &e["model"],
        ) {
            config.embedding_model = metadata.embedding.model.clone();
        }
        if !explicit(
            !args.qdrant_collection.is_empty(),
            "QDRANT_COLLECTION",
            &q["collection"],
        ) {
            config.qdrant_collection = metadata.collection.clone();
        }
        if !explicit(
            args.embedding_query_prefix.is_some(),
            "EMBEDDING_QUERY_PREFIX",
            &e["query_prefix"],
        ) {
            config.embedding_query_prefix = metadata.embedding.query_prefix.clone();
        }
        if !explicit(
            args.embedding_document_prefix.is_some(),
            "EMBEDDING_DOCUMENT_PREFIX",
            &e["document_prefix"],
        ) {
            config.embedding_document_prefix = metadata.embedding.document_prefix.clone();
        }
        let limit = |key: &str, env: &str, fallback: usize| -> Result<usize, String> {
            metadata
                .embedding
                .extra
                .get(key)
                .map(|v| {
                    value(None, env, &e[key], &v.to_string())
                        .parse::<usize>()
                        .map_err(|_| format!("Invalid embedding {key}"))
                })
                .unwrap_or(Ok(fallback))
        };
        let chars = limit("max_input_chars", "MAX_INPUT_CHARS", chars)?;
        let tokens = limit("max_input_tokens", "MAX_INPUT_TOKENS", tokens)?;
        let margin = limit("token_safety_margin", "TOKEN_SAFETY_MARGIN", margin)?;
        let token_budget = tokens
            .checked_sub(margin)
            .filter(|n| *n > 0)
            .ok_or("Metadata token safety margin exhausts token window")?;
        config.embedding_query_char_limit = if chars == 0 {
            token_budget.saturating_mul(3)
        } else {
            chars.min(token_budget.saturating_mul(3))
        };
        if !explicit(
            args.embedding_query_token_budget.is_some(),
            "EMBEDDING_QUERY_TOKEN_BUDGET",
            &e["query_token_budget"],
        ) {
            config.embedding_query_token_budget = token_budget;
        }
        metadata.validate(&config)?;
        if let Some(warning) = metadata.prefix_warning(&config) {
            eprintln!("WARNING: {warning}");
        }
        config.embedding_dimensions = Some(metadata.embedding.dimensions);
    }
    Ok((config, root_path))
}

async fn run_mcp(args: McpArgs) -> Result<(), String> {
    if let Some((config, paths)) = runtime_for_args(&args.search)?
        && config.daemon.autostart
    {
        ensure_daemon(&config, &paths, args.search.config.as_deref()).await?;
    }
    let root_path = inspection_root(
        args.search
            .root
            .as_deref()
            .or_else(|| args.search.base_path.as_deref().map(Path::new)),
        args.search.config.as_deref(),
    )?;
    let mcp_config = crate::mcp::McpConfig {
        args: args.search,
        root_dir: root_path,
        max_concurrent_searches: args.max_concurrent_searches,
    };
    crate::mcp::run_mcp_server(mcp_config).await
}

struct RuntimeProcessLock {
    _file: fs::File,
}

impl RuntimeProcessLock {
    fn held(paths: &runtime_config::RuntimePaths) -> Result<bool, String> {
        use std::os::fd::AsRawFd;
        unsafe extern "C" {
            fn flock(fd: i32, operation: i32) -> i32;
        }
        let path = paths.state.join("daemon.pid");
        service_manager::safe_path(&path).map_err(|e| e.to_string())?;
        let file = match fs::OpenOptions::new().read(true).write(true).open(path) {
            Ok(file) => file,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(false),
            Err(_) => return Err("Cannot inspect daemon process lock".into()),
        };
        const LOCK_EX: i32 = 2;
        const LOCK_NB: i32 = 4;
        if unsafe { flock(file.as_raw_fd(), LOCK_EX | LOCK_NB) } == 0 {
            return Ok(false);
        }
        if std::io::Error::last_os_error().kind() == std::io::ErrorKind::WouldBlock {
            Ok(true)
        } else {
            Err("Cannot inspect daemon process lock".into())
        }
    }

    async fn acquire(
        paths: &runtime_config::RuntimePaths,
        name: &str,
        wait: Option<std::time::Duration>,
    ) -> Result<Self, String> {
        use std::io::{Seek, Write};
        use std::os::fd::AsRawFd;
        use std::os::unix::fs::OpenOptionsExt;
        const LOCK_EX: i32 = 2;
        const LOCK_NB: i32 = 4;
        unsafe extern "C" {
            fn flock(fd: i32, operation: i32) -> i32;
        }
        paths.ensure_dirs().map_err(|e| e.to_string())?;
        let path = paths.state.join(name);
        service_manager::safe_path(&path).map_err(|e| e.to_string())?;
        let mut file = fs::OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .mode(0o600)
            .open(path)
            .map_err(|_| "Cannot open daemon process lock")?;
        let deadline = wait.map(|duration| tokio::time::Instant::now() + duration);
        loop {
            if unsafe { flock(file.as_raw_fd(), LOCK_EX | LOCK_NB) } == 0 {
                file.set_len(0).map_err(|_| "Cannot update daemon PID")?;
                file.rewind().map_err(|_| "Cannot update daemon PID")?;
                writeln!(file, "{}", std::process::id()).map_err(|_| "Cannot update daemon PID")?;
                return Ok(Self { _file: file });
            }
            if std::io::Error::last_os_error().kind() != std::io::ErrorKind::WouldBlock {
                return Err("Cannot acquire daemon process lock".into());
            }
            if deadline.is_none_or(|deadline| tokio::time::Instant::now() >= deadline) {
                return Err("Local daemon process lock is held; run doctor".into());
            }
            tokio::time::sleep(std::time::Duration::from_millis(50)).await;
        }
    }
}

async fn ensure_daemon(
    config: &runtime_config::RuntimeConfig,
    paths: &runtime_config::RuntimePaths,
    explicit: Option<&Path>,
) -> Result<(), String> {
    let _launch_lock = RuntimeProcessLock::acquire(
        paths,
        "daemon-autostart.lock",
        Some(std::time::Duration::from_secs(
            config.daemon.startup_timeout_secs,
        )),
    )
    .await?;
    let client = reqwest::Client::builder()
        .no_proxy()
        .timeout(std::time::Duration::from_millis(500))
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .map_err(|_| "Cannot initialize daemon client")?;
    let url = format!("{}/health", config.daemon_url());
    if client
        .get(&url)
        .send()
        .await
        .is_ok_and(|response| response.status().is_success())
    {
        return Ok(());
    }
    let deadline = tokio::time::Instant::now()
        + std::time::Duration::from_secs(config.daemon.startup_timeout_secs);
    while RuntimeProcessLock::held(paths)? {
        if client
            .get(&url)
            .send()
            .await
            .is_ok_and(|response| response.status().is_success())
        {
            return Ok(());
        }
        if tokio::time::Instant::now() >= deadline {
            return Err(
                "Local daemon holds its PID lock but health is not ready; run doctor".into(),
            );
        }
        tokio::time::sleep(std::time::Duration::from_millis(100)).await;
    }
    let executable = std::env::current_exe().map_err(|_| "Cannot locate daemon executable")?;
    let path = explicit
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("CODE_DIVER_CONFIG").map(PathBuf::from))
        .unwrap_or_else(|| paths.config_file());
    let mut command = tokio::process::Command::new(executable);
    command
        .args(["daemon", "--foreground", "--config"])
        .arg(path)
        .arg("--port")
        .arg(config.daemon.port.to_string())
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null());
    if let Some(binary) = &config.llama_server {
        command.arg("--llama-server").arg(binary);
    }
    if let Some(threads) = config.daemon.threads {
        command.arg("--threads").arg(threads.to_string());
    }
    if let Some(source) = config
        .profile
        .model_manifest_source()
        .map_err(|e| e.to_string())?
    {
        command.arg("--model-manifest").arg(source);
    }
    let mut child = command
        .spawn()
        .map_err(|_| "Cannot launch local daemon; run setup")?;
    let deadline = tokio::time::Instant::now()
        + std::time::Duration::from_secs(config.daemon.startup_timeout_secs);
    loop {
        if client
            .get(&url)
            .send()
            .await
            .is_ok_and(|response| response.status().is_success())
        {
            tokio::spawn(async move {
                let _ = child.wait().await;
            });
            return Ok(());
        }
        if child
            .try_wait()
            .map_err(|_| "Cannot inspect daemon process")?
            .is_some()
            && !RuntimeProcessLock::held(paths)?
        {
            return Err("Local daemon failed to start; run doctor or setup".into());
        }
        if tokio::time::Instant::now() >= deadline {
            let _ = child.kill().await;
            return Err("Local daemon startup timed out; run doctor or setup".into());
        }
        tokio::time::sleep(std::time::Duration::from_millis(100)).await;
    }
}

async fn run_search_cli(args: SearchArgs) -> Result<(), String> {
    if args.doctor {
        return doctor::run(&args, false).await;
    }
    if args.index_update {
        return run_index_update(&args).await;
    }

    let (config, _root_path) = build_search_config(&args)?;

    eprintln!("Initializing search context...");
    let init_start = Instant::now();
    let ctx = init_search_context(config).await?;
    eprintln!(
        "  Initialized in {:.2}s",
        init_start.elapsed().as_secs_f64()
    );

    let query = args.resolved_query();

    if let Some(features_file) = args.dump_features_file {
        dump_features_batch(&ctx, &features_file).await?;
    } else if args.dump_features {
        if let Some(q) = query {
            let expected: Vec<String> = args
                .expected
                .unwrap_or_default()
                .split(',')
                .filter(|s| !s.is_empty())
                .map(|s| s.trim().to_string())
                .collect();
            let query_id = args.query_id.unwrap_or_else(|| "unknown".to_string());
            dump_features(&ctx, &q, &query_id, &expected).await?;
        } else {
            return Err("--query is required with --dump-features".to_string());
        }
    } else if args.server {
        run_server(&ctx).await?;
    } else if let Some(bench_file) = args.bench {
        run_benchmark(&ctx, &bench_file, args.bench_n).await?;
    } else if let Some(q) = query {
        run_single(&ctx, &q, args.limit).await?;
    } else {
        // Interactive mode: read queries from stdin
        run_interactive(&ctx, args.limit).await?;
    }

    Ok(())
}

fn resolve_path(cli_arg: Option<&str>, candidates: &[&str]) -> Option<String> {
    if let Some(arg) = cli_arg
        && !arg.is_empty()
    {
        return Some(arg.to_string());
    }
    for candidate in candidates {
        if Path::new(candidate).exists() {
            return Some(candidate.to_string());
        }
    }
    None
}

/// Incremental index update: diff --catalog against Qdrant, embed + upsert
/// only dirty items, delete removed points. Dry run unless --apply.
async fn run_index_update(args: &SearchArgs) -> Result<(), String> {
    if args.qdrant_collection.trim().is_empty() {
        return Err("An explicit --qdrant-collection is required; use index --collection NAME for new indexing".into());
    }
    if args.apply {
        return Err("Legacy --index-update --apply is disabled; use index --apply --collection NAME (deletion requires --prune)".into());
    }
    use crate::catalog::load_catalog;
    use crate::embedding::embed_texts;
    use crate::index_update::{
        collection_dimensions, delete_points, diff_catalog, embed_text, scroll_indexed,
        upsert_points,
    };

    let resolved_catalog = resolve_path(
        args.catalog.as_deref(),
        &[
            "artifacts/rust_catalog.jsonl",
            ".code-diver/rust_catalog.jsonl",
            "/tmp/rust_catalog.jsonl",
        ],
    )
    .ok_or_else(|| "--catalog is required or place at artifacts/rust_catalog.jsonl".to_string())?;

    let catalog_path = Path::new(&resolved_catalog);
    eprintln!("Loading catalog from: {}", catalog_path.display());
    let catalog = load_catalog(catalog_path)?;
    eprintln!("  Catalog items: {}", catalog.items.len());

    let http_client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(60))
        .pool_idle_timeout(std::time::Duration::from_secs(90))
        .pool_max_idle_per_host(32)
        .build()
        .map_err(|e| format!("HTTP client failed: {}", e))?;

    eprintln!("Scrolling collection: {}", args.qdrant_collection);
    let indexed = scroll_indexed(
        &http_client,
        args.qdrant_url
            .as_deref()
            .unwrap_or("http://localhost:6333"),
        &args.qdrant_collection,
    )
    .await?;
    eprintln!("  Indexed points: {}", indexed.len());

    let diff = diff_catalog(&catalog.items, &indexed);
    eprintln!(
        "Diff: added={} changed={} deleted={} unchanged={}",
        diff.added.len(),
        diff.changed.len(),
        diff.deleted.len(),
        catalog.items.len() - diff.added.len() - diff.changed.len()
    );
    if !args.apply {
        eprintln!("Dry run: pass --apply to write.");
        return Ok(());
    }
    if diff.added.is_empty() && diff.changed.is_empty() && diff.deleted.is_empty() {
        eprintln!("Index already in sync, nothing to do.");
        return Ok(());
    }

    let dimensions = collection_dimensions(
        &http_client,
        args.qdrant_url
            .as_deref()
            .unwrap_or("http://localhost:6333"),
        &args.qdrant_collection,
    )
    .await?;
    eprintln!("  Collection dimensions: {}", dimensions);

    let dirty: Vec<usize> = diff
        .added
        .iter()
        .chain(diff.changed.iter())
        .copied()
        .collect();
    if !dirty.is_empty() {
        let mut upserted = 0;
        for chunk in dirty.chunks(32) {
            let items: Vec<&crate::types::CatalogItem> =
                chunk.iter().map(|&i| &catalog.items[i]).collect();
            let texts: Vec<String> = items
                .iter()
                .map(|it| embed_text(it, args.embed_max_chars))
                .collect();
            let vectors = embed_texts(
                &http_client,
                args.embedding_url
                    .as_deref()
                    .unwrap_or("http://localhost:8001/v1/embeddings"),
                &texts,
            )
            .await?;
            if vectors.first().map(|v| v.len()).unwrap_or(0) != dimensions {
                return Err(format!(
                    "Embedding dimension mismatch: got {}, collection has {}",
                    vectors.first().map(|v| v.len()).unwrap_or(0),
                    dimensions
                ));
            }
            upserted += upsert_points(
                &http_client,
                args.qdrant_url
                    .as_deref()
                    .unwrap_or("http://localhost:6333"),
                &args.qdrant_collection,
                &items,
                &vectors,
                "",
                "openai_compatible",
                crate::embedding::EMBED_MODEL,
                dimensions,
            )
            .await?;
            eprintln!("  Upserted {}/{}", upserted, dirty.len());
        }
    }

    if !diff.deleted.is_empty() {
        let n = delete_points(
            &http_client,
            args.qdrant_url
                .as_deref()
                .unwrap_or("http://localhost:6333"),
            &args.qdrant_collection,
            &diff.deleted,
        )
        .await?;
        eprintln!("  Deleted {}", n);
    }

    let after = scroll_indexed(
        &http_client,
        args.qdrant_url
            .as_deref()
            .unwrap_or("http://localhost:6333"),
        &args.qdrant_collection,
    )
    .await?;
    eprintln!("Indexed points after: {}", after.len());
    Ok(())
}

async fn run_single(
    ctx: &pipeline::SearchContext,
    query: &str,
    limit: usize,
) -> Result<(), String> {
    eprintln!("Searching for: {}", query);
    let start = Instant::now();
    let (response, timings) = pipeline::search_with_options(
        ctx,
        query,
        &types::SearchOptions {
            limit,
            preview_chars: 0,
        },
    )
    .await?;
    for notice in &response.notices {
        eprintln!("WARNING: {notice}");
    }
    let results = &response.results;
    let wall_ms = start.elapsed().as_secs_f64() * 1000.0;

    println!(
        "{}",
        serde_json::to_string_pretty(&serde_json::json!({
            "query": query,
            "results": results,
            "rerank_applied": response.rerank_applied,
            "rerank_second_pass_failed": response.rerank_second_pass_failed,
            "rerank_error": response.rerank_error,
            "meta_ranker_applied": response.meta_ranker_applied,
            "notices": response.notices,
            "timings": {
                "embed_ms": timings.embed_ms,
                "vector_search_ms": timings.vector_search_ms,
                "bm25_ms": timings.bm25_ms,
                "graph_ms": timings.graph_ms,
                "fusion_ms": timings.fusion_ms,
                "ce_first_pass_ms": timings.ce_first_pass_ms,
                "ce_second_pass_ms": timings.ce_second_pass_ms,
                "feature_extract_ms": timings.feature_extract_ms,
                "meta_predict_ms": timings.meta_predict_ms,
                "total_ms": wall_ms,
            },
            "num_results": results.len(),
        }))
        .unwrap_or_default()
    );

    eprintln!("  {} results in {:.1}ms", results.len(), wall_ms);
    Ok(())
}

async fn run_interactive(ctx: &pipeline::SearchContext, limit: usize) -> Result<(), String> {
    eprintln!("Entering interactive mode. Type queries (one per line), Ctrl+D to exit.");
    let mut line = String::new();
    loop {
        line.clear();
        eprint!("> ");

        let bytes = std::io::stdin()
            .read_line(&mut line)
            .map_err(|e| e.to_string())?;
        if bytes == 0 {
            break;
        }
        let query = line.trim();
        if query.is_empty() {
            continue;
        }
        run_single(ctx, query, limit).await?;
    }
    Ok(())
}

async fn run_server(ctx: &pipeline::SearchContext) -> Result<(), String> {
    eprintln!("Server mode: reading queries from stdin as JSON lines");
    eprintln!("Format: {{\"query\": \"...\", \"limit\": 10}}");
    let mut line = String::new();
    loop {
        line.clear();
        let bytes = std::io::stdin()
            .read_line(&mut line)
            .map_err(|e| e.to_string())?;
        if bytes == 0 {
            break;
        }
        let line = line.trim();
        if line.is_empty() {
            continue;
        }

        // Parse JSON request
        let req: serde_json::Value =
            serde_json::from_str(line).map_err(|e| format!("Invalid JSON: {}", e))?;
        let query = req["query"].as_str().ok_or("Missing 'query' field")?;
        let limit = req["limit"].as_u64().unwrap_or(10) as usize;

        let (results, timings) = search(ctx, query, limit).await?;

        let output = serde_json::json!({
            "query": query,
            "results": results,
            "timings": {
                "total_ms": timings.total_ms,
                "embed_ms": timings.embed_ms,
                "vector_search_ms": timings.vector_search_ms,
                "bm25_ms": timings.bm25_ms,
                "fusion_ms": timings.fusion_ms,
                "graph_ms": timings.graph_ms,
                "ce_first_pass_ms": timings.ce_first_pass_ms,
                "ce_second_pass_ms": timings.ce_second_pass_ms,
                "feature_extract_ms": timings.feature_extract_ms,
                "meta_predict_ms": timings.meta_predict_ms,
            },
            "num_results": results.len(),
        });
        println!("{}", serde_json::to_string(&output).unwrap_or_default());
    }
    Ok(())
}

async fn run_benchmark(ctx: &pipeline::SearchContext, path: &str, n: usize) -> Result<(), String> {
    eprintln!("Benchmark mode: reading queries from {}", path);
    let content =
        std::fs::read_to_string(path).map_err(|e| format!("Cannot read {}: {}", path, e))?;

    let mut queries: Vec<String> = Vec::new();
    for line in content.lines() {
        if line.trim().is_empty() {
            continue;
        }
        // Try to parse as JSON and extract query
        if let Ok(val) = serde_json::from_str::<serde_json::Value>(line)
            && let Some(q) = val["query"].as_str()
        {
            queries.push(q.to_string());
            continue;
        }
        // Fallback: use the whole line as query
        queries.push(line.to_string());
    }

    let queries = &queries[..queries.len().min(n)];

    eprintln!("Running {} queries...", queries.len());
    let mut all_timings: Vec<SearchTimings> = Vec::new();
    let total_start = Instant::now();

    for (i, query) in queries.iter().enumerate() {
        let start = Instant::now();
        match search(ctx, query, 10).await {
            Ok((results, timings)) => {
                let elapsed = start.elapsed().as_secs_f64() * 1000.0;
                all_timings.push(timings);
                eprintln!(
                    "  [{}/{}] {:.0}ms, {} results",
                    i + 1,
                    queries.len(),
                    elapsed,
                    results.len()
                );
            }
            Err(e) => {
                eprintln!("  [{}/{}] ERROR: {}", i + 1, queries.len(), e);
            }
        }
    }

    let total_ms = total_start.elapsed().as_secs_f64() * 1000.0;

    if !all_timings.is_empty() {
        let n = all_timings.len();
        let compute_stats = |_name: &str, extract: fn(&SearchTimings) -> f64| {
            let mut vals: Vec<f64> = all_timings.iter().map(extract).collect();
            vals.sort_by(|a, b| a.partial_cmp(b).unwrap());
            let p50 = vals[n / 2];
            let p95 = vals[(n as f64 * 0.95) as usize];
            let mean = vals.iter().sum::<f64>() / n as f64;
            serde_json::json!({
                "p50_ms": (p50 * 100.0).round() / 100.0,
                "p95_ms": (p95 * 100.0).round() / 100.0,
                "mean_ms": (mean * 100.0).round() / 100.0,
            })
        };

        let summary = serde_json::json!({
            "total_queries": n,
            "total_time_ms": (total_ms * 100.0).round() / 100.0,
            "avg_time_per_query_ms": (total_ms / n as f64 * 100.0).round() / 100.0,
            "embed": compute_stats("embed", |t| t.embed_ms),
            "vector_search": compute_stats("vector_search", |t| t.vector_search_ms),
            "bm25": compute_stats("bm25", |t| t.bm25_ms),
            "graph": compute_stats("graph", |t| t.graph_ms),
            "fusion": compute_stats("fusion", |t| t.fusion_ms),
            "ce_first_pass": compute_stats("ce_first_pass", |t| t.ce_first_pass_ms),
            "ce_second_pass": compute_stats("ce_second_pass", |t| t.ce_second_pass_ms),
            "feature_extract": compute_stats("feature_extract", |t| t.feature_extract_ms),
            "meta_predict": compute_stats("meta_predict", |t| t.meta_predict_ms),
            "total": compute_stats("total", |t| t.total_ms),
        });

        let summary_json = serde_json::to_string_pretty(&summary).unwrap_or_default();
        println!("{}", summary_json);

        // Save benchmark results to artifacts
        let artifact_dir = "artifacts/research/2026-09-06_rust-benchmark";
        let _ = fs::create_dir_all(artifact_dir);
        let result_path = format!("{}/results.json", artifact_dir);
        if let Err(e) = fs::write(&result_path, &summary_json) {
            eprintln!("  WARNING: Could not save benchmark results: {}", e);
        } else {
            eprintln!("  Benchmark results saved to {}", result_path);
        }
    }

    Ok(())
}

#[cfg(test)]
mod cli_tests {
    use super::*;

    #[test]
    fn registration_runtime_root_matches_discovered_paths() {
        let home = tempfile::tempdir().unwrap();
        let home = home.path().canonicalize().unwrap();
        for isolated in [true, false] {
            let paths =
                runtime_config::RuntimePaths::from_env(runtime_config::Platform::MacOs, |key| {
                    match key {
                        "CODE_DIVER_HOME" if isolated => Some(home.display().to_string()),
                        "HOME" => Some(home.display().to_string()),
                        _ => None,
                    }
                })
                .unwrap();
            let mut registration = runtime_registration(
                &paths,
                &home.join("code-diver"),
                &home.join("external/config.toml"),
                false,
            )
            .unwrap();
            assert_eq!(registration.runtime_root, isolated.then_some(home.clone()));
            registration.claude_cli = None;
            let host_config = paths.hosts.join(".codex/config.toml");
            fs::create_dir_all(host_config.parent().unwrap()).unwrap();
            fs::write(&host_config, "# preserve\n").unwrap();
            registration.register().unwrap();
            let mut doctor = runtime_registration(
                &paths,
                &home.join("code-diver"),
                &home.join("external/config.toml"),
                true,
            )
            .unwrap();
            doctor.claude_cli = None;
            assert!(doctor.doctor().unwrap().healthy());
            let host: toml::Value =
                toml::from_str(&fs::read_to_string(&host_config).unwrap()).unwrap();
            let root = host["mcp_servers"]["code-diver"]["env"].get("CODE_DIVER_HOME");
            assert_eq!(
                root.and_then(toml::Value::as_str),
                isolated.then(|| home.to_str().unwrap()),
            );
            registration.unregister().unwrap();
            assert_eq!(fs::read_to_string(host_config).unwrap(), "# preserve\n");
        }
    }

    #[tokio::test]
    async fn setup_hook_records_real_updater_receipts_before_publication() {
        use runtime_config::SecretStore;
        use setup::SetupHooks;
        use sha2::{Digest, Sha256};
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        let home = tempfile::tempdir().unwrap();
        let root = home.path().canonicalize().unwrap();
        let paths =
            runtime_config::RuntimePaths::from_env(runtime_config::Platform::MacOs, |key| {
                (key == "CODE_DIVER_HOME").then(|| root.display().to_string())
            })
            .unwrap();
        paths.ensure_dirs().unwrap();
        let cache = paths.data.join(".test-downloads");
        fs::create_dir(&cache).unwrap();
        fs::write(cache.join("preexisting"), "preserve").unwrap();
        runtime_config::FileSecretStore::new(&paths)
            .put(
                "artifacts",
                &runtime_config::SecretValue::new("synthetic-secret".into()).unwrap(),
            )
            .unwrap();
        let mut config = runtime_config::RuntimeConfig::default();
        config.profile.index_name = Some("test".into());
        config.secrets.insert(
            "artifacts".into(),
            runtime_config::SecretRef::File("artifacts".into()),
        );
        let mut metadata: serde_json::Value =
            serde_json::from_str(include_str!("../tests/fixtures/shared-index-metadata.json"))
                .unwrap();
        metadata["files"] = serde_json::json!({"nested/rust_catalog.jsonl": {"bytes":0, "sha256":format!("{:x}", Sha256::digest([]))}});
        let ranker_file = metadata["meta_ranker"]["file"]
            .as_str()
            .unwrap()
            .to_string();
        metadata["files"][&ranker_file] =
            serde_json::json!({"bytes":0, "sha256":format!("{:x}", Sha256::digest([]))});
        let body = metadata.to_string();
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        config.profile.artifact_url = Some(format!("http://{}", listener.local_addr().unwrap()));
        let server = tokio::spawn(async move {
            for _ in 0..2 {
                let (mut stream, _) =
                    tokio::time::timeout(std::time::Duration::from_secs(5), listener.accept())
                        .await
                        .unwrap()
                        .unwrap();
                let mut request = Vec::new();
                while !request.ends_with(b"\r\n\r\n") {
                    request.push(stream.read_u8().await.unwrap());
                }
                assert!(
                    String::from_utf8(request)
                        .unwrap()
                        .contains("Bearer synthetic-secret")
                );
                stream.write_all(format!("HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len()).as_bytes()).await.unwrap();
            }
        });
        let options = setup::SetupOptions::new(
            paths.clone(),
            root.join("code-diver"),
            runtime_config::Platform::MacOs,
            501,
        );
        let mut hooks = RuntimeSetupHooks { options: &options };
        hooks.update_index(&config, &paths).await.unwrap();
        hooks.update_index(&config, &paths).await.unwrap();
        server.await.unwrap();
        let pointer = paths.data.join("test");
        assert!(fs::symlink_metadata(&pointer).unwrap().is_symlink());
        let ledger: serde_json::Value =
            serde_json::from_slice(&fs::read(paths.state.join("setup-owned.json")).unwrap())
                .unwrap();
        let artifacts = ledger["artifacts"].as_object().unwrap();
        assert!(artifacts.contains_key(pointer.to_str().unwrap()));
        assert!(
            artifacts.contains_key(
                pointer
                    .canonicalize()
                    .unwrap()
                    .join("nested/rust_catalog.jsonl")
                    .to_str()
                    .unwrap()
            )
        );
        assert!(!artifacts.contains_key(cache.to_str().unwrap()));
        assert!(!artifacts.contains_key(cache.join("preexisting").to_str().unwrap()));
    }

    #[test]
    fn profile_prompt_reads_once_and_rejects_missing_or_oversized_input() {
        let mut output = Vec::new();
        let mut input = std::io::Cursor::new(b"/team/profile.toml\nnot-a-key\n");
        assert_eq!(
            read_setup_profile(&mut input, &mut output).unwrap(),
            "/team/profile.toml"
        );
        assert_eq!(output, b"Team profile URL or file: ");
        assert!(read_setup_profile(&mut std::io::Cursor::new(b"\n"), &mut Vec::new()).is_err());
        assert!(
            read_setup_profile(&mut std::io::Cursor::new("x".repeat(4097)), &mut Vec::new())
                .is_err()
        );
    }

    #[test]
    fn embedder_cli_limits_override_environment() {
        let cli = Cli::try_parse_from([
            "code-diver",
            "daemon",
            "--embedder-ctx",
            "5120",
            "--embedder-batch",
            "1024",
            "--embedder-ubatch",
            "512",
        ])
        .unwrap();
        let Some(Commands::Daemon(args)) = cli.command else {
            panic!("expected daemon");
        };
        let environment = runtime_config::environment_overrides(|key| {
            (key == "CODE_DIVER_EMBEDDER_CTX").then(|| "2048".into())
        })
        .unwrap();
        let config = runtime_config::effective_config(
            runtime_config::RuntimeConfig::default(),
            &environment,
            &runtime_flags(&args.runtime).unwrap(),
        )
        .unwrap();
        assert_eq!(config.daemon.embedder_ctx, 5120);
        assert_eq!(config.daemon.embedder_batch, 1024);
        assert_eq!(config.daemon.embedder_ubatch, 512);
    }

    #[test]
    fn runtime_explicit_lookup_stays_in_data_and_uses_manifest_paths() {
        let home = tempfile::tempdir().unwrap();
        let paths =
            runtime_config::RuntimePaths::from_env(runtime_config::Platform::MacOs, |key| {
                (key == "CODE_DIVER_HOME").then(|| home.path().display().to_string())
            })
            .unwrap();
        let mut config = runtime_config::RuntimeConfig::default();
        assert!(
            runtime_remote(&config, &paths)
                .unwrap_err()
                .contains("index_name")
        );
        config.profile.index_name = Some("default".into());
        let directory = paths.index_dir("default").unwrap();
        let projected = runtime_remote(&config, &paths).unwrap();
        assert_eq!(
            Path::new(projected["catalog"].as_str().unwrap()),
            directory.join("rust_catalog.jsonl")
        );
        fs::create_dir_all(&directory).unwrap();
        let mut metadata: serde_json::Value =
            serde_json::from_str(include_str!("../tests/fixtures/shared-index-metadata.json"))
                .unwrap();
        metadata["catalog"] = serde_json::json!("nested/catalog.jsonl");
        metadata["graph_path"] = serde_json::json!("nested/graph.jsonl");
        metadata["meta_ranker"]["file"] = serde_json::json!("nested/ranker.txt");
        metadata["files"]["nested/catalog.jsonl"] = serde_json::json!({});
        metadata["files"]["nested/graph.jsonl"] = serde_json::json!({});
        metadata["files"]["nested/ranker.txt"] = serde_json::json!({});
        fs::write(directory.join("index-metadata.json"), metadata.to_string()).unwrap();
        let projected = runtime_remote(&config, &paths).unwrap();
        assert_eq!(
            Path::new(projected["catalog"].as_str().unwrap()),
            directory
                .canonicalize()
                .unwrap()
                .join("nested/catalog.jsonl")
        );
        assert_eq!(
            Path::new(projected["graph_path"].as_str().unwrap()),
            directory.canonicalize().unwrap().join("nested/graph.jsonl")
        );
        assert_eq!(
            Path::new(projected["model"].as_str().unwrap()),
            directory.canonicalize().unwrap().join("nested/ranker.txt")
        );
    }

    #[test]
    fn remote_manifest_identity_does_not_fall_back_to_embedded() {
        let home = tempfile::tempdir().unwrap();
        let paths =
            runtime_config::RuntimePaths::from_env(runtime_config::Platform::MacOs, |key| {
                (key == "CODE_DIVER_HOME").then(|| home.path().display().to_string())
            })
            .unwrap();
        let mut config = runtime_config::RuntimeConfig::default();
        config.profile.model_manifest_url = Some("https://example.invalid/models.json".into());
        config.profile.index_name = Some("test".into());
        let projected = runtime_remote(&config, &paths).unwrap();
        assert!(projected["embedding"]["model"].is_null());
        assert!(projected["embedding"]["dimensions"].is_null());
        config.profile.embedding_model = Some("synthetic-model".into());
        config.profile.embedding_dimensions = Some(123);
        let projected = runtime_remote(&config, &paths).unwrap();
        assert_eq!(projected["embedding"]["model"], "synthetic-model");
        assert_eq!(projected["embedding"]["dimensions"], 123);
    }

    #[test]
    fn setup_snapshot_tracking_records_nested_artifacts() {
        let home = tempfile::tempdir().unwrap();
        let root = home.path().canonicalize().unwrap();
        let paths =
            runtime_config::RuntimePaths::from_env(runtime_config::Platform::MacOs, |key| {
                (key == "CODE_DIVER_HOME").then(|| root.display().to_string())
            })
            .unwrap();
        paths.ensure_dirs().unwrap();
        let options = setup::SetupOptions::new(
            paths.clone(),
            root.join("code-diver"),
            runtime_config::Platform::MacOs,
            501,
        );
        let snapshot = paths.data.join(".test-snapshots/version");
        fs::create_dir_all(snapshot.join("context")).unwrap();
        fs::write(snapshot.join("context/catalog.jsonl"), "catalog").unwrap();
        fs::write(snapshot.join("index-metadata.json"), "metadata").unwrap();
        fs::write(snapshot.join("preexisting.json"), "preserve").unwrap();
        let pointer = paths.data.join("test");
        record_created_artifacts(
            &options,
            &[
                update_index::CreatedArtifact {
                    path: snapshot.clone(),
                    kind: update_index::ArtifactKind::Directory,
                },
                update_index::CreatedArtifact {
                    path: snapshot.join("context"),
                    kind: update_index::ArtifactKind::Directory,
                },
                update_index::CreatedArtifact {
                    path: snapshot.join("context/catalog.jsonl"),
                    kind: update_index::ArtifactKind::File,
                },
                update_index::CreatedArtifact {
                    path: snapshot.join("index-metadata.json"),
                    kind: update_index::ArtifactKind::File,
                },
                update_index::CreatedArtifact {
                    path: pointer.clone(),
                    kind: update_index::ArtifactKind::Symlink {
                        target: snapshot.clone(),
                    },
                },
            ],
        )
        .unwrap();
        std::os::unix::fs::symlink(&snapshot, &pointer).unwrap();
        let ledger: serde_json::Value =
            serde_json::from_slice(&fs::read(paths.state.join("setup-owned.json")).unwrap())
                .unwrap();
        let artifacts = ledger["artifacts"].as_object().unwrap();
        assert_eq!(artifacts.len(), 5);
        assert!(artifacts.contains_key(pointer.to_str().unwrap()));
        assert!(!artifacts.contains_key(snapshot.join("preexisting.json").to_str().unwrap()));
        assert!(artifacts.contains_key(snapshot.join("context/catalog.jsonl").to_str().unwrap()));
        assert!(artifacts.contains_key(snapshot.join("index-metadata.json").to_str().unwrap()));
    }

    #[test]
    fn search_config_budget_tls_and_explicit_default_url_precedence() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(dir.path().join("catalog.jsonl"), "").unwrap();
        std::fs::write(dir.path().join("graph.jsonl"), "").unwrap();
        let path = dir.path().join("config.toml");
        std::fs::write(&path, "catalog='catalog.jsonl'\ngraph_path='graph.jsonl'\nca_bundle='ca.pem'\n[embedding]\nurl='https://config.invalid/embeddings'\nmax_input_tokens=64\ntoken_safety_margin=32\nmax_input_chars=2000\n").unwrap();
        let cli = Cli::try_parse_from([
            "code-diver",
            "search",
            "--config",
            path.to_str().unwrap(),
            "--embedding-url",
            "http://localhost:8001/v1/embeddings",
        ])
        .unwrap();
        let Some(Commands::Search(args)) = cli.command else {
            panic!("expected search");
        };
        let (config, _) = build_search_config(&args).unwrap();
        assert_eq!(config.embedding_url, "http://localhost:8001/v1/embeddings");
        assert_eq!(config.embedding_query_char_limit, 96);
        assert_eq!(
            config.ca_bundle,
            Some(dir.path().join("ca.pem").to_string_lossy().into_owned())
        );
        assert!(!config.insecure_skip_verify);
    }

    #[test]
    fn test_subcommand_search() {
        let cli =
            Cli::try_parse_from(["code-diver-search", "search", "--query", "test_query"]).unwrap();
        match cli.command {
            Some(Commands::Search(args)) => {
                assert_eq!(args.resolved_query(), Some("test_query".to_string()));
            }
            _ => panic!("Expected Search subcommand"),
        }
    }

    #[test]
    fn test_subcommand_info() {
        let cli = Cli::try_parse_from([
            "code-diver-search",
            "info",
            "--qdrant-url",
            "http://qdrant:6333",
        ])
        .unwrap();
        match cli.command {
            Some(Commands::Info(args)) => {
                assert_eq!(args.qdrant_url, "http://qdrant:6333");
            }
            _ => panic!("Expected Info subcommand"),
        }
    }

    #[test]
    fn test_subcommand_doctor() {
        let cli = Cli::try_parse_from([
            "code-diver-search",
            "doctor",
            "--embedding-url",
            "http://embed:8001",
        ])
        .unwrap();
        match cli.command {
            Some(Commands::Doctor(args)) => {
                assert_eq!(
                    args.search.embedding_url.as_deref(),
                    Some("http://embed:8001")
                );
            }
            _ => panic!("Expected Doctor subcommand"),
        }
    }

    #[test]
    fn test_subcommand_mcp() {
        let cli = Cli::try_parse_from(["code-diver-search", "mcp"]).unwrap();
        match cli.command {
            Some(Commands::Mcp(_)) => {}
            _ => panic!("Expected Mcp subcommand"),
        }
    }

    #[test]
    fn test_backward_compat_query_flag() {
        let cli = Cli::try_parse_from(["code-diver-search", "--query", "hello_world"]).unwrap();
        assert!(cli.command.is_none());
        assert_eq!(cli.search.resolved_query(), Some("hello_world".to_string()));
    }

    #[test]
    fn test_backward_compat_positional_query() {
        let cli = Cli::try_parse_from(["code-diver-search", "hello_world"]).unwrap();
        assert!(cli.command.is_none());
        assert_eq!(cli.search.resolved_query(), Some("hello_world".to_string()));
    }

    #[test]
    fn test_backward_compat_doctor_flag() {
        let cli = Cli::try_parse_from(["code-diver-search", "--doctor"]).unwrap();
        assert!(cli.command.is_none());
        assert!(cli.search.doctor);
    }
}
