use std::fs::File;
use std::io::Read;
use std::path::{Component, Path, PathBuf};
use std::time::{Duration, Instant};

use anyhow::{Context, Result, bail, ensure};
use ignore::{Walk, WalkBuilder};
use regex::RegexBuilder;
use serde_json::{Map, Value, json};

use crate::catalog_builder::{pytext, symbols};

pub const DEFAULT_READ_LINES: u64 = 100;
pub const DEFAULT_GREP_LIMIT: u64 = 50;
pub const DEFAULT_SYMBOLS_LIMIT: u64 = 100;
pub const DEFAULT_TREE_DEPTH: u64 = 3;
pub const DEFAULT_TREE_LIMIT: u64 = 100;
pub const MAX_READ_LINES: u64 = 400;
pub const MAX_OUTPUT_CHARS: usize = 40_000;
pub const MAX_FILE_BYTES: u64 = 1_000_000;
pub const MAX_GREP_LINE_CHARS: usize = 2_000;
pub const MAX_RESULTS: u64 = 1_000;
pub const MAX_TREE_DEPTH: u64 = 64;
pub const MAX_FILES: usize = 10_000;
pub const MAX_PATTERN_CHARS: usize = 10_000;
const MAX_REGEX_BYTES: usize = 2_000_000;
const WALK_TIMEOUT: Duration = Duration::from_secs(10);
const READ_TRUNCATION: &str = "\n... [output truncated]";
const EXCLUDED_DIRS: &[&str] = &[
    ".git",
    ".code-diver",
    ".venv",
    "__pycache__",
    ".pytest_cache",
];

/// Return an MCP tool result. The dispatcher converts errors into `isError` results.
pub fn call(root: &Path, tool: &str, args: &Value) -> Result<Value> {
    let args = args
        .as_object()
        .context("Tool arguments must be an object")?;
    let allowed: &[&str] = match tool {
        "code_diver_read" => &["file", "start_line", "lines"],
        "code_diver_grep" => &["pattern", "path", "limit", "regex"],
        "code_diver_tree" => &["path", "depth", "limit"],
        "code_diver_symbols" => &["path", "limit"],
        _ => bail!("Unknown inspection tool: {tool}"),
    };
    for key in args.keys() {
        ensure!(allowed.contains(&key.as_str()), "Unknown argument: {key}");
    }
    let sandbox = Sandbox::new(root)?;
    let text = match tool {
        "code_diver_read" => read(&sandbox, args)?,
        "code_diver_grep" => grep(&sandbox, args)?,
        "code_diver_tree" => tree(&sandbox, args)?,
        "code_diver_symbols" => list_symbols(&sandbox, args)?,
        _ => unreachable!(),
    };
    Ok(json!({"content": [{"type": "text", "text": text}], "isError": false}))
}

fn string_arg<'a>(
    args: &'a Map<String, Value>,
    name: &str,
    required: bool,
) -> Result<Option<&'a str>> {
    match args.get(name) {
        None if !required => Ok(None),
        None => bail!("Missing required argument: {name}"),
        Some(value) => {
            let text = value
                .as_str()
                .with_context(|| format!("{name} must be a string"))?;
            ensure!(!text.trim().is_empty(), "{name} must not be empty");
            Ok(Some(text))
        }
    }
}

fn positive_arg(args: &Map<String, Value>, name: &str, default: u64, cap: u64) -> Result<u64> {
    let value = match args.get(name) {
        None => default,
        Some(value) => value
            .as_u64()
            .with_context(|| format!("{name} must be a positive integer"))?,
    };
    ensure!(value > 0, "{name} must be a positive integer");
    Ok(value.min(cap))
}

struct Sandbox {
    root: PathBuf,
}

impl Sandbox {
    fn new(root: &Path) -> Result<Self> {
        let root = root
            .canonicalize()
            .context("Cannot open repository root; check --root")?;
        ensure!(
            root.is_dir(),
            "Repository root must be a directory; check --root"
        );
        Ok(Self { root })
    }

    fn resolve(&self, path: Option<&str>) -> Result<PathBuf> {
        let path = Path::new(path.unwrap_or("."));
        ensure!(
            !path.is_absolute()
                && !path.components().any(|part| matches!(
                    part,
                    Component::ParentDir | Component::RootDir | Component::Prefix(_)
                )),
            "Path escapes repository root: use a relative path without '..'"
        );
        let target = self
            .root
            .join(path)
            .canonicalize()
            .context("Cannot open path; check that it exists inside --root")?;
        ensure!(
            target.starts_with(&self.root),
            "Path escapes repository root after symlink resolution"
        );
        Ok(target)
    }

    fn label(&self, path: &Path) -> Result<String> {
        let relative = path
            .strip_prefix(&self.root)
            .context("Path escapes repository root")?;
        if relative.as_os_str().is_empty() {
            return Ok(".".into());
        }
        relative
            .components()
            .map(|part| part.as_os_str().to_str().context("Path is not UTF-8"))
            .collect::<Result<Vec<_>>>()
            .map(|parts| parts.join("/"))
    }

    fn walk(&self, start: &Path, hidden: bool, depth: Option<usize>, tree_order: bool) -> Walk {
        let root = self.root.clone();
        let start = start.to_path_buf();
        let mut builder = WalkBuilder::new(&root);
        builder
            .hidden(hidden)
            .parents(false)
            .require_git(false)
            .follow_links(false)
            .add_custom_ignore_filename(".rgignore")
            .max_depth(depth)
            .filter_entry(move |entry| {
                let path = entry.path();
                let relevant = start.starts_with(path) || path.starts_with(&start);
                relevant
                    && !path.strip_prefix(&root).is_ok_and(|relative| {
                        relative
                            .components()
                            .any(|part| EXCLUDED_DIRS.iter().any(|name| part.as_os_str() == *name))
                    })
            });
        builder.sort_by_file_path(move |a, b| {
            if tree_order {
                (
                    !a.is_dir(),
                    a.file_name().map(|s| s.to_string_lossy().to_lowercase()),
                    a,
                )
                    .cmp(&(
                        !b.is_dir(),
                        b.file_name().map(|s| s.to_string_lossy().to_lowercase()),
                        b,
                    ))
            } else {
                a.cmp(b)
            }
        });
        builder.build()
    }

    fn ensure_visible(&self, target: &Path) -> Result<()> {
        let deadline = Instant::now() + WALK_TIMEOUT;
        for entry in self.walk(target, false, None, false) {
            ensure!(
                Instant::now() < deadline,
                "Repository traversal timed out; narrow the path"
            );
            let entry = entry.context("Cannot inspect repository path")?;
            if entry.path() == target {
                return Ok(());
            }
        }
        bail!("Path is ignored; select a non-ignored repository path")
    }
}

fn text_file(sandbox: &Sandbox, path: &Path) -> Result<String> {
    let canonical = path.canonicalize().context("Cannot open repository file")?;
    ensure!(
        canonical.starts_with(&sandbox.root),
        "Path escapes repository root after symlink resolution"
    );
    let path = canonical.as_path();
    ensure!(
        std::fs::metadata(path)
            .context("Cannot inspect file")?
            .is_file(),
        "Path is not a regular file"
    );
    let file = File::open(path).context("Cannot read file; check permissions")?;
    let metadata = file.metadata().context("Cannot inspect file")?;
    ensure!(metadata.is_file(), "Path is not a regular file");
    ensure!(
        metadata.len() <= MAX_FILE_BYTES,
        "Path exceeds max file size ({MAX_FILE_BYTES} bytes)"
    );
    let mut bytes = Vec::new();
    file.take(MAX_FILE_BYTES + 1)
        .read_to_end(&mut bytes)
        .context("Cannot read file")?;
    ensure!(
        bytes.len() as u64 <= MAX_FILE_BYTES,
        "Path exceeds max file size ({MAX_FILE_BYTES} bytes)"
    );
    ensure!(
        !bytes.contains(&0),
        "Binary file refused (contains NUL bytes)"
    );
    String::from_utf8(bytes).context("Non-UTF-8 file refused; convert the file to UTF-8")
}

fn read(sandbox: &Sandbox, args: &Map<String, Value>) -> Result<String> {
    let file = string_arg(args, "file", true)?;
    let start = positive_arg(args, "start_line", 1, u64::MAX)?;
    let count = positive_arg(args, "lines", DEFAULT_READ_LINES, MAX_READ_LINES)?;
    let target = sandbox.resolve(file)?;
    sandbox.ensure_visible(&target)?;
    let text = text_file(sandbox, &target)?;
    let lines = pytext::splitlines(&text);
    let end = start.saturating_add(count - 1).min(lines.len() as u64);
    let mut output = format!("{}:{start}-{end}", sandbox.label(&target)?);
    if let Ok(offset) = usize::try_from(start - 1) {
        for (index, line) in lines.iter().enumerate().skip(offset).take(count as usize) {
            output.push_str(&format!("\n{:>5} | {line}", index + 1));
            if output.chars().count() > MAX_OUTPUT_CHARS {
                break;
            }
        }
    }
    if output.chars().count() > MAX_OUTPUT_CHARS {
        output = format!(
            "{}{}",
            pytext::prefix(&output, MAX_OUTPUT_CHARS - READ_TRUNCATION.chars().count()),
            READ_TRUNCATION
        );
    }
    Ok(output)
}

fn files(sandbox: &Sandbox, start: &Path) -> impl Iterator<Item = Result<PathBuf>> {
    let start = start.to_path_buf();
    let deadline = Instant::now() + WALK_TIMEOUT;
    sandbox
        .walk(&start, start.is_dir(), None, false)
        .filter_map(move |entry| {
            if Instant::now() >= deadline {
                return Some(Err(anyhow::anyhow!(
                    "Repository traversal timed out; narrow the path"
                )));
            }
            match entry {
                Err(error) => Some(Err(error.into())),
                Ok(entry)
                    if entry.path().starts_with(&start)
                        && entry.file_type().is_some_and(|kind| kind.is_file()) =>
                {
                    Some(Ok(entry.into_path()))
                }
                _ => None,
            }
        })
        .take(MAX_FILES)
}

fn grep(sandbox: &Sandbox, args: &Map<String, Value>) -> Result<String> {
    let pattern = string_arg(args, "pattern", true)?.context("Missing pattern")?;
    ensure!(
        pattern.chars().count() <= MAX_PATTERN_CHARS,
        "pattern exceeds {MAX_PATTERN_CHARS} characters; shorten the pattern"
    );
    let limit = positive_arg(args, "limit", DEFAULT_GREP_LIMIT, MAX_RESULTS)? as usize;
    let regex = match args.get("regex") {
        None => false,
        Some(value) => value.as_bool().context("regex must be a boolean")?,
    };
    let compiled = if regex {
        Some(
            RegexBuilder::new(pattern)
                .size_limit(MAX_REGEX_BYTES)
                .build()
                .context("Invalid or too complex regex; simplify the pattern")?,
        )
    } else {
        None
    };
    let start = sandbox.resolve(string_arg(args, "path", false)?)?;
    sandbox.ensure_visible(&start)?;
    let mut matches = Vec::new();
    for path in files(sandbox, &start) {
        let path = path?;
        let Ok(text) = text_file(sandbox, &path) else {
            continue;
        };
        for (index, line) in pytext::splitlines(&text).into_iter().enumerate() {
            if compiled
                .as_ref()
                .map_or_else(|| line.contains(pattern), |regex| regex.is_match(line))
            {
                let line = if line.chars().count() > MAX_GREP_LINE_CHARS {
                    format!("{}...", pytext::prefix(line, MAX_GREP_LINE_CHARS - 3))
                } else {
                    line.into()
                };
                matches
                    .push(json!({"path": sandbox.label(&path)?, "line": index + 1, "text": line}));
                if matches.len() >= limit {
                    return Ok(serde_json::to_string_pretty(&matches)?);
                }
            }
        }
    }
    Ok(serde_json::to_string_pretty(&matches)?)
}

fn list_symbols(sandbox: &Sandbox, args: &Map<String, Value>) -> Result<String> {
    let limit = positive_arg(args, "limit", DEFAULT_SYMBOLS_LIMIT, MAX_RESULTS)? as usize;
    let start = sandbox.resolve(string_arg(args, "path", false)?)?;
    sandbox.ensure_visible(&start)?;
    let mut rows = Vec::new();
    for path in files(sandbox, &start) {
        let path = path?;
        let Ok(text) = text_file(sandbox, &path) else {
            continue;
        };
        let label = sandbox.label(&path)?;
        for ranged in symbols::extract_ranges(&label, &text) {
            let symbol = ranged.symbol;
            rows.push(json!({"path": label, "name": symbol.name, "kind": symbol.kind, "signature": symbol.signature, "startLine": ranged.start_line, "endLine": ranged.end_line, "confidence": 0.7}));
            if rows.len() >= limit {
                return Ok(serde_json::to_string_pretty(&rows)?);
            }
        }
    }
    Ok(serde_json::to_string_pretty(&rows)?)
}

fn tree(sandbox: &Sandbox, args: &Map<String, Value>) -> Result<String> {
    let depth = positive_arg(args, "depth", DEFAULT_TREE_DEPTH, MAX_TREE_DEPTH)? as usize;
    let limit = positive_arg(args, "limit", DEFAULT_TREE_LIMIT, MAX_RESULTS)? as usize;
    let start = sandbox.resolve(string_arg(args, "path", false)?)?;
    sandbox.ensure_visible(&start)?;
    let mut output = sandbox.label(&start)?;
    let start_depth = start.strip_prefix(&sandbox.root)?.components().count();
    let deadline = Instant::now() + WALK_TIMEOUT;
    let mut count = 0;
    for entry in sandbox.walk(&start, false, Some(start_depth + depth), true) {
        ensure!(
            Instant::now() < deadline,
            "Repository traversal timed out; narrow the path"
        );
        let entry = entry.context("Cannot inspect repository tree")?;
        if entry.path() == start
            || !entry.path().starts_with(&start)
            || entry.file_type().is_none_or(|kind| kind.is_symlink())
        {
            continue;
        }
        let level = entry.path().strip_prefix(&start)?.components().count();
        let name = entry.file_name().to_str().context("Path is not UTF-8")?;
        let suffix = if entry.file_type().is_some_and(|kind| kind.is_dir()) {
            "/"
        } else {
            ""
        };
        output.push_str(&format!("\n{}{name}{suffix}", "  ".repeat(level)));
        count += 1;
        if count >= limit {
            output.push_str("\n...");
            break;
        }
    }
    Ok(output)
}
