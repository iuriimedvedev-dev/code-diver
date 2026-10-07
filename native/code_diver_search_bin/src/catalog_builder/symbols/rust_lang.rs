//! Catalog-facing port of `RustStrategy.extract_symbols`, not a Rust parser.

use std::sync::LazyLock;

use regex::Regex;

use super::super::pytext::{prefix, splitlines, strip};
use super::Symbol;

static RULES: LazyLock<Vec<(Regex, &str)>> = LazyLock::new(|| {
    let visibility = r"(?:pub(?:\((?:crate|super|self|in\s+[^)]+)\))?\s+)?";
    [
        (format!(r"^\s*{visibility}struct\s+(?P<name>[A-Za-z_][\w]*)"), "struct"),
        (format!(r"^\s*{visibility}enum\s+(?P<name>[A-Za-z_][\w]*)"), "enum"),
        (format!(r"^\s*{visibility}(?:unsafe\s+)?trait\s+(?P<name>[A-Za-z_][\w]*)"), "trait"),
        (r"^\s*impl(?:<[^>]+>)?\s+(?:(?P<trait>[A-Za-z_][\w:]*(?:<[^>]+>)?)\s+for\s+)?(?P<type>[A-Za-z_][\w:]*(?:<[^>]+>)?)".to_string(), "impl"),
        (format!(r#"^\s*{visibility}(?:default\s+)?(?:const\s+)?(?:async\s+)?(?:unsafe\s+)?(?:extern(?:\s+"[^"]+")?\s+)?fn\s+(?P<name>[A-Za-z_][\w]*)"#), "function"),
        (r"^\s*macro_rules!\s+(?P<name>[A-Za-z_][\w]*)".to_string(), "macro"),
        (format!(r"^\s*{visibility}macro\s+(?P<name>[A-Za-z_][\w]*)"), "macro"),
    ]
    .into_iter()
    .map(|(pattern, kind)| {
        let pattern = pattern
            .replace(r"\w", r"\p{L}\p{N}_")
            .replace(r"\s", r"[\s\x1c-\x1f]");
        (Regex::new(&pattern).unwrap(), kind)
    })
    .collect()
});

pub(super) fn extract(text: &str) -> Vec<Symbol> {
    extract_numbered(text)
        .into_iter()
        .map(|(_, symbol)| symbol)
        .collect()
}

fn extract_numbered(text: &str) -> Vec<(usize, Symbol)> {
    let mut symbols = Vec::new();
    for (index, line) in splitlines(text).into_iter().enumerate() {
        let stripped = strip(line);
        if stripped.is_empty() || ["//", "/*", "*"].iter().any(|p| stripped.starts_with(p)) {
            continue;
        }
        for (rule, kind) in RULES.iter() {
            if let Some(caps) = rule.captures(line) {
                let name = if *kind == "impl" {
                    caps.name("trait").map_or_else(
                        || caps["type"].to_string(),
                        |trait_name| format!("{} for {}", trait_name.as_str(), &caps["type"]),
                    )
                } else {
                    caps["name"].to_string()
                };
                symbols.push((
                    index + 1,
                    Symbol {
                        name,
                        kind: (*kind).to_string(),
                        signature: prefix(stripped, 240).to_string(),
                    },
                ));
                break;
            }
        }
    }
    symbols.sort_by(|a, b| (a.0, &a.1.name).cmp(&(b.0, &b.1.name)));
    symbols
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
    fn reference_derived_rust_golden() {
        let actual = extract_numbered(include_str!("../../../tests/fixtures/m2b_rust_symbols.rs"))
            .iter()
            .map(|(line, s)| format!("{line}\t{}\t{}\t{}", s.kind, s.name, s.signature))
            .collect::<Vec<_>>()
            .join("\n");
        assert_eq!(
            actual,
            include_str!("../../../tests/fixtures/m2b_rust_symbols.tsv").trim_end()
        );
    }

    #[test]
    fn restricted_visibility_is_exact_not_arbitrary_parentheses() {
        assert_eq!(
            names(
                "pub struct A;\npub(crate) enum B {}\npub(super) trait C {}\npub(self) macro D {}\npub(in crate::m) fn E() {}\npub(in\tanything !) struct F;\npub(other) struct No;\npub( crate ) struct No;\npub(crate)struct No;\npub(in ) struct No;"
            ),
            [
                ("A", "struct"),
                ("B", "enum"),
                ("C", "trait"),
                ("D", "macro"),
                ("E", "function"),
                ("F", "struct")
            ]
            .map(|(n, k)| (n.into(), k.into()))
        );
    }

    #[test]
    fn modifiers_have_fixed_order_and_extern_abi_is_nonempty() {
        assert_eq!(
            names(
                "pub default const async unsafe extern \"C\" fn All() {}\nextern fn Bare() {}\nextern \"\" fn Empty() {}\nunsafe async fn Reversed() {}\nasync const fn Reversed() {}\ndefault default fn Twice() {}\npub unsafe trait T {}\nunsafe impl T {}\nconst fn Const;\nasync fn Async\nunsafe fn Unsafe\nextern\"C\" fn Compact"
            ),
            [
                ("All", "function"),
                ("Bare", "function"),
                ("T", "trait"),
                ("Const", "function"),
                ("Async", "function"),
                ("Unsafe", "function"),
            ]
            .map(|(n, k)| (n.into(), k.into()))
        );
    }

    #[test]
    fn impls_use_shallow_generics_paths_and_optional_trait_backtracking() {
        assert_eq!(
            names(
                "impl<T> pkg::Trait<T> for pkg::Type<T> {}\nimpl Type {}\nimpl <T> Type {}\nimpl<T>Type {}\nimpl<> Type {}\nimpl Vec<Vec<T>> {}\nimpl Trait<Vec<T>> for Type {}\nimpl Trait for &Type {}\nimpl !Trait for Type {}\nimpl ::Type {}\nimpl Type<'a, T> where T: X {}"
            ),
            [
                ("pkg::Trait<T> for pkg::Type<T>", "impl"),
                ("Type", "impl"),
                ("Vec<Vec<T>", "impl"),
                ("Trait<Vec<T>", "impl"),
                ("Trait", "impl"),
                ("Type<'a, T>", "impl")
            ]
            .map(|(n, k)| (n.into(), k.into()))
        );
    }

    #[test]
    fn comments_and_attributes_are_line_prefix_only() {
        assert_eq!(
            names(
                "/* start\nfn Inside() {}\n*/\n// fn No() {}\n* fn No() {}\n#[attr] fn No() {}\n#[attr]\nfn Yes() {}\nimpl T {\n    fn Method() {}\n}\nlet s = r#\"\nfn InString() {}\n\"#;"
            ),
            [
                ("Inside", "function"),
                ("Yes", "function"),
                ("T", "impl"),
                ("Method", "function"),
                ("InString", "function")
            ]
            .map(|(n, k)| (n.into(), k.into()))
        );
    }

    #[test]
    fn names_are_prefixes_without_grammar_or_word_boundaries() {
        assert_eq!(
            names(
                "fn NoParen\nstruct Tuple(u8);\nfn r#raw() {}\nfn A$tail() {}\nmacro_rules!Rules {}\nmacro_rules! Rules {}\npub macro_rules! No {}\nmacro Plain {}\nstruct First; enum Second {}\ntype Alias = u8;\nmod Module;\nuse x;\nconst VALUE: u8 = 0;"
            ),
            [
                ("NoParen", "function"),
                ("Tuple", "struct"),
                ("r", "function"),
                ("A", "function"),
                ("Rules", "macro"),
                ("Plain", "macro"),
                ("First", "struct")
            ]
            .map(|(n, k)| (n.into(), k.into()))
        );
    }

    #[test]
    fn python_unicode_classes_strip_and_character_signature_budget() {
        let text = format!("\u{1f}fn A²界() {{ {} }}\u{1f}", "界".repeat(300));
        let symbols = extract(&text);
        assert_eq!(symbols[0].name, "A²界");
        assert_eq!(symbols[0].signature.chars().count(), 240);
        assert_eq!(symbols[0].signature, prefix(strip(&text), 240));
        assert_eq!(
            names("fn A\u{301}() {}\nfn A\u{200c}() {}\nfn Éclair() {}"),
            [
                ("A".into(), "function".into()),
                ("A".into(), "function".into())
            ]
        );
    }

    #[test]
    fn python_splitlines_bom_blank_lines_and_duplicate_source_order() {
        let symbols = extract_numbered(
            "\u{feff}fn Hidden() {}\r\n\rfn Zebra() {}\u{2028}fn Alpha() {}\u{85}fn Zebra() {}\x0bfn Vertical() {}\x0cfn Form() {}\x1cfn File() {}\x1dfn Group() {}\x1efn Record() {}\n",
        );
        assert_eq!(
            symbols
                .iter()
                .map(|(n, s)| (*n, s.name.as_str()))
                .collect::<Vec<_>>(),
            [
                (3, "Zebra"),
                (4, "Alpha"),
                (5, "Zebra"),
                (6, "Vertical"),
                (7, "Form"),
                (8, "File"),
                (9, "Group"),
                (10, "Record")
            ]
        );
        assert!(extract("").is_empty());
        assert!(extract("\n\n").is_empty());
    }
}
