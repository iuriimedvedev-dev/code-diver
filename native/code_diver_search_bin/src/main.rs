mod bm25;
mod catalog;
mod embedding;
mod features;
mod fusion;
mod graph;
mod index_update;
pub mod info;
mod lightgbm;
pub mod mcp;
mod pipeline;
mod types;

use std::fs;
use std::path::{Path, PathBuf};
use std::time::Instant;

use clap::Parser;

use crate::pipeline::{dump_features, dump_features_batch, init_search_context, search, SearchTimings};
use crate::types::{resolve_candidate_limit, resolve_second_pass, SearchConfig};

#[derive(Parser, Debug)]
#[command(
    name = "code-diver-search",
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
pub struct DoctorArgs {
    /// Qdrant service URL
    #[arg(short = 'd', long, default_value = "http://localhost:6333")]
    pub qdrant_url: String,

    /// Embedding service URL
    #[arg(short = 'e', long, default_value = "http://localhost:8001/v1/embeddings")]
    pub embedding_url: String,

    /// CE rerank service URL
    #[arg(short = 'r', long, default_value = "http://localhost:18081/v1/rerank")]
    pub ce_url: String,

    /// Path to catalog JSONL file
    #[arg(short = 'c', long)]
    pub catalog: Option<String>,

    /// Path to graph adjacency JSONL file
    #[arg(short = 'g', long)]
    pub graph: Option<String>,

    /// Path to LightGBM meta-ranker model
    #[arg(short = 'm', long)]
    pub model: Option<String>,
}

#[derive(clap::Args, Debug, Clone)]
pub struct McpArgs {
    #[command(flatten)]
    pub search: SearchArgs,
}

#[derive(clap::Args, Debug, Clone)]
pub struct SearchArgs {
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
    #[arg(short = 'e', long, default_value = "http://localhost:8001/v1/embeddings")]
    pub embedding_url: String,

    /// Qdrant service URL
    #[arg(short = 'd', long, default_value = "http://localhost:6333")]
    pub qdrant_url: String,

    /// CE rerank service URL
    #[arg(short = 'r', long, default_value = "http://localhost:18081/v1/rerank")]
    pub ce_url: String,

    /// Optional second-pass CE URL (mixed routing, e.g. vLLM-metal for long
    /// docs). Empty (default) = reuse --ce-url for both passes.
    #[arg(long, default_value = "")]
    pub second_ce_url: String,

    /// CE rerank route mode: auto (use --ce-url, fall back v1<->legacy on 404/405),
    /// v1 (force .../v1/rerank), legacy (force .../rerank)
    #[arg(long, default_value = "auto")]
    pub ce_route: String,

    /// Per-request CE timeout in ms (Python CrossEncoderRerankConfig.timeout_ms parity)
    #[arg(long, default_value_t = 60000)]
    pub ce_timeout_ms: u64,

    /// Optional CE `model` body field (empty = omit; llama.cpp scores with the
    /// loaded model, vLLM-metal pooling with the served one)
    #[arg(long, default_value = "")]
    pub ce_model: String,

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
    #[arg(long, default_value = "34")]
    pub candidate_limit: usize,

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
    #[arg(long, default_value = "intellij_h66b_budget_qwen")]
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

#[tokio::main]
async fn main() -> Result<(), String> {
    let cli = Cli::parse();

    match cli.command {
        Some(Commands::Doctor(args)) => {
            run_doctor(
                &args.qdrant_url,
                &args.embedding_url,
                &args.ce_url,
                args.catalog.as_deref(),
                args.graph.as_deref(),
                args.model.as_deref(),
            )
            .await
        }
        Some(Commands::Info(args)) => {
            let catalog_path = resolve_path(args.catalog.as_deref(), &[
                "artifacts/rust_catalog.jsonl",
                ".code-diver/rust_catalog.jsonl",
                "/tmp/rust_catalog.jsonl",
            ]);
            let graph_path = resolve_path(args.graph.as_deref(), &[
                "artifacts/rust_graph.jsonl",
                ".code-diver/rust_graph.jsonl",
                "/tmp/rust_graph.jsonl",
            ]);
            crate::info::run_info(catalog_path.as_deref(), graph_path.as_deref(), &args.qdrant_url).await
        }
        Some(Commands::Mcp(args)) => {
            run_mcp(args.search).await
        }
        Some(Commands::Search(args)) => {
            run_search_cli(args).await
        }
        None => {
            if cli.search.doctor {
                run_doctor(
                    &cli.search.qdrant_url,
                    &cli.search.embedding_url,
                    &cli.search.ce_url,
                    cli.search.catalog.as_deref(),
                    cli.search.graph.as_deref(),
                    cli.search.model.as_deref(),
                )
                .await
            } else if cli.search.index_update {
                run_index_update(&cli.search).await
            } else {
                run_search_cli(cli.search).await
            }
        }
    }
}

fn build_search_config(args: &SearchArgs) -> Result<(SearchConfig, PathBuf), String> {
    let catalog_path = resolve_path(args.catalog.as_deref(), &[
        "artifacts/rust_catalog.jsonl",
        ".code-diver/rust_catalog.jsonl",
        "/tmp/rust_catalog.jsonl",
    ])
    .ok_or_else(|| "Catalog file not found. Pass --catalog PATH or place at artifacts/rust_catalog.jsonl".to_string())?;

    let graph_path = resolve_path(args.graph.as_deref(), &[
        "artifacts/rust_graph.jsonl",
        ".code-diver/rust_graph.jsonl",
        "/tmp/rust_graph.jsonl",
    ])
    .ok_or_else(|| "Graph file not found. Pass --graph PATH or place at artifacts/rust_graph.jsonl".to_string())?;

    let model_path = resolve_path(args.model.as_deref(), &[
        "artifacts/ce_meta_ranker/ce_meta_ranker.lgb.txt",
        ".code-diver/models/ce_meta_ranker.lgb.txt",
        "models/ce_meta_ranker.lgb.txt",
    ]);

    let meta_ranker_enabled = model_path.is_some();
    let candidate_limit =
        resolve_candidate_limit(args.candidate_limit, args.first_pass_cap).map_err(|e| e.to_string())?;
    let (second_pass_enabled, second_pass_score_floor, second_pass_candidate_cap) = resolve_second_pass(
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

    let root_path = args.base_path
        .as_deref()
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."));

    let config = SearchConfig {
        catalog_path,
        graph_path,
        embedding_url: args.embedding_url.clone(),
        qdrant_url: args.qdrant_url.clone(),
        ce_url: args.ce_url.clone(),
        second_ce_url: args.second_ce_url.clone(),
        ce_route: args.ce_route.clone(),
        ce_timeout_ms: args.ce_timeout_ms,
        ce_model: args.ce_model.clone(),
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
        ce_meta_model_path: model_path.unwrap_or_default(),
        ce_meta_ranker_enabled: meta_ranker_enabled,
        base_path: args.base_path.clone().unwrap_or_default(),
        embed_cache_size: args.embed_cache_size,
        ..SearchConfig::default()
    };

    Ok((config, root_path))
}

async fn run_mcp(args: SearchArgs) -> Result<(), String> {
    let (config, root_path) = build_search_config(&args)?;
    let ctx = init_search_context(config).await?;
    let mcp_config = crate::mcp::McpConfig {
        ctx: &ctx,
        root_dir: &root_path,
    };
    crate::mcp::run_mcp_server(mcp_config).await
}

async fn run_search_cli(args: SearchArgs) -> Result<(), String> {
    if args.doctor {
        return run_doctor(
            &args.qdrant_url,
            &args.embedding_url,
            &args.ce_url,
            args.catalog.as_deref(),
            args.graph.as_deref(),
            args.model.as_deref(),
        )
        .await;
    }
    if args.index_update {
        return run_index_update(&args).await;
    }

    let (config, _root_path) = build_search_config(&args)?;

    eprintln!("Initializing search context...");
    let init_start = Instant::now();
    let ctx = init_search_context(config).await?;
    eprintln!("  Initialized in {:.2}s", init_start.elapsed().as_secs_f64());

    let query = args.resolved_query();

    if let Some(features_file) = args.dump_features_file {
        dump_features_batch(&ctx, &features_file).await?;
    } else if args.dump_features {
        if let Some(q) = query {
            let expected: Vec<String> = args.expected
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
    if let Some(arg) = cli_arg {
        if !arg.is_empty() {
            return Some(arg.to_string());
        }
    }
    for candidate in candidates {
        if Path::new(candidate).exists() {
            return Some(candidate.to_string());
        }
    }
    None
}

/// Doctor / Healthcheck command
async fn run_doctor(
    qdrant_url: &str,
    embedding_url: &str,
    ce_url: &str,
    catalog: Option<&str>,
    graph: Option<&str>,
    model: Option<&str>,
) -> Result<(), String> {
    eprintln!("=== code-diver doctor ===");
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(5))
        .build()
        .map_err(|e| e.to_string())?;

    // 1. Qdrant
    eprint!("Checking Qdrant ({})... ", qdrant_url);
    match client.get(format!("{}/collections", qdrant_url.trim_end_matches('/'))).send().await {
        Ok(resp) if resp.status().is_success() => eprintln!("OK (status {})", resp.status()),
        Ok(resp) => eprintln!("WARN: HTTP {}", resp.status()),
        Err(e) => eprintln!("FAIL: {}", e),
    }

    // 2. Embedding service
    let embed_health = embedding_url.replace("/v1/embeddings", "/v1/models");
    eprint!("Checking Embedding Service ({})... ", embed_health);
    match client.get(&embed_health).send().await {
        Ok(resp) if resp.status().is_success() => eprintln!("OK (status {})", resp.status()),
        Ok(resp) => eprintln!("WARN: HTTP {}", resp.status()),
        Err(e) => eprintln!("FAIL: {}", e),
    }

    // 3. CE Rerank service
    let ce_health = ce_url.replace("/v1/rerank", "/health").replace("/rerank", "/health");
    eprint!("Checking CE Rerank Service ({})... ", ce_health);
    match client.get(&ce_health).send().await {
        Ok(resp) if resp.status().is_success() => eprintln!("OK (status {})", resp.status()),
        Ok(resp) => eprintln!("WARN: HTTP {}", resp.status()),
        Err(e) => eprintln!("FAIL: {}", e),
    }

    // 4. Artifacts check
    eprintln!("\nChecking local artifacts:");
    let catalog_resolved = resolve_path(catalog, &[
        "artifacts/rust_catalog.jsonl",
        ".code-diver/rust_catalog.jsonl",
        "/tmp/rust_catalog.jsonl",
    ]);
    eprintln!("  Catalog: {:?}", catalog_resolved);

    let graph_resolved = resolve_path(graph, &[
        "artifacts/rust_graph.jsonl",
        ".code-diver/rust_graph.jsonl",
        "/tmp/rust_graph.jsonl",
    ]);
    eprintln!("  Graph:   {:?}", graph_resolved);

    let model_resolved = resolve_path(model, &[
        "artifacts/ce_meta_ranker/ce_meta_ranker.lgb.txt",
        ".code-diver/models/ce_meta_ranker.lgb.txt",
        "models/ce_meta_ranker.lgb.txt",
    ]);
    eprintln!("  Model:   {:?}", model_resolved);

    eprintln!("=========================");
    Ok(())
}

/// Incremental index update: diff --catalog against Qdrant, embed + upsert
/// only dirty items, delete removed points. Dry run unless --apply.
async fn run_index_update(args: &SearchArgs) -> Result<(), String> {
    use crate::catalog::load_catalog;
    use crate::embedding::embed_texts;
    use crate::index_update::{
        collection_dimensions, delete_points, diff_catalog, embed_text,
        scroll_indexed, upsert_points,
    };

    let resolved_catalog = resolve_path(args.catalog.as_deref(), &[
        "artifacts/rust_catalog.jsonl",
        ".code-diver/rust_catalog.jsonl",
        "/tmp/rust_catalog.jsonl",
    ])
    .ok_or_else(|| "--catalog is required or place at artifacts/rust_catalog.jsonl".to_string())?;

    let catalog_path = Path::new(&resolved_catalog);
    eprintln!("Loading catalog from: {}", catalog_path.display());
    let catalog = load_catalog(catalog_path)?;
    eprintln!("  Catalog items: {}", catalog.items.len());

    let http_client = reqwest::Client::builder()
        .pool_idle_timeout(std::time::Duration::from_secs(90))
        .pool_max_idle_per_host(32)
        .build()
        .map_err(|e| format!("HTTP client failed: {}", e))?;

    eprintln!("Scrolling collection: {}", args.qdrant_collection);
    let indexed = scroll_indexed(&http_client, &args.qdrant_url, &args.qdrant_collection).await?;
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

    let dimensions =
        collection_dimensions(&http_client, &args.qdrant_url, &args.qdrant_collection).await?;
    eprintln!("  Collection dimensions: {}", dimensions);

    let dirty: Vec<usize> = diff.added.iter().chain(diff.changed.iter()).copied().collect();
    if !dirty.is_empty() {
        let mut upserted = 0;
        for chunk in dirty.chunks(32) {
            let items: Vec<&crate::types::CatalogItem> =
                chunk.iter().map(|&i| &catalog.items[i]).collect();
            let texts: Vec<String> =
                items.iter().map(|it| embed_text(it, args.embed_max_chars)).collect();
            let vectors = embed_texts(&http_client, &args.embedding_url, &texts).await?;
            if vectors.first().map(|v| v.len()).unwrap_or(0) != dimensions {
                return Err(format!(
                    "Embedding dimension mismatch: got {}, collection has {}",
                    vectors.first().map(|v| v.len()).unwrap_or(0),
                    dimensions
                ));
            }
            upserted += upsert_points(
                &http_client,
                &args.qdrant_url,
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
            &args.qdrant_url,
            &args.qdrant_collection,
            &diff.deleted,
        )
        .await?;
        eprintln!("  Deleted {}", n);
    }

    let after = scroll_indexed(&http_client, &args.qdrant_url, &args.qdrant_collection).await?;
    eprintln!("Indexed points after: {}", after.len());
    Ok(())
}

async fn run_single(ctx: &pipeline::SearchContext, query: &str, limit: usize) -> Result<(), String> {
    eprintln!("Searching for: {}", query);
    let start = Instant::now();
    let (results, timings) = search(ctx, query, limit).await?;
    let wall_ms = start.elapsed().as_secs_f64() * 1000.0;

    println!("{}", serde_json::to_string_pretty(&serde_json::json!({
        "query": query,
        "results": results,
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
    })).unwrap_or_default());

    eprintln!("  {} results in {:.1}ms", results.len(), wall_ms);
    Ok(())
}

async fn run_interactive(ctx: &pipeline::SearchContext, limit: usize) -> Result<(), String> {
    eprintln!("Entering interactive mode. Type queries (one per line), Ctrl+D to exit.");
    let mut line = String::new();
    loop {
        line.clear();
        eprint!("> ");
        
        let bytes = std::io::stdin().read_line(&mut line).map_err(|e| e.to_string())?;
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
        let bytes = std::io::stdin().read_line(&mut line).map_err(|e| e.to_string())?;
        if bytes == 0 {
            break;
        }
        let line = line.trim();
        if line.is_empty() {
            continue;
        }

        // Parse JSON request
        let req: serde_json::Value = serde_json::from_str(line)
            .map_err(|e| format!("Invalid JSON: {}", e))?;
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
    let content = std::fs::read_to_string(path).map_err(|e| format!("Cannot read {}: {}", path, e))?;

    let mut queries: Vec<String> = Vec::new();
    for line in content.lines() {
        if line.trim().is_empty() {
            continue;
        }
        // Try to parse as JSON and extract query
        if let Ok(val) = serde_json::from_str::<serde_json::Value>(line) {
            if let Some(q) = val["query"].as_str() {
                queries.push(q.to_string());
                continue;
            }
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
                eprintln!("  [{}/{}] {:.0}ms, {} results", i + 1, queries.len(), elapsed, results.len());
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
        println!("{}", &summary_json);

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
    fn test_subcommand_search() {
        let cli = Cli::try_parse_from(["code-diver-search", "search", "--query", "test_query"]).unwrap();
        match cli.command {
            Some(Commands::Search(args)) => {
                assert_eq!(args.resolved_query(), Some("test_query".to_string()));
            }
            _ => panic!("Expected Search subcommand"),
        }
    }

    #[test]
    fn test_subcommand_info() {
        let cli = Cli::try_parse_from(["code-diver-search", "info", "--qdrant-url", "http://qdrant:6333"]).unwrap();
        match cli.command {
            Some(Commands::Info(args)) => {
                assert_eq!(args.qdrant_url, "http://qdrant:6333");
            }
            _ => panic!("Expected Info subcommand"),
        }
    }

    #[test]
    fn test_subcommand_doctor() {
        let cli = Cli::try_parse_from(["code-diver-search", "doctor", "--embedding-url", "http://embed:8001"]).unwrap();
        match cli.command {
            Some(Commands::Doctor(args)) => {
                assert_eq!(args.embedding_url, "http://embed:8001");
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
