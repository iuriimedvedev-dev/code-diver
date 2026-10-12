use serde_json::Value;
use std::process::Command;

#[test]
fn shared_metadata_defaults_and_explicit_prefix_opt_out() {
    let dir = tempfile::tempdir().unwrap();
    let metadata = dir.path().join("index-metadata.json");
    std::fs::write(
        &metadata,
        include_str!("fixtures/shared-index-metadata.json"),
    )
    .unwrap();
    let run = |extra: &[&str]| {
        Command::new(env!("CARGO_BIN_EXE_code-diver"))
            .current_dir(dir.path())
            .args(["config", "show", "--catalog", "rust_catalog.jsonl"])
            .args(extra)
            .output()
            .unwrap()
    };
    let output = run(&[]);
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let config: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(config["embedding_model"], "Qwen/Qwen3-Embedding-0.6B");
    assert_eq!(config["embedding_dimensions"], 1024);
    assert_eq!(config["qdrant_collection"], "code_diver_pier_gguf");
    assert_eq!(
        config["embedding_query_prefix"],
        "Represent this code search query for retrieving relevant files: "
    );
    assert_eq!(
        config["embedding_document_prefix"],
        "Represent this code file metadata for retrieval: "
    );
    let output = run(&["--embedding-query-prefix", "", "--no-require-rerank"]);
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let config: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(config["embedding_query_prefix"], "");
    assert_eq!(config["require_rerank"], false);
    assert!(String::from_utf8_lossy(&output.stderr).contains("prefix mismatch"));
    for args in [
        vec!["--embedding-model", "wrong"],
        vec!["--embedding-dimensions", "3"],
        vec!["--qdrant-collection", "wrong"],
    ] {
        assert_eq!(run(&args).status.code(), Some(1));
    }
}

#[test]
fn doctor_failures_exit_one_with_timed_redacted_json() {
    let dir = tempfile::tempdir().unwrap();
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let url = format!("http://{}", listener.local_addr().unwrap());
    drop(listener);
    let output = Command::new(env!("CARGO_BIN_EXE_code-diver"))
        .current_dir(dir.path())
        .args([
            "doctor",
            "--json",
            "--qdrant-url",
            &url,
            "--qdrant-collection",
            "synthetic",
            "--embedding-url",
            &format!("{url}/v1/embeddings"),
            "--ce-url",
            &format!("{url}/v1/rerank"),
            "--ce-timeout-ms",
            "10",
        ])
        .env("CODE_DIVER_QDRANT_API_KEY", "private-qdrant-key")
        .env("CODE_DIVER_EMBEDDING_API_KEY", "private-embedding-key")
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(1));
    let stdout = String::from_utf8(output.stdout).unwrap();
    let stderr = String::from_utf8(output.stderr).unwrap();
    for secret in ["private-qdrant-key", "private-embedding-key"] {
        assert!(!stdout.contains(secret));
        assert!(!stderr.contains(secret));
    }
    let report: Value = serde_json::from_str(&stdout).unwrap();
    assert_eq!(report["passed"], false);
    let checks = report["checks"].as_array().unwrap();
    for name in [
        "catalog",
        "graph",
        "meta_ranker",
        "qdrant",
        "collection",
        "embedding",
        "rerank_short",
        "rerank_long",
    ] {
        let check = checks.iter().find(|c| c["name"] == name).unwrap();
        assert_eq!(check["status"], "FAIL", "{check}");
        assert!(!check["fix"].as_str().unwrap().is_empty());
        assert!(check["elapsed_ms"].as_f64().unwrap() >= 0.0);
    }
}

#[test]
fn doctor_invalid_configuration_is_json_failure() {
    let output = Command::new(env!("CARGO_BIN_EXE_code-diver"))
        .args([
            "doctor",
            "--json",
            "--qdrant-url",
            "http://user:private-password@localhost:1",
        ])
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(1));
    assert!(!String::from_utf8_lossy(&output.stdout).contains("private-password"));
    let report: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(report["checks"][0]["name"], "configuration");
    assert_eq!(report["checks"][0]["status"], "FAIL");
}

#[test]
fn doctor_metadata_configuration_failures_have_structured_checks() {
    let dir = tempfile::tempdir().unwrap();
    let metadata = dir.path().join("index-metadata.json");
    std::fs::write(
        &metadata,
        include_str!("fixtures/shared-index-metadata.json"),
    )
    .unwrap();
    for extra in [
        vec!["--embedding-model", "wrong"],
        vec!["--embedding-dimensions", "3"],
        vec!["--qdrant-collection", "wrong"],
        vec!["--index-metadata", "missing.json"],
    ] {
        let output = Command::new(env!("CARGO_BIN_EXE_code-diver"))
            .current_dir(dir.path())
            .args(["doctor", "--json", "--catalog", "rust_catalog.jsonl"])
            .args(extra)
            .output()
            .unwrap();
        assert_eq!(output.status.code(), Some(1));
        let report: Value = serde_json::from_slice(&output.stdout).unwrap();
        assert_eq!(report["passed"], false);
        let check = &report["checks"][0];
        assert_eq!(check["name"], "configuration");
        assert_eq!(check["status"], "FAIL");
        assert!(!check["message"].as_str().unwrap().is_empty());
        assert!(!check["fix"].as_str().unwrap().is_empty());
        assert!(check["elapsed_ms"].as_f64().unwrap() >= 0.0);
    }
}

#[test]
fn metadata_less_legacy_collection_keeps_empty_prefix_defaults() {
    let dir = tempfile::tempdir().unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_code-diver"))
        .current_dir(dir.path())
        .args(["config", "show", "--qdrant-collection", "legacy-dwq"])
        .output()
        .unwrap();
    assert!(output.status.success());
    let config: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(config["embedding_query_prefix"], "");
    assert_eq!(config["embedding_document_prefix"], "");
}

#[test]
fn effective_config_has_cli_env_file_precedence_and_redacted_secrets() {
    let dir = tempfile::tempdir().unwrap();
    let config = dir.path().join("services.toml");
    std::fs::write(&config, "[embedding]\nmodel='file-model'\nquery_prefix='file-query: '\ndocument_prefix='file-doc: '\napi_key='file-private-key'\n[search]\nrequire_rerank=true\n[cross_encoder_rerank]\ntimeout_ms=1234\nmodel='reranker'\n").unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_code-diver"))
        .args(["config", "show", "--config"])
        .arg(&config)
        .args(["--embedding-model", "cli-model"])
        .env("CODE_DIVER_EMBEDDING_MODEL", "env-model")
        .env("CODE_DIVER_EMBEDDING_QUERY_PREFIX", "env-query: ")
        .env("CODE_DIVER_QDRANT_API_KEY", "env-private-key")
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let effective: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(effective["embedding_model"], "cli-model");
    assert_eq!(effective["embedding_query_prefix"], "env-query: ");
    assert_eq!(effective["embedding_document_prefix"], "file-doc: ");
    assert_eq!(effective["require_rerank"], true);
    assert_eq!(effective["ce_timeout_ms"], 1234);
    assert_eq!(effective["ce_model"], "reranker");
    for key in ["embedding_api_key", "qdrant_api_key", "qdrant_bearer"] {
        assert_eq!(effective[key], "[redacted]");
    }
    assert!(!String::from_utf8_lossy(&output.stdout).contains("private-key"));
}

#[test]
fn profile_defaults_yield_to_canonical_file_and_explicit_flags() {
    let dir = tempfile::tempdir().unwrap();
    let config = dir.path().join("profile.toml");
    std::fs::write(&config, "[profile]\nqdrant_collection='profile-index'\nembedding_model='profile-model'\nembedding_query_prefix='profile-query: '\nembedding_document_prefix='profile-doc: '\n[embedding]\nquery_prefix='file-query: '\n").unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_code-diver"))
        .args(["config", "show", "--config"])
        .arg(&config)
        .args(["--embedding-model", "cli-model"])
        .output()
        .unwrap();
    assert!(output.status.success());
    let effective: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(effective["qdrant_collection"], "profile-index");
    assert_eq!(effective["embedding_model"], "cli-model");
    assert_eq!(effective["embedding_query_prefix"], "file-query: ");
    assert_eq!(effective["embedding_document_prefix"], "profile-doc: ");
}

#[test]
fn yaml_require_rerank_and_prefixes_are_not_ignored() {
    let dir = tempfile::tempdir().unwrap();
    let config = dir.path().join("services.yml");
    std::fs::write(&config, "embedding:\n  query_prefix: 'query: '\n  document_prefix: 'doc: '\nsearch:\n  require_rerank: true\ncross_encoder_rerank:\n  timeout_ms: 123\n").unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_code-diver"))
        .args(["config", "show", "--config"])
        .arg(&config)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let effective: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(effective["embedding_query_prefix"], "query: ");
    assert_eq!(effective["embedding_document_prefix"], "doc: ");
    assert_eq!(effective["require_rerank"], true);
    assert_eq!(effective["ce_timeout_ms"], 123);
}
