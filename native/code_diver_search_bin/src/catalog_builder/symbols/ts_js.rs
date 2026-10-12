//! Catalog-facing port of the shallow `TsJsStrategy.extract_symbols` regexes.

use std::sync::LazyLock;

use regex::Regex;

use super::super::pytext::{prefix, splitlines, strip};
use super::Symbol;

static RULES: LazyLock<Vec<(Regex, &str)>> = LazyLock::new(|| {
    [
        (r"^\s*(?:export\s+(?:default\s+)?)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)", "class"),
        (r"^\s*(?:export\s+)?interface\s+([A-Za-z_$][\w$]*)", "interface"),
        (r"^\s*(?:export\s+)?type\s+([A-Za-z_$][\w$]*)\s*(?:<[^>]+>)?\s*=", "type"),
        (r"^\s*(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*(?::\s*[^=]+)?=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>", "function"),
        (r"^\s*(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*(?::\s*[^=]+)?=\s*(?:async\s*)?function(?:$|[^\w])", "function"),
        (r"^\s*(?:export\s+(?:default\s+)?)?(?:async\s+)?function(?:\s*\*\s*|\s+)([A-Za-z_$][\w$]*)\s*(?:<[^>]+>)?\s*\(", "function"),
        (r"^\s*export\s+(?:const|let|var)\s+([A-Za-z_$][\w$]*)", "symbol"),
    ]
    .into_iter()
    .map(|(pattern, kind)| {
        // Python \w is Unicode alphanumeric plus underscore, not Rust's marks/joiners.
        let pattern = pattern
            .replace(r"\w", r"\p{L}\p{N}_")
            .replace(r"\s", r"[\s\x1c-\x1f]");
        (Regex::new(&pattern).unwrap(), kind)
    })
    .collect()
});

pub(super) struct LocatedSymbol {
    pub(super) line: usize,
    pub(super) symbol: Symbol,
}

pub(super) fn located_symbols(text: &str) -> Vec<LocatedSymbol> {
    let mut symbols = Vec::new();
    for (index, line) in splitlines(text).into_iter().enumerate() {
        let stripped = strip(line);
        if stripped.is_empty() || ["//", "/*", "*"].iter().any(|p| stripped.starts_with(p)) {
            continue;
        }
        for (rule, kind) in RULES.iter() {
            if let Some(captures) = rule.captures(line) {
                symbols.push(LocatedSymbol {
                    line: index + 1,
                    symbol: Symbol {
                        name: captures[1].to_string(),
                        kind: (*kind).to_string(),
                        signature: prefix(stripped, 240).to_string(),
                    },
                });
                break;
            }
        }
    }
    symbols.sort_by(|a, b| (a.line, &a.symbol.name).cmp(&(b.line, &b.symbol.name)));
    symbols
}

pub(super) fn extract(text: &str) -> Vec<Symbol> {
    located_symbols(text)
        .into_iter()
        .map(|s| s.symbol)
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn names(text: &str) -> Vec<(String, String)> {
        extract(text)
            .into_iter()
            .map(|s| (s.name, s.kind))
            .collect()
    }

    #[test]
    fn synthetic_golden() {
        let text = include_str!("../../../tests/fixtures/ts_js_shallow.tsx");
        let actual = located_symbols(text)
            .into_iter()
            .map(|s| {
                format!(
                    "{}\t{}\t{}\t{}",
                    s.line, s.symbol.kind, s.symbol.name, s.symbol.signature
                )
            })
            .collect::<Vec<_>>()
            .join("\n");
        assert_eq!(
            actual,
            include_str!("../../../tests/fixtures/ts_js_shallow.expected.tsv")
        );
    }

    #[test]
    fn arrow_and_expression_priority_and_shallow_limits() {
        assert_eq!(
            names(
                "export const a = async x => x\nexport const b = function*() {}\nexport const c = (x): number => x\nexport const d = <T>(x:T) => x\nlet e = x => x\nconst f = (x = call()) => x\nconst g = asyncfunction() {}\nconst h = function$odd() {}"
            ),
            [
                ("a", "function"),
                ("b", "function"),
                ("c", "symbol"),
                ("d", "symbol"),
                ("g", "function"),
                ("h", "function")
            ]
            .map(|(n, k)| (n.into(), k.into()))
        );
    }

    #[test]
    fn declarations_modifiers_and_first_match_only() {
        assert_eq!(
            names(
                "export default abstract class A {}\nexport interface B {}\nexport type C<T> = T\nexport default async function * D<T>() {}\nclass Z {} class A {}\nexport default interface Nope {}\nexport abstract interface Nope {}\nexport type Missing<T extends X<Y>> = T\nfunction() {}\nexport enum Nope {}"
            ),
            [
                ("A", "class"),
                ("B", "interface"),
                ("C", "type"),
                ("D", "function"),
                ("Z", "class")
            ]
            .map(|(n, k)| (n.into(), k.into()))
        );
    }

    #[test]
    fn comments_are_line_prefix_only_and_nested_symbols_are_kept() {
        let symbols = located_symbols(
            "// class No {}\n/* class No {} */\n* class No {}\n/*\n class InsideComment {}\n*/\n  function Nested() {} // keep\n",
        );
        assert_eq!(
            symbols
                .iter()
                .map(|s| (s.line, s.symbol.name.as_str()))
                .collect::<Vec<_>>(),
            [(5, "InsideComment"), (7, "Nested")]
        );
        assert_eq!(symbols[1].symbol.signature, "function Nested() {} // keep");
    }

    #[test]
    fn unicode_names_match_python_not_rust_word_classes() {
        assert_eq!(
            names(
                "class Aé²漢 {}\nclass A\u{301}tail {}\nclass $foo$ {}\nclass éFirst {}\nconst expr = function\u{301}() {}\nconst no = functioné() {}"
            ),
            [
                ("Aé²漢", "class"),
                ("A", "class"),
                ("$foo$", "class"),
                ("expr", "function")
            ]
            .map(|(n, k)| (n.into(), k.into()))
        );
    }

    #[test]
    fn signatures_cap_unicode_code_points_not_bytes() {
        let text = format!("  export const long = '{}';  ", "界".repeat(300));
        let symbols = extract(&text);
        assert_eq!(
            symbols[0].signature,
            strip(&text).chars().take(240).collect::<String>()
        );
        assert_eq!(symbols[0].signature.chars().count(), 240);
    }

    #[test]
    fn python_splitlines_whitespace_bom_and_source_order() {
        let symbols = located_symbols(
            "\u{feff}class BOM {}\r\nclass Z {}\rclass A {}\u{85}class B {}\u{2028}\u{1f}class C {}\u{2029}class D {}\u{b}class E {}\u{c}class F {}\u{1c}class G {}\u{1d}class H {}\u{1e}class I {}\n",
        );
        assert_eq!(
            symbols
                .iter()
                .map(|s| (s.line, s.symbol.name.as_str()))
                .collect::<Vec<_>>(),
            [
                (2, "Z"),
                (3, "A"),
                (4, "B"),
                (5, "C"),
                (6, "D"),
                (7, "E"),
                (8, "F"),
                (9, "G"),
                (10, "H"),
                (11, "I")
            ]
        );
        assert_eq!(symbols[3].symbol.signature, "class C {}");
    }
}
