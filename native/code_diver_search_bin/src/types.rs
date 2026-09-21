use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// A single search result: a file path with a relevance score.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchResult {
    pub item_id: String,
    pub path: String,
    pub score: f64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub ce_score: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub meta_score: Option<f64>,
}

/// A catalog item as loaded from JSONL.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct CatalogItem {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub path: String,
    #[serde(default)]
    pub kind: String,
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub content: String,
    #[serde(default)]
    pub symbols: Vec<String>,
    #[serde(default)]
    pub tokenized_name: Vec<String>,
    #[serde(default)]
    pub tokenized_path: Vec<String>,
    #[serde(default)]
    pub tokenized_dir: Vec<String>,
    #[serde(default)]
    pub tokenized_content: Vec<String>,
}

/// The full catalog: all items, indexed by id and by path.
#[derive(Debug, Clone)]
#[allow(dead_code)]
pub struct Catalog {
    pub items: Vec<CatalogItem>,
    pub by_id: HashMap<String, usize>,
    pub by_path: HashMap<String, Vec<usize>>,
    pub by_norm_path: HashMap<String, Vec<usize>>,
}

/// BM25 index data.
#[derive(Debug, Clone)]
pub struct Bm25Index {
    /// doc_id -> term -> frequency
    pub term_frequencies: HashMap<String, HashMap<String, u32>>,
    /// doc_id -> total tokens
    pub document_lengths: HashMap<String, u32>,
    /// term -> set of doc_ids
    pub postings: HashMap<String, Vec<String>>,
    /// average document length
    pub avgdl: f64,
    /// total number of documents
    pub num_docs: usize,
}

/// Graph adjacency: for each path, list of (neighbor_path, weight).
#[derive(Debug, Clone)]
pub struct GraphAdjacency {
    pub edges: HashMap<String, Vec<(String, f64)>>,
}

/// A candidate during search, with all score components.
#[derive(Debug, Clone, Default)]
#[allow(dead_code)]
pub struct Candidate {
    pub item_id: String,
    pub path: String,
    /// Catalog title (`name` field = Python `item.title`). Empty = fall back to path.
    pub title: String,
    pub content: Option<String>,
    pub vector_score: f64,
    pub lexical_score: f64,
    pub path_score: f64,
    pub symbol_score: f64,
    pub graph_score: f64,
    pub symbol_match_score: f64,
    pub file_vote_score: f64,
    /// Fused pre-CE score
    pub fused_score: f64,
    /// First-pass CE score until finalization, then the adjusted merged score
    pub ce_score: f64,
    /// CE rerank score (after second pass, max of first/second)
    pub ce_score_final: f64,
    /// Meta-ranker predicted score
    pub meta_score: f64,
    /// Hub prior score
    pub hub_prior: f64,
    /// CE index in the batch
    pub ce_index: usize,
    /// Fused rank until finalization, then adjusted CE rank for Python inference features
    pub base_fused_rank: usize,
    /// CE rank
    pub ce_rank: usize,
}

/// 16 meta-ranker features matching Python's CeMetaFeatureRow exactly.
/// Order must match Python's CeMetaFeatureRow._features() output tuple.
#[derive(Debug, Clone)]
pub struct MetaFeatures {
    pub ce_score: f64,
    pub ce_rank: f64,
    pub fan_in_prior: f64,
    pub role_prior: f64,
    pub base_fused_score: f64,
    pub base_fused_rank: f64,
    pub lexical_overlap: f64,
    pub path_depth: f64,
    pub filename_len: f64,
    pub is_test: f64,
    pub ext_java: f64,
    pub ext_kt: f64,
    pub ext_xml: f64,
    pub ext_md: f64,
    pub query_term_count: f64,
    pub dir_proximity: f64,
}

impl MetaFeatures {
    pub fn to_vec(&self) -> Vec<f64> {
        vec![
            self.ce_score,
            self.ce_rank,
            self.fan_in_prior,
            self.role_prior,
            self.base_fused_score,
            self.base_fused_rank,
            self.lexical_overlap,
            self.path_depth,
            self.filename_len,
            self.is_test,
            self.ext_java,
            self.ext_kt,
            self.ext_xml,
            self.ext_md,
            self.query_term_count,
            self.dir_proximity,
        ]
    }
}

/// A parsed LightGBM tree.
#[derive(Debug, Clone)]
#[allow(dead_code)]
pub struct LgbTree {
    pub split_feature: i32,
    pub threshold: f64,
    pub split_gain: f64,
    pub leaf_values: Vec<f64>,
    pub left_child: Option<Box<LgbTree>>,
    pub right_child: Option<Box<LgbTree>>,
    pub internal_value: f64,
}

/// A complete LightGBM model.
#[derive(Debug, Clone)]
pub struct LgbModel {
    pub trees: Vec<LgbTree>,
    pub num_features: usize,
    pub num_trees: usize,
}

/// Search configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchConfig {
    #[serde(default = "default_retrieval_limit")]
    pub retrieval_limit: usize,
    pub candidate_limit: usize,
    /// H-91a manual fusion weights (NOT learned; docs/h5-hybrid-weight-calibration).
    /// Only the LightGBM meta-ranker is trained; fusion repeats these by hand.
    pub vector_weight: f64,
    pub lexical_weight: f64,
    pub path_weight: f64,
    pub symbol_weight: f64,
    pub graph_weight: f64,
    pub symbol_match_weight: f64,
    pub file_vote_weight: f64,
    pub lexical_candidate_limit: usize,
    pub graph_depth: usize,
    pub graph_neighbor_limit: usize,
    pub graph_decay: f64,
    pub second_pass_enabled: bool,
    pub second_pass_score_floor: f64,
    pub second_pass_candidate_cap: usize,
    pub second_pass_max_document_chars: usize,
    pub max_document_chars: usize,
    pub rank_by_raw_logits: bool,
    pub tie_break_by_fused_score: bool,
    pub tie_break_epsilon: f64,
    pub hub_prior_enabled: bool,
    pub hub_prior_mode: String,
    pub hub_prior_role_weight: f64,
    pub hub_prior_fanin_weight: f64,
    pub hub_prior_band_width: f64,
    pub hub_prior_protect_top: usize,
    pub hub_prior_protect_margin: f64,
    pub ce_meta_ranker_enabled: bool,
    pub ce_meta_model_path: String,
    pub embedding_url: String,
    pub qdrant_url: String,
    pub ce_url: String,
    /// Empty (default) = reuse ce_url. Set for mixed CE routing
    /// (e.g. llama first pass, vLLM-metal second pass).
    #[serde(default)]
    pub second_ce_url: String,
    #[serde(default = "default_ce_route")]
    pub ce_route: String,
    #[serde(default = "default_ce_timeout_ms")]
    pub ce_timeout_ms: u64,
    #[serde(default)]
    pub ce_model: String,
    pub catalog_path: String,
    pub graph_path: String,
    pub base_path: String,
    #[serde(default = "default_embed_cache_size")]
    pub embed_cache_size: usize,
}

fn default_retrieval_limit() -> usize {
    360
}

fn default_ce_route() -> String {
    "auto".to_string()
}

fn default_ce_timeout_ms() -> u64 {
    60_000
}

fn default_embed_cache_size() -> usize {
    0
}

/// Defaults for the selective second CE pass. Kept as constants so CLI help,
/// presets and validation share a single source of truth.
pub const SECOND_PASS_CAP_DEFAULT: usize = 24;
pub const SECOND_PASS_FLOOR_DEFAULT: f64 = 0.3;
/// `selective-strict` preset (recommended for low-variance latency): cap 8, floor 0.15.
pub const SELECTIVE_STRICT_CAP: usize = 8;
pub const SELECTIVE_STRICT_FLOOR: f64 = 0.15;
/// Hard bounds for CLI validation.
pub const CANDIDATE_LIMIT_MAX: usize = 512;
pub const SECOND_PASS_CAP_MAX: usize = 512;

impl Default for SearchConfig {
    fn default() -> Self {
        Self {
            retrieval_limit: default_retrieval_limit(),
            candidate_limit: 34,
            vector_weight: 0.42,
            lexical_weight: 0.26,
            path_weight: 0.12,
            symbol_weight: 0.10,
            graph_weight: 0.0,
            symbol_match_weight: 0.10,
            file_vote_weight: 0.06,
            lexical_candidate_limit: 1000,
            graph_depth: 2,
            graph_neighbor_limit: 40,
            graph_decay: 0.5,
            second_pass_enabled: true,
            second_pass_score_floor: 0.3,
            second_pass_candidate_cap: 24,
            second_pass_max_document_chars: 2400,
            max_document_chars: 850,
            rank_by_raw_logits: false,
            tie_break_by_fused_score: false,
            tie_break_epsilon: 1e-4,
            hub_prior_enabled: true,
            hub_prior_mode: "band".to_string(),
            hub_prior_role_weight: 1.0,
            hub_prior_fanin_weight: 1.0,
            hub_prior_band_width: 0.015,
            hub_prior_protect_top: 4,
            hub_prior_protect_margin: 0.0,
            ce_meta_ranker_enabled: true,
            ce_meta_model_path: String::new(),
            embedding_url: "http://localhost:8001/v1/embeddings".to_string(),
            qdrant_url: "http://localhost:6333".to_string(),
            ce_url: "http://localhost:18081/v1/rerank".to_string(),
            second_ce_url: String::new(),
            ce_route: default_ce_route(),
            ce_timeout_ms: default_ce_timeout_ms(),
            ce_model: String::new(),
            catalog_path: String::new(),
            graph_path: String::new(),
            base_path: String::new(),
            embed_cache_size: default_embed_cache_size(),
        }
    }
}

/// Resolve the effective first-pass (CE) candidate limit.
///
/// `--first-pass-cap` is an alias for `--candidate-limit`: when present it wins,
/// otherwise `candidate_limit` is used. Values must be in `1..=CANDIDATE_LIMIT_MAX`.
pub fn resolve_candidate_limit(candidate_limit: usize, first_pass_cap: Option<usize>) -> Result<usize, String> {
    let effective = first_pass_cap.unwrap_or(candidate_limit);
    if effective == 0 || effective > CANDIDATE_LIMIT_MAX {
        return Err(format!(
            "candidate limit must be in 1..={} (got {})",
            CANDIDATE_LIMIT_MAX, effective
        ));
    }
    Ok(effective)
}

/// Resolve second-pass settings from CLI flags.
///
/// Returns `(enabled, floor, cap)`. `preset == Some("selective-strict")` supplies
/// cap 8 / floor 0.15 as the base; explicit `--second-pass-cap` / `--second-pass-floor`
/// override the preset; `--second-pass-disable` turns the pass off entirely.
/// Unknown preset names are rejected. Defaults (no flags, no preset) are cap 24 / floor 0.3.
pub fn resolve_second_pass(
    preset: Option<&str>,
    cap: Option<usize>,
    floor: Option<f64>,
    disable: bool,
) -> Result<(bool, f64, usize), String> {
    let (mut base_cap, mut base_floor) = (SECOND_PASS_CAP_DEFAULT, SECOND_PASS_FLOOR_DEFAULT);
    if let Some(name) = preset {
        match name {
            "selective-strict" => {
                base_cap = SELECTIVE_STRICT_CAP;
                base_floor = SELECTIVE_STRICT_FLOOR;
            }
            other => return Err(format!(
                "unknown --preset {:?}; expected \"selective-strict\"",
                other
            )),
        }
    }
    let cap = cap.unwrap_or(base_cap);
    let floor = floor.unwrap_or(base_floor);
    if cap > SECOND_PASS_CAP_MAX {
        return Err(format!(
            "second-pass cap must be in 0..={} (got {})",
            SECOND_PASS_CAP_MAX, cap
        ));
    }
    if !(0.0..=1.0).contains(&floor) {
        return Err(format!(
            "second-pass floor must be in [0.0, 1.0] (got {})",
            floor
        ));
    }
    if disable {
        return Ok((false, floor, cap));
    }
    Ok((true, floor, cap))
}

#[cfg(test)]
mod types_tests {
    use super::*;

    #[test]
    fn candidate_limit_defaults_and_alias() {
        assert_eq!(resolve_candidate_limit(34, None).unwrap(), 34);
        assert_eq!(resolve_candidate_limit(34, Some(50)).unwrap(), 50);
        assert!(resolve_candidate_limit(0, None).is_err());
        assert!(resolve_candidate_limit(34, Some(0)).is_err());
        assert!(resolve_candidate_limit(34, Some(513)).is_err());
    }

    #[test]
    fn second_pass_defaults_without_flags() {
        let (enabled, floor, cap) = resolve_second_pass(None, None, None, false).unwrap();
        assert!(enabled);
        assert_eq!((floor, cap), (SECOND_PASS_FLOOR_DEFAULT, SECOND_PASS_CAP_DEFAULT));
    }

    #[test]
    fn selective_strict_preset_and_explicit_override() {
        let (enabled, floor, cap) = resolve_second_pass(Some("selective-strict"), None, None, false).unwrap();
        assert!(enabled);
        assert_eq!((floor, cap), (SELECTIVE_STRICT_FLOOR, SELECTIVE_STRICT_CAP));
        // Explicit flags win over the preset.
        let (_, floor, cap) =
            resolve_second_pass(Some("selective-strict"), Some(12), Some(0.2), false).unwrap();
        assert_eq!((floor, cap), (0.2, 12));
        // Disable wins over everything but still validates.
        let (enabled, _, _) =
            resolve_second_pass(Some("selective-strict"), None, None, true).unwrap();
        assert!(!enabled);
        assert!(resolve_second_pass(Some("unknown"), None, None, false).is_err());
        assert!(resolve_second_pass(None, None, Some(1.5), false).is_err());
        assert!(resolve_second_pass(None, Some(513), None, false).is_err());
    }
}