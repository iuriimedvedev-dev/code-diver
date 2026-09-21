use std::collections::{HashMap, HashSet, VecDeque};
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::Path;

use crate::types::GraphAdjacency;

/// Load graph adjacency from a JSONL file.
/// Format: each line is a JSON object with "path" and "neighbors" fields.
pub fn load_graph_adjacency(path: &Path) -> Result<GraphAdjacency, String> {
    let file = File::open(path).map_err(|e| format!("Cannot open graph: {}", e))?;
    let reader = BufReader::new(file);
    let mut edges: HashMap<String, Vec<(String, f64)>> = HashMap::new();

    for (line_num, line) in reader.lines().enumerate() {
        let line = line.map_err(|e| format!("Graph line {}: {}", line_num + 1, e))?;
        if line.trim().is_empty() {
            continue;
        }
        // Simple JSON parsing without full serde for performance
        if let Some(path) = extract_json_string(&line, "path") {
            if let Some(neighbors) = extract_json_array(&line, "neighbors") {
                let parsed: Vec<(String, f64)> = parse_neighbors(&neighbors);
                if !parsed.is_empty() {
                    edges.insert(path, parsed);
                }
            }
        }
    }

    Ok(GraphAdjacency { edges })
}

/// Propagate scores through the graph.
/// BFS from seed nodes, decaying scores by `decay` at each depth level.
pub fn propagate_scores(
    adjacency: &GraphAdjacency,
    seed_scores: &HashMap<String, f64>,
    depth: usize,
    decay: f64,
    seed_limit: usize,
    neighbor_limit: usize,
) -> HashMap<String, f64> {
    if depth == 0 || seed_scores.is_empty() {
        return seed_scores.clone();
    }

    // Take top seed_limit seeds
    let mut sorted_seeds: Vec<(&String, &f64)> = seed_scores.iter().collect();
    sorted_seeds.sort_by(|a, b| b.1.partial_cmp(a.1).unwrap_or(std::cmp::Ordering::Equal));
    let seeds: Vec<&String> = sorted_seeds
        .iter()
        .take(seed_limit)
        .map(|(k, _)| *k)
        .collect();

    let mut result: HashMap<String, f64> = HashMap::new();
    let mut visited: HashSet<String> = HashSet::new();
    let mut queue: VecDeque<(String, f64, usize)> = VecDeque::new();

    // Initialize queue with seeds
    for seed in &seeds {
        let score = *seed_scores.get(*seed).unwrap_or(&0.0);
        queue.push_back(((*seed).clone(), score, 0));
        visited.insert((*seed).clone());
    }

    while let Some((node, score, level)) = queue.pop_front() {
        // Store the max score for this node
        let entry = result.entry(node.clone()).or_insert(0.0);
        if score > *entry {
            *entry = score;
        }

        if level >= depth {
            continue;
        }

        // Explore neighbors
        if let Some(neighbors) = adjacency.edges.get(&node) {
            let num_neighbors = neighbors.len().min(neighbor_limit);
            for i in 0..num_neighbors {
                let (neighbor, _weight) = &neighbors[i];
                if visited.contains(neighbor) {
                    continue;
                }
                visited.insert(neighbor.clone());
                let propagated = score * decay;
                if propagated > 1e-10 {
                    queue.push_back((neighbor.clone(), propagated, level + 1));
                }
            }
        }
    }

    result
}

/// Extract a string value from a JSON key.
fn extract_json_string(json: &str, key: &str) -> Option<String> {
    let search = format!("\"{}\"", key);
    let start = json.find(&search)?;
    let colon = json[start..].find(':')?;
    let value_start = start + colon + 1;
    let trimmed = json[value_start..].trim();
    if trimmed.starts_with('"') {
        let end = trimmed[1..].find('"')?;
        let raw = trimmed[1..=end].to_string();
        // Unescape basic JSON escapes
        Some(raw.replace("\\\"", "\"").replace("\\\\", "\\"))
    } else {
        None
    }
}

/// Extract a JSON array as a string slice.
fn extract_json_array<'a>(json: &'a str, key: &str) -> Option<String> {
    let search = format!("\"{}\"", key);
    let start = json.find(&search)?;
    let colon = json[start..].find(':')?;
    let value_start = start + colon + 1;
    let trimmed = json[value_start..].trim();
    if trimmed.starts_with('[') {
        // Find the matching closing bracket
        let mut depth = 0;
        for (i, c) in trimmed.char_indices() {
            match c {
                '[' => depth += 1,
                ']' => {
                    depth -= 1;
                    if depth == 0 {
                        return Some(trimmed[..=i].to_string());
                    }
                }
                _ => {}
            }
        }
    }
    None
}

/// Parse a neighbors JSON array into (path, weight) pairs.
/// Supports two formats:
///   - Array of objects: [{"path":"...","weight":0.8}, ...]
///   - Array of arrays:  [["path1", 0.8], ["path2", 0.6]]
fn parse_neighbors(json: &str) -> Vec<(String, f64)> {
    let mut result = Vec::new();
    let mut i = 0;
    let bytes = json.as_bytes();
    while i < json.len() {
        if bytes[i] == b'{' {
            // Object format: {"path":"...","weight":0.8}
            let mut depth = 0;
            let mut j = i;
            while j < json.len() {
                match bytes[j] {
                    b'{' => depth += 1,
                    b'}' => {
                        depth -= 1;
                        if depth == 0 {
                            let obj = &json[i..=j];
                            let path = extract_json_string(obj, "path");
                            let weight = extract_json_string(obj, "weight")
                                .and_then(|w| w.parse::<f64>().ok());
                            if let (Some(p), Some(w)) = (path, weight) {
                                result.push((p, w));
                            }
                            i = j + 1;
                            break;
                        }
                    }
                    _ => {}
                }
                j += 1;
            }
        } else if bytes[i] == b'[' {
            // Array format: ["path", 0.8]
            let mut j = i + 1;
            // Skip whitespace
            while j < json.len() && bytes[j] == b' ' { j += 1; }
            // Extract path string
            let path = if j < json.len() && bytes[j] == b'"' {
                let start = j + 1;
                let mut end = start;
                while end < json.len() && bytes[end] != b'"' {
                    end += 1;
                }
                let p = json[start..end].to_string();
                j = end + 1;
                Some(p)
            } else {
                None
            };
            // Skip comma and whitespace
            while j < json.len() && (bytes[j] == b',' || bytes[j] == b' ') { j += 1; }
            // Extract weight float
            let weight = if j < json.len() {
                let mut end = j;
                while end < json.len() && (bytes[end].is_ascii_digit() || bytes[end] == b'.' || bytes[end] == b'-' || bytes[end] == b'e' || bytes[end] == b'E' || bytes[end] == b'+') {
                    end += 1;
                }
                json[j..end].parse::<f64>().ok()
            } else {
                None
            };
            if let (Some(p), Some(w)) = (path, weight) {
                result.push((p, w));
            }
            // Find closing bracket
            while j < json.len() && bytes[j] != b']' { j += 1; }
            i = j + 1;
        }
        i += 1;
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_propagate_empty() {
        let adj = GraphAdjacency {
            edges: HashMap::new(),
        };
        let seeds = HashMap::new();
        let result = propagate_scores(&adj, &seeds, 2, 0.5, 10, 10);
        assert!(result.is_empty());
    }

    #[test]
    fn test_propagate_simple() {
        let mut edges = HashMap::new();
        edges.insert("a".to_string(), vec![("b".to_string(), 1.0)]);
        let adj = GraphAdjacency { edges };
        let mut seeds = HashMap::new();
        seeds.insert("a".to_string(), 1.0);
        let result = propagate_scores(&adj, &seeds, 1, 0.5, 10, 10);
        assert!(result.contains_key("a"));
        assert!(result.contains_key("b"));
        assert!((result["b"] - 0.5).abs() < 1e-6);
    }
}