use std::path::PathBuf;
use std::process::Command;
use std::sync::OnceLock;

pub fn executable() -> &'static PathBuf {
    static HELPER: OnceLock<PathBuf> = OnceLock::new();
    HELPER.get_or_init(|| {
        let current = std::env::current_exe().unwrap();
        let profile_dir = current.parent().unwrap().parent().unwrap();
        let profile = profile_dir.file_name().unwrap().to_str().unwrap();
        let output = Command::new(env!("CARGO"))
            .args([
                "build",
                "--locked",
                "--test",
                "runtime-test-helper",
                "--message-format=json",
                "--manifest-path",
            ])
            .arg(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("Cargo.toml"))
            .arg("--target-dir")
            .arg(profile_dir.parent().unwrap())
            .arg("--profile")
            .arg(if profile == "debug" { "dev" } else { profile })
            .output()
            .expect("cannot build test-only runtime helper with Cargo");
        assert!(
            output.status.success(),
            "runtime helper build failed: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        String::from_utf8(output.stdout)
            .unwrap()
            .lines()
            .filter_map(|line| {
                let message: serde_json::Value = serde_json::from_str(line).ok()?;
                (message["reason"] == "compiler-artifact"
                    && message["target"]["name"] == "runtime-test-helper")
                    .then(|| message["executable"].as_str().map(PathBuf::from))
                    .flatten()
            })
            .next()
            .expect("Cargo did not report the runtime helper executable")
    })
}
