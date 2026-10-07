use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};

use clap::{Args, ValueEnum};
use serde_json::Value;

use super::{BuildConfig, build_catalog, compare, symbols};

#[derive(Args, Debug, Clone)]
pub struct IndexArgs {
    #[arg(long, required = true)]
    pub catalog_only: bool,
    #[arg(long, default_value = ".")]
    pub root: PathBuf,
    #[arg(long)]
    pub out: PathBuf,
    #[arg(long)]
    pub include: Vec<String>,
    #[arg(long)]
    pub exclude: Vec<String>,
    #[arg(long)]
    pub config: Option<PathBuf>,
    #[arg(long)]
    pub tokenize_content_chars: Option<usize>,
}

#[derive(ValueEnum, Debug, Clone)]
pub enum Lane {
    All,
    Generic,
}

#[derive(Args, Debug, Clone)]
pub struct CompareArgs {
    #[arg(long)]
    pub reference: PathBuf,
    #[arg(long)]
    pub built: PathBuf,
    #[arg(long)]
    pub path_prefix: Vec<String>,
    #[arg(long, value_enum, default_value = "all")]
    pub lane: Lane,
}

pub fn load_config(path: &Path) -> Result<BuildConfig, String> {
    let raw = fs::read_to_string(path)
        .map_err(|e| format!("Cannot read config {}: {e}", path.display()))?;
    let value: Value =
        super::config::parse(&raw, path.extension().is_some_and(|ext| ext == "toml"))?;
    let mut config = BuildConfig::default();
    let Some(scanner) = value.get("scanner") else {
        return Ok(config);
    };
    let map = scanner.as_object().ok_or("scanner must be a mapping")?;
    for (key, value) in map {
        let key = key.as_str();
        let invalid = || format!("Invalid scanner.{key}");
        let boolean = || value.as_bool().ok_or_else(invalid);
        let number = || {
            value
                .as_u64()
                .and_then(|n| usize::try_from(n).ok())
                .ok_or_else(invalid)
        };
        match key {
            "include" | "exclude" => {
                let globs: Vec<String> =
                    serde_json::from_value(value.clone()).map_err(|_| invalid())?;
                if key == "include" {
                    config.include = globs;
                } else {
                    config.exclude = globs;
                }
            }
            "max_file_bytes" => config.max_file_bytes = value.as_u64().ok_or_else(invalid)?,
            "max_symbols_per_file" => {
                config.max_symbols_per_file =
                    if value.is_null() || value.as_i64().is_some_and(|n| n < 0) {
                        None
                    } else {
                        Some(number()?)
                    }
            }
            "tokenize_content_chars" => config.tokenize_content_chars = number()?,
            "file_summary_head_line_max_chars" => config.summary.max_head_line_chars = number()?,
            "file_summary_head_block_max_chars" => config.summary.max_head_block_chars = number()?,
            "file_summary_compact_budget" => config.summary.compact_budget = boolean()?,
            "file_summary_compact_path" => {
                config.summary.compact_path = if value.is_null() {
                    None
                } else {
                    Some(boolean()?)
                }
            }
            "file_summary_term_stopwords" => {
                config.summary.term_stopwords = if value.is_null() {
                    None
                } else {
                    Some(boolean()?)
                }
            }
            "file_manifest_symbol_surface" => config.manifest_symbol_surface = boolean()?,
            "file_summary_chunks" => config.file_summary = boolean()?,
            "file_manifest_chunks" => config.file_manifest = boolean()?,
            "symbol_body" => {
                boolean()?;
            }
            "chunk_lines" => {
                number()?;
            }
            "line_chunks"
            | "structural_chunks"
            | "symbol_chunks"
            | "file_api_manifest_chunks"
            | "file_body_evidence_chunks"
            | "file_purpose_chunks"
            | "symbol_chunk_chunks"
            | "documentation_summary_chunks"
            | "documentation_manifest_chunks"
            | "documentation_chunk_chunks" => {
                if boolean()? {
                    return Err(format!(
                        "scanner.{key}=true is not supported in M1; disable this item kind"
                    ));
                }
            }
            _ => return Err(format!("Unsupported scanner configuration key: {key}")),
        }
    }
    Ok(config)
}

pub fn run_index(args: IndexArgs) -> Result<(), String> {
    let mut config = args
        .config
        .as_deref()
        .map(load_config)
        .transpose()?
        .unwrap_or_default();
    if !args.include.is_empty() {
        config.include = args.include;
    }
    if !args.exclude.is_empty() {
        config.exclude = args.exclude;
    }
    if let Some(chars) = args.tokenize_content_chars {
        config.tokenize_content_chars = chars;
    }
    let items = build_catalog(&args.root, &config)?;
    let dedicated = items
        .iter()
        .map(|item| item.path.as_str())
        .filter(|path| symbols::has_dedicated_strategy(path))
        .collect::<std::collections::HashSet<_>>()
        .len();
    let mut writer = BufWriter::new(
        File::create(&args.out)
            .map_err(|e| format!("Cannot create {}: {e}", args.out.display()))?,
    );
    for item in &items {
        serde_json::to_writer(&mut writer, item).map_err(|e| e.to_string())?;
        writer.write_all(b"\n").map_err(|e| e.to_string())?;
    }
    writer.flush().map_err(|e| e.to_string())?;
    eprintln!(
        "wrote {} items; dedicated-language files (generic fallback, M2 pending): {dedicated}",
        items.len()
    );
    Ok(())
}

pub fn run_compare(args: CompareArgs) -> Result<(), String> {
    let reference = compare::load_jsonl(&args.reference)?;
    let built = compare::load_jsonl(&args.built)?;
    let keep = |path: &str| {
        (args.path_prefix.is_empty()
            || args
                .path_prefix
                .iter()
                .any(|prefix| path.starts_with(prefix)))
            && (!matches!(args.lane, Lane::Generic) || !symbols::has_dedicated_strategy(path))
    };
    let report = compare::compare(&reference, &built, &keep, 2);
    print!("{}", report.render());
    if report.ref_count != report.common_ids
        || report.built_count != report.common_ids
        || report.content_equal != report.common_ids
        || report.tokenized_equal != report.common_ids
        || report.name_equal != report.common_ids
        || report.path_equal != report.common_ids
        || report.kind_equal != report.common_ids
    {
        return Err("Catalog parity failed; see counts and first differing sections above".into());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn load(raw: &str) -> Result<BuildConfig, String> {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("config.yml");
        fs::write(&path, raw).unwrap();
        load_config(&path)
    }

    #[test]
    fn loads_every_builder_setting() {
        for compact in [false, true] {
            let config = load(&format!("scanner:\n  include: ['kb/**']\n  exclude: ['tmp/**']\n  max_file_bytes: 123\n  max_symbols_per_file: 7\n  tokenize_content_chars: 9\n  file_summary_head_line_max_chars: 11\n  file_summary_head_block_max_chars: 13\n  file_summary_compact_budget: {compact}\n  file_summary_compact_path: false\n  file_summary_term_stopwords: true\n  file_manifest_symbol_surface: true\n  file_summary_chunks: false\n  file_manifest_chunks: true\n  symbol_body: false\n  chunk_lines: 20\n")).unwrap();
            assert_eq!(config.include, ["kb/**"]);
            assert_eq!(config.exclude, ["tmp/**"]);
            assert_eq!(config.max_file_bytes, 123);
            assert_eq!(config.max_symbols_per_file, Some(7));
            assert_eq!(config.tokenize_content_chars, 9);
            assert_eq!(config.summary.max_head_line_chars, 11);
            assert_eq!(config.summary.max_head_block_chars, 13);
            assert_eq!(config.summary.compact_budget, compact);
            assert_eq!(config.summary.compact_path, Some(false));
            assert_eq!(config.summary.term_stopwords, Some(true));
            assert!(config.manifest_symbol_surface && config.file_manifest);
            assert!(!config.file_summary);
        }
        for limit in ["null", "-1"] {
            assert_eq!(
                load(&format!("scanner:\n  max_symbols_per_file: {limit}\n"))
                    .unwrap()
                    .max_symbols_per_file,
                None
            );
        }
        assert_eq!(
            load("scanner:\n  tokenize_content_chars: 0\n")
                .unwrap()
                .tokenize_content_chars,
            0
        );
    }

    #[test]
    fn rejects_unsupported_and_wrong_typed_settings() {
        for setting in [
            "unknown_cap: 4",
            "symbol_body: yes",
            "chunk_lines: -1",
            "include: 4",
            "max_file_bytes: -1",
            "tokenize_content_chars: false",
            "max_symbols_per_file: nope",
            "file_summary_compact_budget: 1",
            "file_summary_compact_path: 1",
            "file_summary_term_stopwords: 1",
            "file_summary_head_line_max_chars: -1",
            "file_manifest_symbol_surface: 1",
            "line_chunks: true",
        ] {
            assert!(
                load(&format!("scanner:\n  {setting}\n")).is_err(),
                "{setting}"
            );
        }
    }
}
