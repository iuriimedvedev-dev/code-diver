use super::{
    Symbol, cpp, generic, go, is_cpp, is_jvm, is_ts_js, jvm, python, rust_lang, suffix_lower, ts_js,
};
use crate::catalog_builder::pytext::{splitlines, strip};

const BLOCK_SCAN_LINES: usize = 500;
const DECLARATION_LOOKAHEAD: usize = 5;
const FALLBACK_SPAN: usize = 50;
const GENERIC_SPAN: usize = 160;

pub struct RangedSymbol {
    pub symbol: Symbol,
    pub start_line: usize,
    pub end_line: usize,
}

pub fn extract_ranges(path: &str, text: &str) -> Vec<RangedSymbol> {
    let suffix = suffix_lower(path);
    let lines = splitlines(text);
    let mut located = match suffix.as_str() {
        ".go" => go::extract_numbered(text),
        ".rs" => rust_lang::extract_numbered(text),
        ".py" | ".pyi" => python::located(text).unwrap_or_default(),
        _ if is_ts_js(path) => ts_js::located_symbols(text)
            .into_iter()
            .map(|s| (s.line, s.symbol))
            .collect(),
        _ if is_jvm(path) => {
            let symbols = jvm::numbered(text, false);
            if symbols.is_empty() {
                jvm::numbered(text, true)
            } else {
                symbols
            }
        }
        _ if is_cpp(path) => cpp::extract_numbered(text),
        _ => Vec::new(),
    };
    if located.is_empty() {
        let symbols = generic::extract(path, text);
        if symbols
            .first()
            .is_some_and(|s| s.kind == "title" || s.kind == "section")
        {
            let starts: Vec<_> = lines
                .iter()
                .enumerate()
                .filter_map(|(i, line)| {
                    let hashes = line.chars().take_while(|c| *c == '#').count();
                    (hashes > 0
                        && hashes <= 6
                        && line.chars().nth(hashes).is_some_and(char::is_whitespace))
                    .then_some(i + 1)
                })
                .collect();
            return symbols
                .into_iter()
                .zip(starts.iter().copied())
                .enumerate()
                .map(|(i, (symbol, start_line))| RangedSymbol {
                    symbol,
                    start_line,
                    end_line: starts
                        .get(i + 1)
                        .map_or(lines.len(), |n| n - 1)
                        .max(start_line),
                })
                .collect();
        }
        let starts: Vec<_> = generic::GENERIC_SYMBOL_RE
            .find_iter(text)
            .map(|m| text[..m.start()].bytes().filter(|b| *b == b'\n').count() + 1)
            .collect();
        return symbols
            .into_iter()
            .zip(starts.iter().copied())
            .enumerate()
            .map(|(i, (symbol, start_line))| RangedSymbol {
                symbol,
                start_line,
                end_line: starts
                    .get(i + 1)
                    .copied()
                    .unwrap_or_else(|| text.bytes().filter(|b| *b == b'\n').count() + 1)
                    .min(start_line + GENERIC_SPAN)
                    .max(start_line),
            })
            .collect();
    }
    located
        .drain(..)
        .map(|(start_line, symbol)| {
            let end_line = if [".py", ".pyi"].contains(&suffix.as_str()) {
                python_end(&lines, start_line)
            } else {
                declaration_end(&lines, start_line, suffix != ".go")
            };
            RangedSymbol {
                symbol,
                start_line,
                end_line,
            }
        })
        .collect()
}

fn declaration_end(lines: &[&str], start: usize, semicolon: bool) -> usize {
    if lines[start - 1].contains('{') {
        return block_end(lines, start);
    }
    for (index, line) in lines
        .iter()
        .enumerate()
        .skip(start - 1)
        .take(DECLARATION_LOOKAHEAD)
    {
        if line.contains('{') {
            return block_end(lines, index + 1);
        }
        if semicolon && line.contains(';') {
            return index + 1;
        }
    }
    lines.len().min(start + FALLBACK_SPAN)
}

// Mirrors the reference find_block_end, including its bounded, lexical scan.
fn block_end(lines: &[&str], start: usize) -> usize {
    let (mut depth, mut opened, mut single, mut double, mut comment) =
        (0i32, false, false, false, false);
    for (index, line) in lines
        .iter()
        .enumerate()
        .skip(start - 1)
        .take(BLOCK_SCAN_LINES)
    {
        let chars: Vec<_> = line.chars().collect();
        let mut col = 0;
        while col < chars.len() {
            let c = chars[col];
            if comment {
                if c == '*' && chars.get(col + 1) == Some(&'/') {
                    comment = false;
                    col += 2;
                } else {
                    col += 1;
                }
                continue;
            }
            if !single && !double && c == '/' {
                if chars.get(col + 1) == Some(&'/') {
                    break;
                }
                if chars.get(col + 1) == Some(&'*') {
                    comment = true;
                    col += 2;
                    continue;
                }
            }
            let escaped = col > 0 && chars[col - 1] == '\\' && !(col > 1 && chars[col - 2] == '\\');
            if c == '"' && !single && !escaped {
                double = !double;
            } else if c == '\'' && !double && !escaped {
                single = !single;
            }
            if !single && !double {
                if c == '{' {
                    depth += 1;
                    opened = true;
                } else if c == '}' && opened {
                    depth -= 1;
                    if depth <= 0 {
                        return index + 1;
                    }
                }
            }
            col += 1;
        }
    }
    lines.len().min(start)
}

fn python_end(lines: &[&str], start: usize) -> usize {
    let indent = lines[start - 1].len() - lines[start - 1].trim_start().len();
    let mut end = start;
    let mut definition = false;
    for (index, line) in lines.iter().enumerate().skip(start - 1) {
        let trimmed = strip(line);
        if trimmed.is_empty() || trimmed.starts_with('#') {
            continue;
        }
        let current_indent = line.len() - line.trim_start().len();
        if definition && current_indent <= indent {
            break;
        }
        end = index + 1;
        if !trimmed.starts_with('@') {
            definition = true;
        }
    }
    end
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn ranges_use_source_locations_and_ignore_comment_and_string_braces() {
        let text =
            "// intro\npub fn first() {\n let s = \"}\"; // }\n /* } */\n}\npub fn second();\n";
        let symbols = extract_ranges("a.rs", text);
        assert_eq!(
            symbols
                .iter()
                .map(|s| (s.start_line, s.end_line))
                .collect::<Vec<_>>(),
            [(2, 5), (6, 6)]
        );
        let symbols = extract_ranges(
            "a.py",
            "@decorator\nclass A:\n    def method(self):\n        pass\n\n# end\n",
        );
        assert_eq!(
            symbols
                .iter()
                .map(|s| (s.start_line, s.end_line))
                .collect::<Vec<_>>(),
            [(1, 4), (3, 4)]
        );
    }
}
