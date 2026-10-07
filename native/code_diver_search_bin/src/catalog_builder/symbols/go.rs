use std::sync::LazyLock;

use regex::Regex;

use super::super::pytext::{prefix, splitlines, strip};
use super::Symbol;

fn python_regex(pattern: &str) -> Regex {
    Regex::new(
        &pattern
            .replace(r"\w", r"[\p{L}\p{N}_]")
            .replace(r"\s", r"[\s\x1c-\x1f]"),
    )
    .unwrap()
}

static TYPE_RE: LazyLock<Regex> = LazyLock::new(|| {
    python_regex(r"^\s*type\s+(?P<name>[A-Za-z_]\w*)(?:\[[^\]]+\])?\s+(?P<kind>struct|interface)")
});
static BLOCK_TYPE_RE: LazyLock<Regex> = LazyLock::new(|| {
    python_regex(r"^\s*(?P<name>[A-Za-z_]\w*)(?:\[[^\]]+\])?\s+(?P<kind>struct|interface)")
});
static ALIAS_RE: LazyLock<Regex> = LazyLock::new(|| {
    python_regex(r"^\s*type\s+(?P<name>[A-Za-z_]\w*)(?:\[[^\]]+\])?\s+(?P<alias>[^\s{]+)")
});
static METHOD_RE: LazyLock<Regex> = LazyLock::new(|| {
    python_regex(
        r"^\s*func\s*\(\s*(?:(?P<recv_var>\w+)\s+)?(?:\*)?(?P<recv_type>[A-Za-z_]\w*)\s*\)\s*(?P<name>[A-Za-z_]\w*)\s*(?:\[[^\]]+\])?\s*\(",
    )
});
static FN_RE: LazyLock<Regex> =
    LazyLock::new(|| python_regex(r"^\s*func\s+(?P<name>[A-Za-z_]\w*)\s*(?:\[[^\]]+\])?\s*\("));

fn type_symbol(re: &Regex, line: &str) -> Option<(String, String)> {
    let caps = re.captures(line)?;
    let kind = caps.name("kind")?;
    // Python's word boundary excludes combining marks, unlike regex's Unicode \b.
    if line[kind.end()..]
        .chars()
        .next()
        .is_some_and(|c| c.is_alphanumeric() || c == '_')
    {
        return None;
    }
    Some((caps["name"].to_string(), kind.as_str().to_string()))
}

pub(super) fn extract(text: &str) -> Vec<Symbol> {
    extract_numbered(text)
        .into_iter()
        .map(|(_, symbol)| symbol)
        .collect()
}

fn extract_numbered(text: &str) -> Vec<(usize, Symbol)> {
    let mut symbols = Vec::new();
    let mut in_type_block = false;
    for (index, line) in splitlines(text).into_iter().enumerate() {
        let stripped = strip(line);
        if stripped.is_empty() || ["//", "/*", "*"].iter().any(|p| stripped.starts_with(p)) {
            continue;
        }
        if stripped.starts_with("type (") {
            in_type_block = true;
            continue;
        }
        if in_type_block && stripped == ")" {
            in_type_block = false;
            continue;
        }
        let matched = if in_type_block {
            type_symbol(&BLOCK_TYPE_RE, line)
        } else {
            None
        }
        .or_else(|| {
            METHOD_RE.captures(line).map(|caps| {
                (
                    format!("{}.{}", &caps["recv_type"], &caps["name"]),
                    "method".to_string(),
                )
            })
        })
        .or_else(|| {
            FN_RE
                .captures(line)
                .map(|caps| (caps["name"].to_string(), "function".to_string()))
        })
        .or_else(|| type_symbol(&TYPE_RE, line))
        .or_else(|| {
            ALIAS_RE
                .captures(line)
                .map(|caps| (caps["name"].to_string(), "type".to_string()))
        });
        if let Some((name, kind)) = matched {
            symbols.push((
                index + 1,
                Symbol {
                    name,
                    kind,
                    signature: prefix(stripped, 240).to_string(),
                },
            ));
        }
    }
    symbols.sort_by(|a, b| (a.0, &a.1.name).cmp(&(b.0, &b.1.name)));
    symbols
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reference_derived_go_golden() {
        let source = include_str!("../../../tests/fixtures/m2a_go_symbols.go");
        let expected = include_str!("../../../tests/fixtures/m2a_go_symbols.tsv");
        let actual = extract_numbered(source)
            .iter()
            .map(|(line, s)| format!("{line}\t{}\t{}\t{}", s.kind, s.name, s.signature))
            .collect::<Vec<_>>()
            .join("\n");
        assert_eq!(actual, expected.trim_end());
        assert_eq!(extract(source).len(), 10);
    }

    #[test]
    fn python_unicode_classes_and_signature_budget() {
        let text = format!("\u{1f}func A²() {{ {} }}\u{1f}", "界".repeat(300));
        let symbols = extract(&text);
        assert_eq!(symbols[0].name, "A²");
        assert_eq!(symbols[0].signature.chars().count(), 240);
        assert_eq!(symbols[0].signature, prefix(strip(&text), 240));
        assert!(extract("func A\u{301}() {}\nfunc A\u{200c}() {}").is_empty());
        assert_eq!(extract("type T struct\u{301} {}")[0].kind, "struct");
        assert_eq!(extract("type T struct² {}")[0].kind, "type");
        assert!(extract("func Éclair() {}").is_empty());
    }

    #[test]
    fn splitlines_bom_and_source_order() {
        let symbols = extract_numbered(
            "\u{feff}func Hidden() {}\r\n\rfunc Zebra() {}\u{2028}func Alpha() {}\u{85}func Zebra() {}",
        );
        assert_eq!(
            symbols
                .iter()
                .map(|(n, s)| (*n, s.name.as_str()))
                .collect::<Vec<_>>(),
            vec![(3, "Zebra"), (4, "Alpha"), (5, "Zebra")]
        );
    }

    #[test]
    fn grouped_state_only_closes_on_exact_parenthesis() {
        let symbols = extract(
            "type ( extra\nA int\nB struct {}\n) // not a close\nC interface {}\n)\nD struct {}\ntype E = int\n",
        );
        assert_eq!(
            symbols
                .iter()
                .map(|s| (s.name.as_str(), s.kind.as_str()))
                .collect::<Vec<_>>(),
            vec![("B", "struct"), ("C", "interface"), ("E", "type")]
        );
    }

    #[test]
    fn comments_are_prefix_only_and_receivers_are_not_a_parser() {
        let symbols = extract(
            "/* start\nfunc Inside() {}\n*/\n// func Ignored() {}\n* func Ignored() {}\nfunc(*T)NoSpace() {}\nfunc (T) Bare() {}\nfunc (r pkg.T) Qualified() {}\nfunc (r *T[X]) Generic() {}\nfunc (r **T) Double() {}\nfunc (变量 *T) Unicode() {}\n",
        );
        assert_eq!(
            symbols.iter().map(|s| s.name.as_str()).collect::<Vec<_>>(),
            vec!["Inside", "T.NoSpace", "T.Bare", "T.Unicode"]
        );
    }
}
