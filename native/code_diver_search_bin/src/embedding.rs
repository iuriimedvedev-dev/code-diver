
use crate::fusion::l2_normalize;

/// Embedding model sent in every request body. Shared with the pipeline
/// embedding cache so cache invalidation keys on the exact model string.
pub const EMBED_MODEL: &str = "mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ";

/// Get the embedding for a query from the embedding provider.
pub async fn embed_query(client: &reqwest::Client, url: &str, query: &str) -> Result<Vec<f64>, String> {
    let body = serde_json::json!({
        "model": EMBED_MODEL,
        "input": query,
    });

    let resp = client
        .post(url)
        .json(&body)
        .send()
        .await
        .map_err(|e| format!("Embedding request failed: {}", e))?;

    let status = resp.status();
    if !status.is_success() {
        let text = resp.text().await.unwrap_or_default();
        return Err(format!("Embedding HTTP {}: {}", status, text));
    }

    let data: serde_json::Value = resp
        .json()
        .await
        .map_err(|e| format!("Embedding parse failed: {}", e))?;

    let embedding: Vec<f64> = data["data"][0]["embedding"]
        .as_array()
        .ok_or_else(|| "No embedding in response".to_string())?
        .iter()
        .map(|v| v.as_f64().unwrap_or(0.0))
        .collect();

    Ok(l2_normalize(&embedding))
}

/// Search Qdrant for nearest neighbors.
pub async fn vector_search(
    client: &reqwest::Client,
    qdrant_url: &str,
    collection: &str,
    query_vector: &[f64],
    limit: usize,
) -> Result<Vec<(String, String, f64)>, String> {
    let search_url = format!("{}/collections/{}/points/search", qdrant_url, collection);

    let body = serde_json::json!({
        "vector": query_vector,
        "limit": limit,
        "with_payload": true,
    });

    let resp = client
        .post(&search_url)
        .json(&body)
        .send()
        .await
        .map_err(|e| format!("Qdrant search failed: {}", e))?;

    let status = resp.status();
    if !status.is_success() {
        let text = resp.text().await.unwrap_or_default();
        return Err(format!("Qdrant HTTP {}: {}", status, text));
    }

    let data: serde_json::Value = resp
        .json()
        .await
        .map_err(|e| format!("Qdrant parse failed: {}", e))?;

    let results = data["result"]
        .as_array()
        .ok_or_else(|| "No results in Qdrant response".to_string())?;

    let mut scores = Vec::new();
    for point in results {
        let id = point["id"].as_str().unwrap_or("").to_string();
        let score = point["score"].as_f64().unwrap_or(0.0);
        // Try nested payload.item.path first, then payload.path, then fallback to id
        let path = point["payload"]["item"]["path"]
            .as_str()
            .or_else(|| point["payload"]["path"].as_str())
            .map(|s| s.to_string())
            .unwrap_or_else(|| id.clone());
        scores.push((id, path, score));
    }

    Ok(scores)
}

/// Per-request options for [`ce_rerank_with_options`].
#[derive(Debug, Clone)]
pub struct CeOptions {
    /// "auto" (default), "v1", or "legacy".
    pub route_mode: String,
    /// Per-request timeout in milliseconds (Python `timeout_ms` parity).
    pub timeout_ms: u64,
    /// Optional `model` body field; empty means omit it (llama.cpp scores with
    /// the loaded model, vLLM-metal pooling with the served one).
    pub model: String,
}

impl Default for CeOptions {
    fn default() -> Self {
        Self {
            route_mode: "auto".to_string(),
            timeout_ms: 60_000,
            model: String::new(),
        }
    }
}

/// Swap a CE rerank URL between the `/v1/rerank` and `/rerank` forms.
/// Returns `None` when the URL matches neither suffix (no fallback possible).
pub fn alternate_ce_url(url: &str) -> Option<String> {
    let base = url.trim_end_matches('/');
    if let Some(prefix) = base.strip_suffix("/v1/rerank") {
        Some(format!("{prefix}/rerank"))
    } else if let Some(prefix) = base.strip_suffix("/rerank") {
        Some(format!("{prefix}/v1/rerank"))
    } else {
        None
    }
}

/// Normalize a CE URL to the requested route form.
pub fn normalize_ce_url(url: &str, route_mode: &str) -> Result<String, String> {
    let base = url.trim_end_matches('/').to_string();
    match route_mode.trim().to_ascii_lowercase().as_str() {
        "auto" | "as-is" | "exact" => Ok(base),
        "v1" => {
            if base.ends_with("/v1/rerank") {
                Ok(base)
            } else if let Some(prefix) = base.strip_suffix("/rerank") {
                Ok(format!("{prefix}/v1/rerank"))
            } else {
                Ok(format!("{base}/v1/rerank"))
            }
        }
        "legacy" => {
            if let Some(prefix) = base.strip_suffix("/v1/rerank") {
                Ok(format!("{prefix}/rerank"))
            } else if base.ends_with("/rerank") {
                Ok(base)
            } else {
                Ok(format!("{base}/rerank"))
            }
        }
        other => Err(format!(
            "Unknown CE route mode: '{other}' (expected 'auto', 'v1', or 'legacy')"
        )),
    }
}

/// Resolve the ordered list of URLs to try for one rerank call.
fn resolve_ce_urls(url: &str, route_mode: &str) -> Result<Vec<String>, String> {
    let normalized = normalize_ce_url(url, route_mode)?;
    if route_mode.trim().to_ascii_lowercase().as_str() == "auto" {
        if let Some(alt) = alternate_ce_url(&normalized) {
            return Ok(vec![normalized, alt]);
        }
    }
    Ok(vec![normalized])
}

async fn post_ce(
    client: &reqwest::Client,
    url: &str,
    body: &serde_json::Value,
    timeout_ms: u64,
) -> Result<reqwest::Response, String> {
    client
        .post(url)
        .timeout(std::time::Duration::from_millis(timeout_ms.max(1)))
        .json(body)
        .send()
        .await
        .map_err(|e| {
            if e.is_timeout() {
                format!("CE rerank timed out after {timeout_ms}ms: {e}")
            } else {
                format!("CE rerank request failed: {e}")
            }
        })
}

/// Parse a CE rerank response tolerantly (Python `LlamaCppRerankProvider` parity):
/// accepts a `results` or `data` list with `relevance_score` or `score` values.
/// When every entry carries a valid in-range `index` and the count matches the
/// request, scores are mapped by index (vLLM order safety); otherwise the
/// response order is used positionally, requiring an exact count match.
fn parse_ce_scores(data: &serde_json::Value, num_documents: usize) -> Result<Vec<f64>, String> {
    let results = data
        .get("results")
        .or_else(|| data.get("data"))
        .and_then(|v| v.as_array())
        .ok_or_else(|| "No results in CE response".to_string())?;
    if results.len() != num_documents {
        return Err(format!(
            "CE returned {} scores for {} documents",
            results.len(),
            num_documents
        ));
    }
    let mut indexed: Vec<Option<f64>> = vec![None; num_documents];
    let mut all_indexed = true;
    for entry in results {
        let score = entry
            .get("relevance_score")
            .or_else(|| entry.get("score"))
            .and_then(|v| v.as_f64());
        let (Some(score), Some(index)) = (
            score,
            entry.get("index").and_then(|v| v.as_u64()).map(|i| i as usize),
        ) else {
            all_indexed = false;
            break;
        };
        if index >= num_documents {
            all_indexed = false;
            break;
        }
        indexed[index] = Some(score);
    }
    if all_indexed {
        return indexed
            .into_iter()
            .map(|v| v.ok_or_else(|| "CE response has duplicate indices".to_string()))
            .collect();
    }
    // Fallback: positional order (llama.cpp returns request order).
    results
        .iter()
        .map(|entry| {
            entry
                .get("relevance_score")
                .or_else(|| entry.get("score"))
                .and_then(|v| v.as_f64())
                .ok_or_else(|| "CE result missing relevance_score/score".to_string())
        })
        .collect()
}

/// Rerank documents using the CE (llama.cpp or vLLM-metal pooling) server.
///
/// Route handling:
/// - `route_mode "auto"` (default): POST to `url` as-is; if the server answers
///   404/405 (e.g. vLLM-metal exposes `/rerank` but not `/v1/rerank`), retry once
///   against the alternate route. Any other status or transport error is returned
///   directly -- Python parity is a single attempt, degradation is the caller's job.
/// - `route_mode "v1"` / `"legacy"`: normalize `url` to the `.../v1/rerank` or
///   `.../rerank` form and use it with no fallback.
///
/// Timeout handling mirrors Python's `CrossEncoderRerankConfig.timeout_ms`: one
/// per-request timeout, no retry loop inside the provider.
pub async fn ce_rerank_with_options(
    client: &reqwest::Client,
    url: &str,
    options: &CeOptions,
    query: &str,
    documents: &[String],
) -> Result<Vec<f64>, String> {
    let urls = resolve_ce_urls(url, &options.route_mode)?;
    let mut body = serde_json::json!({
        "query": query,
        "documents": documents,
        "top_n": documents.len(),
    });
    if !options.model.is_empty() {
        body["model"] = serde_json::Value::String(options.model.clone());
    }

    let mut last_status_error: Option<String> = None;
    for (attempt, candidate_url) in urls.iter().enumerate() {
        let resp = post_ce(client, candidate_url, &body, options.timeout_ms).await?;
        let status = resp.status();
        if status == reqwest::StatusCode::NOT_FOUND
            || status == reqwest::StatusCode::METHOD_NOT_ALLOWED
        {
            last_status_error = Some(format!(
                "CE HTTP {status} at {candidate_url} (route fallback {})",
                if attempt + 1 < urls.len() {
                    "will try alternate route"
                } else {
                    "exhausted"
                }
            ));
            // Only 404/405 walks the alternate route; anything else is final.
            continue;
        }
        if !status.is_success() {
            let text = resp.text().await.unwrap_or_default();
            let snippet: String = text.chars().take(300).collect();
            return Err(format!("CE HTTP {status} at {candidate_url}: {snippet}"));
        }
        let data: serde_json::Value = resp
            .json()
            .await
            .map_err(|e| format!("CE parse failed at {candidate_url}: {e}"))?;
        return parse_ce_scores(&data, documents.len())
            .map_err(|e| format!("{e} (from {candidate_url})"));
    }
    Err(last_status_error.unwrap_or_else(|| "CE: no route attempted".to_string()))
}

#[cfg(test)]
mod ce_tests {
    use super::*;

    #[test]
    fn alternate_swaps_v1_and_legacy_forms() {
        assert_eq!(
            alternate_ce_url("http://localhost:18081/v1/rerank"),
            Some("http://localhost:18081/rerank".to_string())
        );
        assert_eq!(
            alternate_ce_url("http://127.0.0.1:18083/rerank"),
            Some("http://127.0.0.1:18083/v1/rerank".to_string())
        );
        assert_eq!(alternate_ce_url("http://x:1/other"), None);
        // Trailing slash tolerance.
        assert_eq!(
            alternate_ce_url("http://x:1/v1/rerank/"),
            Some("http://x:1/rerank".to_string())
        );
    }

    #[test]
    fn route_resolution_orders_primary_before_fallback() {
        assert_eq!(
            resolve_ce_urls("http://h:1/v1/rerank", "auto").unwrap(),
            vec![
                "http://h:1/v1/rerank".to_string(),
                "http://h:1/rerank".to_string()
            ]
        );
        assert_eq!(
            resolve_ce_urls("http://h:1/rerank", "auto").unwrap(),
            vec![
                "http://h:1/rerank".to_string(),
                "http://h:1/v1/rerank".to_string()
            ]
        );
        assert_eq!(
            resolve_ce_urls("http://h:1/rerank", "v1").unwrap(),
            vec!["http://h:1/v1/rerank".to_string()]
        );
        assert_eq!(
            resolve_ce_urls("http://h:1/v1/rerank", "legacy").unwrap(),
            vec!["http://h:1/rerank".to_string()]
        );
        assert!(resolve_ce_urls("http://h:1/v1/rerank", "bogus").is_err());
    }

    #[test]
    fn parse_maps_by_index_when_present() {
        let data = serde_json::json!({"results": [
            {"index": 1, "relevance_score": 0.9},
            {"index": 0, "relevance_score": 0.1},
        ]});
        assert_eq!(parse_ce_scores(&data, 2).unwrap(), vec![0.1, 0.9]);
    }

    #[test]
    fn parse_accepts_data_envelope_and_score_key() {
        let data = serde_json::json!({"data": [
            {"index": 0, "score": 0.3},
            {"index": 1, "score": 0.7},
        ]});
        assert_eq!(parse_ce_scores(&data, 2).unwrap(), vec![0.3, 0.7]);
    }

    #[test]
    fn parse_positional_without_indices() {
        let data = serde_json::json!({"results": [
            {"relevance_score": 0.2},
            {"relevance_score": 0.8},
        ]});
        assert_eq!(parse_ce_scores(&data, 2).unwrap(), vec![0.2, 0.8]);
    }

    #[test]
    fn parse_rejects_count_mismatch_and_duplicates() {        let short = serde_json::json!({"results": [{"index": 0, "relevance_score": 1.0}]});
        assert!(parse_ce_scores(&short, 2).is_err());
        let dup = serde_json::json!({"results": [
            {"index": 0, "relevance_score": 0.5},
            {"index": 0, "relevance_score": 0.6},
        ]});
        assert!(parse_ce_scores(&dup, 2).is_err());
        let empty = serde_json::json!({"results": []});
        assert!(parse_ce_scores(&empty, 2).is_err());
        assert_eq!(parse_ce_scores(&empty, 0).unwrap(), Vec::<f64>::new());
    }

    /// End-to-end route fallback against a loopback stub (own ephemeral port):
    /// `/v1/rerank` answers 404, `/rerank` answers 200. Only std + reqwest.
    #[tokio::test]
    async fn fallback_uses_legacy_route_after_404() {
        use std::io::{Read, Write};
        use std::net::TcpListener;
        use std::sync::{Arc, Mutex};

        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let seen: Arc<Mutex<Vec<String>>> = Arc::new(Mutex::new(Vec::new()));
        let seen_srv = seen.clone();
        let handle = std::thread::spawn(move || {
            for _ in 0..2 {
                let (mut stream, _) = listener.accept().unwrap();
                let mut buf = vec![0u8; 8192];
                let n = stream.read(&mut buf).unwrap();
                let req = String::from_utf8_lossy(&buf[..n]).to_string();
                seen_srv
                    .lock()
                    .unwrap()
                    .push(req.lines().next().unwrap_or("").to_string());
                if req.contains("POST /v1/rerank ") {
                    let resp = "HTTP/1.1 404 Not Found\r\ncontent-length: 9\r\nconnection: close\r\n\r\nnot found";
                    stream.write_all(resp.as_bytes()).unwrap();
                } else {
                    let body = r#"{"results":[{"index":0,"relevance_score":0.25},{"index":1,"relevance_score":0.75}]}"#;
                    let resp = format!(
                        "HTTP/1.1 200 OK\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{body}",
                        body.len()
                    );
                    stream.write_all(resp.as_bytes()).unwrap();
                }
            }
        });

        let client = reqwest::Client::new();
        let url = format!("http://127.0.0.1:{port}/v1/rerank");
        let docs = vec!["a".to_string(), "b".to_string()];
        let scores = ce_rerank_with_options(&client, &url, &CeOptions::default(), "q", &docs)
            .await
            .unwrap();
        assert_eq!(scores, vec![0.25, 0.75]);
        handle.join().unwrap();
        let paths = seen.lock().unwrap();
        assert_eq!(paths.len(), 2);
        assert!(paths[0].contains("POST /v1/rerank "), "first: {}", paths[0]);
        assert!(paths[1].contains("POST /rerank "), "second: {}", paths[1]);
    }
}