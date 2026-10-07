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
