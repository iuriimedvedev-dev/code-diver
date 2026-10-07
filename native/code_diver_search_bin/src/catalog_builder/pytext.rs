//! Helpers that reproduce the Python string semantics the Python indexer relies on.
//!
//! Byte-compatible catalog content depends on these details: `str.splitlines()` line
//! boundaries, `str.strip()` whitespace set, `len()`/slicing in code points, and
//! `fnmatch` glob translation (where `*` also matches `/`).

use regex::Regex;

/// Python `str.isspace()` for one char (Unicode White_Space plus U+001C..U+001F).
pub fn is_py_space(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

/// Python `str.strip()`.
pub fn strip(s: &str) -> &str {
    s.trim_matches(is_py_space)
}

/// Python `str.rstrip()`.
pub fn rstrip(s: &str) -> &str {
    s.trim_end_matches(is_py_space)
}

fn is_line_break(c: char) -> bool {
    matches!(
        c,
        '\n' | '\r'
            | '\u{0b}'
            | '\u{0c}'
            | '\u{1c}'
            | '\u{1d}'
            | '\u{1e}'
            | '\u{85}'
            | '\u{2028}'
            | '\u{2029}'
    )
}

/// Python `str.splitlines()` (no `keepends`).
pub fn splitlines(s: &str) -> Vec<&str> {
    let mut out = Vec::new();
    let mut start = 0;
    let mut iter = s.char_indices().peekable();
    while let Some((i, c)) = iter.next() {
        if is_line_break(c) {
            out.push(&s[start..i]);
            let mut end = i + c.len_utf8();
            if c == '\r'
                && let Some(&(j, '\n')) = iter.peek()
            {
                iter.next();
                end = j + 1;
            }
            start = end;
        }
    }
    if start < s.len() {
        out.push(&s[start..]);
    }
    out
}

/// Number of code points (Python `len(str)`).
pub fn char_len(s: &str) -> usize {
    s.chars().count()
}

/// Python `s[:n]` (code points).
pub fn prefix(s: &str, n: usize) -> &str {
    match s.char_indices().nth(n) {
        Some((i, _)) => &s[..i],
        None => s,
    }
}

/// Python `" ".join(s.split())`.
pub fn normalize_ws(s: &str) -> String {
    s.split(is_py_space)
        .filter(|p| !p.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
}

/// Last component of a posix path.
pub fn file_name(rel_path: &str) -> &str {
    rel_path.rsplit('/').next().unwrap_or(rel_path)
}

/// Python `PurePath.suffix` (not lowercased).
pub fn suffix(rel_path: &str) -> &str {
    let name = file_name(rel_path);
    match name.rfind('.') {
        Some(i) if i > 0 && i < name.len() - 1 => &name[i..],
        _ => "",
    }
}

/// Python `PurePath.stem`.
pub fn stem(rel_path: &str) -> &str {
    let name = file_name(rel_path);
    &name[..name.len() - suffix(rel_path).len()]
}

/// Python `PurePath.parts` for a relative posix path.
pub fn parts(rel_path: &str) -> Vec<&str> {
    rel_path
        .split('/')
        .filter(|p| !p.is_empty() && *p != ".")
        .collect()
}

/// Python `fnmatch.translate` equivalent compiled into an anchored regex.
pub fn fnmatch_regex(pattern: &str) -> Option<Regex> {
    let p: Vec<char> = pattern.chars().collect();
    let n = p.len();
    let mut i = 0;
    let mut res = String::from("(?s)\\A");
    while i < n {
        let c = p[i];
        i += 1;
        match c {
            '*' => res.push_str(".*"),
            '?' => res.push('.'),
            '[' => {
                let mut j = i;
                if j < n && p[j] == '!' {
                    j += 1;
                }
                if j < n && p[j] == ']' {
                    j += 1;
                }
                while j < n && p[j] != ']' {
                    j += 1;
                }
                if j >= n {
                    res.push_str("\\[");
                } else {
                    let stuff: String = p[i..j].iter().collect();
                    i = j + 1;
                    let mut stuff = stuff.replace('\\', "\\\\");
                    for special in ['[', '&', '~', '|'] {
                        stuff = stuff.replace(special, &format!("\\{special}"));
                    }
                    res.push('[');
                    if let Some(rest) = stuff.strip_prefix('!') {
                        res.push('^');
                        res.push_str(rest);
                    } else if stuff.starts_with('^') {
                        res.push('\\');
                        res.push_str(&stuff);
                    } else {
                        res.push_str(&stuff);
                    }
                    res.push(']');
                }
            }
            other => res.push_str(&regex::escape(&other.to_string())),
        }
    }
    res.push_str("\\z");
    Regex::new(&res).ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn splitlines_matches_python() {
        assert_eq!(splitlines(""), Vec::<&str>::new());
        assert_eq!(splitlines("a\n\nb\n"), vec!["a", "", "b"]);
        assert_eq!(splitlines("a\r\nb\rc"), vec!["a", "b", "c"]);
        assert_eq!(
            splitlines("a\u{2028}b\u{0c}c\u{85}d"),
            vec!["a", "b", "c", "d"]
        );
        assert_eq!(splitlines("\n"), vec![""]);
    }

    #[test]
    fn strip_uses_python_whitespace() {
        assert_eq!(strip("\u{1c} x \u{a0}"), "x");
        assert_eq!(rstrip("ab \t"), "ab");
    }

    #[test]
    fn prefix_counts_code_points() {
        assert_eq!(prefix("héllo", 2), "hé");
        assert_eq!(prefix("ab", 5), "ab");
        assert_eq!(char_len("héllo"), 5);
    }

    #[test]
    fn path_parts_follow_pathlib() {
        assert_eq!(suffix("a/b.tar.gz"), ".gz");
        assert_eq!(suffix("a/.gitignore"), "");
        assert_eq!(suffix("a/foo."), "");
        assert_eq!(stem("a/b.tar.gz"), "b.tar");
        assert_eq!(stem("a/Makefile"), "Makefile");
        assert_eq!(parts("a/b/c.md"), vec!["a", "b", "c.md"]);
    }

    #[test]
    fn fnmatch_star_crosses_slash() {
        let re = fnmatch_regex("repos/**").unwrap();
        assert!(re.is_match("repos/a/b/c.go"));
        assert!(!re.is_match("kb/a.md"));
        let re = fnmatch_regex("*.min.js").unwrap();
        assert!(re.is_match("a/b/x.min.js"));
        let re = fnmatch_regex("venv*").unwrap();
        assert!(re.is_match("venv3"));
        let re = fnmatch_regex("[!a]b?").unwrap();
        assert!(re.is_match("xbc"));
        assert!(!re.is_match("abc"));
    }
}
