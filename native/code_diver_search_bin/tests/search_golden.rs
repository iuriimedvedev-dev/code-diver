#![allow(dead_code)]

#[path = "../src/bm25.rs"]
mod bm25;
#[path = "../src/catalog.rs"]
mod catalog;
#[path = "../src/embedding.rs"]
mod embedding;
#[path = "../src/features.rs"]
mod features;
#[path = "../src/fusion.rs"]
mod fusion;
#[path = "../src/graph.rs"]
mod graph;
#[path = "../src/index_net.rs"]
mod index_net;
#[path = "../src/lightgbm.rs"]
mod lightgbm;
#[path = "../src/pipeline.rs"]
mod pipeline;
#[path = "../src/types.rs"]
mod types;

use types::CatalogItem;

#[test]
fn loaded_tokens_share_storage_without_changing_scores_or_json() {
    let original = synthetic_catalog();
    let json = original
        .iter()
        .map(|item| serde_json::to_string(item).unwrap())
        .collect::<Vec<_>>()
        .join("\n");
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("catalog.jsonl");
    std::fs::write(&path, json).unwrap();
    let loaded = catalog::load_catalog(&path).unwrap();
    assert!(std::sync::Arc::ptr_eq(
        &loaded.items[0].tokenized_content[1].0,
        &loaded.items[1].tokenized_content[0].0,
    ));
    assert!(std::sync::Arc::ptr_eq(
        &loaded.items[0].tokenized_content[2].0,
        &loaded.items[1].tokenized_name[0].0,
    ));
    assert!(!std::sync::Arc::ptr_eq(
        &loaded.items[0].tokenized_content[0].0,
        &loaded.items[0].tokenized_content[1].0,
    ));
    assert_eq!(
        serde_json::to_value(&loaded.items).unwrap(),
        serde_json::to_value(&original).unwrap()
    );
    for query in [
        vec!["search".into(), "search".into()],
        vec!["cache".into()],
        vec!["unrelated".into()],
    ] {
        assert_eq!(
            bm25::bm25_scores(&bm25::build_bm25_index(&original), &query, 1.2, 0.75),
            bm25::bm25_scores(&bm25::build_bm25_index(&loaded.items), &query, 1.2, 0.75),
        );
        for (before, after) in original.iter().zip(&loaded.items) {
            assert_eq!(
                bm25::path_coverage_score(before, &query),
                bm25::path_coverage_score(after, &query)
            );
            assert_eq!(
                bm25::lexical_coverage_score(before, &query),
                bm25::lexical_coverage_score(after, &query)
            );
            assert_eq!(
                bm25::symbol_coverage_score(before, &query),
                bm25::symbol_coverage_score(after, &query)
            );
            assert_eq!(
                bm25::symbol_match_score(before, &query),
                bm25::symbol_match_score(after, &query)
            );
        }
    }
}

fn synthetic_catalog() -> Vec<CatalogItem> {
    vec![
        CatalogItem {
            id: "a".into(),
            tokenized_content: vec!["Search".into(), "search".into(), "cache".into()],
            ..Default::default()
        },
        CatalogItem {
            id: "b".into(),
            tokenized_name: vec!["cache".into()],
            tokenized_content: vec!["search".into()],
            ..Default::default()
        },
        CatalogItem {
            id: "c".into(),
            name: "unrelated".into(),
            ..Default::default()
        },
    ]
}

#[test]
fn bm25_synthetic_ranking_golden() {
    let index = bm25::build_bm25_index(&synthetic_catalog());
    let scores = bm25::bm25_scores(&index, &["search".into(), "search".into()], 1.2, 0.75);
    let idf = (1.0_f64 + 1.5 / 2.5).ln();
    assert_eq!(
        scores["a"],
        2.0 * idf * (2.0 * 2.2 / (2.0 + 1.2 * (0.25 + 0.375 * 3.0)))
    );
    assert_eq!(scores["b"], 2.0 * idf);
    assert!(scores["a"] > scores["b"]);
    assert!(!scores.contains_key("c"));
}

#[test]
fn compact_bm25_has_no_legacy_duplicate_storage() {
    let index = bm25::build_bm25_index(&synthetic_catalog());
    assert!(index.term_frequencies.is_empty());
    assert!(index.document_lengths.is_empty());
    assert!(index.postings.is_empty());
}

#[test]
fn old_search_result_deserializes_with_metadata_defaults() {
    let result: types::SearchResult =
        serde_json::from_str(r#"{"item_id":"a","path":"a.rs","score":0.5}"#).unwrap();
    let json = serde_json::to_value(result).unwrap();
    assert_eq!(json["title"], "");
    assert_eq!(json["start_line"], 1);
    assert_eq!(json["end_line"], 1);
    assert!(json.get("preview").is_none());
}

#[test]
fn configured_limits_above_34_are_supported_and_excess_is_explicit() {
    let config = types::SearchConfig {
        candidate_limit: 80,
        ..Default::default()
    };
    assert!(
        pipeline::validate_search_options(
            &config,
            &types::SearchOptions {
                limit: 80,
                ..Default::default()
            }
        )
        .is_ok()
    );
    let error = pipeline::validate_search_options(
        &config,
        &types::SearchOptions {
            limit: 81,
            ..Default::default()
        },
    )
    .unwrap_err();
    assert!(error.contains("1..=80"));
    assert!(
        pipeline::validate_search_options(
            &config,
            &types::SearchOptions {
                limit: 0,
                ..Default::default()
            }
        )
        .is_err()
    );
    assert_eq!(types::SearchOptions::default().preview_chars, 0);
}

#[test]
fn query_budget_includes_prefix_and_notices_unicode_truncation() {
    let config = types::SearchConfig {
        embedding_query_prefix: "prefix: ".into(),
        embedding_query_token_budget: 16,
        ..Default::default()
    };
    let (text, notice) = pipeline::prepare_embedding_query(&config, "検索検索検索").unwrap();
    assert_eq!(text, "prefix: 検索");
    assert!(text.len() <= 16);
    assert!(notice.unwrap().contains("truncated"));
    let short = pipeline::prepare_embedding_query(&config, "cache").unwrap();
    assert_eq!(short, ("prefix: cache".into(), None));
    assert!(pipeline::prepare_embedding_query(&config, " \n").is_err());
    let invalid = types::SearchConfig {
        embedding_query_token_budget: 8,
        ..config
    };
    assert!(pipeline::prepare_embedding_query(&invalid, "cache").is_err());
    let long = pipeline::prepare_embedding_query(&Default::default(), &"a".repeat(10_000)).unwrap();
    assert_eq!(long.0.len(), 480);
    assert!(long.1.is_some());
}

#[test]
fn metadata_uses_source_snippet_or_file_and_catalog_fallback() {
    let root = tempfile::tempdir().unwrap();
    std::fs::write(root.path().join("a.rs"), "header\n検索\nlast\n").unwrap();
    let config = types::SearchConfig {
        base_path: root.path().to_string_lossy().into(),
        ..Default::default()
    };
    let mut candidate = types::Candidate {
        path: "a.rs".into(),
        content: Some("検索\n".into()),
        ..Default::default()
    };
    assert_eq!(
        pipeline::result_content_metadata(&candidate, &config, 1),
        (2, 2, Some("検".into()))
    );
    candidate.content = Some("generated\nsummary\n".into());
    assert_eq!(
        pipeline::result_content_metadata(&candidate, &config, 0),
        (1, 3, None)
    );
    assert_eq!(
        pipeline::result_content_metadata(&candidate, &Default::default(), 0),
        (1, 2, None)
    );
    candidate.content = None;
    assert_eq!(
        pipeline::result_content_metadata(&candidate, &Default::default(), 0),
        (1, 1, None)
    );
}

#[tokio::test]
async fn context_defers_bm25_and_initializes_it_once() {
    let root = tempfile::tempdir().unwrap();
    let catalog = root.path().join("catalog.jsonl");
    let graph = root.path().join("graph.jsonl");
    let items = synthetic_catalog();
    std::fs::write(
        &catalog,
        items
            .iter()
            .map(|item| serde_json::to_string(item).unwrap())
            .collect::<Vec<_>>()
            .join("\n"),
    )
    .unwrap();
    std::fs::write(&graph, "").unwrap();
    let context = pipeline::init_search_context(types::SearchConfig {
        catalog_path: catalog.to_string_lossy().into(),
        graph_path: graph.to_string_lossy().into(),
        ..Default::default()
    })
    .await
    .unwrap();
    assert!(context.bm25_index.get().is_none());
    let first = context.bm25_index();
    assert_eq!(first.num_docs, 3);
    assert!(std::ptr::eq(first, context.bm25_index()));
    assert_eq!(
        bm25::bm25_scores(first, &["search".into()], 1.2, 0.75),
        bm25::bm25_scores(
            &bm25::build_bm25_index(&items),
            &["search".into()],
            1.2,
            0.75
        )
    );
}

#[tokio::test]
async fn adapter_returns_40_results_and_notices_without_preview_ranking_changes() {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}", listener.local_addr().unwrap());
    let server = tokio::spawn(async move {
        for _ in 0..6 {
            let (mut stream, _) =
                tokio::time::timeout(std::time::Duration::from_secs(5), listener.accept())
                    .await
                    .unwrap()
                    .unwrap();
            let mut bytes = Vec::new();
            let (headers, body) = loop {
                let mut buffer = [0; 4096];
                let read = stream.read(&mut buffer).await.unwrap();
                assert!(read > 0);
                bytes.extend_from_slice(&buffer[..read]);
                if let Some(end) = bytes.windows(4).position(|w| w == b"\r\n\r\n") {
                    let headers = String::from_utf8(bytes[..end].to_vec()).unwrap();
                    let size: usize = headers
                        .lines()
                        .find_map(|line| {
                            line.to_lowercase()
                                .strip_prefix("content-length:")
                                .map(|value| value.trim().parse().unwrap())
                        })
                        .unwrap();
                    if bytes.len() >= end + 4 + size {
                        break (
                            headers,
                            serde_json::from_slice::<serde_json::Value>(
                                &bytes[end + 4..end + 4 + size],
                            )
                            .unwrap(),
                        );
                    }
                }
            };
            let response = if headers.starts_with("POST /embed ") {
                assert_eq!(body["input"].as_str().unwrap().len(), 480);
                serde_json::json!({"data": [{"embedding": [1.0, 0.0]}]})
            } else if headers.contains("/points/search ") {
                serde_json::json!({"result": (0..40).map(|i| serde_json::json!({
                    "id": format!("id{i}"), "score": 1.0 - i as f64 / 100.0,
                    "payload": {"item_id": format!("id{i}"), "path": format!("file{i}.rs")}
                })).collect::<Vec<_>>()})
            } else {
                assert_eq!(body["query"].as_str().unwrap().len(), 1000);
                let count = body["documents"].as_array().unwrap().len();
                assert_eq!(count, 40);
                serde_json::json!({"results": (0..count).map(|i| serde_json::json!({
                    "index": i, "relevance_score": 0.2 + i as f64 / 100.0
                })).collect::<Vec<_>>()})
            }
            .to_string();
            stream.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}", response.len(), response).as_bytes()).await.unwrap();
        }
    });
    let root = tempfile::tempdir().unwrap();
    let catalog = root.path().join("catalog.jsonl");
    let graph = root.path().join("graph.jsonl");
    std::fs::write(
        &catalog,
        (0..40)
            .map(|i| {
                serde_json::to_string(&CatalogItem {
                    id: format!("id{i}"),
                    path: format!("file{i}.rs"),
                    name: format!("Title {i}"),
                    content: "first\nsecond\n".into(),
                    ..Default::default()
                })
                .unwrap()
            })
            .collect::<Vec<_>>()
            .join("\n"),
    )
    .unwrap();
    std::fs::write(&graph, "").unwrap();
    let context = pipeline::init_search_context(types::SearchConfig {
        catalog_path: catalog.to_string_lossy().into(),
        graph_path: graph.to_string_lossy().into(),
        embedding_url: format!("{url}/embed"),
        qdrant_url: url.clone(),
        ce_url: format!("{url}/v1/rerank"),
        candidate_limit: 40,
        second_pass_enabled: false,
        ..Default::default()
    })
    .await
    .unwrap();
    let query = "x".repeat(1000);
    let options = types::SearchOptions {
        limit: 40,
        preview_chars: 0,
    };
    let (plain, _) = pipeline::search_with_options(&context, &query, &options)
        .await
        .unwrap();
    let (preview, _) = pipeline::search_with_options(
        &context,
        &query,
        &types::SearchOptions {
            preview_chars: 5,
            ..options
        },
    )
    .await
    .unwrap();
    assert_eq!(plain.results.len(), 40);
    assert_eq!(plain.notices.len(), 2);
    assert!(plain.notices.iter().any(|n| n.contains("truncated")));
    assert!(plain.notices.iter().any(|n| n.contains("Meta-ranker")));
    assert!(
        plain
            .results
            .windows(2)
            .all(|pair| pair[0].score >= pair[1].score)
    );
    for (a, b) in plain.results.iter().zip(&preview.results) {
        assert_eq!(a.score, a.ce_score.unwrap());
        assert_eq!((&a.item_id, a.score), (&b.item_id, b.score));
        assert!(a.title.starts_with("Title "));
        assert_eq!((a.start_line, a.end_line), (1, 2));
        assert!(a.preview.is_none());
        assert_eq!(b.preview.as_deref(), Some("first"));
    }
    server.await.unwrap();
}
