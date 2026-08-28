/// Vector math utilities: normalize, dot product, batch cosine similarity search.
///
/// These are the core operations used by `JsonVectorStore._search_items` and
/// `InMemoryVectorStore.search` — the real latency bottleneck (brute-force
/// cosine similarity over 68k items × 136k vectors).

/// L2-normalize a vector in place.
pub fn normalize(vector: &[f64]) -> Vec<f64> {
    let norm: f64 = vector.iter().map(|v| v * v).sum::<f64>().sqrt();
    if norm == 0.0 {
        return vector.to_vec();
    }
    vector.iter().map(|v| v / norm).collect()
}

/// Dot product of two equal-length vectors.
///
/// # Panics
/// Panics if the vectors have different lengths.
pub fn dot(left: &[f64], right: &[f64]) -> f64 {
    assert_eq!(
        left.len(),
        right.len(),
        "Vector dimension mismatch: {} != {}",
        left.len(),
        right.len()
    );
    left.iter().zip(right.iter()).map(|(a, b)| a * b).sum()
}

/// Batch cosine similarity over a flat f32 array.
///
/// `normalized_query` is the already-normalized query vector.
/// `flat_vectors` is a flat f32 array of all vectors concatenated.
/// `offsets` maps each vector index to its `(start, end)` byte range in the flat array.
/// `limit` caps the number of results.
///
/// Returns `[(index, score), ...]` sorted by score descending.
pub fn search_flat(
    normalized_query: &[f64],
    flat_vectors: &[f32],
    offsets: &[(usize, usize)],
    limit: usize,
) -> Vec<(usize, f64)> {
    let dim = normalized_query.len();
    let mut scored: Vec<(usize, f64)> = Vec::with_capacity(offsets.len());

    for (i, &(start, end)) in offsets.iter().enumerate() {
        let len = end.saturating_sub(start);
        if len == 0 {
            scored.push((i, 0.0));
            continue;
        }
        let slice_len = len.min(dim);
        let mut score = 0.0_f64;
        for j in 0..slice_len {
            score += normalized_query[j] * flat_vectors[start + j] as f64;
        }
        scored.push((i, score));
    }

    scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
    scored.truncate(limit);
    scored
}

/// Batch cosine similarity over a flat f64 array.
///
/// Same as `search_flat` but for f64 flat arrays.
pub fn search_flat_f64(
    normalized_query: &[f64],
    flat_vectors: &[f64],
    offsets: &[(usize, usize)],
    limit: usize,
) -> Vec<(usize, f64)> {
    let dim = normalized_query.len();
    let mut scored: Vec<(usize, f64)> = Vec::with_capacity(offsets.len());

    for (i, &(start, end)) in offsets.iter().enumerate() {
        let len = end.saturating_sub(start);
        if len == 0 {
            scored.push((i, 0.0));
            continue;
        }
        let slice_len = len.min(dim);
        let mut score = 0.0_f64;
        for j in 0..slice_len {
            score += normalized_query[j] * flat_vectors[start + j];
        }
        scored.push((i, score));
    }

    scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
    scored.truncate(limit);
    scored
}

#[cfg(test)]
mod tests {
    use super::*;

    const EPS: f64 = 1e-9;

    fn approx_eq(a: f64, b: f64) -> bool {
        (a - b).abs() < EPS
    }

    #[test]
    fn test_normalize_typical() {
        let result = normalize(&[3.0, 4.0]);
        assert!(approx_eq(result[0], 0.6), "expected 0.6, got {}", result[0]);
        assert!(approx_eq(result[1], 0.8), "expected 0.8, got {}", result[1]);
    }

    #[test]
    fn test_normalize_zero() {
        let result = normalize(&[0.0, 0.0]);
        assert_eq!(result, vec![0.0, 0.0]);
    }

    #[test]
    fn test_normalize_single() {
        let result = normalize(&[5.0]);
        assert!(approx_eq(result[0], 1.0), "expected 1.0, got {}", result[0]);
    }

    #[test]
    fn test_dot_basic() {
        let result = dot(&[1.0, 0.0], &[0.0, 1.0]);
        assert!(approx_eq(result, 0.0), "expected 0.0, got {}", result);
    }

    #[test]
    fn test_dot_same() {
        let result = dot(&[3.0, 4.0], &[3.0, 4.0]);
        assert!(approx_eq(result, 25.0), "expected 25.0, got {}", result);
    }

    #[test]
    #[should_panic(expected = "Vector dimension mismatch")]
    fn test_dot_mismatch() {
        dot(&[1.0, 0.0], &[1.0]);
    }

    #[test]
    fn test_search_flat_basic() {
        // 2 vectors in 2D: [1,0], [0,1]
        let flat: Vec<f32> = vec![1.0, 0.0, 0.0, 1.0];
        let offsets = vec![(0, 2), (2, 4)];
        let query = normalize(&[1.0, 0.0]);

        let result = search_flat(&query, &flat, &offsets, 10);
        assert_eq!(result.len(), 2);
        assert_eq!(result[0].0, 0, "index 0 (vector [1,0]) should be first");
        assert!(approx_eq(result[0].1, 1.0), "expected score 1.0, got {}", result[0].1);
        assert_eq!(result[1].0, 1, "index 1 (vector [0,1]) should be second");
        assert!(approx_eq(result[1].1, 0.0), "expected score 0.0, got {}", result[1].1);
    }

    #[test]
    fn test_search_flat_f64_basic() {
        let flat: Vec<f64> = vec![1.0, 0.0, 0.0, 1.0];
        let offsets = vec![(0, 2), (2, 4)];
        let query = normalize(&[1.0, 0.0]);

        let result = search_flat_f64(&query, &flat, &offsets, 10);
        assert_eq!(result.len(), 2);
        assert_eq!(result[0].0, 0);
        assert!(approx_eq(result[0].1, 1.0));
    }

    #[test]
    fn test_search_flat_limit() {
        // 3 vectors: [1,0], [0,1], [0.707, 0.707]
        let flat: Vec<f32> = vec![1.0, 0.0, 0.0, 1.0, 0.707, 0.707];
        let offsets = vec![(0, 2), (2, 4), (4, 6)];
        let query = normalize(&[1.0, 0.0]);

        let result = search_flat(&query, &flat, &offsets, 1);
        assert_eq!(result.len(), 1);
        assert_eq!(result[0].0, 0);
    }

    #[test]
    fn test_search_flat_empty() {
        let result = search_flat(&[1.0, 0.0], &[], &[], 10);
        assert!(result.is_empty());
    }

    #[test]
    fn test_search_flat_zero_vector() {
        let flat: Vec<f32> = vec![0.0, 0.0, 1.0, 0.0];
        let offsets = vec![(0, 2), (2, 4)];
        let query = normalize(&[1.0, 0.0]);

        let result = search_flat(&query, &flat, &offsets, 10);
        assert_eq!(result.len(), 2);
        // Zero vector should give score 0.0
        assert_eq!(result[0].0, 1, "non-zero vector should be first");
        assert_eq!(result[1].0, 0, "zero vector should be second");
    }

    #[test]
    fn test_search_flat_f64_limit() {
        let flat: Vec<f64> = vec![1.0, 0.0, 0.0, 1.0, 0.707, 0.707];
        let offsets = vec![(0, 2), (2, 4), (4, 6)];
        let query = normalize(&[1.0, 0.0]);

        let result = search_flat_f64(&query, &flat, &offsets, 2);
        assert_eq!(result.len(), 2);
        assert_eq!(result[0].0, 0);
        assert_eq!(result[1].0, 2);
    }
}