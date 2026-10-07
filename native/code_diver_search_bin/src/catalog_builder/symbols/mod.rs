pub mod generic;
pub mod go;
pub mod ts_js;
pub use generic::{Symbol, has_dedicated_strategy, limit_symbols, suffix_lower};

pub fn is_ts_js(path: &str) -> bool {
    [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"]
        .contains(&suffix_lower(path).as_str())
}

pub fn extract(path: &str, text: &str) -> Vec<Symbol> {
    let symbols = if suffix_lower(path) == ".go" {
        go::extract(text)
    } else if is_ts_js(path) {
        ts_js::extract(text)
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
        for suffix in ["go", "ts", "tsx", "js", "jsx", "mjs", "cjs", "mts", "cts"] {
            let text = "impl Display for Thing {}";
            assert_eq!(
                extract(&format!("a.{suffix}"), text),
                generic::extract("a.txt", text)
            );
        }
    }
}
