use std::process::Command;

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
