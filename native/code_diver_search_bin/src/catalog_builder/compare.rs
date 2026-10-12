//! Parity measurement between a reference catalog (Python-built) and a Rust-built one.

use std::collections::{BTreeMap, HashMap, HashSet};
use std::fs;
use std::path::Path;

use serde_json::Value;

const SECTION_LABELS: &[&str] = &[
    "purpose",
    "terms",
    "file",
    "filename",
    "extension",
    "directories",
    "path_tokens",
    "package",
    "symbols",
    "head",
    "imports",
    "config_keys",
    "api",
    "doc",
    "declaration",
];

#[derive(Default, Debug)]
pub struct Report {
    pub ref_count: usize,
    pub built_count: usize,
    pub common_ids: usize,
    pub only_in_ref: Vec<String>,
    pub only_in_built: Vec<String>,
    pub content_equal: usize,
    pub name_equal: usize,
    pub kind_equal: usize,
    pub path_equal: usize,
    pub tokenized_equal: usize,
    /// Items whose embed text (`title: .. | path: .. | text: ..`, first 500 chars) is identical.
    pub embed500_equal: usize,
    /// "kind/section" -> count of items whose first differing line sits in that section
    pub diff_sections: BTreeMap<String, usize>,
    /// (id, ref line, built line) samples per "kind/section"
    pub samples: BTreeMap<String, Vec<(String, String, String)>>,
}

/// Mirrors `index_update::embed_text` (title | path | text, char-truncated).
fn embed_text(v: &Value, max_chars: usize) -> String {
    format!(
        "title: {} | path: {} | text: {}",
        s(v, "name"),
        s(v, "path"),
        s(v, "content")
    )
    .chars()
    .take(max_chars)
    .collect()
}

pub fn load_jsonl(path: &Path) -> Result<Vec<Value>, String> {
    let raw = fs::read_to_string(path).map_err(|e| format!("{}: {e}", path.display()))?;
    let items: Vec<Value> = raw
        .lines()
        .filter(|l| !l.trim().is_empty())
        .enumerate()
        .map(|(i, l)| {
            serde_json::from_str(l).map_err(|e| format!("{}:{}: {e}", path.display(), i + 1))
        })
        .collect::<Result<_, _>>()?;
    let mut seen = HashSet::new();
    for item in &items {
        let id = item
            .get("id")
            .and_then(Value::as_str)
            .filter(|s| !s.is_empty())
            .ok_or("Catalog record must have a nonempty string id")?;
        if !seen.insert(id) {
            return Err("Catalog contains duplicate IDs".into());
        }
        for field in ["path", "name", "kind", "content"] {
            if item.get(field).and_then(Value::as_str).is_none() {
                return Err(format!("Catalog record must have string {field}"));
            }
        }
        for field in [
            "tokenized_name",
            "tokenized_path",
            "tokenized_dir",
            "tokenized_content",
            "symbols",
        ] {
            if !item
                .get(field)
                .and_then(Value::as_array)
                .is_some_and(|values| values.iter().all(Value::is_string))
            {
                return Err(format!(
                    "Catalog record {id} must have string array {field}"
                ));
            }
        }
    }
    Ok(items)
}

fn s<'a>(v: &'a Value, key: &str) -> &'a str {
    v.get(key).and_then(Value::as_str).unwrap_or("")
}

/// Label of the section that contains line `idx` (nearest preceding `label:` line).
fn section_of(lines: &[&str], idx: usize) -> String {
    for i in (0..=idx.min(lines.len().saturating_sub(1))).rev() {
        if let Some(label) = lines.get(i).and_then(|l| l.split(':').next())
            && SECTION_LABELS.contains(&label)
            && !lines[i].starts_with("- ")
        {
            return label.to_string();
        }
    }
    "unknown".to_string()
}

pub fn classify(reference: &str, built: &str) -> (String, String, String) {
    let a: Vec<&str> = reference.split('\n').collect();
    let b: Vec<&str> = built.split('\n').collect();
    let n = a.len().max(b.len());
    for i in 0..n {
        if a.get(i) != b.get(i) {
            let sec = if i < a.len() {
                section_of(&a, i)
            } else {
                section_of(&b, i)
            };
            return (
                sec,
                a.get(i)
                    .copied()
                    .unwrap_or("<missing>")
                    .chars()
                    .take(160)
                    .collect(),
                b.get(i)
                    .copied()
                    .unwrap_or("<missing>")
                    .chars()
                    .take(160)
                    .collect(),
            );
        }
    }
    ("unknown".into(), String::new(), String::new())
}

/// Compare `built` against `reference`, restricted to reference/built items accepted by `keep`.
pub fn compare(
    reference: &[Value],
    built: &[Value],
    keep: &dyn Fn(&str) -> bool,
    max_samples: usize,
) -> Report {
    let ref_items: Vec<&Value> = reference.iter().filter(|v| keep(s(v, "path"))).collect();
    let built_items: Vec<&Value> = built.iter().filter(|v| keep(s(v, "path"))).collect();
    let built_by_id: HashMap<&str, &Value> = built_items.iter().map(|v| (s(v, "id"), *v)).collect();
    let ref_ids: HashSet<&str> = ref_items.iter().map(|v| s(v, "id")).collect();

    let mut r = Report {
        ref_count: ref_items.len(),
        built_count: built_items.len(),
        ..Default::default()
    };
    r.only_in_built = built_items
        .iter()
        .map(|v| s(v, "id"))
        .filter(|id| !ref_ids.contains(id))
        .map(String::from)
        .collect();
    for item in &ref_items {
        let id = s(item, "id");
        let Some(other) = built_by_id.get(id) else {
            r.only_in_ref.push(id.to_string());
            continue;
        };
        r.common_ids += 1;
        r.name_equal += usize::from(s(item, "name") == s(other, "name"));
        r.kind_equal += usize::from(s(item, "kind") == s(other, "kind"));
        r.path_equal += usize::from(s(item, "path") == s(other, "path"));
        let tok_eq = [
            "tokenized_name",
            "tokenized_path",
            "tokenized_dir",
            "tokenized_content",
        ]
        .iter()
        .all(|k| item.get(*k) == other.get(*k));
        r.tokenized_equal += usize::from(tok_eq);
        for fields in [
            &["name", "path", "kind"][..],
            &[
                "tokenized_name",
                "tokenized_path",
                "tokenized_dir",
                "tokenized_content",
            ][..],
        ] {
            if let Some(field) = fields
                .iter()
                .find(|field| item.get(**field) != other.get(**field))
            {
                let key = format!(
                    "{}/{}",
                    if field.starts_with("tokenized_") {
                        "tokens"
                    } else {
                        "metadata"
                    },
                    field
                );
                *r.diff_sections.entry(key.clone()).or_default() += 1;
                let bucket = r.samples.entry(key).or_default();
                if bucket.len() < max_samples {
                    bucket.push((
                        format!("{id} path={}", s(item, "path")),
                        item[*field].to_string(),
                        other[*field].to_string(),
                    ));
                }
            }
        }
        r.embed500_equal += usize::from(embed_text(item, 500) == embed_text(other, 500));
        if s(item, "content") == s(other, "content") {
            r.content_equal += 1;
        } else {
            let (sec, ra, rb) = classify(s(item, "content"), s(other, "content"));
            let key = format!("{}/{}", s(item, "kind"), sec);
            *r.diff_sections.entry(key.clone()).or_default() += 1;
            let bucket = r.samples.entry(key).or_default();
            if bucket.len() < max_samples {
                bucket.push((format!("{id} path={}", s(item, "path")), ra, rb));
            }
        }
    }
    r
}

impl Report {
    pub fn render(&self) -> String {
        let pct = |n: usize| {
            if self.common_ids == 0 {
                0.0
            } else {
                100.0 * n as f64 / self.common_ids as f64
            }
        };
        let mut out = String::new();
        out.push_str(&format!("reference items      : {}\n", self.ref_count));
        out.push_str(&format!("built items          : {}\n", self.built_count));
        out.push_str(&format!(
            "common ids           : {} ({:.2}% of reference)\n",
            self.common_ids,
            if self.ref_count == 0 {
                0.0
            } else {
                100.0 * self.common_ids as f64 / self.ref_count as f64
            }
        ));
        out.push_str(&format!(
            "only in reference    : {}\n",
            self.only_in_ref.len()
        ));
        out.push_str(&format!(
            "only in built        : {}\n",
            self.only_in_built.len()
        ));
        for (category, ids) in [
            ("IDs/missing", &self.only_in_ref),
            ("IDs/extra", &self.only_in_built),
        ] {
            if !ids.is_empty() {
                out.push_str(&format!("first differing category: {category}\n"));
                for id in ids.iter().take(2) {
                    out.push_str(&format!("  {id}\n"));
                }
            }
        }
        out.push_str(&format!(
            "content equal        : {} ({:.2}% of common)\n",
            self.content_equal,
            pct(self.content_equal)
        ));
        out.push_str(&format!(
            "name/kind/path equal : {}/{}/{}\n",
            self.name_equal, self.kind_equal, self.path_equal
        ));
        out.push_str(&format!(
            "tokenized_* all equal: {} ({:.2}% of common)\n",
            self.tokenized_equal,
            pct(self.tokenized_equal)
        ));
        out.push_str(&format!(
            "embed text (500ch) eq: {} ({:.2}% of common)\n",
            self.embed500_equal,
            pct(self.embed500_equal)
        ));
        if !self.diff_sections.is_empty() {
            out.push_str("differences by first differing section/category:\n");
            for (k, n) in &self.diff_sections {
                out.push_str(&format!("  {k:<28} {n}\n"));
                for (id, a, b) in self.samples.get(k).into_iter().flatten() {
                    out.push_str(&format!("    {id}\n      ref  : {a}\n      built: {b}\n"));
                }
            }
        }
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn item(id: &str, content: &str) -> Value {
        json!({"id": id, "path": "kb/a.md", "kind": "file_summary", "name": "n", "content": content,
               "tokenized_name": [], "tokenized_path": [], "tokenized_dir": [], "tokenized_content": []})
    }

    #[test]
    fn embedding_window_is_measured_independently_of_full_content_and_tokens() {
        let content = "文".repeat(500);
        let reference = vec![item("a", &format!("{content}old"))];
        let mut changed = item("a", &format!("{content}new"));
        changed["tokenized_content"] = json!(["new"]);
        let report = compare(&reference, &[changed], &|_| true, 2);
        assert_eq!(report.common_ids, 1);
        assert_eq!(report.content_equal, 0);
        assert_eq!(report.tokenized_equal, 0);
        assert_eq!(report.embed500_equal, 1);
        let output = report.render();
        assert!(output.contains("embed text (500ch) eq: 1 (100.00% of common)"));
    }

    #[test]
    fn counts_and_classifies_differences() {
        let reference = vec![
            item("a", "purpose: x\nterms: a b\nhead:\n- one"),
            item("b", "same"),
            item("gone", "x"),
        ];
        let built = vec![
            item("a", "purpose: x\nterms: a c\nhead:\n- one"),
            item("b", "same"),
            item("new", "y"),
        ];
        let r = compare(&reference, &built, &|_| true, 2);
        assert_eq!((r.common_ids, r.content_equal), (2, 1));
        assert_eq!(r.only_in_ref, vec!["gone"]);
        assert_eq!(r.only_in_built, vec!["new"]);
        assert_eq!(r.diff_sections.get("file_summary/terms"), Some(&1));
    }

    #[test]
    fn head_bullets_do_not_masquerade_as_sections() {
        let lines = ["head:", "- file: x", "- more"];
        assert_eq!(section_of(&lines, 2), "head");
    }

    #[test]
    fn rejects_missing_and_malformed_arrays() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("catalog.jsonl");
        let mut valid = item("a", "x");
        valid["symbols"] = json!([]);
        for field in [
            "tokenized_name",
            "tokenized_path",
            "tokenized_dir",
            "tokenized_content",
            "symbols",
        ] {
            for bad in [None, Some(json!(null)), Some(json!("x")), Some(json!([1]))] {
                let mut value = valid.clone();
                if let Some(bad) = bad {
                    value[field] = bad;
                } else {
                    value.as_object_mut().unwrap().remove(field);
                }
                fs::write(&path, value.to_string()).unwrap();
                assert!(load_jsonl(&path).unwrap_err().contains(field));
            }
        }
        fs::write(&path, valid.to_string()).unwrap();
        assert!(load_jsonl(&path).is_ok());
    }

    #[test]
    fn renders_first_differences_and_id_samples() {
        let reference = vec![item("a", "purpose: old"), item("missing", "x")];
        let mut changed = item("a", "purpose: new");
        changed["name"] = json!("changed");
        changed["tokenized_path"] = json!(["different"]);
        let built = vec![changed, item("extra", "x")];
        let output = compare(&reference, &built, &|_| true, 2).render();
        for expected in [
            "IDs/missing",
            "missing",
            "IDs/extra",
            "extra",
            "metadata/name",
            "tokens/tokenized_path",
            "file_summary/purpose",
            "a path=kb/a.md",
            "different",
            "changed",
            "purpose: old",
            "purpose: new",
        ] {
            assert!(output.contains(expected), "missing {expected}: {output}");
        }
    }
}
