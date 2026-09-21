mod bm25;
mod catalog;
mod embedding;
mod features;
mod fusion;
mod graph;
mod lightgbm;
mod pipeline;
mod types;

use std::fs;
use std::time::Instant;

use clap::Parser;

use crate::pipeline::{dump_features, dump_features_batch, init_search_context, search, SearchTimings};
use crate::types::{resolve_candidate_limit, resolve_second_pass, SearchConfig};

#[derive(Parser, Debug)]
#[command(name = "code-diver-search", about = "Pure Rust search pipeline for code-diver")]
struct Args {
    /// Query to search for
    #[arg(short, long)]
    query: Option<String>,

    /// Number of results to return
    #[arg(short, long, default_value = "10")]
    limit: usize,

    /// Path to catalog JSONL file
    #[arg(short = 'c', long)]
    catalog: String,

    /// Path to graph adjacency JSONL file
    #[arg(short = 'g', long)]
    graph: String,

    /// Path to LightGBM meta-ranker model (TXT format)
    #[arg(short = 'm', long)]
    model: Option<String>,

    /// Embedding service URL
    #[arg(short = 'e', long, default_value = "http://localhost:8001/v1/embeddings")]
    embedding_url: String,

    /// Qdrant service URL
    #[arg(short = 'd', long, default_value = "http://localhost:6333")]
    qdrant_url: String,

    /// CE rerank service URL
    #[arg(short = 'r', long, default_value = "http://localhost:18081/v1/rerank")]
    ce_url: String,

    /// CE rerank route mode: auto (use --ce-url, fall back v1<->legacy on 404/405),
    /// v1 (force .../v1/rerank), legacy (force .../rerank)
    #[arg(long, default_value = "auto")]
    ce_route: String,

    /// Per-request CE timeout in ms (Python CrossEncoderRerankConfig.timeout_ms parity)
    #[arg(long, default_value_t = 60000)]
    ce_timeout_ms: u64,

    /// Optional CE `model` body field (empty = omit; llama.cpp scores with the
    /// loaded model, vLLM-metal pooling with the served one)
    #[arg(long, default_value = "")]
    ce_model: String,

    /// Vector weight in H-91a manual fusion
    #[arg(long, default_value_t = 0.42)]
    vector_weight: f64,

    /// Lexical (BM25) weight in H-91a manual fusion
    #[arg(long, default_value_t = 0.26)]
    lexical_weight: f64,

    /// Path coverage weight in H-91a manual fusion
    #[arg(long, default_value_t = 0.12)]
    path_weight: f64,

    /// Symbol coverage weight in H-91a manual fusion
    #[arg(long, default_value_t = 0.10)]
    symbol_weight: f64,

    /// Graph propagation weight in H-91a manual fusion
    #[arg(long, default_value_t = 0.0)]
    graph_weight: f64,

    /// Symbol match weight in fusion
    #[arg(long, default_value_t = 0.10)]
    symbol_match_weight: f64,

    /// File vote weight in fusion
    #[arg(long, default_value_t = 0.06)]
    file_vote_weight: f64,

    /// Max NEW lexical (BM25-only) candidates admitted per query (H-91a: 1000)
    #[arg(long, default_value_t = 1000)]
    lexical_candidate_limit: usize,

    /// Rank CE candidates by raw logit instead of provider probability
    /// (Python default: false)
    #[arg(long, action = clap::ArgAction::SetTrue)]
    rank_by_raw_logits: bool,

    /// Break near-ties in CE scores by the fused base score (Python default: false)
    #[arg(long, action = clap::ArgAction::SetTrue)]
    tie_break_by_fused_score: bool,

    /// Tie width for --tie-break-by-fused-score (Python default: 1e-4)
    #[arg(long, default_value_t = 1e-4)]
    tie_break_epsilon: f64,

    /// Candidate limit for CE rerank (first pass window)
    #[arg(long, default_value = "34")]
    candidate_limit: usize,

    /// Alias for --candidate-limit: first-pass CE window size (1..=512).
    /// When present, wins over --candidate-limit.
    #[arg(long)]
    first_pass_cap: Option<usize>,

    /// Second-pass candidate cap (default 24, 0 = uncapped).
    /// Explicit value overrides --preset.
    #[arg(long)]
    second_pass_cap: Option<usize>,

    /// Second-pass score floor in [0.0, 1.0] (default 0.3).
    /// Explicit value overrides --preset.
    #[arg(long)]
    second_pass_floor: Option<f64>,

    /// Disable the selective second CE pass entirely.
    #[arg(long, default_value_t = false)]
    second_pass_disable: bool,

    /// Latency preset. Currently supported: "selective-strict"
    /// (second-pass cap 8, floor 0.15). No preset by default.
    #[arg(long)]
    preset: Option<String>,

    /// In-memory embedding cache size (number of query vectors, server mode).
    /// 0 = disabled (default, preserves current behaviour).
    #[arg(long, default_value_t = 0)]
    embed_cache_size: usize,

    /// Vector retrieval width before file selection and CE rerank
    #[arg(long, default_value = "360")]
    retrieval_limit: usize,

    /// Run in server mode (read queries from stdin)
    #[arg(short = 's', long)]
    server: bool,

    /// Benchmark mode: run N queries from a file
    #[arg(short = 'b', long)]
    bench: Option<String>,

    /// Number of benchmark queries to run
    #[arg(long, default_value = "20")]
    bench_n: usize,

    /// Dump features for training (outputs JSONL with 16 features per candidate)
    #[arg(long)]
    dump_features: bool,

    /// Expected paths (comma-separated) for label computation in dump_features mode
    #[arg(long)]
    expected: Option<String>,

    /// Query ID for dump_features output
    #[arg(long)]
    query_id: Option<String>,

    /// Dump features from a JSONL file (batch mode, much faster than per-query)
    #[arg(long)]
    dump_features_file: Option<String>,

    /// Quality mode: run queries from a JSONL file and output per-query results
    #[arg(long)]
    quality: Option<String>,

    /// Base path for reading file content (default: use catalog content)
    #[arg(long)]
    base_path: Option<String>,
}

#[tokio::main]
async fn main() -> Result<(), String> {
    let args = Args::parse();

    let model_path = args.model.clone();
    let meta_ranker_enabled = args.model.is_some();
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
    let config = SearchConfig {
        catalog_path: args.catalog,
        graph_path: args.graph,
        embedding_url: args.embedding_url,
        qdrant_url: args.qdrant_url,
        ce_url: args.ce_url,
        ce_route: args.ce_route,
        ce_timeout_ms: args.ce_timeout_ms,
        ce_model: args.ce_model,
        retrieval_limit: args.retrieval_limit,
        candidate_limit: args.candidate_limit,
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
        ce_meta_model_path: model_path.unwrap_or_default(),
        ce_meta_ranker_enabled: meta_ranker_enabled,
        base_path: args.base_path.unwrap_or_default(),
        embed_cache_size: args.embed_cache_size,
        ..SearchConfig::default()
    };

    eprintln!("Initializing search context...");
    let init_start = Instant::now();
    let ctx = init_search_context(config).await?;
    eprintln!("  Initialized in {:.2}s", init_start.elapsed().as_secs_f64());

    if let Some(features_file) = args.dump_features_file {
        dump_features_batch(&ctx, &features_file).await?;
    } else if args.dump_features {
        if let Some(query) = args.query {
            let expected: Vec<String> = args.expected
                .unwrap_or_default()
                .split(',')
                .filter(|s| !s.is_empty())
                .map(|s| s.trim().to_string())
                .collect();
            let query_id = args.query_id.unwrap_or_else(|| "unknown".to_string());
            dump_features(&ctx, &query, &query_id, &expected).await?;
        } else {
            return Err("--query is required with --dump-features".to_string());
        }
    } else if args.server {
        run_server(&ctx).await?;
    } else if let Some(bench_file) = args.bench {
        run_benchmark(&ctx, &bench_file, args.bench_n).await?;
    } else if let Some(query) = args.query {
        run_single(&ctx, &query, args.limit).await?;
    } else {
        // Interactive mode: read queries from stdin
        run_interactive(&ctx, args.limit).await?;
    }

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