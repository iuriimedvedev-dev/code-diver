//! Dependency-free Python symbol lane. Logical statements, not physical lines,
//! determine suites; only an immediate class suite qualifies a symbol's name.
use super::super::pytext::{prefix, splitlines, strip};
use super::Symbol;

#[derive(Debug)]
struct Statement {
    line: usize,
    indent: usize,
    tokens: Vec<String>,
}

// Strings and comments are consumed before looking for declarations or suites.
// Keeping quoted tokens intact also prevents decorator punctuation in strings
// from being interpreted as call syntax.
fn statements(text: &str) -> Option<Vec<Statement>> {
    let text = text.replace("\r\n", "\n").replace('\r', "\n");
    let chars: Vec<char> = text.chars().collect();
    let mut out = Vec::new();
    let (mut i, mut line, mut start, mut indent) = (0, 1, 1, 0);
    let mut beginning = true;
    let mut tokens = Vec::new();
    let mut brackets = Vec::new();
    while i < chars.len() {
        let c = chars[i];
        if c == '\0' || c == '\u{feff}' {
            return None;
        }
        if beginning && brackets.is_empty() && tokens.is_empty() {
            indent = 0;
            start = line;
            while i < chars.len() && matches!(chars[i], ' ' | '\t' | '\x0c') {
                indent = match chars[i] {
                    '\t' => (indent / 8 + 1) * 8,
                    '\x0c' => 0,
                    _ => indent + 1,
                };
                i += 1;
            }
            beginning = false;
            continue;
        }
        if c == '#' {
            while i < chars.len() && chars[i] != '\n' {
                i += 1;
            }
            continue;
        }
        if c == '\\' {
            if chars.get(i + 1) != Some(&'\n') {
                return None;
            }
            i += 2;
            line += 1;
            continue;
        }
        if c == '\n' {
            if brackets.is_empty() && !tokens.is_empty() {
                out.push(Statement {
                    line: start,
                    indent,
                    tokens: std::mem::take(&mut tokens),
                });
            }
            i += 1;
            line += 1;
            beginning = true;
            continue;
        }
        if c.is_whitespace() {
            if !matches!(c, ' ' | '\t' | '\x0c') {
                return None;
            }
            i += 1;
            continue;
        }
        let begin = i;
        // Recognize Python string prefixes without treating ordinary names as strings.
        let mut quote_at = i;
        while quote_at < chars.len()
            && matches!(
                chars[quote_at],
                'r' | 'R' | 'b' | 'B' | 'u' | 'U' | 'f' | 'F'
            )
            && quote_at - i < 2
        {
            quote_at += 1;
        }
        if matches!(chars.get(quote_at), Some('\'' | '"')) {
            let quote = chars[quote_at];
            let triple =
                chars.get(quote_at + 1) == Some(&quote) && chars.get(quote_at + 2) == Some(&quote);
            let width = if triple { 3 } else { 1 };
            i = quote_at + width;
            let mut closed = false;
            while i < chars.len() {
                if chars[i] == '\\' {
                    if chars.get(i + 1) == Some(&'\n') {
                        line += 1;
                    }
                    i += 2;
                    continue;
                }
                if chars[i] == quote
                    && (!triple
                        || (chars.get(i + 1) == Some(&quote) && chars.get(i + 2) == Some(&quote)))
                {
                    i += width;
                    closed = true;
                    break;
                }
                if chars[i] == '\n' {
                    if !triple {
                        return None;
                    }
                    line += 1;
                }
                i += 1;
            }
            if !closed {
                return None;
            }
        } else if c.is_alphabetic() || c == '_' || c.is_ascii_digit() {
            i += 1;
            while i < chars.len()
                && (chars[i].is_alphanumeric()
                    || chars[i] == '_'
                    || ('\u{300}'..='\u{36f}').contains(&chars[i]))
            {
                i += 1;
            }
        } else {
            if "([{".contains(c) {
                brackets.push(c);
            }
            if ")]}".contains(c) {
                let expected = match c {
                    ')' => '(',
                    ']' => '[',
                    _ => '{',
                };
                if brackets.pop() != Some(expected) {
                    return None;
                }
            }
            i += 1;
            if i < chars.len()
                && ["**", "//", "==", "!=", "<=", ">=", ":=", "->", "<<", ">>"]
                    .contains(&chars[begin..=i].iter().collect::<String>().as_str())
            {
                i += 1;
            }
        }
        tokens.push(chars[begin..i.min(chars.len())].iter().collect());
    }
    if !brackets.is_empty() {
        return None;
    }
    if !tokens.is_empty() {
        out.push(Statement {
            line: start,
            indent,
            tokens,
        });
    }
    Some(out)
}

fn quoted(token: &str) -> String {
    // ast.unparse chooses single quotes unless the value contains a single quote.
    // Preserve escape semantics; unsupported literal families stay verbatim.
    if token.starts_with('"') && token.ends_with('"') && !token.starts_with("\"\"\"") {
        let inner = &token[1..token.len() - 1];
        if !inner.contains('\'') && !inner.contains('\\') {
            return format!("'{inner}'");
        }
    }
    token.to_string()
}

fn unparse(tokens: &[String]) -> String {
    let mut out = String::new();
    let mut stack: Vec<bool> = Vec::new();
    for (i, token) in tokens.iter().enumerate() {
        let prev = i.checked_sub(1).map(|j| tokens[j].as_str()).unwrap_or("");
        let next = tokens.get(i + 1).map(String::as_str).unwrap_or("");
        let t = token.as_str();
        let keyword_arg = t == "=" && stack.last() == Some(&true);
        let previous_keyword_arg = prev == "=" && stack.last() == Some(&true);
        let no_space = out.is_empty()
            || [".", ",", ")", "]", "}", ":"].contains(&t)
            || [".", "(", "[", "{"].contains(&prev)
            || keyword_arg
            || previous_keyword_arg
            || (t == "("
                && (prev
                    .chars()
                    .last()
                    .is_some_and(|c| c.is_alphanumeric() || c == '_')
                    || [")", "]"].contains(&prev)))
            || (t == "["
                && (prev
                    .chars()
                    .last()
                    .is_some_and(|c| c.is_alphanumeric() || c == '_')
                    || [")", "]"].contains(&prev)))
            || (["*", "**", "~"].contains(&prev) && ![",", ")"].contains(&t));
        if !no_space {
            out.push(' ');
        }
        out.push_str(&quoted(token));
        if ["(", "[", "{"].contains(&t) {
            stack.push(
                t == "("
                    && !prev.is_empty()
                    && (prev
                        .chars()
                        .last()
                        .is_some_and(|c| c.is_alphanumeric() || c == '_')
                        || [")", "]"].contains(&prev)),
            );
        } else if [")", "]", "}"].contains(&t) {
            stack.pop();
        }
        if t == "," && [")", "]", "}"].contains(&next) {
            // Calls/lists/dicts lose trailing commas; singleton tuples retain them.
            if stack.last() == Some(&true) || next != ")" {
                out.pop();
            }
        }
    }
    out
}

struct Suite {
    indent: usize,
    class: Option<String>,
}

fn located(text: &str) -> Option<Vec<(usize, Symbol)>> {
    let statements = statements(text)?;
    let lines = splitlines(text);
    let mut symbols = Vec::new();
    let mut suites = vec![Suite {
        indent: 0,
        class: None,
    }];
    let mut pending_suite: Option<Option<String>> = None;
    let mut decorators: Vec<(usize, usize, String)> = Vec::new();
    for statement in statements {
        let current = suites.last()?.indent;
        if statement.indent > current {
            let class = pending_suite.take()?;
            suites.push(Suite {
                indent: statement.indent,
                class,
            });
        } else {
            if pending_suite.take().is_some() {
                return None;
            }
            while suites.last()?.indent > statement.indent {
                suites.pop();
            }
            if suites.last()?.indent != statement.indent {
                return None;
            }
        }
        let t = &statement.tokens;
        if t.first()?.as_str() == "@" {
            if t.len() < 2 {
                return None;
            }
            decorators.push((
                statement.line,
                statement.indent,
                format!("@{}", unparse(&t[1..])),
            ));
            continue;
        }
        let offset = usize::from(t[0] == "async");
        let declaration = t.get(offset).is_some_and(|s| s == "def" || s == "class");
        let mut depth = 0;
        let colon = t.iter().position(|s| {
            match s.as_str() {
                "(" | "[" | "{" => depth += 1,
                ")" | "]" | "}" => depth -= 1,
                _ => {}
            }
            s == ":" && depth == 0
        });
        let head = t.get(offset)?.as_str();
        let compound = declaration
            || [
                "if", "elif", "else", "for", "while", "try", "except", "finally", "with",
            ]
            .contains(&head)
            || (["match", "case"].contains(&head) && colon.is_some());
        if compound && colon.is_none() {
            return None;
        }
        let mut class = None;
        if declaration {
            let name = t.get(offset + 1)?;
            if !name
                .chars()
                .next()
                .is_some_and(|c| c.is_alphabetic() || c == '_')
                || !name.chars().all(|c| {
                    c.is_alphanumeric() || c == '_' || ('\u{300}'..='\u{36f}').contains(&c)
                })
            {
                return None;
            }
            if head == "def" && t.get(offset + 2).map(String::as_str) != Some("(") {
                return None;
            }
            if head == "class"
                && !matches!(t.get(offset + 2).map(String::as_str), Some("(" | "[" | ":"))
            {
                return None;
            }
            if head == "class" {
                class = Some(name.clone());
            }
            if decorators.iter().any(|d| d.1 != statement.indent) {
                return None;
            }
            let parent = suites.last()?.class.as_ref();
            let qualified = parent.map_or_else(|| name.clone(), |p| format!("{p}.{name}"));
            let kind = if head == "class" {
                "class"
            } else if parent.is_some() {
                "method"
            } else {
                "function"
            };
            let start = decorators.first().map_or(statement.line, |d| d.0);
            let definition = strip(lines.get(statement.line - 1).copied().unwrap_or(name));
            let signature = if decorators.is_empty() {
                definition.to_string()
            } else {
                format!(
                    "{} {definition}",
                    decorators
                        .iter()
                        .map(|d| d.2.as_str())
                        .collect::<Vec<_>>()
                        .join(" ")
                )
            };
            symbols.push((
                start,
                Symbol {
                    name: qualified,
                    kind: kind.into(),
                    signature: prefix(&signature, 240).into(),
                },
            ));
            decorators.clear();
        } else if !decorators.is_empty() {
            return None;
        }
        if compound && colon == Some(t.len() - 1) {
            pending_suite = Some(class);
        }
        // Common malformed expressions must invalidate the entire lane, not retain
        // earlier declarations. Full expression grammar remains intentionally out of scope.
        if t.last()
            .is_some_and(|s| ["=", "+", "-", "*", "/", "->"].contains(&s.as_str()))
        {
            return None;
        }
    }
    if pending_suite.is_some() || !decorators.is_empty() {
        return None;
    }
    symbols.sort_by(|a, b| (a.0, &a.1.name).cmp(&(b.0, &b.1.name)));
    Some(symbols)
}

pub(super) fn extract(text: &str) -> Vec<Symbol> {
    located(text)
        .unwrap_or_default()
        .into_iter()
        .map(|(_, s)| s)
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reference_derived_golden() {
        let actual = located(include_str!(
            "../../../tests/fixtures/m2b_python_symbols.py"
        ))
        .unwrap()
        .iter()
        .map(|(line, s)| format!("{line}\t{}\t{}\t{}", s.kind, s.name, s.signature))
        .collect::<Vec<_>>()
        .join("\n");
        assert_eq!(
            actual,
            include_str!("../../../tests/fixtures/m2b_python_symbols.tsv").trim_end()
        );
    }

    #[test]
    fn immediate_parent_only() {
        let symbols = extract(
            "class Outer:\n    class Inner:\n        async def method(self):\n            def nested(): pass\n    if True:\n        def conditional(): pass\n",
        );
        assert_eq!(
            symbols
                .iter()
                .map(|s| (s.name.as_str(), s.kind.as_str()))
                .collect::<Vec<_>>(),
            [
                ("Outer", "class"),
                ("Outer.Inner", "class"),
                ("Inner.method", "method"),
                ("nested", "function"),
                ("conditional", "function")
            ]
        );
    }

    #[test]
    fn malformed_is_empty() {
        for tail in [
            "def bad(: pass",
            "def bad()",
            "def bad():\npass",
            "def bad():",
            "x = (",
            "x =",
            "@orphan",
            "'unterminated",
            "  pass",
            "x = ]",
        ] {
            assert!(
                extract(&format!("def valid(): pass\n{tail}\n")).is_empty(),
                "{tail}"
            );
        }
    }

    #[test]
    fn decorator_calls_strings_and_order() {
        let symbols = located("@outer( x , mode = \"a,b:#\" )\n@inner\ndef f(): pass\n").unwrap();
        assert_eq!(symbols[0].0, 1);
        assert_eq!(
            symbols[0].1.signature,
            "@outer(x, mode='a,b:#') @inner def f(): pass"
        );
        assert_eq!(
            unparse(&statements("deco([1, 2,], key={'x': 3,})").unwrap()[0].tokens),
            "deco([1, 2], key={'x': 3})"
        );
    }

    #[test]
    fn multiline_decorators_and_definitions() {
        let symbols = extract("@decorate(\n    \"value\",\n)\ndef f(\n    x: int,\n):\n    pass\n");
        assert_eq!(symbols[0].signature, "@decorate('value') def f(");
    }

    #[test]
    fn strings_comments_are_not_symbols() {
        assert!(
            extract(
                "\"\"\"\ndef phantom(): pass\n\"\"\"\n# class Fake: pass\nx = 'def fake(): pass'\n"
            )
            .is_empty()
        );
        let symbols = extract("def real():\n    \"\"\"class Fake: pass\"\"\"\n    pass\n");
        assert_eq!(symbols.len(), 1);
    }

    #[test]
    fn continuations_soft_keywords_and_control_suites() {
        let symbols = extract(
            "match = 1\ncase = 2\nclass C:\n    with context():\n        @deco(\"x\")\n        def f(): pass\n    def g(\\\n        self): pass\n",
        );
        assert_eq!(
            symbols.iter().map(|s| s.name.as_str()).collect::<Vec<_>>(),
            ["C", "f", "C.g"]
        );
        assert_eq!(symbols[1].signature, "@deco('x') def f(): pass");
    }

    #[test]
    fn line_endings_bom_tabs_and_unicode_budget() {
        assert_eq!(extract("class C:\r\n\tdef m(self): ...\r\n")[1].name, "C.m");
        assert!(extract("\u{feff}def f(): pass").is_empty());
        let source = format!("def café(): pass # {}", "界".repeat(300));
        assert_eq!(extract(&source)[0].signature.chars().count(), 240);
    }
}
