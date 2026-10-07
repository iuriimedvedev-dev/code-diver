pub mod cli;
pub mod compare;
mod config;
pub mod ids;
pub mod manifest;
pub mod pytext;
pub mod scan;
pub mod summary;
pub mod symbols;
pub mod tokenize;

use std::path::Path;

use crate::types::CatalogItem;
use summary::SummaryConfig;

pub struct BuildConfig {
    pub include: Vec<String>,
    pub exclude: Vec<String>,
    pub max_file_bytes: u64,
    pub max_symbols_per_file: Option<usize>,
    pub tokenize_content_chars: usize,
    pub summary: SummaryConfig,
    pub manifest_symbol_surface: bool,
    pub file_summary: bool,
    pub file_manifest: bool,
}

impl Default for BuildConfig {
    fn default() -> Self {
        Self {
            include: vec![],
            exclude: vec![],
            max_file_bytes: 1_000_000,
            max_symbols_per_file: Some(96),
            tokenize_content_chars: 0,
            summary: SummaryConfig::default(),
            manifest_symbol_surface: false,
            file_summary: true,
            file_manifest: true,
        }
    }
}

fn record(path: &str, kind: &str, content: String, chars: usize) -> CatalogItem {
    let name = format!("{path}::{kind}");
    let dir = path.rsplit_once('/').map_or("", |(dir, _)| dir);
    CatalogItem {
        id: ids::item_id(path, kind),
        path: path.into(),
        kind: kind.into(),
        tokenized_name: tokenize::tokenize(&name),
        tokenized_path: tokenize::tokenize(path),
        tokenized_dir: tokenize::tokenize(dir),
        tokenized_content: tokenize::tokenize(if chars == 0 {
            &content
        } else {
            pytext::prefix(&content, chars)
        }),
        name,
        content,
        symbols: vec![],
    }
}

pub fn build_records(path: &str, text: &str, config: &BuildConfig) -> Vec<CatalogItem> {
    let symbols = symbols::limit_symbols(
        symbols::extract(path, text),
        text,
        config.max_symbols_per_file,
    );
    let mut items = Vec::new();
    if config.file_summary {
        items.push(record(
            path,
            "file_summary",
            summary::build_file_summary(path, text, &symbols, &config.summary),
            config.tokenize_content_chars,
        ));
    }
    if config.file_manifest {
        items.push(record(
            path,
            "file_manifest",
            manifest::build_file_manifest(path, text, &symbols, config.manifest_symbol_surface),
            config.tokenize_content_chars,
        ));
    }
    items
}

pub fn build_catalog(root: &Path, config: &BuildConfig) -> Result<Vec<CatalogItem>, String> {
    let root = root
        .canonicalize()
        .map_err(|e| format!("Cannot open root {}: {e}", root.display()))?;
    if !root.is_dir() {
        return Err(format!("Root {} is not a directory", root.display()));
    }
    let scanner = scan::Scanner::new(&config.include, &config.exclude, config.max_file_bytes);
    let mut items = Vec::new();
    for (path, relative) in scanner.candidate_files(&root) {
        if let Some(text) = scanner.read_text(&path)
            && !pytext::strip(&text).is_empty()
        {
            items.extend(build_records(&relative, &text, config));
        }
    }
    Ok(items)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn synthetic_reference_templates() {
        let cases: Vec<serde_json::Value> =
            serde_json::from_str(include_str!("../../tests/fixtures/generic.json")).unwrap();
        for case in cases {
            let path = case["path"].as_str().unwrap();
            let items = build_records(
                path,
                case["text"].as_str().unwrap(),
                &BuildConfig::default(),
            );
            assert_eq!(
                items[0].content,
                case["summary"].as_str().unwrap(),
                "{path}"
            );
            assert_eq!(
                items[1].content,
                case["manifest"].as_str().unwrap(),
                "{path}"
            );
            for item in items {
                assert_eq!(item.name, format!("{path}::{}", item.kind));
                assert!(item.symbols.is_empty());
                let value = serde_json::to_value(item).unwrap();
                assert_eq!(value.as_object().unwrap().len(), 10);
            }
        }
    }

    #[test]
    fn content_budget_and_kind_switches() {
        let config = BuildConfig {
            tokenize_content_chars: 7,
            file_manifest: false,
            ..Default::default()
        };
        let items = build_records("docs/readMe.md", "# Intro", &config);
        assert_eq!(items.len(), 1);
        assert_eq!(items[0].tokenized_content, vec!["file"]);
        assert!(
            build_records(
                "x.md",
                "# Intro",
                &BuildConfig {
                    file_manifest: false,
                    file_summary: false,
                    ..Default::default()
                }
            )
            .is_empty()
        );
    }

    #[test]
    fn scanner_edge_cases_and_determinism() {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path();
        std::fs::create_dir_all(root.join("nested/deeper")).unwrap();
        std::fs::write(root.join(".gitignore"), "ignored.md\n").unwrap();
        std::fs::write(root.join("nested/.gitignore"), "local.md\n!keep.md\n").unwrap();
        std::fs::write(root.join(".ignore"), "ignored2.md\n").unwrap();
        std::fs::write(root.join(".rgignore"), "ignored3.md\n").unwrap();
        for name in [
            "ignored.md",
            "ignored2.md",
            "ignored3.md",
            "nested/local.md",
            ".hidden.md",
            "nested/deeper/.hidden.md",
        ] {
            std::fs::write(root.join(name), "hidden").unwrap();
        }
        std::fs::write(root.join("a.md"), b"# Intro\r\nBody\r\n").unwrap();
        std::fs::write(root.join("bom.md"), "\u{feff}# Intro\n").unwrap();
        std::fs::write(root.join("lossy.md"), [b'a', 0xff, b'b']).unwrap();
        std::fs::write(root.join("empty.md"), " \r\n\u{2003}").unwrap();
        std::fs::write(root.join("nul.md"), b"x\0y").unwrap();
        std::fs::write(root.join("huge.md"), "x".repeat(101)).unwrap();
        std::fs::write(root.join("nested/keep.md"), "keep").unwrap();
        std::fs::write(root.join("文档.md"), "unicode").unwrap();
        let config = BuildConfig {
            max_file_bytes: 100,
            ..Default::default()
        };
        let items = build_catalog(root, &config).unwrap();
        let paths: Vec<_> = items.iter().step_by(2).map(|i| i.path.as_str()).collect();
        assert_eq!(
            paths,
            vec!["a.md", "bom.md", "lossy.md", "nested/keep.md", "文档.md"]
        );
        assert!(
            items
                .iter()
                .any(|i| i.path == "lossy.md" && i.content.contains("a\u{fffd}b"))
        );
        assert!(
            items
                .iter()
                .any(|i| i.path == "bom.md" && i.content.contains('\u{feff}'))
        );
        assert_eq!(
            serde_json::to_string(&items).unwrap(),
            serde_json::to_string(&build_catalog(root, &config).unwrap()).unwrap()
        );
    }
}
