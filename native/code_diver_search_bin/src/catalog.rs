use std::collections::HashMap;
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::Path;

use crate::types::{Catalog, CatalogItem};

/// Load catalog from a JSONL file.
pub fn load_catalog(path: &Path) -> Result<Catalog, String> {
    let file = File::open(path).map_err(|e| format!("Cannot open catalog: {}", e))?;
    let reader = BufReader::new(file);
    let mut items = Vec::new();

    for (line_num, line) in reader.lines().enumerate() {
        let line = line.map_err(|e| format!("Line {}: {}", line_num + 1, e))?;
        if line.trim().is_empty() {
            continue;
        }
        let item: CatalogItem =
            serde_json::from_str(&line).map_err(|e| format!("Line {}: {}", line_num + 1, e))?;
        items.push(item);
    }

    let mut by_id = HashMap::new();
    let mut by_path = HashMap::new();
    let mut by_norm_path = HashMap::new();

    for (idx, item) in items.iter().enumerate() {
        if !item.id.is_empty() {
            by_id.insert(item.id.clone(), idx);
        }
        if !item.path.is_empty() {
            by_path.entry(item.path.clone()).or_insert_with(Vec::new).push(idx);
            let norm = normalize_path(&item.path);
            by_norm_path.entry(norm).or_insert_with(Vec::new).push(idx);
        }
    }

    Ok(Catalog {
        items,
        by_id,
        by_path,
        by_norm_path,
    })
}

/// Normalize a file path (same as Python _normalize_path).
pub fn normalize_path(path: &str) -> String {
    if path.is_empty() {
        return String::new();
    }
    // Normalize: collapse separators, remove leading ./ and /
    let p = Path::new(path);
    let mut components: Vec<_> = p
        .components()
        .filter(|c| matches!(c, std::path::Component::Normal(_)))
        .map(|c| c.as_os_str().to_string_lossy().to_string())
        .collect();
    components.retain(|s| !s.is_empty() && s != ".");
    let norm = components.join("/");
    if norm == "." || norm.is_empty() {
        return String::new();
    }
    norm
}

/// Tokenize a string by splitting on non-alphanumeric chars (including underscore).
pub fn tokenize(text: &str) -> Vec<String> {
    text.split(|c: char| !c.is_alphanumeric())
        .filter(|s| !s.is_empty())
        .map(|s| s.to_lowercase())
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_normalize_path() {
        assert_eq!(normalize_path(""), "");
        assert_eq!(normalize_path("."), "");
        assert_eq!(normalize_path("src/main.rs"), "src/main.rs");
        assert_eq!(normalize_path("./src/main.rs"), "src/main.rs");
    }

    #[test]
    fn test_tokenize() {
        let tokens = tokenize("helloWorld_test");
        assert!(tokens.contains(&"helloworld".to_string()));
        assert!(tokens.contains(&"test".to_string()));
    }
}