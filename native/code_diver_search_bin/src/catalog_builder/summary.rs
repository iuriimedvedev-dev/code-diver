//! `FileSummaryItemBuilder` (src/code_diver/services/file_summary_item_builder.py).

use std::sync::LazyLock;

use regex::Regex;

use super::pytext::{self, char_len, prefix, rstrip, splitlines, strip};
use super::symbols::{Symbol, suffix_lower};

const TRUNCATION_MARKER: &str = " ...[truncated]";
const MAX_TERM_COUNT: usize = 40;
const MAX_TERMS_LINE_CHARS: usize = 220;
const MAX_PURPOSE_LINE_CHARS: usize = 220;
const MAX_IMPORTS: usize = 24;
const MAX_SYMBOLS: usize = 80;
const MAX_HEAD_LINES: usize = 24;
const MAX_HEAD_IMPORT_LINES: usize = 5;
const COMPACT_FILE_PATH_SEGMENTS: usize = 2;

const KEYWORD_STOPWORDS: &[&str] = &[
    "open",
    "class",
    "interface",
    "object",
    "fun",
    "val",
    "var",
    "private",
    "public",
    "protected",
    "internal",
    "override",
    "const",
    "static",
    "final",
    "abstract",
    "suspend",
    "companion",
    "get",
    "set",
    "constructor",
    "return",
    "void",
    "new",
    "extends",
    "implements",
    "package",
    "import",
    "this",
    "super",
    "null",
    "true",
    "false",
];
const PATH_STOPWORDS: &[&str] = &[
    "src",
    "com",
    "intellij",
    "jetbrains",
    "main",
    "java",
    "kotlin",
    "impl",
];

// Python: ^\s*(//|#|%|;)\s*[Cc]opyright | ^\s*/\*(?!\*) | ^\s*\*[^/] | ^[-]{20,}
// The lookahead `(?!\*)` becomes "followed by end or a non-star char".
static LICENSE_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^\s*(?://|#|%|;)\s*[Cc]opyright|^\s*/\*(?:[^*]|$)|^\s*\*[^/]|^-{20,}").unwrap()
});
static IMPORT_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^\s*(?:from\s+[\w.]+\s+import\s+.+|import\s+[\w.,\s;]+)\s*$").unwrap()
});
static FILE_ANNOTATION_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^\s*@file:\s*").unwrap());

/// Python `re.split(r"(?<=[a-z0-9])(?=[A-Z])|[^A-Za-z0-9]+", s)` without empty pieces.
pub fn identifier_split(s: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut cur = String::new();
    let mut prev: Option<char> = None;
    for c in s.chars() {
        if !c.is_ascii_alphanumeric() {
            if !cur.is_empty() {
                out.push(std::mem::take(&mut cur));
            }
            prev = Some(c);
            continue;
        }
        if c.is_ascii_uppercase()
            && prev.is_some_and(|p| p.is_ascii_lowercase() || p.is_ascii_digit())
            && !cur.is_empty()
        {
            out.push(std::mem::take(&mut cur));
        }
        cur.push(c);
        prev = Some(c);
    }
    if !cur.is_empty() {
        out.push(cur);
    }
    out
}

pub struct SummaryConfig {
    pub compact_budget: bool,
    pub compact_path: Option<bool>,
    pub term_stopwords: Option<bool>,
    pub max_head_line_chars: usize,
    pub max_head_block_chars: usize,
}

impl Default for SummaryConfig {
    fn default() -> Self {
        Self {
            compact_budget: false,
            compact_path: None,
            term_stopwords: None,
            max_head_line_chars: 200,
            max_head_block_chars: 4000,
        }
    }
}

pub fn build_file_summary(
    rel_path: &str,
    text: &str,
    symbols: &[Symbol],
    cfg: &SummaryConfig,
) -> String {
    let mut sections = [
        super::symbols::jvm::purpose_section(rel_path, text, cfg)
            .unwrap_or_else(|| purpose_section(rel_path, cfg)),
        terms_section(rel_path, text, symbols, cfg),
        format!("file: {}", file_line_value(rel_path, cfg)),
        format!("extension: {}", suffix_lower(rel_path)),
        symbols_section(symbols),
        head_section(text, cfg),
        imports_section(text),
    ];
    if !cfg.compact_budget {
        sections.swap(0, 2);
        sections.swap(1, 3);
    }
    strip(&sections.join("\n")).to_string()
}

fn file_line_value(rel_path: &str, cfg: &SummaryConfig) -> String {
    if !cfg.compact_path.unwrap_or(cfg.compact_budget) {
        return rel_path.to_string();
    }
    let parts = pytext::parts(rel_path);
    let keep = COMPACT_FILE_PATH_SEGMENTS + 1;
    let start = parts.len().saturating_sub(keep);
    parts[start..].join("/")
}

fn purpose_section(rel_path: &str, cfg: &SummaryConfig) -> String {
    let words: Vec<String> = identifier_split(pytext::stem(rel_path))
        .into_iter()
        .filter(|t| char_len(t) >= 2)
        .map(|t| t.to_lowercase())
        .collect();
    let purpose = if words.is_empty() {
        "none".to_string()
    } else {
        cap_purpose(&words.join(" "), cfg)
    };
    format!("purpose: {purpose}")
}

fn cap_purpose(line: &str, cfg: &SummaryConfig) -> String {
    let limit = cfg.max_head_line_chars.min(MAX_PURPOSE_LINE_CHARS);
    if char_len(line) <= limit {
        return line.to_string();
    }
    let content_limit = limit.saturating_sub(char_len(TRUNCATION_MARKER));
    let mut content = rstrip(prefix(line, content_limit)).to_string();
    if !content.is_empty() {
        // Python: content.rsplit(" ", 1)[0] or content
        let head = content
            .rsplit_once(' ')
            .map_or(content.as_str(), |(h, _)| h);
        if !head.is_empty() {
            content = head.to_string();
        }
    }
    content + TRUNCATION_MARKER
}

fn terms_section(rel_path: &str, text: &str, symbols: &[Symbol], cfg: &SummaryConfig) -> String {
    let extension = suffix_lower(rel_path).trim_start_matches('.').to_string();
    let values = super::symbols::jvm::term_values(rel_path, text, symbols, cfg);
    let mut terms: Vec<String> = Vec::new();
    let mut seen = std::collections::HashSet::new();
    for value in &values {
        for token in identifier_split(value) {
            let normalized = token.to_lowercase();
            if char_len(&normalized) < 2 || seen.contains(&normalized) {
                continue;
            }
            if cfg.term_stopwords.unwrap_or(cfg.compact_budget)
                && is_noise_term(&normalized, &extension)
            {
                continue;
            }
            // Python: len(f"terms: {' '.join(terms + [normalized])}") > 220
            let joined = if terms.is_empty() {
                normalized.clone()
            } else {
                format!("{} {}", terms.join(" "), normalized)
            };
            if char_len(&format!("terms: {joined}")) > MAX_TERMS_LINE_CHARS {
                return terms_line(&terms);
            }
            seen.insert(normalized.clone());
            terms.push(normalized);
            if terms.len() >= MAX_TERM_COUNT {
                return terms_line(&terms);
            }
        }
    }
    terms_line(&terms)
}

fn terms_line(terms: &[String]) -> String {
    if terms.is_empty() {
        "terms: none".to_string()
    } else {
        format!("terms: {}", terms.join(" "))
    }
}

fn is_noise_term(normalized: &str, extension: &str) -> bool {
    normalized.chars().all(|c| c.is_ascii_digit())
        || normalized == extension
        || KEYWORD_STOPWORDS.contains(&normalized)
        || PATH_STOPWORDS.contains(&normalized)
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

fn is_boilerplate(stripped: &str) -> bool {
    stripped.is_empty() || LICENSE_RE.is_match(stripped) || FILE_ANNOTATION_RE.is_match(stripped)
}

fn skip_boilerplate(text: &str) -> Vec<String> {
    let mut kdoc: Vec<String> = Vec::new();
    let mut meaningful: Vec<String> = Vec::new();
    let mut import_count = 0;
    for line in splitlines(text) {
        let stripped = strip(line);
        if stripped.is_empty() {
            continue;
        }
        if is_boilerplate(stripped) {
            if stripped.starts_with("/**") || stripped.starts_with('*') {
                kdoc.push(stripped.to_string());
            }
            continue;
        }
        if IMPORT_RE.is_match(stripped) {
            if import_count < MAX_HEAD_IMPORT_LINES {
                import_count += 1;
                if meaningful.is_empty() && !kdoc.is_empty() {
                    meaningful.extend(kdoc.drain(..).take(4));
                }
                meaningful.push(stripped.to_string());
            }
            continue;
        }
        if meaningful.is_empty() && !kdoc.is_empty() {
            meaningful.extend(kdoc.drain(..).take(4));
        }
        meaningful.push(stripped.to_string());
        if meaningful.len() >= MAX_HEAD_LINES {
            break;
        }
    }
    if meaningful.is_empty() && !kdoc.is_empty() {
        meaningful = kdoc.into_iter().take(MAX_HEAD_LINES).collect();
    }
    meaningful
}

fn head_section(text: &str, cfg: &SummaryConfig) -> String {
    let meaningful = skip_boilerplate(text);
    if meaningful.is_empty() {
        return "head: empty".to_string();
    }
    let rows: Vec<String> = meaningful
        .iter()
        .take(MAX_HEAD_LINES)
        .map(|row| {
            let row = if char_len(row) <= cfg.max_head_line_chars {
                row.clone()
            } else {
                format!(
                    "{}{}",
                    prefix(row, cfg.max_head_line_chars),
                    TRUNCATION_MARKER
                )
            };
            format!("- {row}")
        })
        .collect();
    let block = format!("head:\n{}", rows.join("\n"));
    if char_len(&block) <= cfg.max_head_block_chars {
        return block;
    }
    let limit = cfg
        .max_head_block_chars
        .saturating_sub(char_len(TRUNCATION_MARKER));
    format!("{}{}", prefix(&block, limit), TRUNCATION_MARKER)
}

fn imports_section(text: &str) -> String {
    let imports: Vec<String> = splitlines(text)
        .into_iter()
        .filter(|l| IMPORT_RE.is_match(l))
        .map(|l| strip(l).to_string())
        .collect();
    if imports.is_empty() {
        return "imports: none".to_string();
    }
    let rows: Vec<String> = imports
        .iter()
        .take(MAX_IMPORTS)
        .map(|r| format!("- {r}"))
        .collect();
    format!("imports:\n{}", rows.join("\n"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn integrated_jvm_purpose_terms_and_generic_fallback() {
        let cfg = SummaryConfig {
            compact_budget: true,
            ..Default::default()
        };
        let text = "package com.work\nclass WorkerServiceImpl : Base {}";
        let symbols = super::super::symbols::extract("src/X.kt", text);
        let output = build_file_summary("src/X.kt", text, &symbols, &cfg);
        assert!(output.starts_with("purpose: service implementation WorkerServiceImpl for Base in work\nterms: worker service implementation base work\n"), "{output}");
        assert!(
            build_file_summary("src/Empty.java", "", &[], &cfg)
                .starts_with("purpose: empty\nterms: empty\n")
        );
        assert!(
            build_file_summary("src/X.scala", text, &symbols, &cfg)
                .starts_with("purpose: none\nterms: worker service base work\n")
        );
    }

    #[test]
    fn package_terms_only_inspect_first_line() {
        let cfg = SummaryConfig {
            compact_budget: true,
            ..Default::default()
        };
        assert_eq!(
            terms_section("worker.go", "package workers\n", &[], &cfg),
            "terms: worker workers"
        );
        assert_eq!(
            terms_section("worker.go", "// header\npackage workers\n", &[], &cfg),
            "terms: worker"
        );
        assert_eq!(
            terms_section("worker.go", "\npackage workers\n", &[], &cfg),
            "terms: worker"
        );
    }

    #[test]
    fn import_head_can_exceed_cap_before_final_truncation() {
        let text = "code\n".repeat(23) + "import first\nimport second\nimport third\nlast\n";
        let meaningful = skip_boilerplate(&text);
        assert_eq!(meaningful.len(), 27);
        let head = head_section(&text, &SummaryConfig::default());
        assert_eq!(head.lines().count(), 25);
        assert!(head.ends_with("- import first"));
        assert_eq!(
            imports_section(&text),
            "imports:\n- import first\n- import second\n- import third"
        );
    }

    #[test]
    fn explicit_compact_path_and_stopword_overrides() {
        let cfg = SummaryConfig {
            compact_budget: true,
            compact_path: Some(false),
            term_stopwords: Some(false),
            ..Default::default()
        };
        let output = build_file_summary("src/com/main/readMe.md", "", &[], &cfg);
        assert!(output.starts_with(
            "purpose: read me\nterms: read me src com main md\nfile: src/com/main/readMe.md"
        ));
        let cfg = SummaryConfig {
            compact_path: Some(true),
            term_stopwords: Some(true),
            ..Default::default()
        };
        let output = build_file_summary("src/com/main/readMe.md", "", &[], &cfg);
        assert!(output.starts_with(
            "file: com/main/readMe.md\nextension: .md\npurpose: read me\nterms: read me\n"
        ));
    }

    #[test]
    fn import_head_and_unicode_budget_caps() {
        let text = (0..30)
            .map(|n| format!("import module{n}\n"))
            .collect::<String>()
            + &"文".repeat(300);
        let cfg = SummaryConfig {
            max_head_line_chars: 10,
            max_head_block_chars: 60,
            ..Default::default()
        };
        let output = build_file_summary("a.md", &text, &[], &cfg);
        let imports = output.split("imports:\n").nth(1).unwrap();
        assert_eq!(imports.lines().count(), 24);
        let head = output
            .split("head:\n")
            .nth(1)
            .unwrap()
            .split("\nimports:")
            .next()
            .unwrap();
        assert!(head.ends_with(TRUNCATION_MARKER));
        assert!(char_len(head) + "head:\n".len() <= 60);
    }

    #[test]
    fn noncompact_default_preserves_full_path_and_section_order() {
        let output = build_file_summary(
            "src/com/main/readMe.md",
            "# Intro",
            &[],
            &SummaryConfig::default(),
        );
        assert!(output.starts_with("file: src/com/main/readMe.md\nextension: .md\npurpose: read me\nterms: read me src com main md\n"), "{output}");
    }

    #[test]
    fn identifier_split_matches_python_regex() {
        assert_eq!(
            identifier_split("readMeFile2Go"),
            vec!["read", "Me", "File2", "Go"]
        );
        assert_eq!(
            identifier_split("kb/aws-readme.md"),
            vec!["kb", "aws", "readme", "md"]
        );
        assert_eq!(identifier_split("XMLParser"), vec!["XMLParser"]);
        assert_eq!(identifier_split("a2B"), vec!["a2", "B"]);
    }

    #[test]
    fn license_regex_lookahead_equivalent() {
        assert!(LICENSE_RE.is_match("/* license"));
        assert!(LICENSE_RE.is_match("/*"));
        assert!(!LICENSE_RE.is_match("/** doc"));
        assert!(LICENSE_RE.is_match("* bullet"));
        assert!(!LICENSE_RE.is_match("*/"));
        assert!(LICENSE_RE.is_match("# Copyright 2024"));
        assert!(LICENSE_RE.is_match(&"-".repeat(20)));
        assert!(!LICENSE_RE.is_match("--- yaml"));
    }

    #[test]
    fn long_purpose_is_cut_on_word_boundary() {
        let cfg = SummaryConfig::default();
        let long = vec!["word"; 80].join(" ");
        let out = cap_purpose(&long, &cfg);
        assert!(out.ends_with(" ...[truncated]"));
        assert!(char_len(&out) <= 200);
    }

    #[test]
    fn terms_stop_at_line_budget_and_skip_noise() {
        let s = vec![Symbol {
            name: "Foo".into(),
            kind: "symbol".into(),
            signature: "class Foo private 123 md".into(),
        }];
        let cfg = SummaryConfig {
            compact_budget: true,
            ..Default::default()
        };
        let out = terms_section("a/bb.md", "x", &s, &cfg);
        assert_eq!(out, "terms: bb foo");
    }
}
