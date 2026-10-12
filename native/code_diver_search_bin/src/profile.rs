use serde::Deserialize;
use std::collections::HashMap;
use std::path::Path;

/// TOML profile structure mirroring the [search] table.
#[derive(Debug, Deserialize)]
pub struct Profile {
    #[serde(default)]
    pub search: SearchProfile,
}

#[derive(Debug, Default, Deserialize)]
pub struct SearchProfile {
    // Core limits
    #[serde(default)]
    pub candidate_limit: Option<usize>,
    #[serde(default)]
    pub retrieval_limit: Option<usize>,
    #[serde(default)]
    pub lexical_candidate_limit: Option<usize>,

    // Fusion weights
    #[serde(default)]
    pub vector_weight: Option<f64>,
    #[serde(default)]
    pub lexical_weight: Option<f64>,
    #[serde(default)]
    pub path_weight: Option<f64>,
    #[serde(default)]
    pub symbol_weight: Option<f64>,
    #[serde(default)]
    pub graph_weight: Option<f64>,
    #[serde(default)]
    pub symbol_match_weight: Option<f64>,
    #[serde(default)]
    pub file_vote_weight: Option<f64>,

    // Graph propagation
    #[serde(default)]
    pub graph_depth: Option<usize>,
    #[serde(default)]
    pub graph_neighbor_limit: Option<usize>,
    #[serde(default)]
    pub graph_decay: Option<f64>,

    // CE second pass
    #[serde(default)]
    pub second_pass_enabled: Option<bool>,
    #[serde(default)]
    pub second_pass_score_floor: Option<f64>,
    #[serde(default)]
    pub second_pass_candidate_cap: Option<usize>,
    #[serde(default)]
    pub second_pass_max_document_chars: Option<usize>,
    #[serde(default)]
    pub max_document_chars: Option<usize>,

    // Hub prior
    #[serde(default)]
    pub hub_prior_enabled: Option<bool>,
    #[serde(default)]
    pub hub_prior_mode: Option<String>,
    #[serde(default)]
    pub hub_prior_role_weight: Option<f64>,
    #[serde(default)]
    pub hub_prior_fanin_weight: Option<f64>,
    #[serde(default)]
    pub hub_prior_band_width: Option<f64>,
    #[serde(default)]
    pub hub_prior_protect_top: Option<usize>,
    #[serde(default)]
    pub hub_prior_protect_margin: Option<f64>,

    // Meta-ranker
    #[serde(default)]
    pub ce_meta_ranker_enabled: Option<bool>,
    #[serde(default)]
    pub ce_meta_model_path: Option<String>,

    // Embedding
    #[serde(default)]
    pub embedding_query_prefix: Option<String>,
    #[serde(default)]
    pub embedding_document_prefix: Option<String>,
    #[serde(default)]
    pub embedding_model: Option<String>,
    #[serde(default)]
    pub embedding_dimensions: Option<usize>,

    // CE config
    #[serde(default)]
    pub ce_url: Option<String>,
    #[serde(default)]
    pub second_ce_url: Option<String>,
    #[serde(default)]
    pub ce_route: Option<String>,
    #[serde(default)]
    pub ce_timeout_ms: Option<u64>,
    #[serde(default)]
    pub ce_model: Option<String>,

    // Qdrant
    #[serde(default)]
    pub qdrant_url: Option<String>,
    #[serde(default)]
    pub qdrant_collection: Option<String>,

    // Ranking
    #[serde(default)]
    pub rank_by_raw_logits: Option<bool>,
    #[serde(default)]
    pub tie_break_by_fused_score: Option<bool>,
    #[serde(default)]
    pub tie_break_epsilon: Option<f64>,

    // H-91a: preserve_vector_top
    #[serde(default)]
    pub preserve_vector_top: Option<bool>,
    #[serde(default)]
    pub vector_top_score_margin: Option<f64>,

    // H-91a: vector kind limits and multipliers
    #[serde(default)]
    pub vector_kind_limits: Option<HashMap<String, usize>>,
    #[serde(default)]
    pub vector_kind_multipliers: Option<HashMap<String, f64>>,

    // H-91a: item kind weights
    #[serde(default)]
    pub item_kind_weights: Option<HashMap<String, f64>>,

    // H-91a: routing
    #[serde(default)]
    pub routing_enabled: Option<bool>,

    // H-91a: min token length
    #[serde(default)]
    pub min_token_length: Option<usize>,

    // H-91a: CE preserve_top
    pub preserve_top_candidate: Option<bool>,
    pub preserve_top_score_margin: Option<f64>,
    pub preserve_top_depth: Option<usize>,

    // H-91a: graph_file_search
    #[serde(default)]
    pub seed_limit: Option<usize>,
    #[serde(default)]
    pub lexical_seed_limit: Option<usize>,
    #[serde(default)]
    pub seed_score_parity: Option<bool>,

    // Embedding cache
    #[serde(default)]
    pub embed_cache_size: Option<usize>,

    // Require rerank
    #[serde(default)]
    pub require_rerank: Option<bool>,
}

/// Allowed keys in the [search] table.
const ALLOWED_SEARCH_KEYS: &[&str] = &[
    "candidate_limit",
    "retrieval_limit",
    "lexical_candidate_limit",
    "vector_weight",
    "lexical_weight",
    "path_weight",
    "symbol_weight",
    "graph_weight",
    "symbol_match_weight",
    "file_vote_weight",
    "graph_depth",
    "graph_neighbor_limit",
    "graph_decay",
    "second_pass_enabled",
    "second_pass_score_floor",
    "second_pass_candidate_cap",
    "second_pass_max_document_chars",
    "max_document_chars",
    "hub_prior_enabled",
    "hub_prior_mode",
    "hub_prior_role_weight",
    "hub_prior_fanin_weight",
    "hub_prior_band_width",
    "hub_prior_protect_top",
    "hub_prior_protect_margin",
    "ce_meta_ranker_enabled",
    "ce_meta_model_path",
    "embedding_query_prefix",
    "embedding_document_prefix",
    "embedding_model",
    "embedding_dimensions",
    "ce_url",
    "second_ce_url",
    "ce_route",
    "ce_timeout_ms",
    "ce_model",
    "qdrant_url",
    "qdrant_collection",
    "rank_by_raw_logits",
    "tie_break_by_fused_score",
    "tie_break_epsilon",
    "preserve_vector_top",
    "vector_top_score_margin",
    "vector_kind_limits",
    "vector_kind_multipliers",
    "item_kind_weights",
    "routing_enabled",
    "min_token_length",
    "preserve_top_candidate",
    "preserve_top_score_margin",
    "preserve_top_depth",
    "seed_limit",
    "lexical_seed_limit",
    "seed_score_parity",
    "embed_cache_size",
    "require_rerank",
];

/// Load and validate a TOML profile file.
///
/// Returns an error naming the unknown key if any key is not recognized.
pub fn load_profile(path: &Path) -> Result<Profile, String> {
    let text = std::fs::read_to_string(path)
        .map_err(|e| format!("Cannot read profile {}: {}", path.display(), e))?;

    // Parse as Value first to validate keys
    let value: toml::Value =
        toml::from_str(&text).map_err(|e| format!("Invalid TOML in {}: {}", path.display(), e))?;

    // Validate top-level keys
    if let Some(table) = value.as_table() {
        for key in table.keys() {
            if key != "search" {
                return Err(format!("Unknown profile key: {}", key));
            }
        }
    }

    // Validate search sub-keys
    if let Some(search_table) = value.get("search").and_then(|v| v.as_table()) {
        for key in search_table.keys() {
            if !ALLOWED_SEARCH_KEYS.contains(&key.as_str()) {
                return Err(format!("Unknown profile key: {}", key));
            }
        }
    }

    // Parse into typed struct
    let profile: Profile =
        toml::from_str(&text).map_err(|e| format!("Profile parse error: {}", e))?;
    Ok(profile)
}

/// Apply profile values to a SearchConfig, overriding only set fields.
pub fn apply_profile(config: &mut crate::types::SearchConfig, profile: &Profile) {
    let s = &profile.search;
    macro_rules! apply {
        ($field:ident) => {
            if let Some(ref v) = s.$field {
                config.$field = v.clone();
            }
        };
    }
    apply!(candidate_limit);
    apply!(retrieval_limit);
    apply!(lexical_candidate_limit);
    apply!(vector_weight);
    apply!(lexical_weight);
    apply!(path_weight);
    apply!(symbol_weight);
    apply!(graph_weight);
    apply!(symbol_match_weight);
    apply!(file_vote_weight);
    apply!(graph_depth);
    apply!(graph_neighbor_limit);
    apply!(graph_decay);
    apply!(second_pass_enabled);
    apply!(second_pass_score_floor);
    apply!(second_pass_candidate_cap);
    apply!(second_pass_max_document_chars);
    apply!(max_document_chars);
    apply!(hub_prior_enabled);
    apply!(hub_prior_mode);
    apply!(hub_prior_role_weight);
    apply!(hub_prior_fanin_weight);
    apply!(hub_prior_band_width);
    apply!(hub_prior_protect_top);
    apply!(hub_prior_protect_margin);
    apply!(ce_meta_ranker_enabled);
    apply!(ce_meta_model_path);
    apply!(embedding_query_prefix);
    apply!(embedding_document_prefix);
    apply!(embedding_model);
    if let Some(v) = s.embedding_dimensions {
        config.embedding_dimensions = Some(v);
    }
    apply!(ce_url);
    apply!(second_ce_url);
    apply!(ce_route);
    apply!(ce_timeout_ms);
    apply!(ce_model);
    apply!(qdrant_url);
    apply!(qdrant_collection);
    apply!(rank_by_raw_logits);
    apply!(tie_break_by_fused_score);
    apply!(tie_break_epsilon);
    apply!(preserve_vector_top);
    apply!(vector_top_score_margin);
    apply!(routing_enabled);
    apply!(min_token_length);
    apply!(preserve_top_candidate);
    apply!(preserve_top_score_margin);
    apply!(preserve_top_depth);
    apply!(seed_limit);
    apply!(lexical_seed_limit);
    apply!(seed_score_parity);
    apply!(embed_cache_size);
    apply!(require_rerank);
    if let Some(v) = &s.vector_kind_limits {
        config.vector_kind_limits = v.clone();
    }
    if let Some(v) = &s.vector_kind_multipliers {
        config.vector_kind_multipliers = v.clone();
    }
    if let Some(v) = &s.item_kind_weights {
        config.item_kind_weights = v.clone();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    fn write_temp_profile(content: &str) -> tempfile::NamedTempFile {
        let mut file = tempfile::NamedTempFile::new().expect("create temp file");
        write!(file, "{}", content).expect("write profile");
        file
    }

    #[test]
    fn load_valid_profile() {
        let file = write_temp_profile(
            r#"
[search]
candidate_limit = 64
vector_weight = 0.42
preserve_vector_top = true
"#,
        );
        let profile = load_profile(file.path()).expect("load profile");
        assert_eq!(profile.search.candidate_limit, Some(64));
        assert_eq!(profile.search.vector_weight, Some(0.42));
        assert_eq!(profile.search.preserve_vector_top, Some(true));
    }

    #[test]
    fn load_profile_with_sub_tables() {
        let file = write_temp_profile(
            r#"
[search]
candidate_limit = 64

[search.vector_kind_limits]
file_summary = 170
file_manifest = 170

[search.item_kind_weights]
file_summary = 1.0
file_manifest = 1.08
"#,
        );
        let profile = load_profile(file.path()).expect("load profile");
        let limits = profile
            .search
            .vector_kind_limits
            .as_ref()
            .expect("vector_kind_limits");
        assert_eq!(limits.get("file_summary"), Some(&170));
        let weights = profile
            .search
            .item_kind_weights
            .as_ref()
            .expect("item_kind_weights");
        assert_eq!(weights.get("file_manifest"), Some(&1.08));
    }

    #[test]
    fn unknown_top_level_key_error() {
        let file = write_temp_profile(
            r#"
[search]
candidate_limit = 64

[embedding]
url = "http://localhost:8001"
"#,
        );
        let err = load_profile(file.path()).expect_err("should fail");
        assert!(err.contains("Unknown profile key"), "Error: {}", err);
        assert!(err.contains("embedding"), "Error: {}", err);
    }

    #[test]
    fn unknown_search_key_error() {
        let file = write_temp_profile(
            r#"
[search]
candidate_limit = 64
bogus_key = 123
"#,
        );
        let err = load_profile(file.path()).expect_err("should fail");
        assert!(err.contains("Unknown profile key"), "Error: {}", err);
        assert!(err.contains("bogus_key"), "Error: {}", err);
    }

    #[test]
    fn apply_profile_overrides_defaults() {
        let file = write_temp_profile(
            r#"
[search]
candidate_limit = 64
vector_weight = 0.5
preserve_vector_top = true
min_token_length = 5
"#,
        );
        let profile = load_profile(file.path()).expect("load profile");
        let mut config = crate::types::SearchConfig::default();
        assert_eq!(config.candidate_limit, 34);
        apply_profile(&mut config, &profile);
        assert_eq!(config.candidate_limit, 64);
        assert_eq!(config.vector_weight, 0.5);
        assert!(config.preserve_vector_top);
        assert_eq!(config.min_token_length, 5);
        assert_eq!(config.lexical_weight, 0.26); // unchanged
    }

    #[test]
    fn empty_profile_is_valid() {
        let file = write_temp_profile(
            r#"
[search]
"#,
        );
        let profile = load_profile(file.path()).expect("load profile");
        assert_eq!(profile.search.candidate_limit, None);
    }

    #[test]
    fn profile_with_all_h91a_keys() {
        let file = write_temp_profile(
            r#"
[search]
candidate_limit = 64
preserve_vector_top = true
vector_top_score_margin = 0.03
routing_enabled = true
min_token_length = 3
preserve_top_candidate = true
preserve_top_score_margin = 0.1
preserve_top_depth = 1
seed_limit = 140
lexical_seed_limit = 280
seed_score_parity = true

[search.vector_kind_limits]
file_summary = 170
file_manifest = 170

[search.vector_kind_multipliers]
file_summary = 1.0
file_manifest = 1.08

[search.item_kind_weights]
file_summary = 1.0
file_manifest = 1.08
"#,
        );
        let profile = load_profile(file.path()).expect("load full H-91a profile");
        assert_eq!(profile.search.candidate_limit, Some(64));
        assert_eq!(profile.search.preserve_vector_top, Some(true));
        assert_eq!(profile.search.routing_enabled, Some(true));
        assert_eq!(profile.search.seed_score_parity, Some(true));
    }
}
