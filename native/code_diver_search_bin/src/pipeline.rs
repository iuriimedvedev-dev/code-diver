use std::collections::HashMap;
use std::collections::HashSet;
use std::collections::VecDeque;
use std::fs;
use std::path::Path;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;

use crate::bm25::{bm25_scores, build_bm25_index, path_coverage_score, symbol_coverage_score, symbol_match_score};
use crate::catalog::{load_catalog, tokenize};
use crate::embedding::{ce_rerank_with_options, embed_query, vector_search, CeOptions, EMBED_MODEL};
use crate::features::{build_fan_in_degrees, extract_features};
use crate::fusion::{logit, normalize_scores, sort_by_ce, sort_by_fused, sort_by_meta, tie_break_by_fused};
use crate::graph::{load_graph_adjacency, propagate_scores};
use crate::lightgbm::{load_lightgbm_txt, predict};
use crate::types::{Candidate, Catalog, GraphAdjacency, LgbModel, MetaFeatures, SearchConfig, SearchResult};

/// Context: all data loaded once at startup.
pub struct SearchContext {
    pub catalog: Catalog,
    pub bm25_index: crate::types::Bm25Index,
    pub graph_adjacency: GraphAdjacency,
    pub fan_in_degrees: HashMap<String, f64>,
    pub meta_ranker: Option<LgbModel>,
    pub config: SearchConfig,
    pub http_client: reqwest::Client,
    /// In-memory LRU cache: query string -> embedding vector.
    /// Capacity 0 = disabled. Shared across server-mode queries via interior mutability.
    pub embed_cache: Mutex<EmbedCache>,
}

/// Bounded in-memory LRU for query embeddings.
///
/// Invalidation: entries are keyed by the exact query string and tagged with the
/// embedding URL + model they were fetched with; a URL/model change drops the cache.
pub struct EmbedCache {
    capacity: usize,
    embedding_url: String,
    model: String,
    entries: HashMap<String, Vec<f64>>,
    order: VecDeque<String>,
}

impl EmbedCache {
    pub fn new(capacity: usize, embedding_url: String, model: String) -> Self {
        Self {
            capacity,
            embedding_url,
            model,
            entries: HashMap::new(),
            order: VecDeque::new(),
        }
    }

    pub fn get(&mut self, url: &str, model: &str, query: &str) -> Option<Vec<f64>> {
        if self.capacity == 0 {
            return None;
        }
        if self.embedding_url != url || self.model != model {
            self.entries.clear();
            self.order.clear();
            self.embedding_url = url.to_string();
            self.model = model.to_string();
            return None;
        }
        let vector = self.entries.get(query)?.clone();
        // LRU touch: most-recently-used goes to the back.
        if let Some(pos) = self.order.iter().position(|q| q == query) {
            self.order.remove(pos);
        }
        self.order.push_back(query.to_string());
        Some(vector)
    }

    pub fn put(&mut self, query: &str, vector: Vec<f64>) {
        if self.capacity == 0 {
            return;
        }
        if self.entries.contains_key(query) {
            self.entries.insert(query.to_string(), vector);
            if let Some(pos) = self.order.iter().position(|q| q == query) {
                self.order.remove(pos);
            }
            self.order.push_back(query.to_string());
            return;
        }
        while self.entries.len() >= self.capacity {
            if let Some(oldest) = self.order.pop_front() {
                self.entries.remove(&oldest);
            } else {
                break;
            }
        }
        self.order.push_back(query.to_string());
        self.entries.insert(query.to_string(), vector);
    }

    #[allow(dead_code)]
    pub fn len(&self) -> usize {
        self.entries.len()
    }
}

/// Embed with the server-mode LRU cache in front. Cache disabled when
/// `embed_cache_size == 0` (default): behaviour identical to a direct call.
async fn cached_embed_query(ctx: &SearchContext, query: &str) -> Result<Vec<f64>, String> {
    if ctx.config.embed_cache_size > 0 {
        if let Ok(mut cache) = ctx.embed_cache.lock() {
            if let Some(vector) = cache.get(&ctx.config.embedding_url, EMBED_MODEL, query) {
                return Ok(vector);
            }
        }
    }
    let vector = embed_query(&ctx.http_client, &ctx.config.embedding_url, query).await?;
    if ctx.config.embed_cache_size > 0 {
        if let Ok(mut cache) = ctx.embed_cache.lock() {
            cache.put(query, vector.clone());
        }
    }
    Ok(vector)
}

/// Timings for performance measurement.
#[derive(Debug, Default)]
pub struct SearchTimings {
    pub embed_ms: f64,
    pub vector_search_ms: f64,
    pub bm25_ms: f64,
    pub graph_ms: f64,
    pub fusion_ms: f64,
    pub ce_first_pass_ms: f64,
    pub ce_second_pass_ms: f64,
    pub feature_extract_ms: f64,
    pub meta_predict_ms: f64,
    pub total_ms: f64,
}

/// Initialize the search context from config.
pub async fn init_search_context(config: SearchConfig) -> Result<SearchContext, String> {
    // One reusable client for the whole process (server/bench loops share it):
    // keep idle pooled connections alive so back-to-back queries skip TCP+TLS setup.
    let http_client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(120))
        .pool_idle_timeout(Duration::from_secs(90))
        .pool_max_idle_per_host(32)
        .build()
        .map_err(|e| format!("HTTP client: {}", e))?;

    eprintln!("Loading catalog from: {}", config.catalog_path);
    let catalog = load_catalog(Path::new(&config.catalog_path))?;
    eprintln!("  Loaded {} items", catalog.items.len());

    eprintln!("Building BM25 index...");
    let bm25_index = build_bm25_index(&catalog.items);
    eprintln!("  {} docs, {} terms", bm25_index.num_docs, bm25_index.postings.len());

    eprintln!("Loading graph adjacency from: {}", config.graph_path);
    let graph_adjacency = load_graph_adjacency(Path::new(&config.graph_path))?;
    eprintln!("  {} nodes", graph_adjacency.edges.len());

    eprintln!("Building fan-in degrees from graph adjacency...");
    let fan_in_degrees = build_fan_in_degrees(&graph_adjacency, &catalog.by_path);

    let meta_ranker = if config.ce_meta_ranker_enabled && !config.ce_meta_model_path.is_empty() {
        let model_path = Path::new(&config.ce_meta_model_path);
        if model_path.exists() {
            eprintln!("Loading meta-ranker model from: {}", config.ce_meta_model_path);
            match load_lightgbm_txt(model_path) {
                Ok(model) => {
                    eprintln!("  {} trees, {} features", model.num_trees, model.num_features);
                    Some(model)
                }
                Err(e) => {
                    eprintln!("  WARNING: Failed to load model: {}", e);
                    None
                }
            }
        } else {
            eprintln!("  WARNING: Model not found at {}", config.ce_meta_model_path);
            None
        }
    } else {
        None
    };

    Ok(SearchContext {
        catalog,
        bm25_index,
        graph_adjacency,
        fan_in_degrees,
        meta_ranker,
        embed_cache: Mutex::new(EmbedCache::new(
            config.embed_cache_size,
            config.embedding_url.clone(),
            EMBED_MODEL.to_string(),
        )),
        config,
        http_client,
    })
}

/// Shared retrieval and CE pipeline for inference and feature export.
async fn prepare_candidates(
    ctx: &SearchContext,
    query: &str,
) -> Result<(Vec<Candidate>, SearchTimings), String> {
    let start = Instant::now();
    let mut timings = SearchTimings::default();

    // Step 1: Embed the query (server-mode LRU cache in front when enabled)
    let t0 = Instant::now();
    let query_vector = cached_embed_query(ctx, query).await?;
    timings.embed_ms = t0.elapsed().as_secs_f64() * 1000.0;

    let query_terms = tokenize(query);

    // Step 2: Vector search via Qdrant
    let t0 = Instant::now();
    let fetch_limit = ctx.config.retrieval_limit;
    let qdrant_collection = "intellij_h66b_budget_qwen";
    let vector_results = vector_search(
        &ctx.http_client,
        &ctx.config.qdrant_url,
        qdrant_collection,
        &query_vector,
        fetch_limit,
    )
    .await?;
    timings.vector_search_ms = t0.elapsed().as_secs_f64() * 1000.0;

    // Build candidate map from vector results
    let mut candidates: HashMap<String, Candidate> = HashMap::new();
    for (item_id, path, score) in &vector_results {
        let (title, content) = if let Some(indices) = ctx.catalog.by_path.get(path) {
            indices.first().map(|&idx| {
                let item = &ctx.catalog.items[idx];
                (
                    item.name.clone(),
                    if item.content.is_empty() { None } else { Some(item.content.clone()) },
                )
            }).unwrap_or_default()
        } else {
            (String::new(), None)
        };
        candidates.entry(item_id.clone()).or_insert(Candidate {
            item_id: item_id.clone(),
            path: path.clone(),
            title,
            content,
            vector_score: *score,
            ..Default::default()
        });
    }

    // Step 3: BM25 scoring for all candidates
    let t0 = Instant::now();
    let bm25_raw = bm25_scores(&ctx.bm25_index, &query_terms, 1.2, 0.75);
    timings.bm25_ms = t0.elapsed().as_secs_f64() * 1000.0;

    // Normalize BM25 scores
    let mut bm25_normalized = bm25_raw.clone();
    normalize_scores(&mut bm25_normalized);

    // Merge BM25 scores into candidates
    for (doc_id, score) in &bm25_normalized {
        if let Some(candidate) = candidates.get_mut(doc_id) {
            candidate.lexical_score = *score;
        }
    }

    // Step 3b: admit BM25-only candidates (Python HybridRetrievalStrategy parity:
    // lexical_candidates merged into scores up to lexical_candidate_limit).
    admit_lexical_candidates(
        &mut candidates,
        &bm25_normalized,
        &ctx.catalog,
        &query_terms,
        ctx.config.lexical_candidate_limit,
    );

    // Also compute path/symbol/symbol_match scores from separate coverage (Python champion parity)
    // Python HybridCandidateScorer.score() computes each field separately:
    //   path_score = path_coverage
    //   symbol_score = symbol_coverage
    //   symbol_match_score = _symbol_match_score(item, profile)
    // lexical_score stays as BM25 (from step 3 above), which matches Python champion.
    for (_doc_id, candidate) in &mut candidates {
        let item = ctx
            .catalog
            .by_id
            .get(&candidate.item_id)
            .map(|&idx| &ctx.catalog.items[idx])
            .or_else(|| {
                ctx.catalog
                    .by_path
                    .get(&candidate.path)
                    .and_then(|indices| indices.first().map(|&idx| &ctx.catalog.items[idx]))
            });
        if let Some(item) = item {
            candidate.path_score = path_coverage_score(item, &query_terms);
            candidate.symbol_score = symbol_coverage_score(item, &query_terms);
            candidate.symbol_match_score = symbol_match_score(item, &query_terms);
        }
    }

    // Step 4: Graph propagation
    let t0 = Instant::now();
    let mut seed_scores: HashMap<String, f64> = HashMap::new();
    for (_doc_id, candidate) in &candidates {
        seed_scores.insert(candidate.path.clone(), candidate.vector_score + candidate.lexical_score);
    }
    let propagated = if ctx.config.graph_weight > 0.0 {
        propagate_scores(
            &ctx.graph_adjacency,
            &seed_scores,
            ctx.config.graph_depth,
            ctx.config.graph_decay,
            140,
            ctx.config.graph_neighbor_limit,
        )
    } else {
        HashMap::new()
    };
    timings.graph_ms = t0.elapsed().as_secs_f64() * 1000.0;

    // Merge graph scores: update ALL candidates matching the path
    for (path, score) in &propagated {
        for candidate in candidates.values_mut() {
            if candidate.path == *path {
                candidate.graph_score = *score;
            }
        }
    }

    // Step 5: Fuse scores
    let t0 = Instant::now();
    let mut candidates_vec: Vec<Candidate> = candidates.into_values().collect();
    // File-level consensus vote (Python _apply_file_vote_scores parity).
    apply_file_vote_scores(&mut candidates_vec, &ctx.config);
    for candidate in &mut candidates_vec {
        candidate.fused_score = candidate.vector_score * ctx.config.vector_weight
            + candidate.lexical_score * ctx.config.lexical_weight
            + candidate.path_score * ctx.config.path_weight
            + candidate.symbol_score * ctx.config.symbol_weight
            + candidate.symbol_match_score * ctx.config.symbol_match_weight
            + candidate.graph_score * ctx.config.graph_weight
            + candidate.file_vote_score * ctx.config.file_vote_weight;
    }
    let mut rerank_candidates = select_ce_candidates(candidates_vec, ctx.config.candidate_limit);
    timings.fusion_ms = t0.elapsed().as_secs_f64() * 1000.0;

    if rerank_candidates.is_empty() {
        return Ok((vec![], timings));
    }

    // Set base fused ranks
    for (i, candidate) in rerank_candidates.iter_mut().enumerate() {
        candidate.base_fused_rank = i;
    }

    // Step 6: CE first pass rerank
    let t0 = Instant::now();
    let documents: Vec<String> = rerank_candidates
        .iter()
        .map(|c| build_document(c, &ctx.config))
        .collect();
    let ce_options = ce_options_from_config(&ctx.config);
    let ce_scores =
        ce_rerank_with_options(&ctx.http_client, &ctx.config.ce_url, &ce_options, query, &documents)
            .await?;
    timings.ce_first_pass_ms = t0.elapsed().as_secs_f64() * 1000.0;

    for (i, score) in ce_scores.iter().enumerate() {
        if i < rerank_candidates.len() {
            rerank_candidates[i].ce_score = *score;
            rerank_candidates[i].ce_score_final = *score;
            rerank_candidates[i].ce_index = i;
        }
    }

    sort_by_ce(&mut rerank_candidates);

    // Set CE ranks
    for (i, candidate) in rerank_candidates.iter_mut().enumerate() {
        candidate.ce_rank = i;
    }

    // Step 7: CE second pass for low-scoring candidates
    let t0 = Instant::now();
    if ctx.config.second_pass_enabled {
        let retry_indices = second_pass_indices(&rerank_candidates, &ctx.config);

        if !retry_indices.is_empty() {
            // Build the long documents for second pass
            let retry_docs: Vec<String> = retry_indices
                .iter()
                .map(|&i| {
                    let c = &rerank_candidates[i];
                    build_long_document(c, &ctx.config)
                })
                .collect();

            if !retry_docs.is_empty() {
                let second_ce_url = if ctx.config.second_ce_url.is_empty() {
                    ctx.config.ce_url.as_str()
                } else {
                    ctx.config.second_ce_url.as_str()
                };
                match ce_rerank_with_options(
                    &ctx.http_client,
                    second_ce_url,
                    &ce_options,
                    query,
                    &retry_docs,
                )
                .await
                {
                    Ok(second_scores) => {
                        for (j, &idx) in retry_indices.iter().enumerate() {
                            if j < second_scores.len() {
                                let second_score = second_scores[j];
                                if second_score > rerank_candidates[idx].ce_score_final {
                                    rerank_candidates[idx].ce_score_final = second_score;
                                }
                            }
                        }
                    }
                    Err(e) => {
                        eprintln!("  WARNING: Second CE pass failed: {}", e);
                    }
                }
            }
        }
    }
    timings.ce_second_pass_ms = t0.elapsed().as_secs_f64() * 1000.0;

    // Step 8: Apply ranking adjustments (logit, tie-break)
    finalize_ce_candidates(&mut rerank_candidates, &ctx.config);

    timings.total_ms = start.elapsed().as_secs_f64() * 1000.0;
    Ok((rerank_candidates, timings))
}

/// Perform a single search query.
pub async fn search(
    ctx: &SearchContext,
    query: &str,
    limit: usize,
) -> Result<(Vec<SearchResult>, SearchTimings), String> {
    let start = Instant::now();
    let (mut rerank_candidates, mut timings) = prepare_candidates(ctx, query).await?;

    // Step 9: Apply meta-ranker
    let t0 = Instant::now();
    if let Some(ref model) = ctx.meta_ranker {
        let feature_vecs: Vec<Vec<f64>> = candidate_features(
            &rerank_candidates, query, &ctx.fan_in_degrees,
        ).iter().map(MetaFeatures::to_vec).collect();

        timings.feature_extract_ms = t0.elapsed().as_secs_f64() * 1000.0;

        let t1 = Instant::now();
        let meta_scores = predict(model, &feature_vecs);
        timings.meta_predict_ms = t1.elapsed().as_secs_f64() * 1000.0;

        for (i, score) in meta_scores.iter().enumerate() {
            if i < rerank_candidates.len() {
                rerank_candidates[i].meta_score = *score;
            }
        }

        sort_by_meta(&mut rerank_candidates);
    }

    timings.total_ms = start.elapsed().as_secs_f64() * 1000.0;

    // Build final results
    let results: Vec<SearchResult> = rerank_candidates
        .into_iter()
        .take(limit)
        .map(|c| SearchResult {
            item_id: c.item_id,
            path: c.path,
            score: c.meta_score.max(c.ce_score_final).max(c.fused_score),
            ce_score: Some(c.ce_score_final),
            meta_score: if c.meta_score != 0.0 { Some(c.meta_score) } else { None },
        })
        .collect();

    Ok((results, timings))
}

// ============================================================================
// Feature dumping for meta-ranker retraining
// ============================================================================

/// Run the full pipeline and dump features for each candidate as JSONL to stdout.
/// Each line: {"query_id": "...", "query": "...", "candidate_path": "...", "label": 0/1,
///   "ce_score": ..., "ce_rank": ..., "fan_in_prior": ..., "role_prior": ...,
///   "base_fused_score": ..., "base_fused_rank": ..., "lexical_overlap": ...,
///   "path_depth": ..., "filename_len": ..., "is_test": ...,
///   "ext_java": ..., "ext_kt": ..., "ext_xml": ..., "ext_md": ...,
///   "query_term_count": ..., "dir_proximity": ...}
pub async fn dump_features(
    ctx: &SearchContext,
    query: &str,
    query_id: &str,
    expected: &[String],
) -> Result<(), String> {
    let expected_set: HashSet<String> = expected.iter().cloned().collect();
    dump_features_single(ctx, query, query_id, &expected_set).await.map(|_| ())
}

/// Admit BM25-only candidates that vector search missed.
///
/// Python parity (`HybridRetrievalStrategy.collect_rank_context` + `_lexical_candidates`):
/// the top `lexical_candidate_limit` lexical hits are merged into the score map with
/// no cap on the combined total. `lexical_limit` therefore bounds only the number of
/// NEW admissions here, not `candidates.len()`.
#[allow(dead_code)]
pub fn admit_lexical_candidates(
    candidates: &mut HashMap<String, Candidate>,
    bm25_normalized: &HashMap<String, f64>,
    catalog: &Catalog,
    query_terms: &[String],
    lexical_limit: usize,
) {
    let mut sorted_bm25: Vec<(&String, &f64)> = bm25_normalized.iter().collect();
    sorted_bm25.sort_by(|a, b| {
        b.1.partial_cmp(a.1)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| a.0.cmp(b.0))
    });
    let mut admitted = 0usize;
    for (doc_id, score) in sorted_bm25 {
        if admitted >= lexical_limit {
            break;
        }
        if *score <= 0.0 {
            continue;
        }
        if !candidates.contains_key(doc_id) {
            if let Some(&idx) = catalog.by_id.get(doc_id) {
                let item = &catalog.items[idx];
                let content = if item.content.is_empty() {
                    None
                } else {
                    Some(item.content.clone())
                };
                let path_score = path_coverage_score(item, query_terms);
                let symbol_score = symbol_coverage_score(item, query_terms);
                let symbol_match_score = symbol_match_score(item, query_terms);
                candidates.insert(
                    doc_id.clone(),
                    Candidate {
                        item_id: doc_id.clone(),
                        path: item.path.clone(),
                        title: item.name.clone(),
                        content,
                        vector_score: 0.0,
                        lexical_score: *score,
                        path_score,
                        symbol_score,
                        symbol_match_score,
                        ..Default::default()
                    },
                );
                admitted += 1;
            }
        }
    }
}

#[allow(dead_code)]
pub fn apply_file_vote_scores(candidates: &mut [Candidate], config: &SearchConfig) {
    if candidates.is_empty() {
        return;
    }

    let mut by_path: HashMap<&str, Vec<f64>> = HashMap::new();
    for cand in candidates.iter() {
        let base_total = cand.vector_score * config.vector_weight
            + cand.lexical_score * config.lexical_weight
            + cand.path_score * config.path_weight
            + cand.symbol_score * config.symbol_weight
            + cand.symbol_match_score * config.symbol_match_weight
            + cand.graph_score * config.graph_weight;
        by_path.entry(cand.path.as_str()).or_default().push(base_total);
    }

    let mut raw_votes: HashMap<String, f64> = HashMap::with_capacity(by_path.len());
    for (path, mut scores) in by_path {
        scores.sort_by(|a, b| b.partial_cmp(a).unwrap_or(std::cmp::Ordering::Equal));
        let vote: f64 = scores
            .iter()
            .take(4)
            .enumerate()
            .map(|(i, &score)| score * 0.5_f64.powi(i as i32))
            .sum();
        raw_votes.insert(path.to_string(), vote);
    }

    normalize_scores(&mut raw_votes);

    for cand in candidates.iter_mut() {
        cand.file_vote_score = raw_votes.get(&cand.path).copied().unwrap_or(0.0);
    }
}

fn select_ce_candidates(mut candidates: Vec<Candidate>, limit: usize) -> Vec<Candidate> {
    // Deterministic fallback for equal fused scores from HashMap iteration.
    candidates.sort_by(|a, b| a.path.cmp(&b.path).then(a.item_id.cmp(&b.item_id)));
    sort_by_fused(&mut candidates);
    // Keep the strongest representative per file before spending CE slots.
    let mut seen = HashSet::new();
    candidates.retain(|candidate| seen.insert(candidate.path.clone()));
    candidates.truncate(limit);
    candidates
}

fn candidate_features(
    candidates: &[Candidate],
    query: &str,
    fan_in_degrees: &HashMap<String, f64>,
) -> Vec<MetaFeatures> {
    let query_terms = crate::features::query_terms(query);
    let query_term_set: HashSet<String> = query_terms.iter().cloned().collect();
    let max_fan_in = candidates.iter()
        .filter_map(|c| fan_in_degrees.get(&c.path)).copied()
        .fold(0.0, f64::max);
    candidates.iter().map(|candidate| extract_features(
        candidate, &query_terms, &query_term_set, query_terms.len() as f64,
        max_fan_in, fan_in_degrees,
    )).collect()
}

fn finalize_ce_candidates(candidates: &mut Vec<Candidate>, config: &SearchConfig) {
    for candidate in candidates.iter_mut() {
        if config.rank_by_raw_logits {
            candidate.ce_score_final = logit(candidate.ce_score_final);
        }
        candidate.ce_score = candidate.ce_score_final;
    }
    sort_by_ce(candidates);
    if config.tie_break_by_fused_score {
        tie_break_by_fused(candidates, config.tie_break_epsilon);
    }
    for (rank, candidate) in candidates.iter_mut().enumerate() {
        // Python inference builds both rank features from the adjusted CE order.
        candidate.ce_rank = rank;
        candidate.base_fused_rank = rank;
    }
}

/// Build per-request CE options from the search config (route mode, timeout,
/// optional model field). The CE URL default is untouched; only the transport
/// behavior is configured here.
fn ce_options_from_config(config: &SearchConfig) -> CeOptions {
    CeOptions {
        route_mode: config.ce_route.clone(),
        timeout_ms: config.ce_timeout_ms,
        model: config.ce_model.clone(),
    }
}

fn second_pass_indices(candidates: &[Candidate], config: &SearchConfig) -> Vec<usize> {
    let mut indices: Vec<usize> = candidates.iter().enumerate()
        .filter(|(_, c)| c.ce_score < config.second_pass_score_floor)
        .map(|(i, _)| i).collect();
    let cap = config.second_pass_candidate_cap;
    if cap > 0 && indices.len() > cap {
        indices.sort_by_key(|&i| candidates[i].ce_index);
        indices.truncate(cap);
    }
    indices
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn embed_cache_disabled_returns_none() {
        let mut cache = EmbedCache::new(0, "http://x".into(), "m".into());
        cache.put("q", vec![1.0]);
        assert_eq!(cache.len(), 0);
        assert!(cache.get("http://x", "m", "q").is_none());
    }

    #[test]
    fn embed_cache_hit_evicts_lru() {
        let mut cache = EmbedCache::new(2, "http://x".into(), "m".into());
        cache.put("a", vec![1.0]);
        cache.put("b", vec![2.0]);
        // Touch "a" so "b" becomes the eviction victim.
        assert_eq!(cache.get("http://x", "m", "a"), Some(vec![1.0]));
        cache.put("c", vec![3.0]);
        assert_eq!(cache.len(), 2);
        assert!(cache.get("http://x", "m", "b").is_none());
        assert_eq!(cache.get("http://x", "m", "a"), Some(vec![1.0]));
        assert_eq!(cache.get("http://x", "m", "c"), Some(vec![3.0]));
    }

    #[test]
    fn embed_cache_invalidates_on_url_or_model_change() {
        let mut cache = EmbedCache::new(4, "http://x".into(), "m1".into());
        cache.put("q", vec![1.0]);
        assert!(cache.get("http://other", "m1", "q").is_none());
        assert_eq!(cache.len(), 0);
        cache.put("q", vec![1.0]);
        assert!(cache.get("http://other", "m2", "q").is_none());
        assert_eq!(cache.len(), 0);
        cache.put("q", vec![1.0]);
        assert_eq!(cache.get("http://other", "m2", "q"), Some(vec![1.0]));
    }

    #[test]
    fn duplicate_paths_do_not_consume_ce_slots() {
        let candidates = vec![
            Candidate { path: "a.rs".into(), fused_score: 3.0, ..Default::default() },
            Candidate { path: "a.rs".into(), fused_score: 2.0, ..Default::default() },
            Candidate { path: "b.rs".into(), fused_score: 1.0, ..Default::default() },
        ];
        let selected = select_ce_candidates(candidates, 2);
        assert_eq!(selected.iter().map(|c| c.path.as_str()).collect::<Vec<_>>(), vec!["a.rs", "b.rs"]);
        assert_eq!(selected[0].fused_score, 3.0);
    }

    #[test]
    fn capped_retry_uses_original_candidate_index() {
        let candidates = vec![
            Candidate { ce_score: 0.2, ce_index: 2, ..Default::default() },
            Candidate { ce_score: 0.1, ce_index: 0, ..Default::default() },
            Candidate { ce_score: 0.05, ce_index: 1, ..Default::default() },
        ];
        let config = SearchConfig { second_pass_candidate_cap: 1, ..Default::default() };
        assert_eq!(second_pass_indices(&candidates, &config), vec![1]);
    }

    #[test]
    fn uncapped_retry_preserves_order_and_excludes_score_floor() {
        let candidates = vec![
            Candidate { ce_score: 0.3, ce_index: 1, ..Default::default() },
            Candidate { ce_score: 0.2, ce_index: 2, ..Default::default() },
            Candidate { ce_score: 0.1, ce_index: 0, ..Default::default() },
        ];
        let config = SearchConfig { second_pass_candidate_cap: 0, ..Default::default() };
        assert_eq!(second_pass_indices(&candidates, &config), vec![1, 2]);
    }

    #[test]
    fn empty_and_zero_candidate_windows_are_safe() {
        let mut candidates = select_ce_candidates(vec![Candidate::default()], 0);
        finalize_ce_candidates(&mut candidates, &SearchConfig::default());
        assert!(candidates.is_empty());
        assert!(candidate_features(&candidates, "", &HashMap::new()).is_empty());
        assert!(select_ce_candidates(vec![], 34).is_empty());
        let config = SearchConfig::default();
        assert_eq!((config.retrieval_limit, config.candidate_limit), (360, 34));
    }

    #[test]
    fn equal_fused_scores_have_deterministic_file_selection() {
        let candidates = vec![
            Candidate { path: "b.rs".into(), fused_score: 1.0, ..Default::default() },
            Candidate { path: "a.rs".into(), fused_score: 1.0, ..Default::default() },
        ];
        let mut reversed = candidates.clone();
        reversed.reverse();
        assert_eq!(select_ce_candidates(candidates, 1)[0].path, "a.rs");
        assert_eq!(select_ce_candidates(reversed, 1)[0].path, "a.rs");
    }

    #[test]
    fn second_pass_improvement_controls_final_order_and_rank_features() {
        let mut candidates = vec![
            Candidate { path: "first.rs".into(), ce_score: 0.8, ce_score_final: 0.8,
                ce_index: 1, ce_rank: 0, base_fused_rank: 1, ..Default::default() },
            Candidate { path: "rescued.rs".into(), ce_score: 0.1, ce_score_final: 0.9,
                ce_index: 0, ce_rank: 1, base_fused_rank: 0, ..Default::default() },
        ];
        let config = SearchConfig { rank_by_raw_logits: false, tie_break_by_fused_score: false,
            ..Default::default() };
        finalize_ce_candidates(&mut candidates, &config);
        assert_eq!(candidates[0].path, "rescued.rs");
        for (rank, candidate) in candidates.iter().enumerate() {
            assert_eq!(candidate.ce_rank, rank);
            assert_eq!(candidate.base_fused_rank, rank);
            assert_eq!(candidate.ce_score, candidate.ce_score_final);
        }
        assert_eq!(candidates[0].ce_index, 0);
        let features = candidate_features(&candidates, "rescued", &HashMap::new());
        for (rank, row) in features.iter().enumerate() {
            let values = row.to_vec();
            assert_eq!(values.len(), 16);
            assert_eq!(values[0], candidates[rank].ce_score_final);
            assert_eq!(values[1], rank as f64);
            assert_eq!(values[5], rank as f64);
        }
    }

    #[test]
    fn final_ties_refresh_both_ranks_after_logit() {
        let mut candidates = vec![
            Candidate { ce_score: 0.9, ce_score_final: 0.9, fused_score: 1.0,
                ce_rank: 0, base_fused_rank: 0, ..Default::default() },
            Candidate { ce_score: 0.1, ce_score_final: 0.9, fused_score: 2.0,
                ce_rank: 1, base_fused_rank: 1, ..Default::default() },
        ];
        let config = SearchConfig { rank_by_raw_logits: true, tie_break_by_fused_score: true,
            tie_break_epsilon: 1e-6, ..Default::default() };
        finalize_ce_candidates(&mut candidates, &config);
        assert_eq!(candidates[0].fused_score, 2.0);
        assert_eq!(candidates[0].ce_rank, 0);
        assert_eq!(candidates[0].base_fused_rank, 0);
        assert!((candidates[0].ce_score - logit(0.9)).abs() < 1e-10);
    }

    #[test]
    fn test_apply_file_vote_scores_weighting_and_norm() {
        let mut candidates = vec![
            // path a.rs: 5 candidates with base totals 10, 8, 6, 4, 2
            Candidate {
                path: "a.rs".into(),
                vector_score: 10.0,
                ..Default::default()
            },
            Candidate {
                path: "a.rs".into(),
                vector_score: 8.0,
                ..Default::default()
            },
            Candidate {
                path: "a.rs".into(),
                vector_score: 6.0,
                ..Default::default()
            },
            Candidate {
                path: "a.rs".into(),
                vector_score: 4.0,
                ..Default::default()
            },
            Candidate {
                path: "a.rs".into(),
                vector_score: 2.0,
                ..Default::default()
            },
            // path b.rs: 1 candidate with base total 4
            Candidate {
                path: "b.rs".into(),
                vector_score: 4.0,
                ..Default::default()
            },
        ];
        let config = SearchConfig {
            vector_weight: 1.0,
            lexical_weight: 0.0,
            path_weight: 0.0,
            symbol_weight: 0.0,
            symbol_match_weight: 0.0,
            graph_weight: 0.0,
            file_vote_weight: 0.06,
            ..Default::default()
        };
        apply_file_vote_scores(&mut candidates, &config);
        // Top 4 for a.rs: 10*1.0 + 8*0.5 + 6*0.25 + 4*0.125 = 10 + 4 + 1.5 + 0.5 = 16.0
        // Top 4 for b.rs: 4*1.0 = 4.0
        // Normalized: a.rs = (16 - 4) / 12 = 1.0, b.rs = (4 - 4) / 12 = 0.0
        for c in &candidates {
            if c.path == "a.rs" {
                assert!((c.file_vote_score - 1.0).abs() < 1e-6);
            } else if c.path == "b.rs" {
                assert!((c.file_vote_score - 0.0).abs() < 1e-6);
            }
        }
    }

    #[test]
    fn test_graph_propagation_updates_all_candidates_on_path() {
        let mut candidates = HashMap::new();
        candidates.insert(
            "doc1".to_string(),
            Candidate {
                item_id: "doc1".into(),
                path: "shared.rs".into(),
                ..Default::default()
            },
        );
        candidates.insert(
            "doc2".to_string(),
            Candidate {
                item_id: "doc2".into(),
                path: "shared.rs".into(),
                ..Default::default()
            },
        );
        candidates.insert(
            "doc3".to_string(),
            Candidate {
                item_id: "doc3".into(),
                path: "other.rs".into(),
                ..Default::default()
            },
        );

        let mut propagated = HashMap::new();
        propagated.insert("shared.rs".to_string(), 0.75);

        for (path, score) in &propagated {
            for candidate in candidates.values_mut() {
                if candidate.path == *path {
                    candidate.graph_score = *score;
                }
            }
        }

        assert_eq!(candidates.get("doc1").unwrap().graph_score, 0.75);
        assert_eq!(candidates.get("doc2").unwrap().graph_score, 0.75);
        assert_eq!(candidates.get("doc3").unwrap().graph_score, 0.0);
    }

    #[test]
    fn test_admit_lexical_candidates() {
        let mut candidates = HashMap::new();
        candidates.insert(
            "vec_doc".to_string(),
            Candidate {
                item_id: "vec_doc".into(),
                path: "src/vec.rs".into(),
                vector_score: 0.9,
                lexical_score: 0.1,
                ..Default::default()
            },
        );

        let mut bm25 = HashMap::new();
        bm25.insert("vec_doc".to_string(), 0.1);
        bm25.insert("lex_doc1".to_string(), 0.8);
        bm25.insert("lex_doc2".to_string(), 0.95);
        bm25.insert("zero_doc".to_string(), 0.0);
        bm25.insert("missing_doc".to_string(), 0.7);

        let mut catalog_by_id = HashMap::new();
        catalog_by_id.insert("lex_doc1".to_string(), 0);
        catalog_by_id.insert("lex_doc2".to_string(), 1);

        let catalog = Catalog {
            items: vec![
                crate::types::CatalogItem {
                    id: "lex_doc1".into(),
                    path: "src/lex1.rs".into(),
                    name: "lex1".into(),
                    ..Default::default()
                },
                crate::types::CatalogItem {
                    id: "lex_doc2".into(),
                    path: "src/lex2.rs".into(),
                    name: "lex2".into(),
                    ..Default::default()
                },
            ],
            by_id: catalog_by_id,
            by_path: HashMap::new(),
            by_norm_path: HashMap::new(),
        };

        let query_terms = vec!["lex2".to_string()];
        // lexical_limit = 1 (only 1 NEW candidate may be admitted on top of vec_doc)
        admit_lexical_candidates(&mut candidates, &bm25, &catalog, &query_terms, 1);

        assert_eq!(candidates.len(), 2);
        // lex_doc2 had higher score (0.95 vs 0.8), so it was admitted first
        assert!(candidates.contains_key("lex_doc2"));
        assert!(!candidates.contains_key("lex_doc1"));

        let cand2 = candidates.get("lex_doc2").unwrap();
        assert_eq!(cand2.vector_score, 0.0);
        assert_eq!(cand2.lexical_score, 0.95);
        assert_eq!(cand2.path, "src/lex2.rs");
        assert!(cand2.symbol_match_score > 0.0);
    }

    #[test]
    fn h91a_manual_fusion_defaults_match_python_champion() {
        let config = SearchConfig::default();
        assert_eq!(config.vector_weight, 0.42);
        assert_eq!(config.lexical_weight, 0.26);
        assert_eq!(config.path_weight, 0.12);
        assert_eq!(config.symbol_weight, 0.10);
        assert_eq!(config.symbol_match_weight, 0.10);
        assert_eq!(config.file_vote_weight, 0.06);
        assert_eq!(config.graph_weight, 0.0);
        assert_eq!(config.lexical_candidate_limit, 1000);
        // Python settings/defaults.py:300-302 — both off by default.
        assert!(!config.rank_by_raw_logits);
        assert!(!config.tie_break_by_fused_score);
        assert_eq!(config.tie_break_epsilon, 1e-4);
    }

    #[test]
    fn truncate_chars_counts_unicode_not_bytes() {
        assert_eq!(truncate_chars("abcdef", 4), "abcd");
        assert_eq!(truncate_chars("abcdef", 10), "abcdef");
        // 'Ж' is 2 bytes; 3 chars must survive a 3-char budget intact.
        assert_eq!(truncate_chars("ЖЖЖЖЖ", 3), "ЖЖЖ");
        // Mixed: byte slicing at 3 bytes would panic or split 'é' (2 bytes).
        assert_eq!(truncate_chars("aébc", 2), "aé");
    }

    #[test]
    fn ce_document_uses_catalog_title_and_content_budget() {
        let config = SearchConfig { max_document_chars: 5, ..Default::default() };
        let candidate = Candidate {
            path: "src/Foo.java".into(),
            title: "CatalogTitle".into(),
            content: Some("abcdefghij".into()),
            fused_score: 1.5,
            ..Default::default()
        };
        // Python _fused_locator_document: header NOT counted, content[:5] chars.
        assert_eq!(
            build_document(&candidate, &config),
            "path: src/Foo.java\ntitle: CatalogTitle\nscore: 1.500000\ncontent:\nabcde"
        );
        // Empty title falls back to the full path (Python `title or path`).
        let no_title = Candidate { title: String::new(), ..candidate.clone() };
        assert!(build_document(&no_title, &config).contains("title: src/Foo.java\n"));
    }

    #[test]
    fn admit_lexical_limit_bounds_new_admissions_not_total() {
        let mut candidates = HashMap::new();
        for i in 0..5 {
            candidates.insert(format!("vec{}", i), Candidate {
                item_id: format!("vec{}", i), path: format!("v{}.rs", i),
                ..Default::default()
            });
        }
        let mut bm25 = HashMap::new();
        bm25.insert("lex1".to_string(), 0.9);
        bm25.insert("lex2".to_string(), 0.8);
        let mut by_id = HashMap::new();
        by_id.insert("lex1".to_string(), 0);
        by_id.insert("lex2".to_string(), 1);
        let catalog = Catalog {
            items: vec![
                crate::types::CatalogItem { id: "lex1".into(), path: "l1.rs".into(), ..Default::default() },
                crate::types::CatalogItem { id: "lex2".into(), path: "l2.rs".into(), ..Default::default() },
            ],
            by_id, by_path: HashMap::new(), by_norm_path: HashMap::new(),
        };
        // Total (5) already exceeds any retrieval cap; both lexical hits must
        // still be admitted because the limit counts NEW admissions only.
        admit_lexical_candidates(&mut candidates, &bm25, &catalog, &[], 1000);
        assert_eq!(candidates.len(), 7);
        // Zero limit admits nothing.
        let mut candidates2 = HashMap::new();
        candidates2.insert("vec0".to_string(), Candidate::default());
        admit_lexical_candidates(&mut candidates2, &bm25, &catalog, &[], 0);
        assert_eq!(candidates2.len(), 1);
    }
}

/// Longest `&str` prefix holding at most `max_chars` Unicode scalar values.
/// Byte slicing would panic on non-char boundaries and miscount non-ASCII text.
fn truncate_chars(s: &str, max_chars: usize) -> &str {
    match s.char_indices().nth(max_chars) {
        Some((idx, _)) => &s[..idx],
        None => s,
    }
}

/// Title for the CE document: catalog title (`name`, = Python `item.title`),
/// falling back to the full path exactly like Python (`title or path`).
fn ce_title(candidate: &Candidate) -> &str {
    if candidate.title.is_empty() {
        &candidate.path
    } else {
        &candidate.title
    }
}

/// Build a document string matching Python's `_fused_locator_document` exactly.
/// Format: "path: {path}\ntitle: {title}\nscore: {score:.6f}\ncontent:\n{content}"
/// where the content slice is `content[:max_document_chars]` (chars, not bytes) and
/// the header is NOT counted against the budget. Falls back to catalog content if
/// filesystem is not available.
fn build_document(candidate: &Candidate, config: &SearchConfig) -> String {
    let title = ce_title(candidate);

    // Try to read from filesystem first (Rust-only extra; base_path empty in eval).
    if !config.base_path.is_empty() {
        let file_path = Path::new(&config.base_path).join(&candidate.path);
        if file_path.exists() {
            if let Ok(content) = std::fs::read_to_string(&file_path) {
                let content = content.trim();
                if !content.is_empty() {
                    return format!(
                        "path: {}\ntitle: {}\nscore: {:.6}\ncontent:\n{}",
                        candidate.path,
                        title,
                        candidate.fused_score,
                        truncate_chars(content, config.max_document_chars),
                    );
                }
            }
        }
    }

    // Catalog content, Python parity: item.content[:max_document_chars], no trim.
    let content = candidate.content.as_deref().unwrap_or("");
    format!(
        "path: {}\ntitle: {}\nscore: {:.6}\ncontent:\n{}",
        candidate.path,
        title,
        candidate.fused_score,
        truncate_chars(content, config.max_document_chars),
    )
}

/// Build a long document string for second pass (same Python format, larger budget).
fn build_long_document(candidate: &Candidate, config: &SearchConfig) -> String {
    let title = ce_title(candidate);

    if !config.base_path.is_empty() {
        let file_path = Path::new(&config.base_path).join(&candidate.path);
        if file_path.exists() {
            if let Ok(content) = std::fs::read_to_string(&file_path) {
                let content = content.trim();
                if !content.is_empty() {
                    return format!(
                        "path: {}\ntitle: {}\nscore: {:.6}\ncontent:\n{}",
                        candidate.path,
                        title,
                        candidate.fused_score,
                        truncate_chars(content, config.second_pass_max_document_chars),
                    );
                }
            }
        }
    }

    let content = candidate.content.as_deref().unwrap_or("");
    format!(
        "path: {}\ntitle: {}\nscore: {:.6}\ncontent:\n{}",
        candidate.path,
        title,
        candidate.fused_score,
        truncate_chars(content, config.second_pass_max_document_chars),
    )
}

/// Batch feature extraction: read queries from a JSONL file, process all in one process.
/// Each line: {"id": "...", "query": "...", "expected": ["path1", "path2", ...]}
/// Outputs JSONL features to stdout.
pub async fn dump_features_batch(ctx: &SearchContext, file_path: &str) -> Result<(), String> {
    let content = fs::read_to_string(file_path).map_err(|e| format!("Read file: {}", e))?;
    let lines: Vec<&str> = content.lines().filter(|l| !l.trim().is_empty()).collect();
    eprintln!("Processing {} queries from {}", lines.len(), file_path);

    let start_total = Instant::now();
    let mut total_candidates = 0;
    let mut errors = 0;

    for (i, line) in lines.iter().enumerate() {
        let record: serde_json::Value = serde_json::from_str(line)
            .map_err(|e| format!("Parse line {}: {}", i + 1, e))?;

        let query_id = record["id"].as_str().unwrap_or("unknown");
        let query = record["query"].as_str().ok_or_else(|| format!("No query at line {}", i + 1))?;
        let expected: Vec<String> = record["expected"]
            .as_array()
            .map(|arr| arr.iter().filter_map(|v| v.as_str().map(|s| s.to_string())).collect())
            .unwrap_or_default();

        let query_start = Instant::now();
        let expected_set: HashSet<String> = expected.iter().cloned().collect();

        // Use the same pre-meta pipeline and output as single-query export.
        match dump_features_single(ctx, query, query_id, &expected_set).await {
            Ok(n) => {
                total_candidates += n;
                let elapsed = query_start.elapsed().as_secs_f64();
                if (i + 1) % 10 == 0 || i == 0 {
                    eprintln!("  [{}/{}] {}: {} candidates in {:.1}s ({:.0}%)",
                        i + 1, lines.len(), query_id, n, elapsed,
                        (i + 1) * 100 / lines.len());
                }
            }
            Err(e) => {
                eprintln!("  [{}/{}] {}: ERROR: {}", i + 1, lines.len(), query_id, e);
                errors += 1;
            }
        }
    }

    let total = start_total.elapsed().as_secs_f64();
    eprintln!("Done: {} queries, {} candidates, {} errors, {:.0}s total ({:.1}s/query)",
        lines.len(), total_candidates, errors, total, total / lines.len() as f64);
    Ok(())
}

/// Process a single query for batch feature extraction, returns candidate count.
async fn dump_features_single(
    ctx: &SearchContext,
    query: &str,
    query_id: &str,
    expected_set: &HashSet<String>,
) -> Result<usize, String> {
    let start = Instant::now();
    let (rerank_candidates, _) = prepare_candidates(ctx, query).await?;

    let feature_rows = candidate_features(&rerank_candidates, query, &ctx.fan_in_degrees);
    let elapsed_s = start.elapsed().as_secs_f64();

    // Output features
    for (candidate, features) in rerank_candidates.iter().zip(&feature_rows) {
        let label = if expected_set.contains(&candidate.path) { 1 } else { 0 };
        let line = serde_json::json!({
            "query_id": query_id, "query": query, "candidate_path": candidate.path, "label": label,
            "ce_score": features.ce_score, "ce_rank": features.ce_rank,
            "fan_in_prior": features.fan_in_prior, "role_prior": features.role_prior,
            "base_fused_score": features.base_fused_score, "base_fused_rank": features.base_fused_rank,
            "lexical_overlap": features.lexical_overlap, "path_depth": features.path_depth,
            "filename_len": features.filename_len, "is_test": features.is_test,
            "ext_java": features.ext_java, "ext_kt": features.ext_kt,
            "ext_xml": features.ext_xml, "ext_md": features.ext_md,
            "query_term_count": features.query_term_count, "dir_proximity": features.dir_proximity,
            "time_s": elapsed_s,
        });
        println!("{}", serde_json::to_string(&line).unwrap_or_default());
    }

    Ok(rerank_candidates.len())
}