pub mod cpp;
pub mod generic;
pub mod go;
pub mod jvm;
pub mod python;
pub mod rust_lang;
pub mod ts_js;
pub use generic::{Symbol, has_dedicated_strategy, limit_symbols, suffix_lower};

pub fn is_ts_js(path: &str) -> bool {
    [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"]
        .contains(&suffix_lower(path).as_str())
}

pub fn is_jvm(path: &str) -> bool {
    jvm::is_jvm(path)
}

pub fn is_cpp(path: &str) -> bool {
    [
        ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".c++", ".h++",
    ]
    .contains(&suffix_lower(path).as_str())
}

pub fn extract(path: &str, text: &str) -> Vec<Symbol> {
    let symbols = if suffix_lower(path) == ".go" {
        go::extract(text)
    } else if is_ts_js(path) {
        ts_js::extract(text)
    } else if [".py", ".pyi"].contains(&suffix_lower(path).as_str()) {
        python::extract(text)
    } else if suffix_lower(path) == ".rs" {
        rust_lang::extract(text)
    } else if is_jvm(path) {
        jvm::extract(text)
    } else if is_cpp(path) {
        cpp::extract(text)
    } else {
        Vec::new()
    };
    if symbols.is_empty() {
        generic::extract(path, text)
    } else {
        symbols
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn m2c_lane_suffixes_match_python_registry() {
        for suffix in ["java", "KT", "kts"] {
            let path = format!("worker.{suffix}");
            assert!(is_jvm(&path));
            assert!(!is_cpp(&path));
            assert!(has_dedicated_strategy(&path));
        }
        for suffix in [
            "c", "CC", "cpp", "cxx", "h", "hh", "hpp", "hxx", "c++", "H++",
        ] {
            let path = format!("worker.{suffix}");
            assert!(is_cpp(&path));
            assert!(!is_jvm(&path));
            assert!(has_dedicated_strategy(&path));
        }
        for path in [
            "worker.scala",
            "worker.SCALA",
            "worker.cs",
            "worker.cpp.txt",
        ] {
            assert!(!is_jvm(path));
            assert!(!is_cpp(path));
            assert!(!has_dedicated_strategy(path));
        }
        let text = "class Worker {}";
        assert_eq!(
            extract("worker.SCALA", text),
            generic::extract("worker.SCALA", text)
        );
    }

    #[test]
    fn nonempty_dedicated_results_replace_generic_results() {
        let go = extract("a.GO", "type Worker struct {}\nimpl Display for Thing {}");
        assert_eq!(go.len(), 1);
        assert_eq!(go[0].kind, "struct");
        for suffix in ["TS", "tsx", "js", "jsx", "mjs", "cjs", "mts", "cts"] {
            let ts = extract(
                &format!("a.{suffix}"),
                "class Worker {}\nimpl Display for Thing {}",
            );
            assert_eq!(ts.len(), 1);
            assert_eq!(ts[0].kind, "class");
        }
    }

    #[test]
    fn empty_dedicated_results_use_generic_fallback() {
        for suffix in [
            "go", "ts", "tsx", "js", "jsx", "mjs", "cjs", "mts", "cts", "PY", "PYI", "java", "kt",
            "kts", "c", "cc", "cpp", "cxx", "h", "hh", "hpp", "hxx", "c++", "h++",
        ] {
            let text = "impl Display for Thing {}";
            assert_eq!(
                extract(&format!("a.{suffix}"), text),
                generic::extract("a.txt", text)
            );
        }
        let text = "class Fallback";
        assert_eq!(extract("a.RS", text), generic::extract("a.txt", text));
    }
}
