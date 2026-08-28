mod bm25;
mod file_propagate;
mod seed_scores;
mod vector_math;

pub use bm25::{
    bm25_scores_from_data, coverage, fuse_hybrid, fuse_hybrid_batch, lexical_from_coverages,
    HybridWeights, InvertedIndex,
};
pub use file_propagate::{
    expand_adjacency, propagate_file_scores, AdjacencyExpandParams, FileAdjacency,
    FilePropagateParams,
};
pub use seed_scores::{seed_coverages, ItemSeedData};
pub use vector_math::{normalize, dot, search_flat, search_flat_f64};

#[cfg(feature = "python")]
use pyo3::exceptions::PyValueError;
#[cfg(feature = "python")]
use pyo3::prelude::*;
#[cfg(feature = "python")]
use pyo3::types::{PyDict, PySet};
#[cfg(feature = "python")]
use std::collections::{HashMap, HashSet};

#[cfg(feature = "python")]
#[pyfunction]
fn normalize_py(vector: Vec<f64>) -> Vec<f64> {
    normalize(&vector)
}

#[cfg(feature = "python")]
#[pyfunction]
fn dot_py(left: Vec<f64>, right: Vec<f64>) -> PyResult<f64> {
    if left.len() != right.len() {
        return Err(PyValueError::new_err(format!(
            "Vector dimension mismatch: {} != {}", left.len(), right.len()
        )));
    }
    Ok(dot(&left, &right))
}

#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(signature = (normalized_query, flat_vectors, offsets, limit))]
fn search_flat_py(
    normalized_query: Vec<f64>,
    flat_vectors: Vec<f32>,
    offsets: Vec<(usize, usize)>,
    limit: usize,
) -> Vec<(usize, f64)> {
    search_flat(&normalized_query, &flat_vectors, &offsets, limit)
}

#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(signature = (normalized_query, flat_vectors, offsets, limit))]
fn search_flat_f64_py(
    normalized_query: Vec<f64>,
    flat_vectors: Vec<f64>,
    offsets: Vec<(usize, usize)>,
    limit: usize,
) -> Vec<(usize, f64)> {
    search_flat_f64(&normalized_query, &flat_vectors, &offsets, limit)
}

#[cfg(feature = "python")]
#[pyclass(name = "InvertedIndex")]
struct PyInvertedIndex {
    inner: InvertedIndex,
}

#[cfg(feature = "python")]
#[pymethods]
impl PyInvertedIndex {
    #[new]
    fn new() -> Self {
        Self {
            inner: InvertedIndex::new(),
        }
    }

    /// Ingest a tokenized document. Tokens must already be split (Python tokenizer).
    fn ingest(&mut self, doc_id: String, tokens: Vec<String>) {
        self.inner.ingest(doc_id, &tokens);
    }

    fn document_count(&self) -> usize {
        self.inner.document_count()
    }

    /// Return `{doc_id: score}` for BM25 (k1=1.2, b=0.75 by default).
    #[pyo3(signature = (terms, k1=1.2, b=0.75))]
    fn bm25_scores(&self, terms: Vec<String>, k1: f64, b: f64) -> PyResult<PyObject> {
        Python::with_gil(|py| {
            let scores = self.inner.bm25_scores(&terms, k1, b);
            let dict = PyDict::new(py);
            for (id, score) in scores {
                dict.set_item(id, score)?;
            }
            Ok(dict.into())
        })
    }

    #[pyo3(signature = (terms, k, k1=1.2, b=0.75))]
    fn bm25_topk(
        &self,
        terms: Vec<String>,
        k: usize,
        k1: f64,
        b: f64,
    ) -> Vec<(String, f64)> {
        self.inner.bm25_topk(&terms, k, k1, b)
    }
}

/// Field fusion matching `HybridCandidateScore.total`.
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(signature = (vector, lexical, path, symbol, symbol_match=0.0, graph=0.0, file_vote=0.0, vector_weight=0.0, lexical_weight=0.0, path_weight=0.0, symbol_weight=0.0, symbol_match_weight=0.0, graph_weight=0.0, file_vote_weight=0.0))]
fn fuse_hybrid_py(
    vector: f64,
    lexical: f64,
    path: f64,
    symbol: f64,
    symbol_match: f64,
    graph: f64,
    file_vote: f64,
    vector_weight: f64,
    lexical_weight: f64,
    path_weight: f64,
    symbol_weight: f64,
    symbol_match_weight: f64,
    graph_weight: f64,
    file_vote_weight: f64,
) -> f64 {
    fuse_hybrid(
        vector,
        lexical,
        path,
        symbol,
        symbol_match,
        graph,
        file_vote,
        HybridWeights {
            vector: vector_weight,
            lexical: lexical_weight,
            path: path_weight,
            symbol: symbol_weight,
            symbol_match: symbol_match_weight,
            graph: graph_weight,
            file_vote: file_vote_weight,
        },
    )
}

#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(signature = (vector, lexical, path, symbol, symbol_match, graph, file_vote, vector_weight=0.0, lexical_weight=0.0, path_weight=0.0, symbol_weight=0.0, symbol_match_weight=0.0, graph_weight=0.0, file_vote_weight=0.0))]
fn fuse_hybrid_batch_py(
    vector: Vec<f64>,
    lexical: Vec<f64>,
    path: Vec<f64>,
    symbol: Vec<f64>,
    symbol_match: Vec<f64>,
    graph: Vec<f64>,
    file_vote: Vec<f64>,
    vector_weight: f64,
    lexical_weight: f64,
    path_weight: f64,
    symbol_weight: f64,
    symbol_match_weight: f64,
    graph_weight: f64,
    file_vote_weight: f64,
) -> PyResult<Vec<f64>> {
    fuse_hybrid_batch(
        &vector,
        &lexical,
        &path,
        &symbol,
        &symbol_match,
        &graph,
        &file_vote,
        HybridWeights {
            vector: vector_weight,
            lexical: lexical_weight,
            path: path_weight,
            symbol: symbol_weight,
            symbol_match: symbol_match_weight,
            graph: graph_weight,
            file_vote: file_vote_weight,
        },
    )
    .map_err(PyValueError::new_err)
}

#[cfg(feature = "python")]
fn py_adjacency_to_rust(adjacency: HashMap<String, Vec<(String, f64)>>) -> FileAdjacency {
    adjacency
}

#[cfg(feature = "python")]
fn rust_scores_to_py(py: Python<'_>, scores: HashMap<String, f64>) -> PyResult<PyObject> {
    let dict = PyDict::new(py);
    for (id, score) in scores {
        dict.set_item(id, score)?;
    }
    Ok(dict.into())
}

/// Graph-file `_propagate` (decay ** (depth+1), seed/neighbor/frontier limits).
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(signature = (adjacency, seed_file_scores, depth, decay, seed_limit, neighbor_limit, frontier_limit=None))]
fn propagate_file_scores_py(
    py: Python<'_>,
    adjacency: HashMap<String, Vec<(String, f64)>>,
    seed_file_scores: HashMap<String, f64>,
    depth: usize,
    decay: f64,
    seed_limit: usize,
    neighbor_limit: usize,
    frontier_limit: Option<usize>,
) -> PyResult<PyObject> {
    let scores = propagate_file_scores(
        &py_adjacency_to_rust(adjacency),
        &seed_file_scores,
        FilePropagateParams {
            depth,
            decay,
            seed_limit,
            neighbor_limit,
            frontier_limit,
        },
    );
    rust_scores_to_py(py, scores)
}

/// `FileGraphAdjacencyIndex.expand` (decay ** depth, best_seen, min_score).
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(signature = (adjacency, seed_file_scores, depth, decay, neighbor_limit, min_score=0.0))]
fn expand_adjacency_py(
    py: Python<'_>,
    adjacency: HashMap<String, Vec<(String, f64)>>,
    seed_file_scores: HashMap<String, f64>,
    depth: usize,
    decay: f64,
    neighbor_limit: usize,
    min_score: f64,
) -> PyResult<PyObject> {
    let scores = expand_adjacency(
        &py_adjacency_to_rust(adjacency),
        &seed_file_scores,
        AdjacencyExpandParams {
            depth,
            decay,
            neighbor_limit,
            min_score,
        },
    );
    rust_scores_to_py(py, scores)
}

#[cfg(feature = "python")]
#[pyfunction]
fn coverage_py(query_terms: Vec<String>, candidates: Vec<String>) -> f64 {
    use std::collections::HashSet;
    let set: HashSet<String> = candidates.into_iter().collect();
    coverage(&query_terms, &set)
}

#[cfg(feature = "python")]
#[pyfunction]
fn lexical_from_coverages_py(content_coverage: f64, title_coverage: f64) -> f64 {
    lexical_from_coverages(content_coverage, title_coverage)
}

/// BM25 scores from pre-computed index data (avoids rebuilding InvertedIndex).
///
/// Accepts Python-native data structures:
/// - ``term_frequencies``: {doc_id: {term: tf}}
/// - ``document_lengths``: {doc_id: total_tokens}
/// - ``postings``: {term: {doc_id, ...}}
/// - ``average_document_length``: avgdl
/// - ``terms``: query terms
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(signature = (term_frequencies, document_lengths, postings, average_document_length, terms, k1=1.2, b=0.75))]
fn bm25_scores_from_data_py(
    py: Python<'_>,
    term_frequencies: HashMap<String, HashMap<String, u32>>,
    document_lengths: HashMap<String, u32>,
    postings: HashMap<String, Py<PySet>>,
    average_document_length: f64,
    terms: Vec<String>,
    k1: f64,
    b: f64,
) -> PyResult<PyObject> {
    // Convert Python sets to Rust HashSets
    let mut rust_postings: HashMap<String, HashSet<String>> = HashMap::new();
    for (term, py_set) in postings {
        let set = py_set.bind(py);
        let mut rust_set = HashSet::new();
        for item in set.iter() {
            if let Ok(s) = item.extract::<String>() {
                rust_set.insert(s);
            }
        }
        rust_postings.insert(term, rust_set);
    }

    let scores = bm25_scores_from_data(
        &term_frequencies,
        &document_lengths,
        &rust_postings,
        average_document_length,
        &terms,
        k1,
        b,
    );

    let dict = PyDict::new(py);
    for (id, score) in scores {
        dict.set_item(id, score)?;
    }
    Ok(dict.into())
}

/// Seed coverages: compute lexical/path/symbol scores for all catalog items.
///
/// Accepts:
/// - ``profiles``: ``{item_id: {"title": [str], "path": [str], "content": [str], "metadata": [str]}}``
/// - ``item_ids``: ordered list of item IDs
/// - ``paths``: ordered list of item paths (same order as item_ids)
/// - ``query_terms``: query terms
/// - ``lexical_seed_limit``: max items to return
/// - ``symbols``: ``{item_id: str | None}``
///
/// Returns ``[(item_id, lexical_score, path_score, symbol_score), ...]`` sorted by
/// (lexical desc, path desc, symbol desc, path asc), limited to ``lexical_seed_limit``.
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(signature = (profiles, item_ids, paths, query_terms, lexical_seed_limit, symbols))]
fn seed_coverages_py(
    profiles: HashMap<String, HashMap<String, Vec<String>>>,
    item_ids: Vec<String>,
    paths: Vec<String>,
    query_terms: Vec<String>,
    lexical_seed_limit: usize,
    symbols: HashMap<String, Option<String>>,
) -> Vec<(String, f64, f64, f64)> {
    let mut items = Vec::with_capacity(item_ids.len());

    for (i, id) in item_ids.iter().enumerate() {
        let path = paths.get(i).cloned().unwrap_or_default();
        let profile = match profiles.get(id) {
            Some(p) => p,
            None => continue,
        };

        let title_terms: HashSet<String> = profile
            .get("title")
            .map(|v| v.iter().cloned().collect())
            .unwrap_or_default();
        let content_terms: HashSet<String> = profile
            .get("content")
            .map(|v| v.iter().cloned().collect())
            .unwrap_or_default();
        let path_terms: HashSet<String> = profile
            .get("path")
            .map(|v| v.iter().cloned().collect())
            .unwrap_or_default();
        let metadata_terms: HashSet<String> = profile
            .get("metadata")
            .map(|v| v.iter().cloned().collect())
            .unwrap_or_default();
        let symbol = symbols.get(id).cloned().unwrap_or(None);

        items.push(ItemSeedData {
            id: id.clone(),
            path,
            title_terms,
            content_terms,
            path_terms,
            metadata_terms,
            symbol,
        });
    }

    seed_coverages(items, &query_terms, lexical_seed_limit)
}

#[cfg(feature = "python")]
#[pymodule]
fn code_diver_search(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyInvertedIndex>()?;
    m.add_function(wrap_pyfunction!(fuse_hybrid_py, m)?)?;
    m.add_function(wrap_pyfunction!(fuse_hybrid_batch_py, m)?)?;
    m.add_function(wrap_pyfunction!(propagate_file_scores_py, m)?)?;
    m.add_function(wrap_pyfunction!(expand_adjacency_py, m)?)?;
    m.add_function(wrap_pyfunction!(coverage_py, m)?)?;
    m.add_function(wrap_pyfunction!(lexical_from_coverages_py, m)?)?;
    m.add_function(wrap_pyfunction!(bm25_scores_from_data_py, m)?)?;
    m.add_function(wrap_pyfunction!(seed_coverages_py, m)?)?;
    m.add_function(wrap_pyfunction!(normalize_py, m)?)?;
    m.add_function(wrap_pyfunction!(dot_py, m)?)?;
    m.add_function(wrap_pyfunction!(search_flat_py, m)?)?;
    m.add_function(wrap_pyfunction!(search_flat_f64_py, m)?)?;
    m.add("__version__", "0.2.0")?;
    Ok(())
}
