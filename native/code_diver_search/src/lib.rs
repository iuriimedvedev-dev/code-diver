mod bm25;

pub use bm25::{fuse_hybrid, HybridWeights, InvertedIndex};

#[cfg(feature = "python")]
use pyo3::prelude::*;
#[cfg(feature = "python")]
use pyo3::types::PyDict;

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

/// Field fusion stub matching `HybridCandidateScore.total`.
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
#[pymodule]
fn code_diver_search(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyInvertedIndex>()?;
    m.add_function(wrap_pyfunction!(fuse_hybrid_py, m)?)?;
    m.add("__version__", "0.1.0")?;
    Ok(())
}
