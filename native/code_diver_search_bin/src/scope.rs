/// Detect path scopes in a query string.
///
/// Scopes are tokens like `repos/cloud-console`, `repos/sre/infra`, `kb/docs/guides`.
/// They can appear anywhere in the query, surrounded by any language text.
use regex::Regex;
use std::sync::LazyLock;

static SCOPE_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"\b(repos/[a-zA-Z0-9_][a-zA-Z0-9_/\-]*|kb/[a-zA-Z0-9_][a-zA-Z0-9_/\-]*)").unwrap()
});

/// Return all detected scope prefixes from the query.
///
/// Each scope is normalized (no trailing slash). Returns empty vec if none found.
pub fn detect_scopes(query: &str) -> Vec<String> {
    let mut scopes = Vec::new();
    for cap in SCOPE_RE.captures_iter(query) {
        if let Some(s) = cap
            .get(1)
            .map(|m| m.as_str().trim_end_matches('/').to_string())
            && !scopes.contains(&s)
        {
            scopes.push(s);
        }
    }
    scopes
}

/// Check whether a file path falls within any of the given scopes.
pub fn is_in_scope(path: &str, scopes: &[String]) -> bool {
    for scope in scopes {
        if path == scope.as_str() || path.starts_with(&format!("{}/", scope)) {
            return true;
        }
    }
    false
}

/// Remove detected scope tokens from the query, collapsing whitespace.
pub fn strip_scope_tokens(query: &str) -> String {
    let stripped = SCOPE_RE.replace_all(query, "");
    // Collapse multiple spaces and trim
    let mut result = String::with_capacity(stripped.len());
    let mut prev_space = false;
    for ch in stripped.chars() {
        if ch.is_whitespace() {
            if !prev_space && !result.is_empty() {
                result.push(' ');
            }
            prev_space = true;
        } else {
            prev_space = false;
            result.push(ch);
        }
    }
    result.trim().to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn detect_repos_scope() {
        let scopes = detect_scopes("В каком файле repos/cloud-console описаны структуры");
        assert_eq!(scopes, vec!["repos/cloud-console"]);
    }

    #[test]
    fn detect_repos_scope_with_subdir() {
        let scopes = detect_scopes("show me repos/cloud-console/pkg/config");
        assert_eq!(scopes, vec!["repos/cloud-console/pkg/config"]);
    }

    #[test]
    fn detect_kb_scope() {
        let scopes = detect_scopes("look in kb/faq for the answer");
        assert_eq!(scopes, vec!["kb/faq"]);
    }

    #[test]
    fn detect_kb_scope_with_subdirs() {
        let scopes = detect_scopes("check kb/docs/guides for details");
        assert_eq!(scopes, vec!["kb/docs/guides"]);
    }

    #[test]
    fn detect_multiple_scopes() {
        let scopes = detect_scopes("compare repos/a and repos/b");
        assert_eq!(scopes.len(), 2);
        assert!(scopes.contains(&"repos/a".to_string()));
        assert!(scopes.contains(&"repos/b".to_string()));
    }

    #[test]
    fn detect_no_scope() {
        let scopes = detect_scopes("what is the main function");
        assert!(scopes.is_empty());
    }

    #[test]
    fn detect_scope_at_beginning() {
        let scopes = detect_scopes("repos/sre настройка Thanos Compact");
        assert_eq!(scopes, vec!["repos/sre"]);
    }

    #[test]
    fn detect_scope_in_cyrillic_sentence() {
        let scopes =
            detect_scopes("В каком файле repos/cloud-console описаны Go-структуры CRD квот?");
        assert_eq!(scopes, vec!["repos/cloud-console"]);
    }

    #[test]
    fn is_in_scope_matching() {
        let scopes = vec!["repos/cloud-console".to_string()];
        assert!(is_in_scope("repos/cloud-console/src/main.go", &scopes));
    }

    #[test]
    fn is_in_scope_exact_match() {
        let scopes = vec!["repos/cloud-console".to_string()];
        assert!(is_in_scope("repos/cloud-console", &scopes));
    }

    #[test]
    fn is_in_scope_non_matching() {
        let scopes = vec!["repos/cloud-console".to_string()];
        assert!(!is_in_scope("repos/other/src/main.go", &scopes));
    }

    #[test]
    fn is_in_scope_empty_scopes() {
        assert!(!is_in_scope("repos/cloud-console/src/main.go", &[]));
    }

    #[test]
    fn strip_scope_tokens_removes_scope() {
        let result = strip_scope_tokens("В каком файле repos/cloud-console описаны структуры");
        assert!(!result.contains("repos/cloud-console"));
        assert!(result.contains("файле"));
        assert!(result.contains("описаны"));
    }

    #[test]
    fn strip_scope_tokens_no_scope_unchanged() {
        let result = strip_scope_tokens("what is the main function");
        assert_eq!(result, "what is the main function");
    }

    #[test]
    fn strip_multiple_scopes() {
        let result = strip_scope_tokens("compare repos/a and repos/b for differences");
        assert!(!result.contains("repos/a"));
        assert!(!result.contains("repos/b"));
        assert!(result.contains("compare"));
    }

    #[test]
    fn scope_with_hyphenated_name() {
        let scopes = detect_scopes("check repos/my-repo-name for the config");
        assert_eq!(scopes, vec!["repos/my-repo-name"]);
    }
}
