use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::types::SearchConfig;

pub const SCHEMA_VERSION: u32 = 2;

#[derive(Debug, Serialize, Deserialize)]
pub struct Embedding {
    pub model: String,
    pub dimensions: usize,
    pub query_prefix: String,
    pub document_prefix: String,
    #[serde(flatten)]
    pub extra: std::collections::BTreeMap<String, serde_json::Value>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct Metadata {
    #[serde(alias = "schema")]
    pub schema_version: u32,
    /// UTC Unix timestamp in seconds.
    pub generated_at: u64,
    pub collection: String,
    pub embedding: Embedding,
    #[serde(flatten)]
    pub extra: std::collections::BTreeMap<String, serde_json::Value>,
}

impl Metadata {
    pub fn validate(&self, config: &SearchConfig) -> Result<(), String> {
        if self.schema_version != SCHEMA_VERSION {
            return Err("Unsupported index metadata schema; regenerate schema 2 metadata with the index producer".into());
        }
        for (name, equal) in [
            ("collection", self.collection == config.qdrant_collection),
            (
                "embedding model",
                self.embedding.model == config.embedding_model,
            ),
            (
                "dimensions",
                self.embedding.dimensions > 0
                    && config
                        .embedding_dimensions
                        .is_none_or(|d| d == self.embedding.dimensions),
            ),
        ] {
            if !equal {
                return Err(format!(
                    "Index metadata {name} mismatch; select the matching embedding settings or a compatible index (reindex into a new collection for migration)"
                ));
            }
        }
        Ok(())
    }

    pub fn prefix_warning(&self, config: &SearchConfig) -> Option<String> {
        (self.embedding.query_prefix != config.embedding_query_prefix
            || self.embedding.document_prefix != config.embedding_document_prefix)
            .then(|| "Index metadata prefix mismatch: explicit override may degrade retrieval; use metadata prefixes outside controlled benchmarks".into())
    }
}

pub fn sidecar(catalog: &Path) -> PathBuf {
    let mut name = catalog.as_os_str().to_os_string();
    name.push(".metadata.json");
    PathBuf::from(name)
}

pub fn discover(explicit: &Path, catalog: &Path) -> Option<PathBuf> {
    if !explicit.as_os_str().is_empty() {
        return Some(explicit.into());
    }
    let parent = catalog.parent().unwrap_or_else(|| Path::new("."));
    [
        sidecar(catalog),
        parent.join("index-metadata.json"),
        parent.join("index_metadata.json"),
        parent.join("rust_index_metadata.json"),
    ]
    .into_iter()
    .find(|path| path.is_file())
}

pub fn load(path: &Path) -> Result<Metadata, String> {
    let bytes = std::fs::read(path).map_err(
        |_| "Cannot read index metadata; pass --index-metadata PATH or fetch matching artifacts",
    )?;
    decode(&bytes)
}

fn decode(bytes: &[u8]) -> Result<Metadata, String> {
    let parse = || -> Result<Metadata, String> {
        let mut value: serde_json::Value =
            serde_json::from_slice(bytes).map_err(|_| "Invalid JSON")?;
        if value.get("collection").is_none() {
            value["collection"] = value["qdrant"]["collection"].clone();
        } else if let Some(collection) = value["qdrant"]["collection"].as_str()
            && value["collection"].as_str() != Some(collection)
        {
            return Err("Conflicting collection fields".into());
        }
        if let Some(timestamp) = value["generated_at"].as_str() {
            let parsed = time::OffsetDateTime::parse(
                timestamp,
                &time::format_description::well_known::Rfc3339,
            )
            .map_err(|_| "Invalid generated_at timestamp")?
            .unix_timestamp();
            value["generated_at"] = serde_json::json!(
                u64::try_from(parsed).map_err(|_| "Timestamp before Unix epoch")?
            );
        }
        let metadata: Metadata =
            serde_json::from_value(value).map_err(|_| "Invalid metadata fields")?;
        for key in ["max_input_chars", "max_input_tokens", "token_safety_margin"] {
            if let Some(value) = metadata.embedding.extra.get(key)
                && value.as_u64().is_none()
            {
                return Err(format!("Invalid embedding {key}"));
            }
        }
        for section in [&metadata.embedding.extra, &metadata.extra] {
            if let Some(hash) = section.get("sha256") {
                validate_hash(hash)?;
            }
        }
        for section in ["meta_ranker", "reranker"] {
            if let Some(hash) = metadata.extra.get(section).and_then(|v| v.get("sha256")) {
                validate_hash(hash)?;
            }
        }
        if let Some(files) = metadata.extra.get("files") {
            for file in files.as_object().ok_or("Invalid files manifest")?.values() {
                if let Some(hash) = file.get("sha256") {
                    validate_hash(hash)?;
                }
            }
        }
        Ok(metadata)
    };
    parse().map_err(|error| {
        format!("Invalid schema 2 index metadata: {error}; regenerate or fetch matching artifacts")
    })
}

fn validate_hash(value: &serde_json::Value) -> Result<(), String> {
    if value
        .as_str()
        .is_some_and(|hash| hash.len() == 64 && hash.bytes().all(|b| b.is_ascii_hexdigit()))
    {
        Ok(())
    } else {
        Err("Invalid sha256 manifest hash".into())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn shared_manifest_timestamps_limits_and_hash_validation() {
        let fixture = include_bytes!("../tests/fixtures/shared-index-metadata.json");
        let metadata = decode(fixture).unwrap();
        assert_eq!(metadata.embedding.extra["max_input_chars"], 2000);
        assert_eq!(metadata.embedding.extra["max_input_tokens"], 512);
        assert_eq!(
            metadata.extra["files"]["rust_catalog.jsonl"]["bytes"],
            49619641
        );
        let mut value: serde_json::Value = serde_json::from_slice(fixture).unwrap();
        value["generated_at"] = serde_json::json!("2026-10-07T15:58:36+02:00");
        assert_eq!(
            decode(&serde_json::to_vec(&value).unwrap())
                .unwrap()
                .generated_at,
            metadata.generated_at
        );
        value["generated_at"] = serde_json::json!(metadata.generated_at);
        assert_eq!(
            decode(&serde_json::to_vec(&value).unwrap())
                .unwrap()
                .generated_at,
            metadata.generated_at
        );
        for timestamp in ["not-a-date", "2026-02-30T00:00:00Z", "1969-12-31T23:59:59Z"] {
            value["generated_at"] = serde_json::json!(timestamp);
            assert!(decode(&serde_json::to_vec(&value).unwrap()).is_err());
        }
        value["generated_at"] = serde_json::json!(metadata.generated_at);
        value["embedding"]["sha256"] = serde_json::json!("invalid");
        assert!(
            decode(&serde_json::to_vec(&value).unwrap())
                .unwrap_err()
                .contains("sha256")
        );
        value["embedding"]["sha256"] = metadata.embedding.extra["sha256"].clone();
        value["embedding"]["max_input_chars"] = serde_json::json!(-1);
        assert!(
            decode(&serde_json::to_vec(&value).unwrap())
                .unwrap_err()
                .contains("max_input_chars")
        );
    }

    #[test]
    fn discovery_and_incompatibilities_are_explicit() {
        let dir = tempfile::tempdir().unwrap();
        let catalog = dir.path().join("catalog.jsonl");
        assert!(discover(Path::new(""), &catalog).is_none());
        let metadata = Metadata {
            schema_version: 2,
            generated_at: 0,
            collection: "test".into(),
            extra: Default::default(),
            embedding: Embedding {
                model: "model".into(),
                dimensions: 2,
                query_prefix: "query: ".into(),
                document_prefix: "doc: ".into(),
                extra: Default::default(),
            },
        };
        std::fs::write(sidecar(&catalog), serde_json::to_vec(&metadata).unwrap()).unwrap();
        let path = discover(Path::new(""), &catalog).unwrap();
        let mut config = SearchConfig {
            qdrant_collection: "test".into(),
            embedding_model: "model".into(),
            embedding_query_prefix: "query: ".into(),
            embedding_document_prefix: "doc: ".into(),
            ..Default::default()
        };
        assert!(load(&path).unwrap().validate(&config).is_ok());
        config.embedding_query_prefix.clear();
        assert!(
            metadata
                .prefix_warning(&config)
                .unwrap()
                .contains("prefix mismatch")
        );
        assert_eq!(
            discover(Path::new("missing.json"), &catalog),
            Some(PathBuf::from("missing.json"))
        );
        config.embedding_query_prefix = "query: ".into();
        config.embedding_dimensions = Some(3);
        assert!(
            metadata
                .validate(&config)
                .unwrap_err()
                .contains("dimensions mismatch")
        );
        config.embedding_dimensions = Some(2);
        config.embedding_document_prefix.clear();
        assert!(
            metadata
                .prefix_warning(&config)
                .unwrap()
                .contains("prefix mismatch")
        );
        config.embedding_document_prefix = "doc: ".into();
        config.qdrant_collection = "other".into();
        assert!(
            metadata
                .validate(&config)
                .unwrap_err()
                .contains("collection mismatch")
        );
        let mut unsupported = metadata;
        unsupported.schema_version = 1;
        assert!(
            unsupported
                .validate(&config)
                .unwrap_err()
                .contains("schema")
        );
    }
}
