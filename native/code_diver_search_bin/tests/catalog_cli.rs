use std::process::Command;

fn records(path: &std::path::Path) -> Vec<serde_json::Value> {
    std::fs::read_to_string(path)
        .unwrap()
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect()
}

#[test]
fn m2a_reference_derived_templates_and_lane_filters() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().join("root");
    std::fs::create_dir(&root).unwrap();
    let go = "package workers\nimport \"fmt\"\ntype Worker struct {}\nfunc (w *Worker) Run() {}\n";
    let ts = "import { dep } from 'pkg';\nexport class Worker {}\n";
    std::fs::write(root.join("worker.go"), go).unwrap();
    for suffix in ["ts", "tsx", "js", "jsx", "mjs", "cjs", "mts", "cts"] {
        std::fs::write(root.join(format!("worker.{suffix}")), ts).unwrap();
    }
    std::fs::write(root.join("readme.md"), "# Synthetic\n").unwrap();
    let config = dir.path().join("config.yml");
    std::fs::write(&config, "scanner:\n  file_summary_compact_budget: true\n").unwrap();
    let out = dir.path().join("catalog.jsonl");
    let build = binary()
        .env("PATH", "")
        .args(["index", "--catalog-only", "--root"])
        .arg(&root)
        .args(["--include", "*"])
        .arg("--config")
        .arg(&config)
        .arg("--out")
        .arg(&out)
        .output()
        .unwrap();
    assert!(
        build.status.success(),
        "{}",
        String::from_utf8_lossy(&build.stderr)
    );
    let items = records(&out);
    let go_summary = "purpose: worker\nterms: worker type struct run func workers\nfile: worker.go\nextension: .go\nsymbols:\n- struct Worker: type Worker struct {}\n- method Worker.Run: func (w *Worker) Run() {}\nhead:\n- package workers\n- import \"fmt\"\n- type Worker struct {}\n- func (w *Worker) Run() {}\nimports: none";
    let go_manifest = "file: worker.go\nfilename: worker.go\nextension: .go\ndirectories: none\npath_tokens: worker go\npackage: workers\nsymbols:\n- struct Worker: type Worker struct {}\n- method Worker.Run: func (w *Worker) Run() {}\nimports: none\nconfig_keys: none";
    for item in &items {
        let path = item["path"].as_str().unwrap();
        if path == "readme.md" {
            continue;
        }
        let summary = item["kind"] == "file_summary";
        let expected = if path == "worker.go" {
            if summary {
                go_summary.to_string()
            } else {
                go_manifest.to_string()
            }
        } else {
            let suffix = path.rsplit('.').next().unwrap();
            if summary {
                format!(
                    "purpose: worker\nterms: worker export\nfile: {path}\nextension: .{suffix}\nsymbols:\n- class Worker: export class Worker {{}}\nhead:\n- import {{ dep }} from 'pkg';\n- export class Worker {{}}\nimports: none"
                )
            } else {
                format!(
                    "file: {path}\nfilename: {path}\nextension: .{suffix}\ndirectories: none\npath_tokens: worker {suffix}\npackage: none\nsymbols:\n- class Worker: export class Worker {{}}\nimports: none\nconfig_keys: none"
                )
            }
        };
        assert_eq!(item["content"], expected, "{path}");
        assert_eq!(item["symbols"], serde_json::json!([]));
    }
    assert_eq!(items.len(), 20);
    for (lane, count) in [("go", 2), ("ts-js", 16), ("generic", 2), ("all", 20)] {
        let result = binary()
            .args(["catalog-compare", "--reference"])
            .arg(&out)
            .arg("--built")
            .arg(&out)
            .args(["--lane", lane])
            .output()
            .unwrap();
        assert!(result.status.success(), "{lane}");
        let stdout = String::from_utf8_lossy(&result.stdout);
        for label in [
            "reference items      :",
            "content equal        :",
            "tokenized_* all equal:",
            "embed text (500ch) eq:",
        ] {
            assert!(
                stdout.contains(&format!("{label} {count}")),
                "{lane}: {stdout}"
            );
        }
    }
    let mut changed = items.clone();
    for item in &mut changed {
        if item["path"] == "worker.cts" {
            item["content"] = serde_json::json!("changed");
        }
    }
    let altered = dir.path().join("altered.jsonl");
    std::fs::write(
        &altered,
        changed
            .iter()
            .map(|item| format!("{item}\n"))
            .collect::<String>(),
    )
    .unwrap();
    for (lane, success) in [("go", true), ("ts-js", false), ("generic", true)] {
        let result = binary()
            .args(["catalog-compare", "--reference"])
            .arg(&out)
            .arg("--built")
            .arg(&altered)
            .args(["--lane", lane])
            .output()
            .unwrap();
        assert_eq!(result.status.success(), success, "{lane}");
    }
}

fn binary() -> Command {
    Command::new(env!("CARGO_BIN_EXE_code-diver"))
}

#[test]
fn catalog_build_and_compare_without_runtime_dependencies() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().join("root");
    std::fs::create_dir(&root).unwrap();
    std::fs::write(root.join("readme.md"), "# Synthetic\nBody\n").unwrap();
    let out = dir.path().join("catalog.jsonl");
    let build = binary()
        .env("PATH", "")
        .args(["index", "--catalog-only", "--root"])
        .arg(&root)
        .arg("--out")
        .arg(&out)
        .output()
        .unwrap();
    assert!(
        build.status.success(),
        "{}",
        String::from_utf8_lossy(&build.stderr)
    );
    assert_eq!(std::fs::read_to_string(&out).unwrap().lines().count(), 2);
    let compare = binary()
        .args(["catalog-compare", "--reference"])
        .arg(&out)
        .arg("--built")
        .arg(&out)
        .args(["--lane", "generic"])
        .output()
        .unwrap();
    assert!(compare.status.success());
    assert!(String::from_utf8_lossy(&compare.stdout).contains("content equal        : 2"));
    let original = std::fs::read_to_string(&out).unwrap();
    std::fs::write(&out, format!("{original}{original}")).unwrap();
    assert!(
        !binary()
            .args(["catalog-compare", "--reference"])
            .arg(&out)
            .arg("--built")
            .arg(&out)
            .status()
            .unwrap()
            .success()
    );
}

#[test]
fn config_validation_and_explicit_catalog_only() {
    let dir = tempfile::tempdir().unwrap();
    let config = dir.path().join("config.yml");
    std::fs::write(&config, "scanner:\n  line_chunks: true\n").unwrap();
    let result = binary()
        .args(["index", "--catalog-only", "--config"])
        .arg(&config)
        .arg("--out")
        .arg(dir.path().join("out"))
        .output()
        .unwrap();
    assert!(!result.status.success());
    assert!(String::from_utf8_lossy(&result.stderr).contains("line_chunks=true"));
    assert!(
        !binary()
            .args(["index", "--out"])
            .arg(dir.path().join("out"))
            .output()
            .unwrap()
            .status
            .success()
    );
}

#[test]
fn comparator_reports_fields_and_rejects_invalid_schema() {
    let dir = tempfile::tempdir().unwrap();
    let reference = dir.path().join("reference.jsonl");
    let built = dir.path().join("built.jsonl");
    let valid = serde_json::json!({"id": "sample", "path": "kb/sample.md", "name": "sample", "kind": "file_summary", "content": "purpose: old", "symbols": [], "tokenized_name": [], "tokenized_path": [], "tokenized_dir": [], "tokenized_content": []});
    std::fs::write(&reference, valid.to_string()).unwrap();
    for field in [
        "name",
        "path",
        "kind",
        "content",
        "tokenized_name",
        "tokenized_path",
        "tokenized_dir",
        "tokenized_content",
        "id",
    ] {
        let mut changed = valid.clone();
        changed[field] = if field.starts_with("tokenized_") {
            serde_json::json!(["changed"])
        } else {
            serde_json::json!("changed")
        };
        std::fs::write(&built, changed.to_string()).unwrap();
        let result = binary()
            .args(["catalog-compare", "--reference"])
            .arg(&reference)
            .arg("--built")
            .arg(&built)
            .output()
            .unwrap();
        assert!(!result.status.success(), "{field}");
        let output = String::from_utf8_lossy(&result.stdout);
        let category = if field == "id" {
            "IDs/missing".to_string()
        } else if field == "content" {
            "file_summary/purpose".to_string()
        } else if field.starts_with("tokenized_") {
            format!("tokens/{field}")
        } else {
            format!("metadata/{field}")
        };
        assert!(output.contains(&category), "{field}: {output}");
        assert!(output.contains("sample") && output.contains("changed"));
    }
    for field in [
        "tokenized_name",
        "tokenized_path",
        "tokenized_dir",
        "tokenized_content",
        "symbols",
    ] {
        let mut invalid = valid.clone();
        invalid.as_object_mut().unwrap().remove(field);
        std::fs::write(&reference, invalid.to_string()).unwrap();
        std::fs::write(&built, invalid.to_string()).unwrap();
        let result = binary()
            .args(["catalog-compare", "--reference"])
            .arg(&reference)
            .arg("--built")
            .arg(&built)
            .output()
            .unwrap();
        assert!(!result.status.success());
        assert!(String::from_utf8_lossy(&result.stderr).contains(field));
    }
}
