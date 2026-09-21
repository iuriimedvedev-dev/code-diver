use std::collections::HashMap;
use std::collections::HashSet;

use crate::types::{Candidate, GraphAdjacency, MetaFeatures};

// ============================================================================
// Exact Python `HubPriorScorer` role_prior implementation
// ============================================================================

/// Python regex: `(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|[_\-.\s]+`
/// Splits CamelCase into tokens: "ServiceManager" -> ["Service", "Manager"]
fn camel_case_tokens(text: &str) -> Vec<String> {
    let mut tokens = Vec::new();
    let mut current = String::new();
    let chars: Vec<char> = text.chars().collect();
    let mut i = 0;
    while i < chars.len() {
        let c = chars[i];
        // Check for separators: _, -, ., whitespace
        if c == '_' || c == '-' || c == '.' || c.is_whitespace() {
            if !current.is_empty() {
                tokens.push(current.clone().to_lowercase());
                current.clear();
            }
            i += 1;
            continue;
        }
        // Check for CamelCase boundaries:
        // 1. (?<=[a-z0-9])(?=[A-Z]) — "aA" or "0A"
        // 2. (?<=[A-Z])(?=[A-Z][a-z]) — "AAa"
        if !current.is_empty() {
            let prev = current.chars().last().unwrap();
            if c.is_ascii_uppercase() {
                if prev.is_ascii_lowercase() || prev.is_ascii_digit() {
                    // Boundary: ...aA... or ...0A...
                    tokens.push(current.clone().to_lowercase());
                    current.clear();
                } else if prev.is_ascii_uppercase() && i + 1 < chars.len() && chars[i + 1].is_ascii_lowercase() {
                    // Boundary: ...AAa... — push all of current, start fresh
                    tokens.push(current.clone().to_lowercase());
                    current.clear();
                }
            }
        }
        current.push(c);
        i += 1;
    }
    if !current.is_empty() {
        tokens.push(current.to_lowercase());
    }
    tokens
}

/// Python: `HubPriorConfig` token lists — ALL LOWERCASE (Python normalizes via _tokens)
/// HUB_PRIOR_HUB_TOKENS
const HUB_TOKENS: &[&[&str]] = &[
    &["manager"],
    &["processor"],
    &["service"],
    &["impl"],
    &["engine"],
    &["queue"],
    &["area"],
    &["evaluator"],
    &["registry"],
    &["coordinator"],
];

/// HUB_PRIOR_PERIPHERAL_TOKENS
const PERIPHERAL_TOKENS: &[&[&str]] = &[
    &["action"],
    &["dialog"],
    &["handler"],
    &["delegate"],
    &["provider"],
    &["strategy"],
    &["util"],
    &["utils"],
    &["test"],
    &["tests"],
    &["testutil"],
    &["bundle"],
    &["inspection"],
    &["reporter"],
    &["logger"],
    &["mock"],
    &["command"],
];

const TEST_PATH_SEGMENTS: &[&str] = &["test", "tests", "testsrc", "testdata"];
const NON_SOURCE_EXTENSIONS: &[&str] = &[
    ".xml", ".md", ".json", ".properties", ".txt", ".yaml", ".yml", ".html",
];

/// Python: `NON_SOURCE_ROLE_PRIOR = -1.0`
const NON_SOURCE_ROLE_PRIOR: f64 = -1.0;
/// Python: `TEST_PATH_ROLE_PRIOR = -0.75`
const TEST_PATH_ROLE_PRIOR: f64 = -0.75;
/// Python: `HUB_ROLE_PRIOR = 1.0`
const HUB_ROLE_PRIOR: f64 = 1.0;
/// Python: `PERIPHERAL_ROLE_PRIOR = -0.5`
const PERIPHERAL_ROLE_PRIOR: f64 = -0.5;
/// Python: `NEUTRAL_ROLE_PRIOR = 0.0`
const NEUTRAL_ROLE_PRIOR: f64 = 0.0;

/// Exact Python `HubPriorScorer.role_prior(path)`.
fn role_prior(path: &str) -> f64 {
    let posix_path = path.replace('\\', "/");

    // Check non-source extensions first
    if let Some((_, ext)) = posix_path.rsplit_once('.') {
        let dot_ext = format!(".{}", ext.to_lowercase());
        if NON_SOURCE_EXTENSIONS.contains(&dot_ext.as_str()) {
            return NON_SOURCE_ROLE_PRIOR;
        }
    }

    // Check test path segments (Python: PurePosixPath(path).parts[:-1])
    let parts: Vec<&str> = posix_path.split('/').collect();
    let parent_parts = &parts[..parts.len().saturating_sub(1)];
    for segment in parent_parts {
        let lowered = segment.to_lowercase();
        if TEST_PATH_SEGMENTS.contains(&lowered.as_str()) {
            return TEST_PATH_ROLE_PRIOR;
        }
    }

    // Get stem (filename without extension) — Python: PurePosixPath.stem
    let filename = parts.last().unwrap_or(&"");
    let stem = filename.rsplit_once('.').map(|(s, _)| s).unwrap_or(filename);
    let tokens = camel_case_tokens(stem);

    if tokens.is_empty() {
        return NEUTRAL_ROLE_PRIOR;
    }

    // Python: _ends_with_any(tokens, self._hub_entries)
    if ends_with_any(&tokens, HUB_TOKENS) {
        return HUB_ROLE_PRIOR;
    }
    // Python: _ends_with_any(tokens, self._peripheral_entries)
    if ends_with_any(&tokens, PERIPHERAL_TOKENS) {
        return PERIPHERAL_ROLE_PRIOR;
    }
    // Python: _contains_any(tokens, self._peripheral_entries)
    if contains_any(&tokens, PERIPHERAL_TOKENS) {
        return PERIPHERAL_ROLE_PRIOR;
    }
    // Python: _contains_any(tokens, self._hub_entries)
    if contains_any(&tokens, HUB_TOKENS) {
        return HUB_ROLE_PRIOR;
    }

    NEUTRAL_ROLE_PRIOR
}

/// Python: `_ends_with_any(tokens, entries)`
fn ends_with_any(tokens: &[String], entries: &[&[&str]]) -> bool {
    for entry in entries {
        if entry.len() <= tokens.len() && &tokens[tokens.len() - entry.len()..] == *entry {
            return true;
        }
    }
    false
}

/// Python: `_contains_any(tokens, entries)`
fn contains_any(tokens: &[String], entries: &[&[&str]]) -> bool {
    for entry in entries {
        if entry.is_empty() || entry.len() > tokens.len() {
            continue;
        }
        for start in 0..=(tokens.len() - entry.len()) {
            if &tokens[start..start + entry.len()] == *entry {
                return true;
            }
        }
    }
    false
}

// ============================================================================
// Exact Python `CeMetaFeatureExtractor` implementation
// ============================================================================

/// Python: `_query_terms(query)` — exact match
pub fn query_terms(query: &str) -> Vec<String> {
    query
        .replace('-', " ")
        .replace('_', " ")
        .replace('/', " ")
        .split_whitespace()
        .filter(|t| !t.is_empty())
        .map(|t| t.to_lowercase())
        .collect()
}

/// Python: `_file_extension(path)` — exact match
fn file_extension(path: &str) -> &'static str {
    let ext = path.rsplit_once('.').map(|(_, e)| e).unwrap_or("");
    match ext.to_lowercase().as_str() {
        "java" => "java",
        "kt" | "kts" => "kt",
        "xml" => "xml",
        "md" | "markdown" => "md",
        _ => "other",
    }
}

/// Python: `_is_test_path(path)` — exact match
fn is_test_path(path: &str) -> bool {
    let lowered = path.to_lowercase();
    let markers = ["/test/", "/tests/", "/testdata/", "test/", "tests/"];
    markers.iter().any(|m| lowered.contains(m))
}

/// Extract 16 meta-ranker features for a candidate.
/// Exact match of Python's `CeMetaFeatureExtractor._features()`.
pub fn extract_features(
    candidate: &Candidate,
    query_terms: &[String],
    query_term_set: &HashSet<String>,
    query_term_count: f64,
    max_fan_in: f64,
    fan_in_degrees: &HashMap<String, f64>,
) -> MetaFeatures {
    let path = &candidate.path;
    let path_lower = path.to_lowercase();

    // Python: path_lower.replace("/", " ").replace("-", " ").replace("_", " ").split()
    let _path_terms: Vec<String> = path_lower
        .replace('/', " ")
        .replace('-', " ")
        .replace('_', " ")
        .split_whitespace()
        .filter(|t| !t.is_empty())
        .map(|t| t.to_string())
        .collect();

    // Python: dir_parts = [p for p in path_lower.split("/") if p and "." not in p]
    let dir_parts: Vec<&str> = path_lower
        .split('/')
        .filter(|p| !p.is_empty() && !p.contains('.'))
        .collect();

    // Python: dir_tokens = set(); for part in dir_parts: dir_tokens.update(part.replace("-", " ").replace("_", " ").split())
    let mut dir_tokens: HashSet<String> = HashSet::new();
    for part in &dir_parts {
        for token in part.replace('-', " ").replace('_', " ").split_whitespace() {
            if !token.is_empty() {
                dir_tokens.insert(token.to_string());
            }
        }
    }

    // Python: file_extension(path)
    let ext = file_extension(path);

    // Python: path.count("/")
    let path_depth = path.chars().filter(|&c| c == '/').count() as f64;

    // Python: len(path.rsplit("/", 1)[-1]) — chars, not bytes.
    let filename_len = path
        .rsplit('/')
        .next()
        .map(|s| s.chars().count() as f64)
        .unwrap_or(0.0);

    // Python: is_test
    let is_test = is_test_path(path);

    // Python: fan_in_degree (raw count from lookup)
    let fan_in = fan_in_degrees.get(path).copied().unwrap_or(0.0);

    // Python CeMetaFeatureExtractor: fan_in_prior = (fan_in / max_fan_in) if max_fan_in > 0 else 0.0
    // NOTE: Python's HubPriorScorer.fanin_prior uses log1p, but the meta-ranker
    // feature (CeMetaFeatureExtractor._features) uses LINEAR normalization.
    let fan_in_prior = if max_fan_in > 0.0 {
        fan_in / max_fan_in
    } else {
        0.0
    };

    // Python: role_prior = HubPriorScorer.role_prior(path)
    let role_prior = role_prior(path);

    // Python: lexical_overlap = sum(1 for t in query_terms if t in path_lower) / query_term_count
    let lexical_overlap = if query_term_count > 0.0 {
        let matched = query_terms
            .iter()
            .filter(|t| path_lower.contains(t.as_str()))
            .count() as f64;
        matched / query_term_count
    } else {
        0.0
    };

    // Python: dir_proximity = len(overlap) / max(len(dir_tokens), 1)
    let dir_proximity = if !dir_tokens.is_empty() {
        let overlap = dir_tokens.intersection(query_term_set).count() as f64;
        overlap / dir_tokens.len() as f64
    } else {
        0.0
    };

    MetaFeatures {
        ce_score: candidate.ce_score,
        ce_rank: candidate.ce_rank as f64,
        fan_in_prior,
        role_prior,
        base_fused_score: candidate.fused_score,
        base_fused_rank: candidate.base_fused_rank as f64,
        lexical_overlap,
        path_depth,
        filename_len,
        is_test: if is_test { 1.0 } else { 0.0 },
        ext_java: if ext == "java" { 1.0 } else { 0.0 },
        ext_kt: if ext == "kt" { 1.0 } else { 0.0 },
        ext_xml: if ext == "xml" { 1.0 } else { 0.0 },
        ext_md: if ext == "md" { 1.0 } else { 0.0 },
        query_term_count,
        dir_proximity,
    }
}

/// Returns neutral fan-in degree of 1.0 for each file path so the pretrained LightGBM model
/// does not penalize paths with 0.0 in its trees.
pub fn build_fan_in_degrees(
    _adjacency: &GraphAdjacency,
    by_path: &HashMap<String, Vec<usize>>,
) -> HashMap<String, f64> {
    let mut degrees: HashMap<String, f64> = HashMap::with_capacity(by_path.len());
    for path in by_path.keys() {
        degrees.insert(path.clone(), 1.0);
    }
    degrees
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_query_terms_simple() {
        assert_eq!(query_terms("find Project Manager"), vec!["find", "project", "manager"]);
    }

    #[test]
    fn test_query_terms_special_chars() {
        assert_eq!(query_terms("cross-encoder_rerank/find"), vec!["cross", "encoder", "rerank", "find"]);
    }

    #[test]
    fn test_camel_case_tokens_simple() {
        assert_eq!(camel_case_tokens("ServiceManager"), vec!["service", "manager"]);
    }

    #[test]
    fn test_camel_case_tokens_acronym() {
        assert_eq!(camel_case_tokens("XMLParser"), vec!["xml", "parser"]);
    }

    #[test]
    fn test_camel_case_tokens_single() {
        assert_eq!(camel_case_tokens("Main"), vec!["main"]);
    }

    #[test]
    fn test_camel_case_tokens_lowercase() {
        assert_eq!(camel_case_tokens("index"), vec!["index"]);
    }

    #[test]
    fn test_role_prior_hub() {
        // "ServiceManager" -> ["service", "manager"] -> ends_with ["manager"] -> HUB
        let score = role_prior("src/manager/ServiceManager.kt");
        assert!((score - HUB_ROLE_PRIOR).abs() < 1e-6, "expected 1.0, got {}", score);
    }

    #[test]
    fn test_role_prior_peripheral() {
        // "TestAction" -> ["test", "action"] -> ends_with ["action"] -> PERIPHERAL
        let score = role_prior("src/actions/TestAction.java");
        assert!((score - PERIPHERAL_ROLE_PRIOR).abs() < 1e-6, "expected -0.5, got {}", score);
    }

    #[test]
    fn test_role_prior_neutral() {
        // "Main" -> ["main"] -> no match -> NEUTRAL
        let score = role_prior("src/main/Main.java");
        assert!((score - NEUTRAL_ROLE_PRIOR).abs() < 1e-6, "expected 0.0, got {}", score);
    }

    #[test]
    fn test_role_prior_test_path() {
        let score = role_prior("src/test/java/com/example/MyTest.java");
        assert!((score - TEST_PATH_ROLE_PRIOR).abs() < 1e-6, "expected -0.75, got {}", score);
    }

    #[test]
    fn test_role_prior_non_source() {
        let score = role_prior("src/main/resources/application.xml");
        assert!((score - NON_SOURCE_ROLE_PRIOR).abs() < 1e-6, "expected -1.0, got {}", score);
    }

    #[test]
    fn test_build_fan_in_degrees() {
        use std::collections::HashMap;
        let edges: HashMap<String, Vec<(String, f64)>> = HashMap::new();
        let adjacency = GraphAdjacency { edges };
        let mut by_path: HashMap<String, Vec<usize>> = HashMap::new();
        by_path.insert("a.rs".to_string(), vec![0]);
        by_path.insert("b.rs".to_string(), vec![1]);
        let degrees = build_fan_in_degrees(&adjacency, &by_path);
        assert_eq!(degrees.get("a.rs"), Some(&1.0));
        assert_eq!(degrees.get("b.rs"), Some(&1.0));
    }

    #[test]
    fn test_extract_features_filename_len_counts_chars() {
        use crate::types::Candidate;
        // 'Ж' is 2 bytes in UTF-8; Python len() counts 3 chars, not 6 bytes.
        let cand = Candidate {
            item_id: "t".to_string(),
            path: "src/ЖЖЖ.java".to_string(),
            ..Default::default()
        };
        let features = extract_features(&cand, &[], &HashSet::new(), 0.0, 0.0, &HashMap::new());
        assert_eq!(features.filename_len, 8.0); // "ЖЖЖ.java" = 3 + 5 chars
    }

    #[test]
    fn test_extract_features_basic() {
        use crate::types::Candidate;
        let cand = Candidate {
            item_id: "test".to_string(),
            path: "src/main/TestService.java".to_string(),
            ce_score: 0.5,
            ce_rank: 1,
            fused_score: 0.8,
            base_fused_rank: 2,
            ..Default::default()
        };
        let query_terms = vec!["test".to_string(), "service".to_string()];
        let query_term_set: HashSet<String> = query_terms.iter().cloned().collect();
        let mut fan_in = HashMap::new();
        fan_in.insert("src/main/TestService.java".to_string(), 5.0);

        let features = extract_features(
            &cand, &query_terms, &query_term_set, 2.0, 10.0, &fan_in
        );
        assert!((features.ce_score - 0.5).abs() < 1e-6);
        assert!((features.ce_rank - 1.0).abs() < 1e-6);
        assert!((features.base_fused_score - 0.8).abs() < 1e-6);
        assert!((features.base_fused_rank - 2.0).abs() < 1e-6);
        assert!((features.query_term_count - 2.0).abs() < 1e-6);
        // fan_in_prior = 5.0 / 10.0 = 0.5 (linear formula)
        assert!((features.fan_in_prior - 0.5).abs() < 0.01, "expected 0.5, got {}", features.fan_in_prior);
        // "TestService" -> ["test", "service"] -> ends_with ["service"] -> HUB_ROLE_PRIOR = 1.0
        assert!((features.role_prior - 1.0).abs() < 1e-6, "expected 1.0, got {}", features.role_prior);
        // ext = "java"
        assert!((features.ext_java - 1.0).abs() < 1e-6);
        assert!((features.ext_kt - 0.0).abs() < 1e-6);
    }
}