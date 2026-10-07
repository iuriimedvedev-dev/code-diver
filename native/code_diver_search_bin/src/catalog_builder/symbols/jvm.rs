//! Catalog-facing JVM regexes and declaration evidence from the Python builders.
use std::sync::LazyLock;

use regex::Regex;

use super::super::pytext::{self, prefix, rstrip, splitlines, strip};
use super::super::summary::SummaryConfig;
use super::Symbol;

fn python_regex(pattern: &str) -> Regex {
    Regex::new(
        &pattern
            .replace(r"\w", r"\p{L}\p{N}_")
            .replace(r"\s", r"[\s\x1c-\x1f]"),
    )
    .unwrap()
}

static RULES: LazyLock<Vec<(Regex, &str)>> = LazyLock::new(|| {
    [
        (r"^\s*(?:(?:public|private|protected|internal|open|final|abstract|sealed|data|value|inner|static|non-sealed)\s+)*(?P<kind>class|interface|enum\s+class|enum|object|record|annotation\s+class|@interface)\s+(?P<name>[A-Za-z_][\w$]*)", "type"),
        (r"^\s*(?:(?:public|private|protected|internal|open|final|abstract|override|suspend|inline|tailrec|operator|infix|external)\s+)*fun(?:\s*<[^>]+>)?\s+(?:(?:[A-Za-z_][\w$]*\.)+)?(?P<name>[A-Za-z_][\w$]*)\s*\(", "function"),
        (r"^\s*(?:(?:public|private|protected)\s+)+(?P<name>[A-Za-z_][\w$]*)\s*\([^;)]*\)\s*(?:throws\s+[^{]+)?\{", "constructor"),
        (r"^\s*(?:(?:public|private|protected|static|final|abstract|synchronized|native|strictfp|default)\s+)*(?:<[^>]+>\s*)?(?:[A-Za-z_][\w$<>\[\].?,]*\s+)+(?P<name>[A-Za-z_][\w$]*)\s*\(", "method"),
    ].into_iter().map(|(p, k)| (python_regex(p), k)).collect()
});

const CONTROL_WORDS: &[&str] = &[
    "if", "for", "while", "switch", "catch", "when", "return", "throw", "new",
];

static LEGACY_RULES: LazyLock<Vec<(Regex, &str)>> = LazyLock::new(|| {
    RULES
        .iter()
        .filter(|(_, kind)| *kind != "constructor")
        .map(|(rule, kind)| {
            (
                Regex::new(
                    &rule
                        .as_str()
                        .replace("|non-sealed", "")
                        .replace("|@interface", ""),
                )
                .unwrap(),
                *kind,
            )
        })
        .collect()
});

fn numbered(text: &str, legacy: bool) -> Vec<(usize, Symbol)> {
    let mut symbols = Vec::new();
    for (index, line) in splitlines(text).into_iter().enumerate() {
        let stripped = strip(line);
        if stripped.is_empty() || ["//", "/*", "*"].iter().any(|p| stripped.starts_with(p)) {
            continue;
        }
        let rules = if legacy { &*LEGACY_RULES } else { &*RULES };
        for (rule, kind) in rules {
            if let Some(caps) = rule.captures(line) {
                let name = &caps["name"];
                if *kind != "type"
                    && (CONTROL_WORDS.contains(&name) || (!legacy && name == "synchronized"))
                {
                    break;
                }
                let kind = if *kind == "type" {
                    match caps["kind"]
                        .split_whitespace()
                        .collect::<Vec<_>>()
                        .join(" ")
                        .as_str()
                    {
                        "enum class" | "enum" => "enum".to_string(),
                        "annotation class" | "@interface" => "annotation".to_string(),
                        k => k.to_string(),
                    }
                } else if *kind == "constructor" {
                    "method".to_string()
                } else {
                    kind.to_string()
                };
                symbols.push((
                    index + 1,
                    Symbol {
                        name: name.into(),
                        kind,
                        signature: prefix(stripped, 240).into(),
                    },
                ));
                break;
            }
        }
    }
    symbols
}

pub(crate) fn is_jvm(path: &str) -> bool {
    [".java", ".kt", ".kts"].contains(&super::suffix_lower(path).as_str())
}

/// Empty results must still use the caller's generic fallback.
pub(crate) fn extract(text: &str) -> Vec<Symbol> {
    let mut symbols = numbered(text, false);
    if symbols.is_empty() {
        symbols = numbered(text, true);
    }
    symbols.into_iter().map(|(_, s)| s).collect()
}

static DECLARATION_RE: LazyLock<Regex> = LazyLock::new(|| {
    python_regex(
        r"^\s*(?:(?:public|private|protected|internal|open|final|abstract|sealed|data|value|inner|static)\s+)*(?P<kind>class|interface|object)\s+(?P<name>[A-Za-z_][\w$]*)(?P<tail>[^\{\n]*)",
    )
});
static PACKAGE_RE: LazyLock<Regex> = LazyLock::new(|| python_regex(r"^\s*package\s+([\w.]+)"));
static DOC_START_RE: LazyLock<Regex> = LazyLock::new(|| python_regex(r"^\s*/\*\*?"));
static DOC_END_RE: LazyLock<Regex> = LazyLock::new(|| python_regex(r"\*/\s*$"));
static DOC_CLEAN_RE: LazyLock<Vec<Regex>> = LazyLock::new(|| {
    [r"^\s*/\*\*?\s?", r"^\s*\*\s?", r"\s*\*/\s*$"]
        .into_iter()
        .map(python_regex)
        .collect()
});
static SUPER_RE: LazyLock<Regex> =
    LazyLock::new(|| python_regex(r"(?::|(?:^|[^\w])extends\s+|(?:^|[^\w])implements\s+)(.+)$"));
static CLAUSE_RE: LazyLock<Regex> = LazyLock::new(|| python_regex(r"\b(?:extends|implements)\b"));

#[derive(Debug, PartialEq)]
pub(crate) struct Declaration {
    pub kind: String,
    pub name: String,
    pub tail: String,
    pub line: usize,
}

pub(crate) fn primary_declaration(text: &str) -> Option<Declaration> {
    splitlines(text)
        .into_iter()
        .enumerate()
        .find_map(|(i, line)| {
            DECLARATION_RE.captures(line).map(|c| Declaration {
                kind: c["kind"].into(),
                name: c["name"].into(),
                tail: strip(&c["tail"]).into(),
                line: i + 1,
            })
        })
}

pub(crate) fn preceding_doc_sentence(text: &str, line: usize) -> Option<String> {
    let lines = splitlines(text);
    let mut end = line.checked_sub(2)?;
    while strip(lines.get(end)?).is_empty() {
        end = end.checked_sub(1)?;
    }
    if !DOC_END_RE.is_match(lines[end]) {
        return None;
    }
    let mut start = end;
    while !DOC_START_RE.is_match(lines[start]) {
        start = start.checked_sub(1)?;
    }
    let doc = lines[start..=end]
        .iter()
        .map(|line| {
            let mut cleaned = line.to_string();
            for re in DOC_CLEAN_RE.iter() {
                cleaned = re.replace(&cleaned, "").into_owned();
            }
            strip(&cleaned).to_string()
        })
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>()
        .join(" ");
    let mut previous = ' ';
    for (i, c) in doc.char_indices() {
        if pytext::is_py_space(c) && matches!(previous, '.' | '!' | '?') {
            return Some(doc[..i].into());
        }
        previous = c;
    }
    if doc.is_empty() { None } else { Some(doc) }
}

pub(crate) fn supertypes(tail: &str) -> Vec<String> {
    let mut depth = 0usize;
    let kept: String = tail
        .chars()
        .filter(|c| match c {
            '(' => {
                depth += 1;
                false
            }
            ')' => {
                depth = depth.saturating_sub(1);
                false
            }
            _ => depth == 0,
        })
        .collect();
    let Some(caps) = SUPER_RE.captures(&kept) else {
        return Vec::new();
    };
    CLAUSE_RE
        .split(&caps[1])
        .flat_map(|clause| clause.split(','))
        .filter(|item| !strip(item).is_empty())
        .map(|item| {
            strip(
                strip(item)
                    .split('<')
                    .next()
                    .unwrap()
                    .split('(')
                    .next()
                    .unwrap(),
            )
            .to_string()
        })
        .collect()
}

pub(crate) fn declaration_role(name: &str) -> String {
    let base = name.strip_suffix("Impl").unwrap_or(name);
    for (suffix, role) in [
        ("Service", "service"),
        ("Controller", "controller"),
        ("Manager", "manager"),
        ("Repository", "repository"),
        ("Factory", "factory"),
        ("Action", "action"),
        ("Handler", "handler"),
        ("Provider", "provider"),
    ] {
        if base.ends_with(suffix) {
            return format!(
                "{role}{}",
                if base != name { " implementation" } else { "" }
            );
        }
    }
    if base != name {
        "implementation".into()
    } else {
        "type".into()
    }
}

fn first_line_package(text: &str) -> Option<String> {
    PACKAGE_RE
        .captures(splitlines(text).first()?)
        .map(|c| c[1].into())
}

/// Returns None outside the JVM lane, allowing the existing path-purpose helper.
pub(crate) fn purpose_section(path: &str, text: &str, cfg: &SummaryConfig) -> Option<String> {
    if !is_jvm(path) {
        return None;
    }
    let d = primary_declaration(text)?;
    let purpose = preceding_doc_sentence(text, d.line).unwrap_or_else(|| {
        let mut value = format!("{} {}", declaration_role(&d.name), d.name);
        let supers = supertypes(&d.tail);
        if !supers.is_empty() {
            value += &format!(" for {}", supers.join(", "));
        }
        let parts = pytext::parts(path);
        let domain = first_line_package(text)
            .map(|p| p.rsplit('.').next().unwrap().to_string())
            .or_else(|| parts.len().checked_sub(2).map(|i| parts[i].to_string()));
        if let Some(domain) = domain {
            value += &format!(" in {domain}");
        }
        value
    });
    let limit = cfg.max_head_line_chars.min(220);
    let purpose = if purpose.chars().count() <= limit {
        purpose
    } else {
        let content = rstrip(prefix(&purpose, limit.saturating_sub(15)));
        let head = content
            .rsplit_once(' ')
            .map_or(content, |(h, _)| if h.is_empty() { content } else { h });
        format!("{head} ...[truncated]")
    };
    Some(format!("purpose: {purpose}"))
}

/// Feed these ordered values into summary.rs's existing dedup/stopword/budget loop.
pub(crate) fn term_values(
    path: &str,
    text: &str,
    symbols: &[Symbol],
    cfg: &SummaryConfig,
) -> Vec<String> {
    let declaration = if is_jvm(path) {
        primary_declaration(text)
    } else {
        None
    };
    let package = first_line_package(text);
    let mut values = Vec::new();
    if !cfg.compact_budget {
        values.push(pytext::stem(path).into());
        values.extend(pytext::parts(path).into_iter().map(String::from));
    }
    if let Some(d) = declaration {
        values.extend([d.name.clone(), declaration_role(&d.name)]);
        values.extend(supertypes(&d.tail));
        if !cfg.compact_budget
            && let Some(p) = &package
        {
            values.push(p.clone());
        }
    }
    if cfg.compact_budget {
        values.push(pytext::stem(path).into());
    }
    for s in symbols.iter().take(80) {
        values.extend([s.name.clone(), s.signature.clone()]);
    }
    if cfg.compact_budget {
        if let Some(p) = &package {
            values.push(p.rsplit('.').next().unwrap().into());
        }
        if !cfg.term_stopwords.unwrap_or(cfg.compact_budget) {
            values.extend(pytext::parts(path).into_iter().map(String::from));
            if let Some(p) = package {
                values.push(p);
            }
        }
    }
    values
}

#[cfg(test)]
mod tests {
    use super::super::super::summary::identifier_split;
    use super::*;

    #[test]
    fn reference_derived_goldens() {
        for (source, golden) in [
            (
                include_str!("../../../tests/fixtures/m2c_jvm.java"),
                include_str!("../../../tests/fixtures/m2c_jvm_java.tsv"),
            ),
            (
                include_str!("../../../tests/fixtures/m2c_jvm.kt"),
                include_str!("../../../tests/fixtures/m2c_jvm_kotlin.tsv"),
            ),
        ] {
            let actual = numbered(source, false)
                .iter()
                .map(|(line, s)| format!("{line}\t{}\t{}\t{}", s.kind, s.name, s.signature))
                .collect::<Vec<_>>()
                .join("\n");
            assert_eq!(actual, golden.trim_end());
        }
    }

    #[test]
    fn routing_is_not_scala() {
        for path in ["a.JAVA", "a.Kt", "a.kts"] {
            assert!(is_jvm(path));
        }
        for path in ["a.scala", "a.sc", "a.groovy", "a.clj"] {
            assert!(!is_jvm(path));
        }
    }

    #[test]
    fn legacy_fallback_only_when_strategy_empty() {
        assert_eq!(extract("fun synchronized() {}")[0].name, "synchronized");
        assert_eq!(extract("class C {}\nfun synchronized() {}").len(), 1);
        assert!(extract("fun if() {}\nvoid return() {}").is_empty());
    }

    #[test]
    fn shallow_comments_modifiers_and_constructor_quirks() {
        let s = extract(
            "/* start\nclass Phantom {}\n*/\n@Deprecated class Hidden {}\npublic C() {}\nC() {}\npublic C();\nfun String.ext() {}\nfun List<T>.hidden() {}\ncompanion object Hidden {}\nnon-sealed class Visible {}",
        );
        assert_eq!(
            s.iter().map(|s| s.name.as_str()).collect::<Vec<_>>(),
            ["Phantom", "C", "C", "ext", "Visible"]
        );
    }

    #[test]
    fn python_unicode_lines_and_signature_budget() {
        let source = format!(
            "\u{feff}class Hidden {{}}\r\nclass A²$ {{}}\u{2028}\u{1f}fun Z() {{ {} }}",
            "界".repeat(300)
        );
        let s = numbered(&source, false);
        assert_eq!((s[0].0, s[0].1.name.as_str()), (2, "A²$"));
        assert_eq!(s[1].1.signature.chars().count(), 240);
        assert_eq!(extract("class A\u{301}tail {}")[0].name, "A");
    }

    #[test]
    fn purpose_docs_roles_domain_and_caps() {
        let cfg = SummaryConfig::default();
        assert_eq!(
            purpose_section(
                "src/tools/X.java",
                "package com.work;\npublic class WorkerServiceImpl extends Base implements API {}",
                &cfg
            )
            .unwrap(),
            "purpose: service implementation WorkerServiceImpl for Base, API in work"
        );
        assert_eq!(
            purpose_section(
                "src/tools/X.kt",
                "// license\npackage com.work\nclass Worker {}",
                &cfg
            )
            .unwrap(),
            "purpose: type Worker in tools"
        );
        assert_eq!(
            purpose_section(
                "X.kt",
                "/** First sentence! Second one. */\n\nclass X {}",
                &cfg
            )
            .unwrap(),
            "purpose: First sentence!"
        );
        assert!(preceding_doc_sentence("/** Doc. */\n@Anno\nclass X {}", 3).is_none());
        assert!(primary_declaration("record R() {}\nenum E {}\nnon-sealed class X {}").is_none());
        let tiny = SummaryConfig {
            max_head_line_chars: 5,
            ..Default::default()
        };
        assert_eq!(
            purpose_section("X.kt", "class Worker {}", &tiny).unwrap(),
            "purpose:  ...[truncated]"
        );
    }

    #[test]
    fn supertypes_preserve_shallow_generic_comma_quirks() {
        assert_eq!(
            supertypes("(x: Int) : Base(call()), Map<A, B>, API"),
            ["Base", "Map", "B>", "API"]
        );
        assert_eq!(
            supertypes(" extends Base implements API, Other"),
            ["Base", "API", "Other"]
        );
        assert_eq!(declaration_role("OtherImpl"), "implementation");
    }

    #[test]
    fn terms_order_and_stopword_override_inputs() {
        let text = "package com.example.work\nclass WorkerServiceImpl : Base {}";
        let cfg = SummaryConfig {
            compact_budget: true,
            ..Default::default()
        };
        assert_eq!(
            term_values("src/X.kt", text, &[], &cfg),
            [
                "WorkerServiceImpl",
                "service implementation",
                "Base",
                "X",
                "work"
            ]
        );
        let cfg = SummaryConfig {
            term_stopwords: Some(false),
            ..cfg
        };
        assert_eq!(
            term_values("src/X.kt", text, &[], &cfg),
            [
                "WorkerServiceImpl",
                "service implementation",
                "Base",
                "X",
                "work",
                "src",
                "X.kt",
                "com.example.work"
            ]
        );
        let values = term_values("src/X.kt", text, &[], &SummaryConfig::default());
        assert_eq!(
            values,
            [
                "X",
                "src",
                "X.kt",
                "WorkerServiceImpl",
                "service implementation",
                "Base",
                "com.example.work"
            ]
        );
        assert_eq!(identifier_split(&values[3]), ["Worker", "Service", "Impl"]);
    }
}
