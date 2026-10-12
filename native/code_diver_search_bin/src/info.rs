use serde::Serialize;
use serde_json::Value;
use std::io::{BufRead, BufReader};
use std::path::Path;

#[derive(Debug, Serialize)]
pub struct NativeInfo {
    pub version: &'static str,
    pub qdrant_collection: String,
    pub catalog_present: bool,
    pub graph_present: bool,
    pub model_present: bool,
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
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(2))
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .expect("default HTTP client configuration is valid");
    collect_info_with_client(
        catalog_path,
        graph_path,
        model_path,
        qdrant_url,
        qdrant_collection,
        &client,
    )
    .await
}

pub async fn collect_info_with_client(
    catalog_path: Option<&str>,
    graph_path: Option<&str>,
    model_path: Option<&str>,
    qdrant_url: &str,
    qdrant_collection: &str,
    client: &reqwest::Client,
) -> NativeInfo {
    let mut catalog_items = 0;
    let mut catalog_size_bytes = 0;
    if let Some(p) = catalog_path {
        let path = Path::new(p);
        if let Ok(meta) = path.metadata() {
            catalog_size_bytes = meta.len();
        }
        if let Ok(file) = std::fs::File::open(path) {
            catalog_items = BufReader::new(file)
                .lines()
                .map_while(Result::ok)
                .filter(|l| !l.trim().is_empty())
                .count();
        }
    }

    let mut graph_nodes = 0;
    let mut graph_size_bytes = 0;
    if let Some(p) = graph_path {
        let path = Path::new(p);
        if let Ok(meta) = path.metadata() {
            graph_size_bytes = meta.len();
        }
        if let Ok(file) = std::fs::File::open(path) {
            graph_nodes = BufReader::new(file)
                .lines()
                .map_while(Result::ok)
                .filter(|l| !l.trim().is_empty())
                .count();
        }
    }

    let mut model_size_bytes = 0;
    if let Some(p) = model_path {
        let path = Path::new(p);
        if let Ok(meta) = path.metadata() {
            model_size_bytes = meta.len();
        }
    }

    let qdrant_check = client.get(qdrant_url).send().await;
    let qdrant_status = match qdrant_check {
        Ok(resp) if resp.status().is_success() => "connected".to_string(),
        Ok(resp) => format!("http_{}", resp.status().as_u16()),
        Err(_) => "unreachable; check Qdrant URL and credentials".to_string(),
    };

    let mut points_count = None;
    let col_url = reqwest::Url::parse(qdrant_url).ok().and_then(|mut url| {
        url.path_segments_mut()
            .ok()?
            .pop_if_empty()
            .push("collections")
            .push(qdrant_collection);
        Some(url)
    });
    if !qdrant_collection.is_empty()
        && let Some(col_url) = col_url
        && let Ok(resp) = client.get(col_url).send().await
        && resp.status().is_success()
        && let Ok(json) = resp.json::<Value>().await
    {
        if let Some(pts) = json["result"]["points_count"].as_u64() {
            points_count = Some(pts);
        } else if let Some(pts) = json["result"]["indexed_vectors_count"].as_u64() {
            points_count = Some(pts);
        }
    }

    NativeInfo {
        version: env!("CARGO_PKG_VERSION"),
        qdrant_collection: qdrant_collection.to_owned(),
        catalog_present: catalog_path.is_some_and(|p| Path::new(p).is_file()),
        graph_present: graph_path.is_some_and(|p| Path::new(p).is_file()),
        model_present: model_path.is_some_and(|p| Path::new(p).is_file()),
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
    model_path: Option<&str>,
    qdrant_url: &str,
    qdrant_collection: &str,
) -> Result<(), String> {
    let info = collect_info(
        catalog_path,
        graph_path,
        model_path,
        qdrant_url,
        qdrant_collection,
    )
    .await;

    let json = serde_json::to_string_pretty(&info).map_err(|e| e.to_string())?;
    println!("{}", json);
    Ok(())
}
