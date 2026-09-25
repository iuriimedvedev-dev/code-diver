use std::path::Path;
use serde::Serialize;
use serde_json::Value;

#[derive(Debug, Serialize)]
pub struct NativeInfo {
    pub catalog_path: Option<String>,
    pub catalog_items: usize,
    pub catalog_size_bytes: u64,
    pub graph_path: Option<String>,
    pub graph_nodes: usize,
    pub graph_size_bytes: u64,
    pub model_path: Option<String>,
    pub model_size_bytes: u64,
    pub qdrant_status: String,
    pub qdrant_collection_points: Option<u64>,
}

pub async fn collect_info(
    catalog_path: Option<&str>,
    graph_path: Option<&str>,
    model_path: Option<&str>,
    qdrant_url: &str,
    qdrant_collection: &str,
) -> NativeInfo {
    let mut catalog_items = 0;
    let mut catalog_size_bytes = 0;
    if let Some(p) = catalog_path {
        let path = Path::new(p);
        if let Ok(meta) = path.metadata() {
            catalog_size_bytes = meta.len();
        }
        if let Ok(content) = std::fs::read_to_string(path) {
            catalog_items = content.lines().filter(|l| !l.trim().is_empty()).count();
        }
    }

    let mut graph_nodes = 0;
    let mut graph_size_bytes = 0;
    if let Some(p) = graph_path {
        let path = Path::new(p);
        if let Ok(meta) = path.metadata() {
            graph_size_bytes = meta.len();
        }
        if let Ok(content) = std::fs::read_to_string(path) {
            graph_nodes = content.lines().filter(|l| !l.trim().is_empty()).count();
        }
    }

    let mut model_size_bytes = 0;
    if let Some(p) = model_path {
        let path = Path::new(p);
        if let Ok(meta) = path.metadata() {
            model_size_bytes = meta.len();
        }
    }

    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(2))
        .build()
        .unwrap_or_default();

    let qdrant_check = client.get(qdrant_url).send().await;
    let qdrant_status = match qdrant_check {
        Ok(resp) if resp.status().is_success() => "connected".to_string(),
        Ok(resp) => format!("http_{}", resp.status().as_u16()),
        Err(e) => format!("error: {}", e),
    };

    let mut points_count = None;
    let col_url = format!("{}/collections/{}", qdrant_url.trim_end_matches('/'), qdrant_collection);
    if let Ok(resp) = client.get(&col_url).send().await {
        if resp.status().is_success() {
            if let Ok(json) = resp.json::<Value>().await {
                if let Some(pts) = json["result"]["points_count"].as_u64() {
                    points_count = Some(pts);
                } else if let Some(pts) = json["result"]["indexed_vectors_count"].as_u64() {
                    points_count = Some(pts);
                }
            }
        }
    }

    NativeInfo {
        catalog_path: catalog_path.map(|s| s.to_string()),
        catalog_items,
        catalog_size_bytes,
        graph_path: graph_path.map(|s| s.to_string()),
        graph_nodes,
        graph_size_bytes,
        model_path: model_path.map(|s| s.to_string()),
        model_size_bytes,
        qdrant_status,
        qdrant_collection_points: points_count,
    }
}

pub async fn run_info(
    catalog_path: Option<&str>,
    graph_path: Option<&str>,
    qdrant_url: &str,
) -> Result<(), String> {
    let model_path = [
        "artifacts/ce_meta_ranker/ce_meta_ranker.lgb.txt",
        ".code-diver/models/ce_meta_ranker.lgb.txt",
        "models/ce_meta_ranker.lgb.txt",
    ]
    .into_iter()
    .find(|p| Path::new(p).exists());

    let info = collect_info(
        catalog_path,
        graph_path,
        model_path,
        qdrant_url,
        "intellij_h66b_budget_qwen",
    )
    .await;

    let json = serde_json::to_string_pretty(&info).map_err(|e| e.to_string())?;
    println!("{}", json);
    Ok(())
}
