use std::collections::HashMap;

use crate::catalog::tokenize;
use crate::types::{Bm25Index, CatalogItem};

/// Build a BM25 index from a slice of catalog items.
pub fn build_bm25_index(items: &[CatalogItem]) -> Bm25Index {
    let mut term_frequencies: HashMap<String, HashMap<String, u32>> = HashMap::new();
    let mut document_lengths: HashMap<String, u32> = HashMap::new();
    let mut postings: HashMap<String, Vec<String>> = HashMap::new();
    let mut total_tokens: u64 = 0;
    let mut num_docs: usize = 0;

    for item in items {
        let doc_id = if !item.id.is_empty() {
            item.id.clone()
        } else {
            item.path.clone()
        };
        if doc_id.is_empty() {
            continue;
        }

        // Collect all tokens from different fields
        let mut all_tokens: Vec<String> = Vec::new();
        // Use pre-tokenized fields if available (all 4 fields), otherwise fall back
        // to raw tokenization of name, path, and content (Rust v11 baseline parity).
        let has_pre_tokenized = !item.tokenized_name.is_empty()
            || !item.tokenized_path.is_empty()
            || !item.tokenized_dir.is_empty()
            || !item.tokenized_content.is_empty();

        if has_pre_tokenized {
            for t in &item.tokenized_name {
                all_tokens.push(t.to_lowercase());
            }
            for t in &item.tokenized_path {
                all_tokens.push(t.to_lowercase());
            }
            for t in &item.tokenized_dir {
                all_tokens.push(t.to_lowercase());
            }
            for t in &item.tokenized_content {
                all_tokens.push(t.to_lowercase());
            }
        } else {
            // Fallback: tokenize raw fields
            for t in tokenize(&item.name) {
                all_tokens.push(t);
            }
            for t in tokenize(&item.path) {
                all_tokens.push(t);
            }
            for t in tokenize(&item.content) {
                all_tokens.push(t.to_lowercase());
            }
        }

        let mut tf: HashMap<String, u32> = HashMap::new();
        for token in &all_tokens {
            *tf.entry(token.clone()).or_insert(0) += 1;
        }

        let doc_len = all_tokens.len() as u32;
        document_lengths.insert(doc_id.clone(), doc_len);
        total_tokens += doc_len as u64;
        num_docs += 1;

        for (term, _freq) in &tf {
            postings.entry(term.clone()).or_default().push(doc_id.clone());
        }

        term_frequencies.insert(doc_id, tf);
    }

    let avgdl = if num_docs > 0 {
        total_tokens as f64 / num_docs as f64
    } else {
        1.0
    };

    Bm25Index {
        term_frequencies,
        document_lengths,
        postings,
        avgdl,
        num_docs,
    }
}

/// Compute BM25 scores for a query against a BM25 index.
/// Returns document_id -> score.
pub fn bm25_scores(
    index: &Bm25Index,
    query_terms: &[String],
    k1: f64,
    b: f64,
) -> HashMap<String, f64> {
    let mut scores: HashMap<String, f64> = HashMap::new();

    let num_docs = index.num_docs as f64;
    if num_docs == 0.0 {
        return scores;
    }

    for term in query_terms {
        let term_lower = term.to_lowercase();
        let docs_with_term = match index.postings.get(&term_lower) {
            Some(docs) => docs,
            None => continue,
        };

        let idf = ((num_docs - docs_with_term.len() as f64 + 0.5)
            / (docs_with_term.len() as f64 + 0.5)
            + 1.0)
            .ln();

        for doc_id in docs_with_term {
            let tf = index
                .term_frequencies
                .get(doc_id)
                .and_then(|tf_map| tf_map.get(&term_lower))
                .copied()
                .unwrap_or(0) as f64;

            if tf == 0.0 {
                continue;
            }

            let doc_len = *index.document_lengths.get(doc_id).unwrap_or(&1) as f64;
            let score = idf * ((tf * (k1 + 1.0)) / (tf + k1 * (1.0 - b + b * (doc_len / index.avgdl))));
            *scores.entry(doc_id.clone()).or_insert(0.0) += score;
        }
    }

    scores
}

/// Compute a simple coverage score: what fraction of query terms appear in the document's tokens.
#[allow(dead_code)]
pub fn coverage_score(doc: &CatalogItem, query_terms: &[String]) -> f64 {
    if query_terms.is_empty() {
        return 0.0;
    }

    // Collect all tokens from this document
    let mut all_tokens: Vec<String> = Vec::new();
    for t in &doc.tokenized_name {
        all_tokens.push(t.to_lowercase());
    }
    for t in &doc.tokenized_path {
        all_tokens.push(t.to_lowercase());
    }
    for t in &doc.tokenized_dir {
        all_tokens.push(t.to_lowercase());
    }

    let token_set: std::collections::HashSet<&str> =
        all_tokens.iter().map(|s| s.as_str()).collect();

    let matched = query_terms
        .iter()
        .filter(|t| token_set.contains(t.as_str()))
        .count();

    matched as f64 / query_terms.len() as f64
}

/// Compute path coverage: what fraction of query terms appear in the item's path tokens.
/// Python: path_coverage = self._coverage(profile.path_terms)
pub fn path_coverage_score(doc: &CatalogItem, query_terms: &[String]) -> f64 {
    if query_terms.is_empty() {
        return 0.0;
    }
    let fallback_path: Vec<String>;
    let path_tokens: &[String] = if !doc.tokenized_path.is_empty() {
        &doc.tokenized_path
    } else if !doc.path.is_empty() {
        fallback_path = tokenize(&doc.path);
        &fallback_path
    } else {
        &[]
    };
    let token_set: std::collections::HashSet<&str> =
        path_tokens.iter().map(|s| s.as_str()).collect();
    let matched = query_terms.iter().filter(|t| token_set.contains(t.as_str())).count();
    matched as f64 / query_terms.len() as f64
}

/// Compute content coverage (lexical): what fraction of query terms appear in content/name tokens.
/// Python: content_coverage * 0.75 + title_coverage * 0.25
#[allow(dead_code)]
pub fn lexical_coverage_score(doc: &CatalogItem, query_terms: &[String]) -> f64 {
    if query_terms.is_empty() {
        return 0.0;
    }
    // Content coverage: from tokenized_content and tokenized_name
    let fallback_content: Vec<String>;
    let content_tokens: &[String] = if !doc.tokenized_content.is_empty() {
        &doc.tokenized_content
    } else if !doc.content.is_empty() {
        fallback_content = tokenize(&doc.content);
        &fallback_content
    } else {
        &[]
    };
    let content_set: std::collections::HashSet<&str> =
        content_tokens.iter().map(|s| s.as_str()).collect();
    let content_matched = query_terms.iter().filter(|t| content_set.contains(t.as_str())).count();
    let content_cov = content_matched as f64 / query_terms.len() as f64;

    // Title coverage: from tokenized_name
    let fallback_name: Vec<String>;
    let title_tokens: &[String] = if !doc.tokenized_name.is_empty() {
        &doc.tokenized_name
    } else if !doc.name.is_empty() {
        fallback_name = tokenize(&doc.name);
        &fallback_name
    } else {
        &[]
    };
    let title_set: std::collections::HashSet<&str> =
        title_tokens.iter().map(|s| s.as_str()).collect();
    let title_matched = query_terms.iter().filter(|t| title_set.contains(t.as_str())).count();
    let title_cov = title_matched as f64 / query_terms.len() as f64;

    // Python: min(1.0, content_coverage * 0.75 + title_coverage * 0.25)
    (content_cov * 0.75 + title_cov * 0.25).min(1.0)
}

/// Compute symbol coverage: what fraction of query terms appear in the item's symbol tokens.
/// Python: symbol_coverage = self._coverage(profile.metadata_terms)
pub fn symbol_coverage_score(doc: &CatalogItem, query_terms: &[String]) -> f64 {
    if query_terms.is_empty() {
        return 0.0;
    }
    let fallback_name: Vec<String>;
    let name_tokens: &[String] = if !doc.tokenized_name.is_empty() {
        &doc.tokenized_name
    } else if !doc.name.is_empty() {
        fallback_name = tokenize(&doc.name);
        &fallback_name
    } else if !doc.path.is_empty() {
        fallback_name = tokenize(&doc.path);
        &fallback_name
    } else {
        &[]
    };

    let fallback_content: Vec<String>;
    let content_tokens: &[String] = if !doc.tokenized_content.is_empty() {
        &doc.tokenized_content
    } else if !doc.content.is_empty() {
        fallback_content = tokenize(&doc.content);
        &fallback_content
    } else {
        &[]
    };

    // Use content + name tokens + symbols as proxy for symbol terms (Python: metadata_terms)
    let token_set: std::collections::HashSet<&str> = content_tokens
        .iter()
        .chain(name_tokens.iter())
        .chain(doc.symbols.iter())
        .map(|s| s.as_str())
        .collect();
    let matched = query_terms.iter().filter(|t| token_set.contains(t.as_str())).count();
    matched as f64 / query_terms.len() as f64
}

/// Compute symbol match score: special match against item's symbol metadata.
/// Python: matches / max(min(len(symbol_terms), len(query_terms)), 1)
pub fn symbol_match_score(doc: &CatalogItem, query_terms: &[String]) -> f64 {
    if query_terms.is_empty() {
        return 0.0;
    }
    // Use name tokens as proxy for symbol metadata (Python: CodeItemMetadata.SYMBOL)
    // If tokenized_name is empty, fallback to tokenizing doc.name or doc.path.
    let fallback_tokens: Vec<String>;
    let symbol_terms: Vec<&str> = if !doc.tokenized_name.is_empty() {
        doc.tokenized_name.iter().map(|s| s.as_str()).collect()
    } else if !doc.name.is_empty() {
        fallback_tokens = tokenize(&doc.name);
        fallback_tokens.iter().map(|s| s.as_str()).collect()
    } else if !doc.path.is_empty() {
        fallback_tokens = tokenize(&doc.path);
        fallback_tokens.iter().map(|s| s.as_str()).collect()
    } else {
        return 0.0;
    };
    if symbol_terms.is_empty() {
        return 0.0;
    }
    let symbol_set: std::collections::HashSet<&str> = symbol_terms.iter().cloned().collect();
    let matches = query_terms.iter().filter(|t| symbol_set.contains(t.as_str())).count();
    if matches == 0 {
        return 0.0;
    }
    // Python: min(1.0, matches / max(min(len(symbol_terms), len(query_terms)), 1))
    let denom = (symbol_terms.len().min(query_terms.len())).max(1);
    (matches as f64 / denom as f64).min(1.0)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::CatalogItem;

    fn make_item(id: &str, name: &str, path: &str) -> CatalogItem {
        CatalogItem {
            id: id.to_string(),
            path: path.to_string(),
            name: name.to_string(),
            kind: String::new(),
            content: String::new(),
            symbols: vec![],
            tokenized_name: vec![],
            tokenized_path: vec![],
            tokenized_dir: vec![],
            tokenized_content: vec![],
        }
    }

    #[test]
    fn test_bm25_empty_index() {
        let index = build_bm25_index(&[]);
        let scores = bm25_scores(&index, &["hello".to_string()], 1.2, 0.75);
        assert!(scores.is_empty());
    }

    #[test]
    fn test_bm25_single_doc() {
        let mut item = make_item("doc1", "hello world", "/path/file.rs");
        item.tokenized_name = vec!["hello".to_string(), "world".to_string()];
        let items = vec![item];
        let index = build_bm25_index(&items);
        let scores = bm25_scores(&index, &["hello".to_string()], 1.2, 0.75);
        assert!(scores.contains_key("doc1"));
        assert!(scores["doc1"] > 0.0);
    }

    #[test]
    fn test_coverage_score() {
        let mut item = make_item("doc1", "hello world", "/path/file.rs");
        item.tokenized_name = vec!["hello".to_string(), "world".to_string()];
        let terms = vec!["hello".to_string(), "world".to_string()];
        let score = coverage_score(&item, &terms);
        assert!(score > 0.0);
    }

    #[test]
    fn test_symbol_match_fallback_to_name() {
        let item = make_item("doc1", "ProjectManager", "/path/file.rs");
        // tokenized_name is empty, should tokenize item.name -> ["projectmanager"] or tokens
        let query = vec!["projectmanager".to_string()];
        let score = symbol_match_score(&item, &query);
        assert!(score > 0.0, "Expected positive score from name fallback, got {}", score);
    }

    #[test]
    fn test_symbol_match_fallback_to_path() {
        let item = make_item("doc1", "", "src/ide/ProjectManager.kt");
        // tokenized_name and name empty, should tokenize item.path
        let query = vec!["projectmanager".to_string()];
        let score = symbol_match_score(&item, &query);
        assert!(score > 0.0, "Expected positive score from path fallback, got {}", score);
    }

    #[test]
    fn test_symbol_coverage_with_symbols() {
        let mut item = make_item("doc1", "", "/path/file.rs");
        item.symbols = vec!["indexer".to_string(), "scanner".to_string()];
        let query = vec!["indexer".to_string(), "query".to_string()];
        let score = symbol_coverage_score(&item, &query);
        assert!((score - 0.5).abs() < 1e-6, "Expected 0.5 coverage, got {}", score);
    }
}