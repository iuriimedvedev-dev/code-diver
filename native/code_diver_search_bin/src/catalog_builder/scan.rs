//! File enumeration mirroring `CodebaseScanner` (src/code_diver/services/codebase_scanner.py).
//!
//! Python lists candidates with `rg --files --no-require-git` (honours .gitignore, .ignore,
//! .rgignore, global git excludes, skips hidden files and symlinks), sorts the paths, then
//! applies its own exclude/include fnmatch rules. The `ignore` crate is ripgrep's walker,
//! so the first stage is reproduced by configuration, not re-implementation.

use std::fs;
use std::path::{Path, PathBuf};

use ignore::WalkBuilder;
use regex::Regex;

use super::pytext::{fnmatch_regex, suffix};

pub const DEFAULT_EXCLUDES: &[&str] = &[
    ".git/**",
    ".hg/**",
    ".svn/**",
    ".code-diver/**",
    ".pi/npm/**",
    ".venv*/**",
    "venv*/**",
    "node_modules/**",
    "dist/**",
    "build/**",
    "target/**",
    "**/testSrc/**",
    "**/testSources/**",
    "**/platform-tests/**",
    "__pycache__/**",
    ".pytest_cache/**",
    ".mypy_cache/**",
    ".ruff_cache/**",
    "uv.lock",
];

pub const DEFAULT_INCLUDE_SUFFIXES: &[&str] = &[
    ".c", ".cc", ".cpp", ".cs", ".css", ".go", ".h", ".hpp", ".html", ".java", ".js", ".jsx",
    ".json", ".kt", ".kts", ".md", ".mdx", ".php", ".py", ".rb", ".rst", ".rs", ".scala", ".sh",
    ".sql", ".swift", ".toml", ".ts", ".tsx", ".txt", ".adoc", ".yaml", ".yml",
];

enum ExcludeRule {
    /// Pattern ending in `/**`: directory segment run (any depth) or root-anchored prefix.
    Dir {
        base: String,
        any_depth: bool,
        segment_res: Vec<Option<Regex>>,
    },
    /// Anything else: plain fnmatch on the relative path.
    Glob(Option<Regex>),
}

pub struct Scanner {
    include: Vec<Option<Regex>>,
    include_directories: Vec<Regex>,
    hidden_includes: Vec<Regex>,
    exclude: Vec<ExcludeRule>,
    pub max_file_bytes: u64,
}

impl Scanner {
    pub fn new(include: &[String], exclude: &[String], max_file_bytes: u64) -> Self {
        let mut all_excludes: Vec<String> =
            DEFAULT_EXCLUDES.iter().map(|s| s.to_string()).collect();
        all_excludes.extend(exclude.iter().cloned());
        Self {
            include: include.iter().map(|p| fnmatch_regex(p)).collect(),
            include_directories: include
                .iter()
                .filter_map(|p| p.strip_suffix("/**"))
                .filter(|p| !p.contains('/'))
                .filter_map(fnmatch_regex)
                .collect(),
            hidden_includes: include
                .iter()
                .flat_map(|p| p.split('/'))
                .filter(|p| p.starts_with('.') && *p != ".")
                .filter_map(fnmatch_regex)
                .collect(),
            exclude: all_excludes.iter().map(|p| compile_exclude(p)).collect(),
            max_file_bytes,
        }
    }

    fn include_is_empty(&self) -> bool {
        self.include.is_empty()
    }

    fn matches_include(&self, rel_path: &str) -> bool {
        let dotted = format!("./{rel_path}");
        self.include
            .iter()
            .flatten()
            .any(|re| re.is_match(rel_path) || re.is_match(&dotted))
            || rel_path.rsplit_once('/').is_some_and(|(dirs, _)| {
                dirs.split('/')
                    .any(|dir| self.include_directories.iter().any(|re| re.is_match(dir)))
            })
    }

    pub fn is_excluded(&self, rel_path: &str) -> bool {
        self.exclude.iter().any(|rule| match rule {
            ExcludeRule::Glob(re) => re
                .as_ref()
                .is_some_and(|re| re.is_match(rel_path) || re.is_match(&format!("./{rel_path}"))),
            ExcludeRule::Dir {
                base,
                any_depth,
                segment_res,
            } => {
                if base.is_empty() {
                    return true;
                }
                if *any_depth || !base.contains('/') {
                    let segments: Vec<&str> = rel_path.split('/').collect();
                    // File path: the run must end above the file itself.
                    let searchable = &segments[..segments.len().saturating_sub(1)];
                    contains_segment_run(searchable, segment_res)
                } else {
                    rel_path == base || rel_path.starts_with(&format!("{base}/"))
                }
            }
        })
    }

    pub fn should_skip(&self, rel_path: &str) -> bool {
        if self.is_excluded(rel_path) {
            return true;
        }
        if !self.include_is_empty() {
            return !self.matches_include(rel_path);
        }
        let ext = suffix(rel_path).to_lowercase();
        !DEFAULT_INCLUDE_SUFFIXES.contains(&ext.as_str())
    }

    /// Sorted `(absolute path, relative posix path)` candidates.
    pub fn candidate_files(&self, root: &Path) -> Vec<(PathBuf, String)> {
        let mut walker = WalkBuilder::new(root);
        walker
            .hidden(false)
            .ignore(true)
            .git_ignore(true)
            .git_global(true)
            .git_exclude(true)
            .parents(true)
            .require_git(false)
            .follow_links(false)
            .add_custom_ignore_filename(".rgignore");
        let hidden = self.hidden_includes.clone();
        let filter_root = root.to_path_buf();
        walker.filter_entry(move |entry| {
            if entry.depth() == 0 {
                return true;
            }
            let Ok(relative) = entry.path().strip_prefix(&filter_root) else {
                return false;
            };
            let relative = relative.to_string_lossy();
            for part in relative.split('/') {
                if part.starts_with('.') && !hidden.iter().any(|re| re.is_match(part)) {
                    return false;
                }
            }
            true
        });
        let mut rels: Vec<(PathBuf, String)> = Vec::new();
        for entry in walker.build().flatten() {
            if !entry.file_type().is_some_and(|t| t.is_file()) {
                continue;
            }
            if let Ok(rel) = entry.path().strip_prefix(root) {
                let rel = rel
                    .components()
                    .map(|c| c.as_os_str().to_string_lossy().into_owned())
                    .collect::<Vec<_>>()
                    .join("/");
                rels.push((entry.path().to_path_buf(), rel));
            }
        }
        rels.sort_by(|a, b| a.1.cmp(&b.1));
        rels.into_iter()
            .filter(|(_, rel)| !self.should_skip(rel))
            .collect()
    }

    /// `_read_text`: size cap, NUL check, lossy UTF-8.
    pub fn read_text(&self, path: &Path) -> Option<String> {
        let meta = fs::metadata(path).ok()?;
        if meta.len() > self.max_file_bytes {
            return None;
        }
        let raw = fs::read(path).ok()?;
        if raw.len() as u64 > self.max_file_bytes || raw.contains(&0) {
            return None;
        }
        Some(String::from_utf8_lossy(&raw).into_owned())
    }
}

fn compile_exclude(pattern: &str) -> ExcludeRule {
    let normalized = pattern.trim_end_matches('/');
    let Some(base) = normalized.strip_suffix("/**") else {
        return ExcludeRule::Glob(fnmatch_regex(pattern));
    };
    let (base, any_depth) = match base.strip_prefix("**/") {
        Some(rest) => (rest, true),
        None => (base, false),
    };
    ExcludeRule::Dir {
        base: base.to_string(),
        any_depth,
        segment_res: base.split('/').map(fnmatch_regex).collect(),
    }
}

fn contains_segment_run(segments: &[&str], run: &[Option<Regex>]) -> bool {
    let span = run.len();
    if span == 0 || segments.len() < span {
        return false;
    }
    (0..=segments.len() - span).any(|offset| {
        segments[offset..offset + span]
            .iter()
            .zip(run)
            .all(|(seg, re)| re.as_ref().is_some_and(|re| re.is_match(seg)))
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bare_include_directory_matches_at_any_depth() {
        assert!(!scanner(&["kb/**"], &[]).should_skip("nested/kb/page.md"));
        assert!(scanner(&["kb/**"], &[]).should_skip("nested/kb_helper.md"));
    }

    #[test]
    fn explicitly_included_hidden_directory() {
        let root = tempfile::tempdir().unwrap();
        fs::create_dir(root.path().join(".github")).unwrap();
        fs::write(root.path().join(".github/workflow.yml"), "name: demo").unwrap();
        let paths = scanner(&[".github/**"], &[]).candidate_files(root.path());
        assert_eq!(paths.len(), 1);
    }

    fn scanner(include: &[&str], exclude: &[&str]) -> Scanner {
        let inc: Vec<String> = include.iter().map(|s| s.to_string()).collect();
        let exc: Vec<String> = exclude.iter().map(|s| s.to_string()).collect();
        Scanner::new(&inc, &exc, 1_000_000)
    }

    #[test]
    fn dir_excludes_match_segment_runs_not_substrings() {
        let s = scanner(&[], &[]);
        assert!(s.is_excluded("a/node_modules/x/y.js"));
        assert!(!s.is_excluded("src/node_modules_helper.py"));
        assert!(s.is_excluded("x/.venv-vllm/lib/a.py"));
        assert!(!s.is_excluded("src/venv_helper.py"));
        assert!(s.is_excluded("uv.lock"));
        // root-anchored multi-segment base
        assert!(s.is_excluded(".pi/npm/a.js"));
        assert!(!s.is_excluded("x/.pi/npm/a.js"));
    }

    #[test]
    fn include_globs_replace_the_suffix_whitelist() {
        let s = scanner(&["kb/**"], &[]);
        assert!(!s.should_skip("kb/a/b.md"));
        assert!(!s.should_skip("kb/a/b.weird"));
        assert!(s.should_skip("repos/a.md"));
        let s = scanner(&[], &[]);
        assert!(!s.should_skip("a/b.go"));
        assert!(s.should_skip("a/b.weird"));
    }

    #[test]
    fn star_star_prefixed_user_excludes() {
        let s = scanner(&["**"], &["**/.git/**", "tmp/**"]);
        assert!(s.is_excluded("repos/x/.git/config"));
        assert!(s.is_excluded("tmp/a.md"));
        assert!(s.is_excluded("deep/tmp/a.md"));
    }
}
