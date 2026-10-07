//! Symbol extraction. The Python indexer is regex-based (no tree-sitter anywhere): see
//! `indexing/languages/*.py` and `services/code_symbol_extractor.py`.
//!
//! Ported here: the markdown-header extractor and the generic regex fallback, which together
//! cover every extension that has no dedicated Python strategy (md, yaml, tf, html, css, sh,
//! json, txt, ...). Dedicated strategies (py/pyi via `ast`, go, ts/js, java/kt/kts, rs, c/cpp)
//! are routed in the parent module; `has_dedicated_strategy` describes the Python registry.

use std::sync::LazyLock;

use regex::Regex;

use super::super::pytext::{self, prefix, strip};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Symbol {
    pub name: String,
    pub kind: String,
    pub signature: String,
}

const MD_EXTS: &[&str] = &[".md", ".markdown", ".mdown", ".rst", ".txt"];
const DEDICATED_EXTS: &[&str] = &[
    ".py", ".pyi", ".java", ".kt", ".kts", ".rs", ".go", ".c", ".cc", ".cpp", ".cxx", ".h", ".hh",
    ".hpp", ".hxx", ".c++", ".h++", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts",
];

static MARKDOWN_HEADER_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^(#{1,6})\s+(.+)$").unwrap());

static GENERIC_SYMBOL_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        r"(?m)^\s*(?:export\s+)?(?:pub(?:\([^)]+\))?\s+)?(?:async\s+)?(?:class|interface|trait|type|function|def|fn|struct|enum)\s+([A-Za-z_][\w$]*)|^\s*func\s+(?:\([^)]+\)\s+)?([A-Za-z_]\w*)|^\s*impl(?:\s*<[^>]+>)?\s+(?:[A-Za-z_]\w+\s+for\s+)?([A-Za-z_]\w*)|^\s*(?:export\s+)?const\s+([A-Za-z_][\w$]*)\s*=",
    )
    .unwrap()
});

pub fn suffix_lower(rel_path: &str) -> String {
    pytext::suffix(rel_path).to_lowercase()
}

/// True when the Python indexer routes this path to a language-specific strategy.
pub fn has_dedicated_strategy(rel_path: &str) -> bool {
    DEDICATED_EXTS.contains(&suffix_lower(rel_path).as_str())
}

pub fn extract(rel_path: &str, text: &str) -> Vec<Symbol> {
    if MD_EXTS.contains(&suffix_lower(rel_path).as_str()) {
        let symbols = markdown_symbols(text);
        if !symbols.is_empty() {
            return symbols;
        }
    }
    generic_symbols(text)
}

/// `CodebaseScanner._symbols_for_file`: adaptive cap `max(max_symbols, line_count // 4)`.
pub fn limit_symbols(
    mut symbols: Vec<Symbol>,
    text: &str,
    max_symbols_per_file: Option<usize>,
) -> Vec<Symbol> {
    let Some(max) = max_symbols_per_file else {
        return symbols;
    };
    let line_count = text.matches('\n').count() + 1;
    let effective = max.max(line_count / 4);
    symbols.truncate(effective);
    symbols
}

fn markdown_symbols(text: &str) -> Vec<Symbol> {
    let mut out = Vec::new();
    for line in pytext::splitlines(text) {
        if let Some(caps) = MARKDOWN_HEADER_RE.captures(line) {
            let level = caps[1].len();
            out.push(Symbol {
                name: strip(&caps[2]).to_string(),
                kind: if level == 1 { "title" } else { "section" }.to_string(),
                signature: prefix(strip(line), 240).to_string(),
            });
        }
    }
    out
}

fn generic_symbols(text: &str) -> Vec<Symbol> {
    GENERIC_SYMBOL_RE
        .captures_iter(text)
        .map(|caps| {
            let name = (1..=4)
                .filter_map(|i| caps.get(i))
                .map(|m| m.as_str())
                .find(|s| !s.is_empty())
                .unwrap_or("");
            // The Python regex starts with `^\s*`, so a match can begin on an earlier blank
            // line; the signature is then that (blank) line. Reproduced on purpose.
            let start = caps.get(0).unwrap().start();
            let end = text[start..].find('\n').map_or(text.len(), |i| start + i);
            Symbol {
                name: name.to_string(),
                kind: "symbol".to_string(),
                signature: prefix(strip(&text[start..end]), 240).to_string(),
            }
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn markdown_headers_become_title_and_sections() {
        let s = extract("kb/a.md", "# AWS\ntext\n## Sub  \n#nospace\n");
        assert_eq!(s.len(), 2);
        assert_eq!(
            (
                s[0].kind.as_str(),
                s[0].name.as_str(),
                s[0].signature.as_str()
            ),
            ("title", "AWS", "# AWS")
        );
        assert_eq!(
            (
                s[1].kind.as_str(),
                s[1].name.as_str(),
                s[1].signature.as_str()
            ),
            ("section", "Sub", "## Sub")
        );
    }

    #[test]
    fn markdown_without_headers_falls_back_to_generic_regex() {
        let s = extract("kb/a.md", "intro\n\nclass Foo:\n");
        assert_eq!(s.len(), 1);
        assert_eq!(s[0].name, "Foo");
        assert_eq!(s[0].kind, "symbol");
        // match began on the blank line: signature is that blank line (Python quirk)
        assert_eq!(s[0].signature, "");
    }

    #[test]
    fn generic_regex_covers_function_forms() {
        let s = extract(
            "x.tf",
            "func (r *T) Run() {}\nexport const FOO = 1\nimpl Display for Thing {}\n",
        );
        let names: Vec<_> = s.iter().map(|s| s.name.as_str()).collect();
        assert_eq!(names, vec!["Run", "FOO", "Thing"]);
        assert_eq!(s[0].signature, "func (r *T) Run() {}");
    }

    #[test]
    fn symbol_cap_scales_with_file_size() {
        let sym = |i: usize| Symbol {
            name: format!("n{i}"),
            kind: "symbol".into(),
            signature: String::new(),
        };
        let many: Vec<Symbol> = (0..500).map(sym).collect();
        assert_eq!(limit_symbols(many.clone(), "a\nb", Some(96)).len(), 96);
        let big = "x\n".repeat(1999); // 2000 lines -> cap 500
        assert_eq!(limit_symbols(many.clone(), &big, Some(96)).len(), 500);
        assert_eq!(limit_symbols(many, "a", None).len(), 500);
    }

    #[test]
    fn dedicated_lane_detection() {
        assert!(has_dedicated_strategy("a/b.GO"));
        assert!(!has_dedicated_strategy("a/b.yaml"));
        assert!(!has_dedicated_strategy("kb/a.md"));
    }
}
