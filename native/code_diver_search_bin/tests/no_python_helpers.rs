#[test]
fn runtime_helper_is_not_an_installable_binary() {
    let manifest: toml::Value = toml::from_str(include_str!("../Cargo.toml")).unwrap();
    assert!(
        manifest["bin"]
            .as_array()
            .unwrap()
            .iter()
            .all(|target| { target["name"].as_str() != Some("runtime-test-helper") })
    );
    assert!(manifest["test"].as_array().unwrap().iter().any(|target| {
        target["name"].as_str() == Some("runtime-test-helper")
            && target["harness"].as_bool() == Some(false)
    }));
}

#[test]
fn integration_helpers_do_not_execute_python() {
    fn check(path: &std::path::Path) {
        for entry in std::fs::read_dir(path).unwrap() {
            let path = entry.unwrap().path();
            if path.is_dir() {
                check(&path);
            } else if path.extension().is_some_and(|extension| extension == "py") {
                let source = std::fs::read_to_string(&path).unwrap();
                assert!(
                    !source
                        .lines()
                        .next()
                        .is_some_and(|line| line.starts_with("#!") && line.contains("python")),
                    "executable Python helper: {}",
                    path.display()
                );
            } else if path.extension().is_some_and(|extension| extension == "rs") {
                let source = std::fs::read_to_string(&path).unwrap();
                for fixture in [
                    "acceptance_host",
                    "acceptance_llama",
                    "acceptance_pty",
                    "fake_daemon_llama",
                ] {
                    assert!(
                        !source.contains(&format!("{fixture}.py")),
                        "Python executable fixture referenced by {}",
                        path.display()
                    );
                }
                for interpreter in ["python", "python3"] {
                    assert!(
                        !source.contains(&format!("Command::new(\"{interpreter}\")")),
                        "Python interpreter invoked by {}",
                        path.display()
                    );
                }
            }
        }
    }
    check(&std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("tests"));
}
