//! `FileManifestItemBuilder` generic templates, including symbol-surface mode.

use std::collections::HashSet;
use std::sync::LazyLock;

use regex::Regex;

use super::pytext::{self, normalize_ws, strip};
use super::symbols::{Symbol, suffix_lower};

const MAX_IMPORTS: usize = 20;
const MAX_SYMBOLS: usize = 80;
const MAX_CONFIG_KEYS: usize = 80;

static PACKAGE_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?m)^\s*package\s+([A-Za-z_][\w.]*);?\s*$").unwrap());
static IMPORT_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        r"(?m)^\s*(?:import\s+(?:static\s+)?[A-Za-z_][\w.*]*(?:\s+as\s+[A-Za-z_][\w]*)?;?|from\s+[\w.]+\s+import\s+.+)\s*$",
    )
    .unwrap()
});
static CONFIG_KEY_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?m)^\s*([A-Za-z_][\w.-]{1,120})\s*[:=]").unwrap());
static XML_NAME_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"<\s*([A-Za-z_][\w.-]*)(?:\s|>|/)").unwrap());

fn unique<I: IntoIterator<Item = String>>(values: I) -> Vec<String> {
    let mut seen = HashSet::new();
    let mut rows = Vec::new();
    for value in values {
        let row = normalize_ws(&value);
        let key = row.to_lowercase();
        if row.is_empty() || !seen.insert(key) {
            continue;
        }
        rows.push(row);
    }
    rows
}

pub fn build_file_manifest(
    rel_path: &str,
    text: &str,
    symbols: &[Symbol],
    symbol_surface: bool,
) -> String {
    if symbol_surface {
        return format!(
            "filename: {}\n{}\n{}",
            pytext::file_name(rel_path),
            config_section(rel_path, text),
            surface_section(symbols)
        );
    }
    let sections = [
        format!("file: {rel_path}"),
        format!("filename: {}", pytext::file_name(rel_path)),
        format!("extension: {}", suffix_lower(rel_path)),
        path_section(rel_path),
        package_section(text),
        symbols_section(symbols),
        imports_section(text),
        config_section(rel_path, text),
    ];
    let joined = sections
        .iter()
        .filter(|s| !s.is_empty())
        .cloned()
        .collect::<Vec<_>>()
        .join("\n");
    strip(&joined).to_string()
}

fn path_section(rel_path: &str) -> String {
    let parts = pytext::parts(rel_path);
    let tokens = unique(
        parts
            .join(" ")
            .split(|c: char| !c.is_ascii_alphanumeric())
            .filter(|t| t.chars().count() >= 2)
            .map(|t| t.to_lowercase()),
    );
    let dirs = if parts.len() > 1 {
        parts[..parts.len() - 1].join(" / ")
    } else {
        String::new()
    };
    let dirs = if dirs.is_empty() {
        "none".to_string()
    } else {
        dirs
    };
    let tok = if tokens.is_empty() {
        "none".to_string()
    } else {
        tokens.join(" ")
    };
    format!("directories: {dirs}\npath_tokens: {tok}")
}

fn package_section(text: &str) -> String {
    let packages = unique(PACKAGE_RE.captures_iter(text).map(|c| c[1].to_string()));
    match packages.first() {
        Some(p) => format!("package: {p}"),
        None => "package: none".to_string(),
    }
}

fn imports_section(text: &str) -> String {
    let imports = IMPORT_RE
        .find_iter(text)
        .map(|m| strip(m.as_str()).trim_end_matches(';').to_string());
    let rows: Vec<String> = unique(imports).into_iter().take(MAX_IMPORTS).collect();
    if rows.is_empty() {
        return "imports: none".to_string();
    }
    format!(
        "imports:\n{}",
        rows.iter()
            .map(|r| format!("- {r}"))
            .collect::<Vec<_>>()
            .join("\n")
    )
}

fn symbols_section(symbols: &[Symbol]) -> String {
    if symbols.is_empty() {
        return "symbols: none".to_string();
    }
    let rows: Vec<String> = symbols
        .iter()
        .take(MAX_SYMBOLS)
        .map(|s| format!("- {} {}: {}", s.kind, s.name, s.signature))
        .collect();
    format!("symbols:\n{}", rows.join("\n"))
}

fn surface_section(symbols: &[Symbol]) -> String {
    let trivial = [
        "tostring",
        "equals",
        "hashcode",
        "clone",
        "finalize",
        "copy",
        "compareto",
        "iterator",
        "invoke",
        "main",
    ];
    let candidates: Vec<&Symbol> = symbols
        .iter()
        .take(MAX_SYMBOLS)
        .filter(|s| {
            !trivial.contains(&s.name.to_lowercase().as_str())
                && !s.name.starts_with('_')
                && !s.signature.split_whitespace().any(|w| w == "private")
        })
        .collect();
    let mut ranked: Vec<(usize, i64)> = candidates
        .iter()
        .enumerate()
        .map(|(index, s)| {
            let words = super::summary::identifier_split(&s.name);
            let mut score = words.len() as i64;
            if ["class", "interface", "object", "enum"].contains(&s.kind.as_str()) {
                score += 2;
            }
            if words
                .first()
                .is_some_and(|w| ["get", "set", "is", "has"].contains(&w.to_lowercase().as_str()))
            {
                score -= 1;
            }
            (index, score)
        })
        .collect();
    ranked.sort_by_key(|(index, score)| (-score, *index));
    ranked.truncate(22);
    ranked.sort_by_key(|(index, _)| *index);
    let rows: Vec<String> = ranked
        .into_iter()
        .map(|(index, _)| {
            let s = candidates[index];
            let signature = pytext::normalize_ws(&s.signature);
            let signature = if signature.is_empty() {
                s.name.as_str()
            } else {
                &signature
            };
            format!("- {}", pytext::rstrip(pytext::prefix(signature, 120)))
        })
        .collect();
    if rows.is_empty() {
        "api: none".into()
    } else {
        format!("api:\n{}", rows.join("\n"))
    }
}

fn config_section(rel_path: &str, text: &str) -> String {
    let suffix = suffix_lower(rel_path);
    let mut keys: Vec<String> = Vec::new();
    if [".properties", ".yaml", ".yml", ".toml"].contains(&suffix.as_str()) {
        keys.extend(CONFIG_KEY_RE.captures_iter(text).map(|c| c[1].to_string()));
    }
    if suffix == ".xml" {
        keys.extend(XML_NAME_RE.captures_iter(text).map(|c| c[1].to_string()));
    }
    let keys: Vec<String> = unique(keys).into_iter().take(MAX_CONFIG_KEYS).collect();
    if keys.is_empty() {
        return "config_keys: none".to_string();
    }
    format!(
        "config_keys:\n{}",
        keys.iter()
            .map(|k| format!("- {k}"))
            .collect::<Vec<_>>()
            .join("\n")
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn package_search_and_import_dedup_precede_caps() {
        assert_eq!(
            package_section("// header\npackage workers\n"),
            "package: workers"
        );
        let text = "import first;\n".repeat(24)
            + &(0..25)
                .map(|n| format!("import module{n};\n"))
                .collect::<String>();
        let imports = imports_section(&text);
        assert_eq!(imports.lines().count(), 21);
        assert!(imports.starts_with("imports:\n- import first\n- import module0"));
        assert!(imports.ends_with("- import module18"));
    }

    #[test]
    fn generic_surface_mode_and_caps() {
        let symbols = super::super::symbols::extract(
            "a.sh",
            "function processDomain() {}\nfunction _hidden() {}\nfunction main() {}\n",
        );
        let out = build_file_manifest("a.sh", "", &symbols, true);
        assert_eq!(
            out,
            "filename: a.sh\nconfig_keys: none\napi:\n- function processDomain() {}"
        );
        let text = (0..100)
            .map(|n| format!("key{n}: value\n"))
            .collect::<String>();
        let output = build_file_manifest("a.yml", &text, &[], false);
        assert_eq!(
            output
                .split("config_keys:\n")
                .nth(1)
                .unwrap()
                .lines()
                .count(),
            80
        );
    }

    #[test]
    fn yaml_manifest_lists_unique_config_keys() {
        let text = "name: a\nspec:\n  name: b\n  Image: x\n";
        let out = build_file_manifest("deploy/app.yaml", text, &[], false);
        assert!(out.contains("directories: deploy\npath_tokens: deploy app yaml"));
        assert!(out.ends_with("config_keys:\n- name\n- spec\n- Image"));
    }

    #[test]
    fn root_file_has_no_directories() {
        let out = build_file_manifest("readme.md", "x", &[], false);
        assert!(out.contains("directories: none\npath_tokens: readme md"));
    }
}
