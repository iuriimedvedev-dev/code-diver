#![allow(dead_code)]

#[path = "../src/catalog_builder/manifest.rs"]
pub mod manifest;
#[path = "../src/catalog_builder/pytext.rs"]
pub mod pytext;
#[path = "../src/catalog_builder/summary.rs"]
pub mod summary;
#[path = "../src/catalog_builder/symbols/mod.rs"]
pub mod symbols;
mod catalog_builder {
    pub use crate::{pytext, symbols};
}
#[path = "../src/inspection.rs"]
mod inspection;

use std::fs;
use std::path::Path;

use serde_json::{Value, json};
use tempfile::TempDir;

fn write(root: &Path, path: &str, text: impl AsRef<[u8]>) {
    let path = root.join(path);
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::write(path, text).unwrap();
}

fn text(root: &Path, tool: &str, args: Value) -> String {
    let result = inspection::call(root, tool, &args).unwrap();
    assert_eq!(result["isError"], false);
    assert_eq!(result["content"].as_array().unwrap().len(), 1);
    assert_eq!(result["content"][0]["type"], "text");
    result["content"][0]["text"].as_str().unwrap().into()
}

fn rows(root: &Path, tool: &str, args: Value) -> Vec<Value> {
    serde_json::from_str(&text(root, tool, args)).unwrap()
}

#[test]
fn inspection_read_numbering_defaults_and_line_boundaries() {
    let root = TempDir::new().unwrap();
    write(root.path(), "a.txt", "alpha\r\nbeta\rgamma\u{2028}delta\n");
    assert_eq!(
        text(
            root.path(),
            "code_diver_read",
            json!({"file": "a.txt", "start_line": 2, "lines": 2})
        ),
        "a.txt:2-3\n    2 | beta\n    3 | gamma"
    );
    write(root.path(), "many.txt", "x\n".repeat(500));
    let output = text(root.path(), "code_diver_read", json!({"file": "many.txt"}));
    assert_eq!(output.lines().count(), 101);
    let output = text(
        root.path(),
        "code_diver_read",
        json!({"file": "many.txt", "lines": u64::MAX}),
    );
    assert_eq!(output.lines().count(), 401);
    assert!(output.starts_with("many.txt:1-400"));
    assert_eq!(
        text(
            root.path(),
            "code_diver_read",
            json!({"file": "many.txt", "start_line": u64::MAX})
        ),
        format!("many.txt:{}-500", u64::MAX)
    );
    write(root.path(), "empty.txt", "");
    assert_eq!(
        text(root.path(), "code_diver_read", json!({"file": "empty.txt"})),
        "empty.txt:1-0"
    );
}

#[test]
fn inspection_read_caps_unicode_output_and_refuses_invalid_files() {
    let root = TempDir::new().unwrap();
    write(root.path(), "wide.txt", "界".repeat(50_000));
    let output = text(root.path(), "code_diver_read", json!({"file": "wide.txt"}));
    assert_eq!(output.chars().count(), inspection::MAX_OUTPUT_CHARS);
    assert!(output.ends_with("[output truncated]"));
    for (path, bytes, message) in [
        ("binary", vec![b'a', 0, b'b'], "Binary"),
        ("invalid", vec![0xff], "Non-UTF-8"),
        (
            "large",
            vec![b'a'; inspection::MAX_FILE_BYTES as usize + 1],
            "max file size",
        ),
    ] {
        write(root.path(), path, bytes);
        let error =
            inspection::call(root.path(), "code_diver_read", &json!({"file": path})).unwrap_err();
        assert!(error.to_string().contains(message), "{error:#}");
    }
    assert!(inspection::call(root.path(), "code_diver_read", &json!({"file": "."})).is_err());
}

#[test]
fn inspection_all_tools_reject_hostile_paths_and_invalid_types() {
    let root = TempDir::new().unwrap();
    write(root.path(), "a.txt", "needle");
    for tool in [
        "code_diver_read",
        "code_diver_grep",
        "code_diver_tree",
        "code_diver_symbols",
    ] {
        let key = if tool == "code_diver_read" {
            "file"
        } else {
            "path"
        };
        for path in [
            "../outside".to_owned(),
            "nested/../a.txt".into(),
            root.path().join("a.txt").display().to_string(),
        ] {
            let mut args = json!({"pattern": "needle"});
            if tool != "code_diver_grep" {
                args.as_object_mut().unwrap().remove("pattern");
            }
            args[key] = json!(path);
            let error = inspection::call(root.path(), tool, &args).unwrap_err();
            assert!(error.to_string().contains("escapes"), "{tool}: {error:#}");
        }
        for value in [
            json!(null),
            json!(false),
            json!(42),
            json!([]),
            json!({}),
            json!(""),
        ] {
            let mut args = if tool == "code_diver_grep" {
                json!({"pattern": "needle"})
            } else {
                json!({})
            };
            args[key] = value;
            assert!(
                inspection::call(root.path(), tool, &args).is_err(),
                "{tool}: {args}"
            );
        }
        assert!(inspection::call(root.path(), tool, &json!([])).is_err());
        assert!(inspection::call(root.path(), tool, &json!({"bogus": true})).is_err());
    }
    for (tool, field, base) in [
        ("code_diver_read", "lines", json!({"file": "a.txt"})),
        ("code_diver_read", "start_line", json!({"file": "a.txt"})),
        ("code_diver_grep", "limit", json!({"pattern": "needle"})),
        ("code_diver_tree", "limit", json!({})),
        ("code_diver_tree", "depth", json!({})),
        ("code_diver_symbols", "limit", json!({})),
    ] {
        for value in [
            json!(null),
            json!(false),
            json!("1"),
            json!(0),
            json!(-1),
            json!(1.5),
        ] {
            let mut args = base.clone();
            args[field] = value;
            assert!(
                inspection::call(root.path(), tool, &args).is_err(),
                "{tool}: {args}"
            );
        }
    }
    for value in [json!(null), json!("false"), json!(0)] {
        assert!(
            inspection::call(
                root.path(),
                "code_diver_grep",
                &json!({"pattern": "a", "regex": value})
            )
            .is_err()
        );
    }
    for args in [
        json!({}),
        json!({"pattern": " "}),
        json!({"pattern": false}),
        json!({"pattern": "[", "regex": true}),
    ] {
        assert!(inspection::call(root.path(), "code_diver_grep", &args).is_err());
    }
    assert!(inspection::call(root.path(), "not_a_tool", &json!({})).is_err());
}

#[cfg(unix)]
#[test]
fn inspection_symlink_escape_and_traversal_are_blocked() {
    use std::os::unix::fs::symlink;
    let root = TempDir::new().unwrap();
    let outside = TempDir::new().unwrap();
    write(root.path(), "kept.rs", "fn needle() {}\n");
    write(outside.path(), "secret.rs", "fn secret() {}\n");
    symlink(outside.path(), root.path().join("escape")).unwrap();
    symlink(
        outside.path().join("secret.rs"),
        root.path().join("leak.rs"),
    )
    .unwrap();
    symlink(root.path(), root.path().join("loop")).unwrap();
    symlink(root.path().join("kept.rs"), root.path().join("alias.rs")).unwrap();
    for tool in [
        "code_diver_read",
        "code_diver_grep",
        "code_diver_tree",
        "code_diver_symbols",
    ] {
        for path in ["escape/secret.rs", "leak.rs"] {
            let args = match tool {
                "code_diver_read" => json!({"file": path}),
                "code_diver_grep" => json!({"path": path, "pattern": "secret"}),
                _ => json!({"path": path}),
            };
            assert!(
                inspection::call(root.path(), tool, &args)
                    .unwrap_err()
                    .to_string()
                    .contains("escapes")
            );
        }
    }
    assert!(
        text(root.path(), "code_diver_read", json!({"file": "alias.rs"}))
            .starts_with("kept.rs:1-1")
    );
    assert_eq!(
        rows(root.path(), "code_diver_grep", json!({"pattern": "secret"})),
        Vec::<Value>::new()
    );
    let output = text(root.path(), "code_diver_tree", json!({}));
    assert!(!output.contains("escape"));
    assert!(!output.contains("loop"));
    assert!(!output.contains("leak"));
    let output = rows(root.path(), "code_diver_symbols", json!({}));
    assert_eq!(output.len(), 1);
    assert_eq!(output[0]["name"], "needle");
}

#[test]
fn inspection_grep_literal_regex_limits_and_ignores() {
    let root = TempDir::new().unwrap();
    write(root.path(), ".gitignore", "ignored/\n*.log\n");
    write(root.path(), ".ignore", "ignore_file.rs\n");
    write(root.path(), ".rgignore", "rg_file.rs\n");
    write(root.path(), "ignored/secret.rs", "needle\n");
    write(root.path(), "debug.log", "needle\n");
    write(root.path(), "ignore_file.rs", "needle\n");
    write(root.path(), "rg_file.rs", "needle\n");
    write(root.path(), ".code-diver/catalog", "needle\n");
    write(root.path(), "src/.gitignore", "nested.rs\n");
    write(root.path(), "src/nested.rs", "needle\n");
    write(root.path(), "a.rs", "needle.*\nneedle123\n");
    write(root.path(), "b.rs", "needle\n");
    write(root.path(), "binary.rs", b"needle\0");
    write(root.path(), "nonutf.rs", b"needle\xff");
    write(root.path(), ".hidden.rs", "needle\n");
    assert_eq!(
        rows(
            root.path(),
            "code_diver_grep",
            json!({"pattern": "needle", "path": ".hidden.rs"})
        )
        .len(),
        1
    );
    let matches = rows(root.path(), "code_diver_grep", json!({"pattern": "needle"}));
    assert_eq!(matches.len(), 3);
    assert_eq!(
        matches[0],
        json!({"path": "a.rs", "line": 1, "text": "needle.*"})
    );
    assert_eq!(
        rows(
            root.path(),
            "code_diver_grep",
            json!({"pattern": "needle.*"})
        )
        .len(),
        1
    );
    assert_eq!(
        rows(
            root.path(),
            "code_diver_grep",
            json!({"pattern": "needle[0-9]+", "regex": true})
        )[0]["line"],
        2
    );
    assert_eq!(
        rows(
            root.path(),
            "code_diver_grep",
            json!({"pattern": "needle", "limit": 1})
        )
        .len(),
        1
    );
    assert_eq!(
        rows(
            root.path(),
            "code_diver_grep",
            json!({"pattern": "needle", "path": "b.rs"})
        )
        .len(),
        1
    );
    assert!(
        inspection::call(
            root.path(),
            "code_diver_read",
            &json!({"file": "ignored/secret.rs"})
        )
        .unwrap_err()
        .to_string()
        .contains("ignored")
    );
    write(root.path(), "wide.rs", "needle界".repeat(1_000));
    let matches = rows(
        root.path(),
        "code_diver_grep",
        json!({"pattern": "needle", "path": "wide.rs"}),
    );
    let line = matches[0]["text"].as_str().unwrap();
    assert_eq!(line.chars().count(), inspection::MAX_GREP_LINE_CHARS);
    assert!(line.ends_with("..."));
    write(root.path(), "defaults.rs", "needle\n".repeat(1_200));
    assert_eq!(
        rows(
            root.path(),
            "code_diver_grep",
            json!({"pattern": "needle", "path": "defaults.rs"})
        )
        .len(),
        50
    );
    assert_eq!(
        rows(
            root.path(),
            "code_diver_grep",
            json!({"pattern": "needle", "path": "defaults.rs", "limit": u64::MAX})
        )
        .len(),
        inspection::MAX_RESULTS as usize
    );
}

#[test]
fn inspection_tree_python_layout_order_depth_and_limits() {
    let root = TempDir::new().unwrap();
    write(root.path(), "a.txt", "");
    write(root.path(), "Zdir/nested/deep.txt", "");
    write(root.path(), "Zdir/b.txt", "");
    write(root.path(), ".gitignore", "ignored/\n");
    write(root.path(), "ignored/secret", "");
    assert_eq!(
        text(root.path(), "code_diver_tree", json!({"path": "Zdir"})),
        "Zdir\n  nested/\n    deep.txt\n  b.txt"
    );
    assert_eq!(
        text(
            root.path(),
            "code_diver_tree",
            json!({"path": "Zdir", "depth": 1})
        ),
        "Zdir\n  nested/\n  b.txt"
    );
    assert_eq!(
        text(
            root.path(),
            "code_diver_tree",
            json!({"path": "Zdir", "limit": 1})
        ),
        "Zdir\n  nested/\n..."
    );
    let output = text(root.path(), "code_diver_tree", json!({}));
    assert!(output.starts_with(".\n  Zdir/"));
    assert!(!output.contains("ignored"));
    assert_eq!(
        text(root.path(), "code_diver_tree", json!({"path": "a.txt"})),
        "a.txt"
    );
}

#[test]
fn inspection_symbols_reuses_all_indexer_lanes_and_limits() {
    let root = TempDir::new().unwrap();
    for (path, source) in [
        ("a.rs", "pub fn alpha() {}\n"),
        ("b.py", "class Worker:\n    def run(self):\n        pass\n"),
        ("c.go", "package main\nfunc Run() {}\n"),
        ("d.ts", "export function work() {}\n"),
        ("e.java", "public class Worker {}\n"),
        ("f.cpp", "class Worker {};\n"),
        ("g.md", "# Heading\n"),
    ] {
        write(root.path(), path, source);
        let actual = rows(root.path(), "code_diver_symbols", json!({"path": path}));
        let expected: Vec<Value> = catalog_builder::symbols::extract(path, source).into_iter().enumerate().map(|(i, symbol)| {
            let (start, end) = match path {
                "b.py" => if i == 0 { (1, 3) } else { (2, 3) },
                "c.go" => (2, 2),
                _ => (1, 1),
            };
            json!({"path": path, "name": symbol.name, "kind": symbol.kind, "signature": symbol.signature, "startLine": start, "endLine": end, "confidence": 0.7})
        }).collect();
        assert_eq!(actual, expected, "{path}");
        assert!(!actual.is_empty(), "{path}");
    }
    write(root.path(), ".gitignore", "ignored.rs\n");
    write(root.path(), "ignored.rs", "fn hidden() {}\n");
    let all = rows(root.path(), "code_diver_symbols", json!({}));
    assert!(!all.iter().any(|row| row["path"] == "ignored.rs"));
    assert_eq!(
        rows(root.path(), "code_diver_symbols", json!({"limit": 1})).len(),
        1
    );
    write(
        root.path(),
        "many.rs",
        (0..1_200)
            .map(|index| format!("fn task{index}() {{}}\n"))
            .collect::<String>(),
    );
    assert_eq!(
        rows(
            root.path(),
            "code_diver_symbols",
            json!({"path": "many.rs"})
        )
        .len(),
        100
    );
    assert_eq!(
        rows(
            root.path(),
            "code_diver_symbols",
            json!({"path": "many.rs", "limit": u64::MAX})
        )
        .len(),
        inspection::MAX_RESULTS as usize
    );
}
