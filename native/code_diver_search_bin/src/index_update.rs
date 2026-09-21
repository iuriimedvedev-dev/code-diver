//! Incremental Qdrant index updates: diff a fresh catalog against the live
//! collection, then embed + upsert only what changed.
//!
//! Point-id and payload construction mirror Python's
//! `QdrantVectorStore._upsert_points_to_collection` exactly:
//! point id = UUIDv5(NAMESPACE_URL, item.id), payload =
//! `{item: {id, path, title, content, ...}, root, provider, model, dimensions}`.
//! Embed text mirrors `CodeItem.to_embedding_text` with character-budget
//! truncation (Python additionally tries token-aware truncation when a
//! tokenizer is available; long texts may differ at the boundary).

use std::collections::{HashMap, HashSet};

use crate::types::CatalogItem;

/// One indexed point: (point id, embedded content).
pub type IndexedMap = HashMap<String, (String, String)>;

/// Diff result: catalog indices for added/changed, point ids for deleted.
pub struct IndexDiff {
    pub added: Vec<usize>,
    pub changed: Vec<usize>,
    pub deleted: Vec<String>,
}

/// Diff fresh catalog items against scrolled index state.
pub fn diff_catalog(items: &[CatalogItem], indexed: &IndexedMap) -> IndexDiff {
    let mut added = Vec::new();
    let mut changed = Vec::new();
    let mut seen = HashSet::new();
    for (idx, item) in items.iter().enumerate() {
        if item.id.is_empty() {
            continue;
        }
        seen.insert(item.id.as_str());
        match indexed.get(&item.id) {
            None => added.push(idx),
            Some((_, content)) if *content != item.content => changed.push(idx),
            _ => {}
        }
    }
    let mut deleted: Vec<String> = indexed
        .iter()
        .filter(|(id, _)| !seen.contains(id.as_str()))
        .map(|(_, (point_id, _))| point_id.clone())
        .collect();
    deleted.sort();
    IndexDiff {
        added,
        changed,
        deleted,
    }
}

/// UUIDv5(NAMESPACE_URL, item_id) as 32-hex (no dashes), matching Python's
/// `uuid.uuid5(uuid.NAMESPACE_URL, item_id).hex`.
pub fn point_id(item_id: &str) -> String {
    uuid::Uuid::new_v5(&uuid::Uuid::NAMESPACE_URL, item_id.as_bytes())
        .simple()
        .to_string()
}

/// Embed text mirroring `CodeItem.to_embedding_text` (no start_line in the
/// Rust catalog, so `path` without line suffix), char-truncated to budget.
pub fn embed_text(item: &CatalogItem, max_chars: usize) -> String {
    let text = format!(
        "title: {} | path: {} | text: {}",
        item.name, item.path, item.content
    );
    if max_chars == 0 || text.chars().count() <= max_chars {
        return text;
    }
    text.chars().take(max_chars).collect()
}

/// Scroll a whole collection: item.id -> (point id, embedded content).
pub async fn scroll_indexed(
    client: &reqwest::Client,
    qdrant_url: &str,
    collection: &str,
) -> Result<IndexedMap, String> {
    let url = format!(
        "{}/collections/{}/points/scroll",
        qdrant_url.trim_end_matches('/'),
        collection
    );
    let mut out = IndexedMap::new();
    let mut offset: Option<serde_json::Value> = None;
    loop {
        let mut body = serde_json::json!({
            "limit": 8192,
            "with_payload": true,
            "with_vector": false,
        });
        if let Some(off) = &offset {
            body["offset"] = off.clone();
        }
        let resp = client
            .post(&url)
            .json(&body)
            .send()
            .await
            .map_err(|e| format!("Qdrant scroll failed: {}", e))?;
        if !resp.status().is_success() {
            let text = resp.text().await.unwrap_or_default();
            return Err(format!("Qdrant scroll HTTP error: {}", text));
        }
        let data: serde_json::Value = resp
            .json()
            .await
            .map_err(|e| format!("Qdrant scroll parse failed: {}", e))?;
        let points = data["result"]["points"]
            .as_array()
            .ok_or_else(|| "Qdrant scroll: no result.points".to_string())?;
        for point in points {
            let item = &point["payload"]["item"];
            if let Some(item_id) = item["id"].as_str().filter(|s| !s.is_empty()) {
                let point_id = point["id"].to_string().trim_matches('"').to_string();
                let content = item["content"].as_str().unwrap_or("").to_string();
                out.insert(item_id.to_string(), (point_id, content));
            }
        }
        offset = match &data["result"]["next_page_offset"] {
            v if v.is_null() => break,
            v => Some(v.clone()),
        };
    }
    Ok(out)
}

/// Read vector dimensions of a collection (single unnamed vector).
pub async fn collection_dimensions(
    client: &reqwest::Client,
    qdrant_url: &str,
    collection: &str,
) -> Result<usize, String> {
    let url = format!(
        "{}/collections/{}",
        qdrant_url.trim_end_matches('/'),
        collection
    );
    let resp = client
        .get(&url)
        .send()
        .await
        .map_err(|e| format!("Qdrant collection lookup failed: {}", e))?;
    if !resp.status().is_success() {
        let text = resp.text().await.unwrap_or_default();
        return Err(format!("Qdrant collection HTTP error: {}", text));
    }
    let data: serde_json::Value = resp
        .json()
        .await
        .map_err(|e| format!("Qdrant collection parse failed: {}", e))?;
    data["result"]["config"]["params"]["vectors"]["size"]
        .as_u64()
        .map(|v| v as usize)
        .ok_or_else(|| "Qdrant: cannot read vectors.size (named vectors unsupported)".to_string())
}

/// Upsert items + vectors with indexing-path-identical payloads, in chunks.
#[allow(clippy::too_many_arguments)]
pub async fn upsert_points(
    client: &reqwest::Client,
    qdrant_url: &str,
    collection: &str,
    items: &[&CatalogItem],
    vectors: &[Vec<f64>],
    root: &str,
    provider: &str,
    model: &str,
    dimensions: usize,
) -> Result<usize, String> {
    if items.len() != vectors.len() {
        return Err(format!(
            "Item/vector mismatch: {} items, {} vectors",
            items.len(),
            vectors.len()
        ));
    }
    let url = format!(
        "{}/collections/{}/points",
        qdrant_url.trim_end_matches('/'),
        collection
    );
    let mut done = 0;
    for (chunk_items, chunk_vectors) in items.chunks(256).zip(vectors.chunks(256)) {
        let points: Vec<serde_json::Value> = chunk_items
            .iter()
            .zip(chunk_vectors.iter())
            .map(|(item, vector)| {
                serde_json::json!({
                    "id": point_id(&item.id),
                    "vector": vector,
                    "payload": {
                        "item": {
                            "id": item.id,
                            "path": item.path,
                            "title": item.name,
                            "content": item.content,
                            "start_line": null,
                            "end_line": null,
                            "metadata": {},
                        },
                        "root": root,
                        "provider": provider,
                        "model": model,
                        "dimensions": dimensions,
                    }
                })
            })
            .collect();
        let resp = client
            .put(&url)
            .json(&serde_json::json!({"points": points}))
            .send()
            .await
            .map_err(|e| format!("Qdrant upsert failed: {}", e))?;
        if !resp.status().is_success() {
            let text = resp.text().await.unwrap_or_default();
            return Err(format!("Qdrant upsert HTTP error: {}", text));
        }
        done += chunk_items.len();
    }
    Ok(done)
}

/// Delete points by point id.
pub async fn delete_points(
    client: &reqwest::Client,
    qdrant_url: &str,
    collection: &str,
    point_ids: &[String],
) -> Result<usize, String> {
    if point_ids.is_empty() {
        return Ok(0);
    }
    let url = format!(
        "{}/collections/{}/points/delete",
        qdrant_url.trim_end_matches('/'),
        collection
    );
    let mut done = 0;
    for chunk in point_ids.chunks(4096) {
        let resp = client
            .post(&url)
            .json(&serde_json::json!({"points": chunk}))
            .send()
            .await
            .map_err(|e| format!("Qdrant delete failed: {}", e))?;
        if !resp.status().is_success() {
            let text = resp.text().await.unwrap_or_default();
            return Err(format!("Qdrant delete HTTP error: {}", text));
        }
        done += chunk.len();
    }
    Ok(done)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn item(id: &str, content: &str) -> CatalogItem {
        CatalogItem {
            id: id.to_string(),
            path: format!("{}.kt", id),
            kind: "file_summary".to_string(),
            name: id.to_string(),
            content: content.to_string(),
            symbols: vec![],
            tokenized_name: vec![],
            tokenized_path: vec![],
            tokenized_dir: vec![],
            tokenized_content: vec![],
        }
    }

    #[test]
    fn point_id_matches_python_uuid5() {
        // python: uuid.uuid5(uuid.NAMESPACE_URL,
        //   'probe_incremental_xyz123.md::file_summary#60932d5b959f').hex
        assert_eq!(
            point_id("probe_incremental_xyz123.md::file_summary#60932d5b959f"),
            "54fbee890e3a5075ba60968ddf3f1aa8"
        );
    }

    #[test]
    fn diff_splits_added_changed_deleted() {
        let items = vec![
            item("same", "content"),
            item("changed", "new content"),
            item("added", "fresh"),
        ];
        let mut indexed = IndexedMap::new();
        indexed.insert("same".to_string(), ("p1".to_string(), "content".to_string()));
        indexed.insert(
            "changed".to_string(),
            ("p2".to_string(), "old content".to_string()),
        );
        indexed.insert(
            "gone".to_string(),
            ("p3".to_string(), "whatever".to_string()),
        );
        let diff = diff_catalog(&items, &indexed);
        assert_eq!(diff.added, vec![2]);
        assert_eq!(diff.changed, vec![1]);
        assert_eq!(diff.deleted, vec!["p3".to_string()]);
    }

    #[test]
    fn diff_skips_empty_ids() {
        let items = vec![item("", "x")];
        let diff = diff_catalog(&items, &IndexedMap::new());
        assert!(diff.added.is_empty());
    }

    #[test]
    fn embed_text_format_and_truncation() {
        let it = item("a", "hello world");
        assert_eq!(
            embed_text(&it, 0),
            "title: a | path: a.kt | text: hello world"
        );
        let long = item("a", "abcdefghij");
        let text = embed_text(&long, 10);
        assert_eq!(text.chars().count(), 10);
        assert!(text.starts_with("title: a "));
    }
}
