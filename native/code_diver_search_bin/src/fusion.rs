use std::collections::HashMap;

use crate::types::{Candidate, SearchConfig};

/// Fuse multiple score signals into a single score.
#[allow(dead_code)]
pub fn fuse_scores(
    vector_score: f64,
    lexical_score: f64,
    path_score: f64,
    symbol_score: f64,
    graph_score: f64,
    hub_prior: f64,
    config: &SearchConfig,
) -> f64 {
    vector_score * config.vector_weight
        + lexical_score * config.lexical_weight
        + path_score * config.path_weight
        + symbol_score * config.symbol_weight
        + graph_score * config.graph_weight
        + hub_prior * config.hub_prior_fanin_weight
}

/// Normalize a vector of scores to [0, 1] range.
pub fn normalize_scores(scores: &mut HashMap<String, f64>) {
    if scores.is_empty() {
        return;
    }
    let max_val = scores
        .values()
        .cloned()
        .fold(f64::NEG_INFINITY, f64::max);
    let min_val = scores
        .values()
        .cloned()
        .fold(f64::INFINITY, f64::min);
    let range = max_val - min_val;
    if range <= 0.0 {
        for v in scores.values_mut() {
            *v = 0.0;
        }
        return;
    }
    for v in scores.values_mut() {
        *v = (*v - min_val) / range;
    }
}

/// L2 normalize a vector.
pub fn l2_normalize(vec: &[f64]) -> Vec<f64> {
    let norm: f64 = vec.iter().map(|x| x * x).sum();
    if norm <= 0.0 {
        return vec.to_vec();
    }
    let inv_norm = 1.0 / norm.sqrt();
    vec.iter().map(|x| x * inv_norm).collect()
}

/// Compute dot product.
#[allow(dead_code)]
pub fn dot(a: &[f64], b: &[f64]) -> f64 {
    a.iter().zip(b.iter()).map(|(x, y)| x * y).sum()
}

/// Compute the inverse sigmoid (logit) of a probability.
pub fn logit(probability: f64) -> f64 {
    const EPSILON: f64 = 1e-7;
    let clamped = probability.clamp(EPSILON, 1.0 - EPSILON);
    (clamped / (1.0 - clamped)).ln()
}

/// Sort candidates by their fused score, descending.
pub fn sort_by_fused(candidates: &mut Vec<Candidate>) {
    candidates.sort_by(|a, b| b.fused_score.partial_cmp(&a.fused_score).unwrap_or(std::cmp::Ordering::Equal));
}

/// Sort candidates by their CE score, descending.
pub fn sort_by_ce(candidates: &mut Vec<Candidate>) {
    candidates.sort_by(|a, b| {
        b.ce_score
            .partial_cmp(&a.ce_score)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
}

/// Sort candidates by their meta score, descending.
pub fn sort_by_meta(candidates: &mut Vec<Candidate>) {
    candidates.sort_by(|a, b| {
        b.meta_score
            .partial_cmp(&a.meta_score)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
}

/// Break ties in CE scores by the fused base score.
pub fn tie_break_by_fused(candidates: &mut Vec<Candidate>, epsilon: f64) {
    if candidates.len() < 2 {
        return;
    }
    // Group adjacent candidates with near-equal CE scores
    let mut i = 0;
    while i < candidates.len() {
        let mut j = i + 1;
        while j < candidates.len()
            && (candidates[i].ce_score - candidates[j].ce_score).abs() <= epsilon
        {
            j += 1;
        }
        if j - i > 1 {
            // Sort this tie group by fused score
            candidates[i..j].sort_by(|a, b| {
                b.fused_score
                    .partial_cmp(&a.fused_score)
                    .unwrap_or(std::cmp::Ordering::Equal)
            });
        }
        i = j;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_normalize_scores() {
        let mut scores = HashMap::from([
            ("a".to_string(), 10.0),
            ("b".to_string(), 5.0),
            ("c".to_string(), 0.0),
        ]);
        normalize_scores(&mut scores);
        assert!((scores["a"] - 1.0).abs() < 1e-6);
        assert!((scores["b"] - 0.5).abs() < 1e-6);
        assert!((scores["c"] - 0.0).abs() < 1e-6);
    }

    #[test]
    fn test_l2_normalize() {
        let v = vec![3.0, 4.0];
        let n = l2_normalize(&v);
        assert!((n[0] - 0.6).abs() < 1e-6);
        assert!((n[1] - 0.8).abs() < 1e-6);
    }

    #[test]
    fn test_logit() {
        let l = logit(0.5);
        assert!(l.abs() < 1e-6);
        let l = logit(0.9);
        assert!((l - 2.197224).abs() < 1e-3);
    }

    #[test]
    fn test_tie_break() {
        let mut candidates = vec![
            Candidate {
                ce_score: 0.9, fused_score: 5.0, ..Default::default()
            },
            Candidate {
                ce_score: 0.9, fused_score: 10.0, ..Default::default()
            },
        ];
        tie_break_by_fused(&mut candidates, 1e-6);
        assert_eq!(candidates[0].fused_score, 10.0);
        assert_eq!(candidates[1].fused_score, 5.0);
    }
}