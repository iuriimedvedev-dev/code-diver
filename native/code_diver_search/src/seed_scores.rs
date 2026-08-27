use std::collections::HashSet;

/// Per-item data needed for seed score computation.
pub struct ItemSeedData {
    pub id: String,
    pub path: String,
    pub title_terms: HashSet<String>,
    pub content_terms: HashSet<String>,
    pub path_terms: HashSet<String>,
    pub metadata_terms: HashSet<String>,
    pub symbol: Option<String>,
}

/// Coverage fraction of `query_terms` found in `candidates`.
fn coverage(query_terms: &[String], candidates: &HashSet<String>) -> f64 {
    if candidates.is_empty() {
        return 0.0;
    }
    let matches = query_terms
        .iter()
        .filter(|t| candidates.contains(*t))
        .count() as f64;
    matches / query_terms.len() as f64
}

/// Symbol match score: matches / max(min(len(candidates), len(query_terms)), 1)
fn symbol_match(
    query_terms: &[String],
    candidates: &HashSet<String>,
) -> f64 {
    if candidates.is_empty() {
        return 0.0;
    }
    let matches = query_terms
        .iter()
        .filter(|t| candidates.contains(*t))
        .count() as f64;
    if matches == 0.0 {
        return 0.0;
    }
    let denom = (candidates.len().min(query_terms.len())).max(1) as f64;
    (matches / denom).min(1.0)
}

/// Compute seed coverages for all items, filter zero-score, sort, and return top N.
///
/// Returns `Vec<(item_id, lexical_score, path_score, symbol_score)>` sorted by
/// (lexical_score desc, path_score desc, symbol_score desc, path asc).
pub fn seed_coverages(
    items: Vec<ItemSeedData>,
    query_terms: &[String],
    lexical_seed_limit: usize,
) -> Vec<(String, f64, f64, f64)> {
    let mut scored: Vec<(String, f64, f64, f64, String)> = Vec::with_capacity(items.len());

    for item in items {
        let title_cov = coverage(query_terms, &item.title_terms);
        let content_cov = coverage(query_terms, &item.content_terms);
        let path_cov = coverage(query_terms, &item.path_terms);
        let meta_cov = coverage(query_terms, &item.metadata_terms);

        let lexical_score = (content_cov * 0.75 + title_cov * 0.25).min(1.0);
        let path_score = path_cov;

        let sym_match = if item.symbol.is_some() {
            symbol_match(query_terms, &item.metadata_terms)
        } else {
            0.0
        };
        let symbol_score = meta_cov.max(sym_match);

        if lexical_score <= 0.0 && path_score <= 0.0 && symbol_score <= 0.0 {
            continue;
        }

        scored.push((item.id, lexical_score, path_score, symbol_score, item.path));
    }

    // Sort by lexical_score desc, path_score desc, symbol_score desc, path asc
    scored.sort_by(|a, b| {
        b.1.partial_cmp(&a.1)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| b.2.partial_cmp(&a.2).unwrap_or(std::cmp::Ordering::Equal))
            .then_with(|| b.3.partial_cmp(&a.3).unwrap_or(std::cmp::Ordering::Equal))
            .then_with(|| a.4.cmp(&b.4))
    });

    scored
        .into_iter()
        .take(lexical_seed_limit)
        .map(|(id, lex, path, sym, _)| (id, lex, path, sym))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_item(
        id: &str,
        path: &str,
        title: &[&str],
        content: &[&str],
        path_terms: &[&str],
        metadata: &[&str],
        symbol: Option<&str>,
    ) -> ItemSeedData {
        ItemSeedData {
            id: id.to_string(),
            path: path.to_string(),
            title_terms: title.iter().map(|s| s.to_string()).collect(),
            content_terms: content.iter().map(|s| s.to_string()).collect(),
            path_terms: path_terms.iter().map(|s| s.to_string()).collect(),
            metadata_terms: metadata.iter().map(|s| s.to_string()).collect(),
            symbol: symbol.map(|s| s.to_string()),
        }
    }

    #[test]
    fn empty_items() {
        let result = seed_coverages(vec![], &[], 10);
        assert!(result.is_empty());
    }

    #[test]
    fn empty_items_with_query_terms() {
        let result = seed_coverages(vec![], &["foo".to_string()], 10);
        assert!(result.is_empty());
    }

    #[test]
    fn single_item_matches_all() {
        let items = vec![make_item(
            "doc1", "/src/foo.py",
            &["foo", "bar"],
            &["foo", "bar", "baz"],
            &["foo", "bar"],
            &["foo", "bar", "class"],
            Some("FooClass"),
        )];
        let terms: Vec<String> = vec!["foo".to_string(), "bar".to_string()];
        let result = seed_coverages(items, &terms, 10);
        assert_eq!(result.len(), 1);
        assert_eq!(result[0].0, "doc1");
        // lexical = min(1.0, 1.0*0.75 + 1.0*0.25) = 1.0
        assert!((result[0].1 - 1.0).abs() < 1e-12);
        // path = 2/2 = 1.0
        assert!((result[0].2 - 1.0).abs() < 1e-12);
        // meta_cov = 2/2 = 1.0, symbol_match = max(2/2, 2/2) = 1.0, symbol = max(1.0, 1.0) = 1.0
        assert!((result[0].3 - 1.0).abs() < 1e-12);
    }

    #[test]
    fn no_match_filtered() {
        let items = vec![make_item(
            "doc1", "/src/foo.py",
            &["aaa"],
            &["bbb"],
            &["ccc"],
            &["ddd"],
            None,
        )];
        let terms: Vec<String> = vec!["zzz".to_string()];
        let result = seed_coverages(items, &terms, 10);
        assert!(result.is_empty());
    }

    #[test]
    fn partial_match() {
        let items = vec![make_item(
            "doc1", "/src/foo.py",
            &["foo"],
            &["bar"],
            &["foo"],
            &["class"],
            None,
        )];
        let terms: Vec<String> = vec!["foo".to_string(), "bar".to_string(), "baz".to_string()];
        let result = seed_coverages(items, &terms, 10);
        assert_eq!(result.len(), 1);
        // title_cov = 1/3, content_cov = 1/3
        // lexical = min(1.0, 1/3*0.75 + 1/3*0.25) = 1/3
        assert!((result[0].1 - 1.0 / 3.0).abs() < 1e-12);
        // path_cov = 1/3 (path_terms={"foo"}) matches 1/3 query terms
        assert!((result[0].2 - 1.0 / 3.0).abs() < 1e-12);
        // meta_cov = 0/3 = 0, no symbol -> symbol = 0
        assert!((result[0].3 - 0.0).abs() < 1e-12);
    }

    #[test]
    fn sorting_by_lexical_desc() {
        let items = vec![
            make_item("low", "/low.py", &[], &["foo"], &[], &[], None),
            make_item("high", "/high.py", &["foo"], &["foo", "bar"], &[], &[], None),
        ];
        let terms: Vec<String> = vec!["foo".to_string(), "bar".to_string()];
        let result = seed_coverages(items, &terms, 10);
        assert_eq!(result.len(), 2);
        // high should be first (higher lexical score: content_cov=1.0, title_cov=0.5)
        assert_eq!(result[0].0, "high");
        assert_eq!(result[1].0, "low");
    }

    #[test]
    fn sorting_by_path_asc_when_scores_equal() {
        let items = vec![
            make_item("b", "/b.py", &["foo"], &["foo"], &["a"], &[], None),
            make_item("a", "/a.py", &["foo"], &["foo"], &["a"], &[], None),
        ];
        let terms: Vec<String> = vec!["foo".to_string()];
        let result = seed_coverages(items, &terms, 10);
        assert_eq!(result.len(), 2);
        // Both have same lexical/path/symbol scores, so sort by path asc
        assert_eq!(result[0].0, "a");
        assert_eq!(result[1].0, "b");
    }

    #[test]
    fn lexical_seed_limit_truncation() {
        let items = (0..5)
            .map(|i| {
                make_item(
                    &format!("doc{}", i),
                    &format!("/{}.py", i),
                    &["foo"],
                    &["foo"],
                    &[],
                    &[],
                    None,
                )
            })
            .collect();
        let terms: Vec<String> = vec!["foo".to_string()];
        let result = seed_coverages(items, &terms, 3);
        assert_eq!(result.len(), 3);
    }

    #[test]
    fn symbol_match_used_when_symbol_present() {
        let items = vec![
            // With symbol: symbol_match = matches / max(min(len(metadata), len(query)), 1)
            // metadata = {"Foo", "class"}, query = {"foo", "bar"}
            // matches = 1 (foo matches Foo? depends on case: "foo" in {"Foo", "class"}? No, case-sensitive)
            // Actually tokenize is case-insensitive in Python, but for Rust test we're case-sensitive
            // Let's make it match: metadata has "foo"
            make_item(
                "with_sym", "/f.py",
                &[], &[], &[], &["foo", "class"],
                Some("Foo"),
            ),
            // Without symbol: symbol = meta_cov = 1/2 = 0.5
            make_item(
                "no_sym", "/f.py",
                &[], &[], &[], &["foo", "class"],
                None,
            ),
        ];
        let terms: Vec<String> = vec!["foo".to_string(), "bar".to_string()];
        let result = seed_coverages(items, &terms, 10);
        assert_eq!(result.len(), 2);
        // with_sym: meta_cov = 1/2 = 0.5, symbol_match = 1/2 = 0.5, symbol = max(0.5, 0.5) = 0.5
        // no_sym: meta_cov = 1/2 = 0.5, symbol = 0.5
        // Both should be similar
        assert!((result[0].3 - 0.5).abs() < 1e-12);
        assert!((result[1].3 - 0.5).abs() < 1e-12);
    }

    #[test]
    fn symbol_match_zero_when_no_metadata_match() {
        let items = vec![make_item(
            "doc1", "/f.py",
            &["foo"], &[], &[], &["zzz"],
            Some("Foo"),
        )];
        let terms: Vec<String> = vec!["foo".to_string()];
        let result = seed_coverages(items, &terms, 10);
        assert_eq!(result.len(), 1);
        // lexical_score nonzero (title_cov=1/1), so not filtered
        // meta_cov = 0, symbol_match = 0 (matches == 0), symbol = 0
        assert!((result[0].3 - 0.0).abs() < 1e-12);
    }
}