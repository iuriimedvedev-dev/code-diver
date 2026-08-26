//! BM25 over a sparse inverted index.
//!
//! Formula matches `HybridLexicalIndex.bm25_scores` in
//! `src/code_diver/strategies/hybrid_lexical_index.py`:
//!
//! ```text
//! idf = ln(1 + (N - df + 0.5) / (df + 0.5))
//! denom = tf + k1 * (1 - b + b * dl / avgdl)
//! score += idf * (tf * (k1 + 1) / denom)
//! ```

use std::collections::{HashMap, HashSet};

#[derive(Debug, Clone)]
pub struct InvertedIndex {
    /// doc_id -> term -> tf (weighted token counts as ingested)
    term_frequencies: HashMap<String, HashMap<String, u32>>,
    document_lengths: HashMap<String, u32>,
    /// term -> set of doc ids that contain the term
    postings: HashMap<String, HashSet<String>>,
    average_document_length: f64,
}

impl InvertedIndex {
    pub fn new() -> Self {
        Self {
            term_frequencies: HashMap::new(),
            document_lengths: HashMap::new(),
            postings: HashMap::new(),
            average_document_length: 0.0,
        }
    }

    /// Ingest one document. `tokens` are already tokenized (and optionally field-weighted
    /// by repeating title/path/metadata tokens, as Python does).
    pub fn ingest(&mut self, doc_id: String, tokens: &[String]) {
        let mut freqs: HashMap<String, u32> = HashMap::new();
        for token in tokens {
            *freqs.entry(token.clone()).or_insert(0) += 1;
        }
        let length: u32 = freqs.values().copied().sum();
        for term in freqs.keys() {
            self.postings
                .entry(term.clone())
                .or_default()
                .insert(doc_id.clone());
        }
        self.term_frequencies.insert(doc_id.clone(), freqs);
        self.document_lengths.insert(doc_id, length);
        self.recompute_avgdl();
    }

    fn recompute_avgdl(&mut self) {
        let n = self.document_lengths.len().max(1);
        let total: u64 = self.document_lengths.values().map(|v| u64::from(*v)).sum();
        self.average_document_length = total as f64 / n as f64;
    }

    pub fn document_count(&self) -> usize {
        self.term_frequencies.len()
    }

    pub fn candidate_ids<'a>(&'a self, terms: &'a [String]) -> HashSet<&'a str> {
        let mut ids: HashSet<&str> = HashSet::new();
        for term in terms {
            if let Some(posting) = self.postings.get(term) {
                for id in posting {
                    ids.insert(id.as_str());
                }
            }
        }
        ids
    }

    /// BM25 scores for documents that contain at least one query term.
    /// Only positive scores are returned (same as Python).
    pub fn bm25_scores(&self, terms: &[String], k1: f64, b: f64) -> HashMap<String, f64> {
        let item_ids = self.candidate_ids(terms);
        let total_documents = self.term_frequencies.len().max(1) as f64;
        let avgdl = self.average_document_length.max(1.0);
        let mut scores = HashMap::new();

        for item_id in item_ids {
            let frequencies = match self.term_frequencies.get(item_id) {
                Some(f) => f,
                None => continue,
            };
            let document_length = f64::from(*self.document_lengths.get(item_id).unwrap_or(&0));
            let mut score = 0.0;
            for term in terms {
                let tf = f64::from(*frequencies.get(term).unwrap_or(&0));
                if tf <= 0.0 {
                    continue;
                }
                let document_frequency = self
                    .postings
                    .get(term)
                    .map(|s| s.len())
                    .unwrap_or(0) as f64;
                let idf = (1.0
                    + (total_documents - document_frequency + 0.5) / (document_frequency + 0.5))
                    .ln();
                let denominator = tf + k1 * (1.0 - b + b * document_length / avgdl);
                score += idf * ((tf * (k1 + 1.0)) / denominator);
            }
            if score > 0.0 {
                scores.insert(item_id.to_string(), score);
            }
        }
        scores
    }

    pub fn bm25_topk(&self, terms: &[String], k: usize, k1: f64, b: f64) -> Vec<(String, f64)> {
        let mut ranked: Vec<(String, f64)> = self.bm25_scores(terms, k1, b).into_iter().collect();
        ranked.sort_by(|a, b| {
            b.1.partial_cmp(&a.1)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then_with(|| a.0.cmp(&b.0))
        });
        ranked.truncate(k);
        ranked
    }
}

impl Default for InvertedIndex {
    fn default() -> Self {
        Self::new()
    }
}

/// Weighted linear fusion of field scores (Python `HybridCandidateScore.total` without item).
pub fn fuse_hybrid(
    vector: f64,
    lexical: f64,
    path: f64,
    symbol: f64,
    symbol_match: f64,
    graph: f64,
    file_vote: f64,
    weights: HybridWeights,
) -> f64 {
    vector * weights.vector
        + lexical * weights.lexical
        + path * weights.path
        + symbol * weights.symbol
        + symbol_match * weights.symbol_match
        + graph * weights.graph
        + file_vote * weights.file_vote
}

/// Fuse parallel batches of field scores using the scalar fusion formula.
pub fn fuse_hybrid_batch(
    vector: &[f64],
    lexical: &[f64],
    path: &[f64],
    symbol: &[f64],
    symbol_match: &[f64],
    graph: &[f64],
    file_vote: &[f64],
    weights: HybridWeights,
) -> Result<Vec<f64>, String> {
    let length = vector.len();
    let fields = [
        ("lexical", lexical.len()),
        ("path", path.len()),
        ("symbol", symbol.len()),
        ("symbol_match", symbol_match.len()),
        ("graph", graph.len()),
        ("file_vote", file_vote.len()),
    ];
    for (name, field_length) in fields {
        if field_length != length {
            return Err(format!(
                "batch field {name} has length {field_length}, expected {length}"
            ));
        }
    }

    Ok((0..length)
        .map(|index| {
            fuse_hybrid(
                vector[index],
                lexical[index],
                path[index],
                symbol[index],
                symbol_match[index],
                graph[index],
                file_vote[index],
                weights,
            )
        })
        .collect())
}

#[derive(Debug, Clone, Copy)]
pub struct HybridWeights {
    pub vector: f64,
    pub lexical: f64,
    pub path: f64,
    pub symbol: f64,
    pub symbol_match: f64,
    pub graph: f64,
    pub file_vote: f64,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn idx_two_docs() -> InvertedIndex {
        let mut idx = InvertedIndex::new();
        idx.ingest(
            "target".into(),
            &["authorization".into(), "token".into(), "helper".into()],
        );
        idx.ingest(
            "generic".into(),
            &[
                "authorization".into(),
                "helper".into(),
                "common".into(),
                "common".into(),
                "common".into(),
                "common".into(),
            ],
        );
        idx
    }

    #[test]
    fn bm25_ranks_rarer_match_higher() {
        let idx = idx_two_docs();
        let terms = vec!["authorization".into(), "token".into()];
        let scores = idx.bm25_scores(&terms, 1.2, 0.75);
        assert!(scores["target"] > scores["generic"]);
        assert!(scores["target"] > 0.0);
    }

    #[test]
    fn bm25_skips_docs_without_terms() {
        let mut idx = InvertedIndex::new();
        idx.ingest("a".into(), &["foo".into()]);
        idx.ingest("b".into(), &["bar".into()]);
        let scores = idx.bm25_scores(&["zzz".into()], 1.2, 0.75);
        assert!(scores.is_empty());
    }

    #[test]
    fn test_weights() -> HybridWeights {
        HybridWeights {
            vector: 0.5,
            lexical: 0.3,
            path: 0.1,
            symbol: 0.1,
            symbol_match: 0.0,
            graph: 0.0,
            file_vote: 0.0,
        }
    }

    #[test]
    fn fuse_hybrid_is_weighted_sum() {
        let t = fuse_hybrid(1.0, 0.5, 0.0, 0.0, 0.0, 0.0, 0.0, test_weights());
        assert!((t - 0.65).abs() < 1e-12);
    }

    #[test]
    fn fuse_hybrid_batch_matches_scalar_for_all_fields() {
        let fields = [
            vec![1.0, 2.0],
            vec![3.0, 4.0],
            vec![5.0, 6.0],
            vec![7.0, 8.0],
            vec![9.0, 10.0],
            vec![11.0, 12.0],
            vec![13.0, 14.0],
        ];
        let weights = HybridWeights {
            vector: 0.1,
            lexical: 0.2,
            path: 0.3,
            symbol: 0.4,
            symbol_match: 0.5,
            graph: 0.6,
            file_vote: 0.7,
        };
        let actual = fuse_hybrid_batch(
            &fields[0], &fields[1], &fields[2], &fields[3], &fields[4], &fields[5],
            &fields[6], weights,
        )
        .unwrap();
        let expected = vec![
            fuse_hybrid(1.0, 3.0, 5.0, 7.0, 9.0, 11.0, 13.0, weights),
            fuse_hybrid(2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0, weights),
        ];
        assert_eq!(actual, expected);
    }

    #[test]
    fn fuse_hybrid_batch_handles_zeros_and_missing_fields() {
        let zeros = vec![0.0, 0.0];
        let values = vec![2.0, 4.0];
        let result = fuse_hybrid_batch(
            &values,
            &zeros,
            &zeros,
            &zeros,
            &zeros,
            &zeros,
            &zeros,
            HybridWeights {
                vector: 0.25,
                lexical: 1.0,
                path: 1.0,
                symbol: 1.0,
                symbol_match: 1.0,
                graph: 1.0,
                file_vote: 1.0,
            },
        )
        .unwrap();
        assert_eq!(result, vec![0.5, 1.0]);
    }

    #[test]
    fn fuse_hybrid_batch_handles_typical_mix() {
        let result = fuse_hybrid_batch(
            &[0.8, 0.2],
            &[0.5, 0.9],
            &[0.1, 0.3],
            &[0.0, 0.4],
            &[0.2, 0.0],
            &[0.1, 0.5],
            &[0.0, 0.2],
            test_weights(),
        )
        .unwrap();
        assert_eq!(result, vec![0.56, 0.44]);
    }

    #[test]
    fn fuse_hybrid_batch_handles_empty_input() {
        let empty: Vec<f64> = Vec::new();
        assert!(fuse_hybrid_batch(
            &empty, &empty, &empty, &empty, &empty, &empty, &empty, test_weights()
        )
        .unwrap()
        .is_empty());
    }

    #[test]
    fn fuse_hybrid_batch_rejects_mismatched_lengths() {
        let result = fuse_hybrid_batch(
            &[1.0], &[], &[1.0], &[1.0], &[1.0], &[1.0], &[1.0], test_weights(),
        );
        assert_eq!(
            result.unwrap_err(),
            "batch field lexical has length 0, expected 1"
        );
    }

    #[test]
    fn topk_respects_k() {
        let idx = idx_two_docs();
        let top = idx.bm25_topk(&["authorization".into()], 1, 1.2, 0.75);
        assert_eq!(top.len(), 1);
    }
}
