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

/// Fraction of query terms present in `candidates` (`HybridCandidateScorer._coverage`).
pub fn coverage(query_terms: &[String], candidates: &HashSet<String>) -> f64 {
    if candidates.is_empty() || query_terms.is_empty() {
        return 0.0;
    }
    let matches = query_terms
        .iter()
        .filter(|term| candidates.contains(*term))
        .count();
    matches as f64 / query_terms.len() as f64
}

/// `min(1, content * 0.75 + title * 0.25)` — lexical mix from field coverages.
pub fn lexical_from_coverages(content_coverage: f64, title_coverage: f64) -> f64 {
    (content_coverage * 0.75 + title_coverage * 0.25).min(1.0)
}

/// BM25 scores from pre-computed index data (no InvertedIndex needed).
///
/// Accepts the same data structures that `HybridLexicalIndex` holds internally:
/// - `term_frequencies`: {doc_id: {term: tf}}
/// - `document_lengths`: {doc_id: total_tokens}
/// - `postings`: {term: {doc_id, ...}}
/// - `average_document_length`: avgdl
/// - `terms`: query terms
///
/// Returns only positive scores (same as Python).
pub fn bm25_scores_from_data(
    term_frequencies: &HashMap<String, HashMap<String, u32>>,
    document_lengths: &HashMap<String, u32>,
    postings: &HashMap<String, HashSet<String>>,
    average_document_length: f64,
    terms: &[String],
    k1: f64,
    b: f64,
) -> HashMap<String, f64> {
    let total_documents = term_frequencies.len().max(1) as f64;
    let avgdl = average_document_length.max(1.0);
    let mut scores = HashMap::new();

    // Collect candidate doc IDs from postings
    let mut candidate_ids: HashSet<&str> = HashSet::new();
    for term in terms {
        if let Some(posting) = postings.get(term) {
            for id in posting {
                candidate_ids.insert(id.as_str());
            }
        }
    }

    for item_id in candidate_ids {
        let frequencies = match term_frequencies.get(item_id) {
            Some(f) => f,
            None => continue,
        };
        let document_length = f64::from(*document_lengths.get(item_id).unwrap_or(&0));
        let mut score = 0.0;
        for term in terms {
            let tf = f64::from(*frequencies.get(term).unwrap_or(&0));
            if tf <= 0.0 {
                continue;
            }
            let document_frequency = postings
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
        // 0.8*0.5 + 0.5*0.3 + 0.1*0.1 = 0.56
        // 0.2*0.5 + 0.9*0.3 + 0.3*0.1 + 0.4*0.1 = 0.44 (fp may be 0.44000000000000006)
        assert_eq!(result.len(), 2);
        assert!((result[0] - 0.56).abs() < 1e-12);
        assert!((result[1] - 0.44).abs() < 1e-12);
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
        let fields = [
            vec![1.0],
            vec![1.0],
            vec![1.0],
            vec![1.0],
            vec![1.0],
            vec![1.0],
            vec![1.0],
        ];
        let names = [
            "vector",
            "lexical",
            "path",
            "symbol",
            "symbol_match",
            "graph",
            "file_vote",
        ];

        for (index, name) in names.into_iter().enumerate() {
            let mut mismatched = fields.clone();
            mismatched[index].clear();
            let result = fuse_hybrid_batch(
                &mismatched[0],
                &mismatched[1],
                &mismatched[2],
                &mismatched[3],
                &mismatched[4],
                &mismatched[5],
                &mismatched[6],
                test_weights(),
            );
            let (field, length) = if index == 0 {
                ("lexical", 1)
            } else {
                (name, 0)
            };
            let expected = if index == 0 { 0 } else { 1 };
            assert_eq!(
                result.unwrap_err(),
                format!("batch field {field} has length {length}, expected {expected}")
            );
        }
    }

    #[test]
    fn bm25_scores_from_data_matches_inverted_index() {
        let mut idx = InvertedIndex::new();
        idx.ingest(
            "doc1".into(),
            &["foo".into(), "bar".into(), "bar".into()],
        );
        idx.ingest("doc2".into(), &["foo".into(), "foo".into(), "foo".into()]);
        idx.ingest("doc3".into(), &["baz".into()]);

        let expected = idx.bm25_scores(&["foo".into(), "bar".into()], 1.2, 0.75);

        let mut tf = HashMap::new();
        let mut dl = HashMap::new();
        let mut postings: HashMap<String, HashSet<String>> = HashMap::new();

        for (id, terms) in [
            ("doc1", &["foo", "bar", "bar"] as &[&str]),
            ("doc2", &["foo", "foo", "foo"]),
            ("doc3", &["baz"]),
        ] {
            let mut freqs: HashMap<String, u32> = HashMap::new();
            for t in terms {
                *freqs.entry((*t).to_string()).or_insert(0) += 1;
            }
            tf.insert(id.to_string(), freqs);
            dl.insert(id.to_string(), terms.len() as u32);
            for t in terms {
                postings
                    .entry((*t).to_string())
                    .or_default()
                    .insert(id.to_string());
            }
        }

        let actual = bm25_scores_from_data(&tf, &dl, &postings, 7.0 / 3.0, &["foo".into(), "bar".into()], 1.2, 0.75);
        assert_eq!(expected.len(), actual.len(), "same number of positive scores");
        for (id, exp_score) in &expected {
            let act_score = actual.get(id).expect("id should be in result");
            assert!(
                (exp_score - act_score).abs() < 1e-12,
                "score mismatch for {id}: expected {exp_score}, got {act_score}"
            );
        }
    }

    #[test]
    fn bm25_scores_from_data_empty_terms() {
        let tf = HashMap::new();
        let dl = HashMap::new();
        let postings = HashMap::new();
        let result = bm25_scores_from_data(&tf, &dl, &postings, 1.0, &[], 1.2, 0.75);
        assert!(result.is_empty());
    }

    #[test]
    fn bm25_scores_from_data_no_match() {
        let mut tf = HashMap::new();
        tf.insert("doc1".into(), {
            let mut f = HashMap::new();
            f.insert("foo".into(), 1);
            f
        });
        let mut dl = HashMap::new();
        dl.insert("doc1".into(), 1);
        let mut postings = HashMap::new();
        postings.insert(
            "foo".into(),
            {
                let mut s = HashSet::new();
                s.insert("doc1".into());
                s
            },
        );

        let result = bm25_scores_from_data(&tf, &dl, &postings, 1.0, &["bar".into()], 1.2, 0.75);
        assert!(result.is_empty());
    }

    #[test]
    fn coverage_is_query_term_fraction() {
        let candidates: HashSet<String> = ["foo".into(), "bar".into(), "zzz".into()]
            .into_iter()
            .collect();
        let terms = vec!["foo".into(), "bar".into(), "missing".into()];
        assert!((coverage(&terms, &candidates) - 2.0 / 3.0).abs() < 1e-12);
        assert_eq!(coverage(&[], &candidates), 0.0);
        assert_eq!(coverage(&terms, &HashSet::new()), 0.0);
    }

    #[test]
    fn lexical_from_coverages_caps_at_one() {
        assert!((lexical_from_coverages(1.0, 1.0) - 1.0).abs() < 1e-12);
        assert!((lexical_from_coverages(0.8, 0.4) - 0.7).abs() < 1e-12);
    }

    #[test]
    fn topk_respects_k() {
        let idx = idx_two_docs();
        let top = idx.bm25_topk(&["authorization".into()], 1, 1.2, 0.75);
        assert_eq!(top.len(), 1);
    }
}
