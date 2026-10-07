//! Catalog-facing port of `CppStrategy.extract_symbols`, not a C++ parser.

use std::sync::LazyLock;

use regex::Regex;

use super::super::pytext::{prefix, splitlines, strip};
use super::Symbol;

const CONTROL_WORDS: &[&str] = &[
    "if", "for", "while", "switch", "catch", "return", "sizeof", "case", "delete", "new", "throw",
];

fn python_regex(pattern: &str) -> Regex {
    Regex::new(
        &pattern
            .replace(r"\w", r"\p{L}\p{N}_")
            .replace(r"\s", r"[\s\x1c-\x1f]"),
    )
    .unwrap()
}

static TYPE_RE: LazyLock<Regex> = LazyLock::new(|| {
    python_regex(
        r"^\s*(?:template\s*<[^>]*>\s*)?(?P<kind>class|struct|enum\s+class|enum\s+struct|enum)\s+(?:[A-Za-z0-9_]+_API\s+)?(?P<name>[A-Za-z_][\w]*)",
    )
});

// The final (?=\{|$) becomes (?:\{|$): consuming the brace cannot change
// captures or success because nothing follows it and match offsets are unused.
static CTOR_RE: LazyLock<Regex> = LazyLock::new(|| {
    python_regex(
        r"^\s*(?:template\s*<[^>]*>\s*)?(?:(?:explicit|inline|constexpr)\s+)*(?:(?P<cls>[A-Za-z_][\w]*)::)?(?P<tilde>~)?(?P<name>[A-Za-z_][\w]*)\s*\([^;)]*\)\s*(?::\s*[^{]+)?(?:\{|$)",
    )
});

static MEMBER_RE: LazyLock<Regex> = LazyLock::new(|| {
    python_regex(
        r"^\s*(?:template\s*<[^>]*>\s*)?(?:(?:static|inline|virtual|constexpr|consteval|explicit|friend)\s+)*(?P<ret>[A-Za-z_][\w:<>,*&\[\]\s]*?\s+)(?P<cls>[A-Za-z_][\w]*)::(?P<name>[A-Za-z_][\w]*)\s*\([^;)]*\)(?:\s*const)?(?:\s*noexcept(?:\([^)]*\))?)?(?:\s*override)?(?:\s*final)?\s*(?:->\s*[^;{]+)?(?:\{|$)",
    )
});

static FREE_RE: LazyLock<Regex> = LazyLock::new(|| {
    python_regex(
        r#"^\s*(?:template\s*<[^>]*>\s*)?(?:(?:static|inline|virtual|constexpr|consteval|extern(?:\s+"[^"]+")?)\s+)*(?P<ret>[A-Za-z_][\w:<>,*&\[\]\s]*?\s+)(?P<name>[A-Za-z_][\w]*)\s*\([^;)]*\)(?:\s*const)?(?:\s*noexcept(?:\([^)]*\))?)?(?:\s*override)?(?:\s*final)?\s*(?:->\s*[^;{]+)?(?:\{|$)"#,
    )
});

pub(super) fn extract(text: &str) -> Vec<Symbol> {
    extract_numbered(text)
        .into_iter()
        .map(|(_, symbol)| symbol)
        .collect()
}

fn forward_decl(lines: &[&str], index: usize) -> bool {
    for line in lines.iter().skip(index).take(3) {
        if line.contains(';') && !line.contains('{') {
            return true;
        }
        if line.contains('{') {
            return false;
        }
    }
    false
}

fn has_return_type_prefix(stripped: &str, name: &str) -> bool {
    stripped.find(name).is_some_and(|index| {
        index > 0
            && split_words(strip(&stripped[..index]))
                .any(|word| !["explicit", "inline", "constexpr", "virtual"].contains(&word))
    })
}

fn split_words(value: &str) -> impl Iterator<Item = &str> {
    value
        .split(|c: char| c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c))
        .filter(|word| !word.is_empty())
}

fn extract_numbered(text: &str) -> Vec<(usize, Symbol)> {
    let lines = splitlines(text);
    let mut symbols = Vec::new();
    for (index, line) in lines.iter().enumerate() {
        let stripped = strip(line);
        if stripped.is_empty()
            || ["//", "/*", "*", "#"]
                .iter()
                .any(|p| stripped.starts_with(p))
        {
            continue;
        }
        let mut matched = None;
        if let Some(caps) = TYPE_RE.captures(line)
            && !forward_decl(&lines, index)
        {
            let raw_kind = &caps["kind"];
            let kind = if raw_kind.contains("enum") {
                "enum"
            } else if raw_kind == "struct" {
                "struct"
            } else {
                "class"
            };
            matched = Some((caps["name"].to_string(), kind));
        }
        if matched.is_none()
            && let Some(caps) = CTOR_RE.captures(line)
        {
            let name = &caps["name"];
            let cls = caps.name("cls").map(|m| m.as_str());
            let dtor = caps.name("tilde").is_some();
            let ctor = cls == Some(name)
                || (cls.is_none() && !dtor && !has_return_type_prefix(stripped, name));
            if (dtor || ctor) && !CONTROL_WORDS.contains(&name) {
                let name = format!("{}{name}", if dtor { "~" } else { "" });
                matched = Some((
                    cls.map_or_else(|| name.clone(), |cls| format!("{cls}::{name}")),
                    if dtor { "destructor" } else { "constructor" },
                ));
            }
        }
        if matched.is_none()
            && let Some(caps) = MEMBER_RE.captures(line)
            && !CONTROL_WORDS.contains(&&caps["name"])
            && !CONTROL_WORDS.contains(&&caps["cls"])
        {
            matched = Some((format!("{}::{}", &caps["cls"], &caps["name"]), "method"));
        }
        if matched.is_none()
            && let Some(caps) = FREE_RE.captures(line)
            && !CONTROL_WORDS.contains(&&caps["name"])
        {
            matched = Some((caps["name"].to_string(), "function"));
        }
        if let Some((name, kind)) = matched {
            symbols.push((
                index + 1,
                Symbol {
                    name,
                    kind: kind.to_string(),
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

    fn names(text: &str) -> Vec<(String, String)> {
        extract(text)
            .into_iter()
            .map(|s| (s.name, s.kind))
            .collect()
    }

    #[test]
    fn reference_derived_c_golden() {
        let actual = extract_numbered(include_str!("../../../tests/fixtures/m2c_c_symbols.c"))
            .iter()
            .map(|(line, s)| format!("{line}\t{}\t{}\t{}", s.kind, s.name, s.signature))
            .collect::<Vec<_>>()
            .join("\n");
        assert_eq!(
            actual,
            include_str!("../../../tests/fixtures/m2c_c_symbols.tsv").trim_end()
        );
    }

    #[test]
    fn reference_derived_cpp_golden() {
        let actual = extract_numbered(include_str!("../../../tests/fixtures/m2c_cpp_symbols.cpp"))
            .iter()
            .map(|(line, s)| format!("{line}\t{}\t{}\t{}", s.kind, s.name, s.signature))
            .collect::<Vec<_>>()
            .join("\n");
        assert_eq!(
            actual,
            include_str!("../../../tests/fixtures/m2c_cpp_symbols.tsv").trim_end()
        );
    }

    #[test]
    fn forward_declarations_scan_three_lines_with_raw_braces() {
        assert!(extract("class A;\nstruct B\n;\nenum C\n// ;").is_empty());
        assert_eq!(
            names("class A; // {\nstruct B\n\n\n;"),
            [("A", "class"), ("B", "struct")].map(|(n, k)| (n.into(), k.into()))
        );
        assert!(extract("class A\nint value;\n{").is_empty());
    }

    #[test]
    fn constructors_do_not_require_a_declared_class() {
        assert_eq!(
            names(
                "Call()\nexplicit Build() {}\nA::A() {}\nA::B() {}\nA::~Other() {}\n~Loose() {}\nif(x) {}\nvirtual Virtual() {}"
            ),
            [
                ("Call", "constructor"),
                ("Build", "constructor"),
                ("A::A", "constructor"),
                ("A::~Other", "destructor"),
                ("~Loose", "destructor"),
                ("Virtual", "function")
            ]
            .map(|(n, k)| (n.into(), k.into()))
        );
    }

    #[test]
    fn lookahead_rewrite_accepts_brace_or_end_not_prototypes() {
        assert_eq!(
            names(
                "int end()\nint body() { trailing\nint proto();\nint comment() // no\nint bad(int x = call()) {}\nint semicolon(int x;) {}\nint good() const noexcept(x) override final -> Result {}"
            ),
            [
                ("end", "function"),
                ("body", "function"),
                ("good", "function")
            ]
            .map(|(n, k)| (n.into(), k.into()))
        );
        assert_eq!(
            names("A() : value(1);\nA() : value(1) {"),
            [("A", "constructor"), ("A", "constructor")].map(|(n, k)| (n.into(), k.into()))
        );
    }

    #[test]
    fn types_are_shallow_prefixes_and_first_match_wins() {
        assert_eq!(
            names(
                "template<> struct LIB_API Box {}\nenum class Mode {}\nenum struct Flags {}\nclass First {} class Second {}\nclass A$tail {}\ntemplate<class T> class Wrap {}\nnamespace ns {\nusing Alias = int;"
            ),
            [
                ("Box", "struct"),
                ("Mode", "enum"),
                ("Flags", "enum"),
                ("First", "class"),
                ("A", "class"),
                ("Wrap", "class")
            ]
            .map(|(n, k)| (n.into(), k.into()))
        );
    }

    #[test]
    fn member_methods_and_modifiers_are_shallow() {
        assert_eq!(
            names(
                "int Worker::run() {}\nfriend int Worker::friendFn() {}\nextern \"C\" int exported() {}\nint *pointer() {}\nint* spaced() {}\nint ns:: Worker::deep() {}\nint Worker::if() {}"
            ),
            [
                ("Worker::run", "method"),
                ("Worker::friendFn", "method"),
                ("exported", "function"),
                ("spaced", "function"),
                ("Worker::deep", "method")
            ]
            .map(|(n, k)| (n.into(), k.into()))
        );
    }

    #[test]
    fn comments_and_preprocessor_are_only_line_prefix_filters() {
        assert!(extract("int ns::Worker::deep() {}").is_empty());
        assert_eq!(
            names(
                "/*\nint inside() {}\n*/\n# int no() {}\n// int no() {}\n* int no() {}\nint yes() {} // retained"
            ),
            [("inside", "function"), ("yes", "function")].map(|(n, k)| (n.into(), k.into()))
        );
    }

    #[test]
    fn python_unicode_splitlines_and_signature_budget() {
        let symbols = extract_numbered(
            "\u{feff}class Hidden {}\r\n\rclass A²界 {}\u{2028}\u{1f}int B() {}\u{85}class A\u{301}tail {}",
        );
        assert_eq!(
            symbols
                .iter()
                .map(|(line, s)| (*line, s.name.as_str()))
                .collect::<Vec<_>>(),
            [(3, "A²界"), (4, "B"), (5, "A")]
        );
        let text = format!(" int longName() {{ {} }}\u{1f}", "界".repeat(300));
        assert_eq!(extract(&text)[0].signature, prefix(strip(&text), 240));
        assert!(extract("int Éclair() {}\nint A\u{301}() {}").is_empty());
        assert!(extract("").is_empty());
    }

    #[test]
    fn cpp_summary_uses_generic_import_purpose_and_terms_contract() {
        let text = "#include <vector>\nnamespace tools {\nint runTask() {}";
        let symbols = extract(text);
        let cfg = super::super::super::summary::SummaryConfig {
            compact_budget: true,
            ..Default::default()
        };
        let summary = super::super::super::summary::build_file_summary(
            "src/taskRunner.cpp",
            text,
            &symbols,
            &cfg,
        );
        assert!(summary.starts_with("purpose: task runner\nterms: task runner run int\n"));
        assert!(summary.ends_with("imports: none"));
        let manifest = super::super::super::manifest::build_file_manifest(
            "src/taskRunner.cpp",
            text,
            &symbols,
            false,
        );
        assert!(manifest.contains("package: none"));
        assert!(manifest.contains("imports: none"));
    }
}
