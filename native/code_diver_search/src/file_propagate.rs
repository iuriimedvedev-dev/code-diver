//! File-level decayed neighbor propagation.
//!
//! Two algorithms:
//! - [`propagate_file_scores`] matches `GraphFileRetrievalStrategy._propagate`
//! - [`expand_adjacency`] matches `FileGraphAdjacencyIndex.expand`

use std::collections::HashMap;

/// Parameters for graph-file `_propagate` (config-driven).
#[derive(Debug, Clone, Copy)]
pub struct FilePropagateParams {
    pub depth: usize,
    pub decay: f64,
    pub seed_limit: usize,
    pub neighbor_limit: usize,
    /// When `None`, uses `neighbor_limit` (Python `frontier_limit or neighbor_limit`).
    pub frontier_limit: Option<usize>,
}

/// Parameters for `FileGraphAdjacencyIndex.expand` / `GraphExpansionProfile`.
#[derive(Debug, Clone, Copy)]
pub struct AdjacencyExpandParams {
    pub depth: usize,
    pub decay: f64,
    pub neighbor_limit: usize,
    pub min_score: f64,
}

/// Adjacency: path -> list of (neighbor_path, edge_weight), already sorted by weight desc
/// as produced by Python `FileGraphAdjacencyIndex`.
pub type FileAdjacency = HashMap<String, Vec<(String, f64)>>;

fn sort_scores_desc(scores: &HashMap<String, f64>) -> Vec<(String, f64)> {
    let mut ranked: Vec<(String, f64)> = scores.iter().map(|(k, v)| (k.clone(), *v)).collect();
    ranked.sort_by(|a, b| {
        b.1.partial_cmp(&a.1)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| a.0.cmp(&b.0))
    });
    ranked
}

/// Graph-file strategy neighbor walk.
///
/// - Initial frontier: top `seed_limit` seeds by score.
/// - At depth `d` (0-based), `decay_factor = decay.powi(d + 1)`.
/// - Each path expands at most `neighbor_limit` adjacency edges (list prefix).
/// - Next frontier truncated to `frontier_limit` (or `neighbor_limit` if unset).
/// - Accumulates **neighbor** scores only (seeds are not auto-inserted).
pub fn propagate_file_scores(
    adjacency: &FileAdjacency,
    seed_file_scores: &HashMap<String, f64>,
    params: FilePropagateParams,
) -> HashMap<String, f64> {
    if seed_file_scores.is_empty() || params.depth == 0 {
        return HashMap::new();
    }

    let frontier_limit = params.frontier_limit.unwrap_or(params.neighbor_limit);
    let mut accumulated: HashMap<String, f64> = HashMap::new();

    let mut frontier: HashMap<String, f64> = sort_scores_desc(seed_file_scores)
        .into_iter()
        .take(params.seed_limit)
        .collect();

    for depth in 0..params.depth {
        let mut next_frontier: HashMap<String, f64> = HashMap::new();
        let decay = params.decay.powi((depth + 1) as i32);

        for (path, seed_score) in &frontier {
            let neighbors = match adjacency.get(path) {
                Some(n) => n,
                None => continue,
            };
            let limit = params.neighbor_limit.min(neighbors.len());
            for (neighbor_path, edge_weight) in neighbors.iter().take(limit) {
                let score = seed_score * edge_weight * decay;
                if score <= 0.0 {
                    continue;
                }
                accumulated
                    .entry(neighbor_path.clone())
                    .and_modify(|v| *v = v.max(score))
                    .or_insert(score);
                next_frontier
                    .entry(neighbor_path.clone())
                    .and_modify(|v| *v = v.max(score))
                    .or_insert(score);
            }
        }

        if next_frontier.is_empty() {
            break;
        }
        frontier = sort_scores_desc(&next_frontier)
            .into_iter()
            .take(frontier_limit)
            .collect();
    }

    accumulated
}

/// `FileGraphAdjacencyIndex.expand` walk with `best_seen` gating.
///
/// - At depth `d`, `decay_factor = decay.powi(d)` (including d=0 → 1.0).
/// - Full neighbor lists (no prefix slice); frontier capped by `neighbor_limit`.
/// - Only improves frontier when score beats `best_seen`.
pub fn expand_adjacency(
    adjacency: &FileAdjacency,
    seed_file_scores: &HashMap<String, f64>,
    params: AdjacencyExpandParams,
) -> HashMap<String, f64> {
    if seed_file_scores.is_empty() || params.depth == 0 {
        return HashMap::new();
    }

    let mut accumulated: HashMap<String, f64> = HashMap::new();
    let mut frontier = seed_file_scores.clone();
    let mut best_seen = seed_file_scores.clone();

    for depth in 0..params.depth {
        let mut next_frontier: HashMap<String, f64> = HashMap::new();
        let decay = params.decay.powi(depth as i32);

        for (path, seed_score) in &frontier {
            let neighbors = match adjacency.get(path) {
                Some(n) => n,
                None => continue,
            };
            for (neighbor_path, weight) in neighbors {
                let score = seed_score * weight * decay;
                if score <= params.min_score {
                    continue;
                }
                accumulated
                    .entry(neighbor_path.clone())
                    .and_modify(|v| *v = v.max(score))
                    .or_insert(score);

                let previous = best_seen.get(neighbor_path).copied().unwrap_or(0.0);
                if score > previous {
                    best_seen.insert(neighbor_path.clone(), score);
                    next_frontier
                        .entry(neighbor_path.clone())
                        .and_modify(|v| *v = v.max(score))
                        .or_insert(score);
                }
            }
        }

        if next_frontier.is_empty() {
            break;
        }
        frontier = sort_scores_desc(&next_frontier)
            .into_iter()
            .take(params.neighbor_limit)
            .collect();
    }

    accumulated
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_adj() -> FileAdjacency {
        let mut adj = FileAdjacency::new();
        adj.insert(
            "a.py".into(),
            vec![("b.py".into(), 1.0), ("c.py".into(), 0.5)],
        );
        adj.insert("b.py".into(), vec![("d.py".into(), 0.8)]);
        adj.insert("c.py".into(), vec![("d.py".into(), 0.4)]);
        adj
    }

    #[test]
    fn propagate_applies_decay_depth_plus_one() {
        let adj = sample_adj();
        let mut seeds = HashMap::new();
        seeds.insert("a.py".into(), 1.0);

        let out = propagate_file_scores(
            &adj,
            &seeds,
            FilePropagateParams {
                depth: 1,
                decay: 0.5,
                seed_limit: 10,
                neighbor_limit: 10,
                frontier_limit: None,
            },
        );
        // depth 0 → decay**1 = 0.5; b = 1.0*1.0*0.5, c = 1.0*0.5*0.5
        assert!((out["b.py"] - 0.5).abs() < 1e-12);
        assert!((out["c.py"] - 0.25).abs() < 1e-12);
        assert!(!out.contains_key("a.py"));
    }

    #[test]
    fn propagate_second_hop_uses_decay_squared() {
        let adj = sample_adj();
        let mut seeds = HashMap::new();
        seeds.insert("a.py".into(), 1.0);

        let out = propagate_file_scores(
            &adj,
            &seeds,
            FilePropagateParams {
                depth: 2,
                decay: 0.5,
                seed_limit: 10,
                neighbor_limit: 10,
                frontier_limit: None,
            },
        );
        // hop1: b=0.5; hop2 from b: d = 0.5 * 0.8 * (0.5**2) = 0.5*0.8*0.25 = 0.1
        assert!((out["d.py"] - 0.1).abs() < 1e-12);
    }

    #[test]
    fn propagate_respects_neighbor_limit_prefix() {
        let adj = sample_adj();
        let mut seeds = HashMap::new();
        seeds.insert("a.py".into(), 1.0);

        let out = propagate_file_scores(
            &adj,
            &seeds,
            FilePropagateParams {
                depth: 1,
                decay: 1.0,
                seed_limit: 10,
                neighbor_limit: 1, // only first edge b.py
                frontier_limit: None,
            },
        );
        assert!(out.contains_key("b.py"));
        assert!(!out.contains_key("c.py"));
    }

    #[test]
    fn propagate_empty_or_zero_depth() {
        let adj = sample_adj();
        let mut seeds = HashMap::new();
        seeds.insert("a.py".into(), 1.0);
        assert!(propagate_file_scores(
            &adj,
            &seeds,
            FilePropagateParams {
                depth: 0,
                decay: 0.5,
                seed_limit: 10,
                neighbor_limit: 10,
                frontier_limit: None,
            },
        )
        .is_empty());
        assert!(propagate_file_scores(
            &adj,
            &HashMap::new(),
            FilePropagateParams {
                depth: 2,
                decay: 0.5,
                seed_limit: 10,
                neighbor_limit: 10,
                frontier_limit: None,
            },
        )
        .is_empty());
    }

    #[test]
    fn expand_adjacency_decay_pow_depth_zero_is_one() {
        let adj = sample_adj();
        let mut seeds = HashMap::new();
        seeds.insert("a.py".into(), 1.0);

        let out = expand_adjacency(
            &adj,
            &seeds,
            AdjacencyExpandParams {
                depth: 1,
                decay: 0.5,
                neighbor_limit: 10,
                min_score: 0.0,
            },
        );
        // depth 0 → decay**0 = 1.0
        assert!((out["b.py"] - 1.0).abs() < 1e-12);
        assert!((out["c.py"] - 0.5).abs() < 1e-12);
    }

    #[test]
    fn expand_adjacency_respects_min_score() {
        let adj = sample_adj();
        let mut seeds = HashMap::new();
        seeds.insert("a.py".into(), 1.0);

        let out = expand_adjacency(
            &adj,
            &seeds,
            AdjacencyExpandParams {
                depth: 1,
                decay: 1.0,
                neighbor_limit: 10,
                min_score: 0.6,
            },
        );
        assert!(out.contains_key("b.py"));
        assert!(!out.contains_key("c.py")); // 0.5 <= 0.6
    }

    #[test]
    fn expand_keeps_max_on_collision() {
        let mut adj = FileAdjacency::new();
        adj.insert("a.py".into(), vec![("d.py".into(), 1.0)]);
        adj.insert("b.py".into(), vec![("d.py".into(), 0.3)]);
        let mut seeds = HashMap::new();
        seeds.insert("a.py".into(), 1.0);
        seeds.insert("b.py".into(), 1.0);

        let out = expand_adjacency(
            &adj,
            &seeds,
            AdjacencyExpandParams {
                depth: 1,
                decay: 1.0,
                neighbor_limit: 10,
                min_score: 0.0,
            },
        );
        assert!((out["d.py"] - 1.0).abs() < 1e-12);
    }
}
