//! Sandboxed MCP host registration. The caller supplies the home; this module never reads HOME.
use anyhow::{Context, Result, bail};
use serde::Serialize;
use serde_json::{Value, json};
use std::ffi::OsString;
use std::fs;
use std::ops::Range;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

const NAME: &str = "code-diver";
const OWNER: &str = "CODE_DIVER_REGISTRATION_OWNER";
const OWNER_VALUE: &str = "code-diver-m5b";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub enum Host {
    ClaudeCode,
    OpenCode,
    Codex,
    Gemini,
}

#[derive(Debug, Clone, Serialize)]
pub struct HostReport {
    pub host: Host,
    pub path: PathBuf,
    pub detected: bool,
    pub registered: bool,
    pub owned: bool,
    pub changed: bool,
    pub backup: Option<PathBuf>,
    pub diff: String,
    pub command: Option<String>,
    pub problem: Option<String>,
}

#[derive(Debug, Clone, Default, Serialize)]
pub struct RegistrationReport {
    pub hosts: Vec<HostReport>,
}

impl RegistrationReport {
    pub fn detected_hosts(&self) -> Vec<Host> {
        let mut hosts = Vec::new();
        for row in self.hosts.iter().filter(|h| h.detected) {
            if !hosts.contains(&row.host) {
                hosts.push(row.host);
            }
        }
        hosts
    }

    pub fn healthy(&self) -> bool {
        self.hosts
            .iter()
            .filter(|h| h.detected)
            .all(|h| h.registered && h.problem.is_none())
    }
}

/// CLI discovery is injectable, so tests need not execute anything on the user's PATH.
pub struct Registration {
    home: PathBuf,
    binary: PathBuf,
    config: PathBuf,
    dry_run: bool,
    /// Explicit CODE_DIVER_HOME override, independent of host discovery home.
    /// None preserves the runtime's default paths; never inferred from the process environment.
    pub runtime_root: Option<PathBuf>,
    pub claude_cli: Option<PathBuf>,
}

pub fn register(
    home: &Path,
    binary: &Path,
    config: &Path,
    dry_run: bool,
) -> Result<RegistrationReport> {
    Registration::new(home, binary, config, dry_run)?.register()
}

pub fn unregister(
    home: &Path,
    binary: &Path,
    config: &Path,
    dry_run: bool,
) -> Result<RegistrationReport> {
    Registration::new(home, binary, config, dry_run)?.unregister()
}

pub fn doctor(
    home: &Path,
    binary: &Path,
    config: &Path,
    dry_run: bool,
) -> Result<RegistrationReport> {
    Registration::new(home, binary, config, dry_run)?.doctor()
}

impl Registration {
    pub fn new(home: &Path, binary: &Path, config: &Path, dry_run: bool) -> Result<Self> {
        for (label, path) in [("home", home), ("binary", binary), ("config", config)] {
            if !path.is_absolute()
                || path
                    .components()
                    .any(|c| matches!(c, std::path::Component::ParentDir))
            {
                bail!("{label} must be an absolute path without parent traversal");
            }
            if path.to_str().is_none() {
                bail!("{label} must be UTF-8");
            }
        }
        safe_path(home)?;
        let claude_cli = std::env::var_os("PATH").and_then(|paths| {
            std::env::split_paths(&paths)
                .map(|p| p.join("claude"))
                .find(|p| executable(p))
        });
        Ok(Self {
            home: home.into(),
            binary: binary.into(),
            config: config.into(),
            dry_run,
            runtime_root: None,
            claude_cli,
        })
    }

    pub fn register(&self) -> Result<RegistrationReport> {
        self.run(Some(true))
    }
    pub fn unregister(&self) -> Result<RegistrationReport> {
        self.run(Some(false))
    }
    pub fn doctor(&self) -> Result<RegistrationReport> {
        self.run(None)
    }
    pub fn detected_hosts(&self) -> Result<Vec<Host>> {
        Ok(self.doctor()?.detected_hosts())
    }

    fn targets(&self) -> Result<Vec<(Host, PathBuf)>> {
        let oc = self.home.join(".config/opencode");
        safe_path(&oc)?;
        let mut targets = vec![(Host::ClaudeCode, self.home.join(".claude.json"))];
        // Update both existing variants rather than silently ignoring the lower-precedence file.
        for file in ["opencode.jsonc", "opencode.json"] {
            let path = oc.join(file);
            safe_path(&path)?;
            if path.is_file() {
                targets.push((Host::OpenCode, path));
            }
        }
        if !targets.iter().any(|(h, _)| *h == Host::OpenCode) {
            targets.push((Host::OpenCode, oc.join("opencode.jsonc")));
        }
        targets.push((Host::Codex, self.home.join(".codex/config.toml")));
        targets.push((Host::Gemini, self.home.join(".gemini/settings.json")));
        Ok(targets)
    }

    fn entry(&self, host: Host) -> Value {
        let mut env = json!({OWNER: OWNER_VALUE, "CODE_DIVER_CONFIG": self.config});
        if let Some(root) = &self.runtime_root {
            env["CODE_DIVER_HOME"] = json!(root);
        }
        if host == Host::OpenCode {
            json!({"type":"local", "command":[self.binary, "mcp", "--config", self.config], "environment":env, "enabled":true})
        } else if host == Host::ClaudeCode {
            json!({"type":"stdio", "command":self.binary, "args":["mcp", "--config", self.config], "env":env})
        } else {
            json!({"command":self.binary, "args":["mcp", "--config", self.config], "env":env})
        }
    }

    fn run(&self, action: Option<bool>) -> Result<RegistrationReport> {
        if let Some(root) = &self.runtime_root {
            if !root.is_absolute()
                || root.to_str().is_none()
                || root
                    .components()
                    .any(|c| matches!(c, std::path::Component::ParentDir))
            {
                bail!("runtime root must be an absolute UTF-8 path without parent traversal");
            }
            safe_path(root)?;
        }
        let mut report = RegistrationReport::default();
        for (host, path) in self.targets()? {
            safe_path(&path)?;
            let exists = path.is_file();
            let detected = exists
                || match host {
                    Host::ClaudeCode => self.claude_cli.is_some(),
                    Host::OpenCode => path.parent().is_some_and(Path::is_dir),
                    _ => false,
                };
            let before = if exists {
                fs::read_to_string(&path).context("read host configuration")?
            } else {
                String::new()
            };
            let desired = self.entry(host);
            let parsed = if host == Host::Codex {
                toml::from_str::<toml::Value>(if exists { &before } else { "" })
                    .map_err(|_| anyhow::anyhow!("invalid Codex TOML (contents redacted)"))
                    .and_then(|v| serde_json::to_value(v).map_err(Into::into))
            } else {
                parse_jsonc(if exists { &before } else { "{}" })
            };
            let parsed = match parsed {
                Ok(value) => value,
                Err(error) if action.is_none() => {
                    report.hosts.push(HostReport {
                        host,
                        path,
                        detected,
                        registered: false,
                        owned: false,
                        changed: false,
                        backup: None,
                        diff: String::new(),
                        command: None,
                        problem: Some(format!("{error}; fix: repair host configuration")),
                    });
                    continue;
                }
                Err(error) => return Err(error),
            };
            let key = match host {
                Host::OpenCode => "mcp",
                Host::Codex => "mcp_servers",
                _ => "mcpServers",
            };
            let existing = parsed.get(key).and_then(|v| v.get(NAME));
            let owned = existing.is_some_and(|v| self.owned(v, host));
            let registered = owned && existing == Some(&desired);
            let mut row = HostReport {
                host,
                path: path.clone(),
                detected,
                registered,
                owned,
                changed: false,
                backup: None,
                diff: String::new(),
                command: None,
                problem: None,
            };
            if existing.is_some() && !owned {
                row.problem = Some(
                    "code-diver entry is not owned by this installation; left unchanged".into(),
                );
            }
            if host == Host::ClaudeCode {
                if let Some(add) = action {
                    let args = self.claude_args(add);
                    row.command = Some(self.display_command(&args));
                    if row.problem.is_none() && ((add && !registered) || (!add && owned)) {
                        if let Some(cli) = &self.claude_cli {
                            if !self.dry_run {
                                // CLAUDE_CONFIG_DIR redirects both user state and user-scope MCP config.
                                safe_path(&self.home)?;
                                fs::create_dir_all(&self.home)?;
                                if exists {
                                    row.backup = Some(backup(&path, &before)?);
                                }
                                if add && owned {
                                    self.claude_execute(cli, &self.claude_args(false))?;
                                }
                                self.claude_execute(cli, &args)?;
                                safe_path(&path)?;
                                let after =
                                    fs::read_to_string(&path).unwrap_or_else(|_| "{}".into());
                                let value = parse_jsonc(&after)?;
                                row.registered = value["mcpServers"][NAME] == desired;
                                row.owned = self.owned(&value["mcpServers"][NAME], host);
                                row.diff = diff(
                                    &path,
                                    &before,
                                    &after,
                                    if add { Some(&desired) } else { None },
                                );
                                print!("{}", row.diff);
                                row.changed = true;
                                if (add && !row.registered) || (!add && row.owned) {
                                    row.problem = Some(
                                        "Claude CLI succeeded but registration was not verified"
                                            .into(),
                                    );
                                }
                            }
                        } else {
                            println!("{}", row.command.as_deref().unwrap());
                            row.problem =
                                Some("Claude CLI unavailable; run the printed command".into());
                        }
                    }
                }
            } else if detected
                && row.problem.is_none()
                && let Some(add) = action
                && ((add && !registered) || (!add && owned))
            {
                let source = if exists { &before } else { "{}" };
                let after = if host == Host::Codex {
                    edit_toml(&before, if add { Some(&desired) } else { None })?
                } else {
                    edit_jsonc(source, key, if add { Some(&desired) } else { None })?
                };
                row.diff = diff(
                    &path,
                    &before,
                    &after,
                    if add { Some(&desired) } else { None },
                );
                print!("{}", row.diff);
                if !self.dry_run {
                    if exists {
                        row.backup = Some(backup(&path, &before)?);
                    }
                    safe_path(&path)?;
                    fs::create_dir_all(path.parent().context("host configuration has no parent")?)?;
                    write_atomic(&path, &after)?;
                    row.changed = true;
                    row.registered = add;
                    row.owned = add;
                }
            }
            if action.is_none() && detected && !registered && row.problem.is_none() {
                row.problem =
                    Some("MCP registration missing or stale; fix: code-diver setup".into());
            }
            report.hosts.push(row);
        }
        Ok(report)
    }

    fn owned(&self, value: &Value, host: Host) -> bool {
        let env = &value[if host == Host::OpenCode {
            "environment"
        } else {
            "env"
        }];
        env[OWNER] == OWNER_VALUE
            && match &self.runtime_root {
                Some(root) => env["CODE_DIVER_HOME"] == root.to_string_lossy().as_ref(),
                None => {
                    env.get("CODE_DIVER_HOME").is_none()
                        && env["CODE_DIVER_CONFIG"] == self.config.to_string_lossy().as_ref()
                }
            }
    }

    fn claude_args(&self, add: bool) -> Vec<OsString> {
        if !add {
            return ["mcp", "remove", "--scope", "user", NAME]
                .into_iter()
                .map(Into::into)
                .collect();
        }
        let mut args: Vec<OsString> = [
            "mcp",
            "add",
            "--scope",
            "user",
            "--transport",
            "stdio",
            NAME,
            "--env",
        ]
        .into_iter()
        .map(Into::into)
        .collect();
        args.push(format!("{OWNER}={OWNER_VALUE}").into());
        for (key, path) in std::iter::once(("CODE_DIVER_CONFIG", &self.config)).chain(
            self.runtime_root
                .as_ref()
                .map(|root| ("CODE_DIVER_HOME", root)),
        ) {
            args.push("--env".into());
            args.push(format!("{key}={}", path.display()).into());
        }
        args.extend([
            OsString::from("--"),
            self.binary.as_os_str().into(),
            OsString::from("mcp"),
            OsString::from("--config"),
            self.config.as_os_str().into(),
        ]);
        args
    }

    fn display_command(&self, args: &[OsString]) -> String {
        format!(
            "CLAUDE_CONFIG_DIR={} {} {}",
            quote(&self.home.to_string_lossy()),
            quote(
                &self
                    .claude_cli
                    .as_deref()
                    .unwrap_or(Path::new("claude"))
                    .to_string_lossy()
            ),
            args.iter()
                .map(|s| quote(&s.to_string_lossy()))
                .collect::<Vec<_>>()
                .join(" ")
        )
    }

    fn claude_execute(&self, cli: &Path, args: &[OsString]) -> Result<()> {
        let mut command = Command::new(cli);
        command.env_remove("CODE_DIVER_HOME");
        if let Some(root) = &self.runtime_root {
            command.env("CODE_DIVER_HOME", root);
        }
        let status = command
            .args(args)
            .current_dir(&self.home)
            .env("CLAUDE_CONFIG_DIR", &self.home)
            // Host output can contain credentials: never surface it in errors or logs.
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .status()
            .context("execute Claude MCP command")?;
        if !status.success() {
            bail!("Claude MCP command failed ({status}); configuration backup retained");
        }
        Ok(())
    }
}

fn quote(s: &str) -> String {
    format!("'{}'", s.replace('\'', "'\\''"))
}

fn executable(path: &Path) -> bool {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::metadata(path).is_ok_and(|m| m.is_file() && m.permissions().mode() & 0o111 != 0)
    }
    #[cfg(not(unix))]
    {
        path.is_file()
    }
}

fn safe_path(path: &Path) -> Result<()> {
    for ancestor in path.ancestors() {
        match fs::symlink_metadata(ancestor) {
            Ok(m) if m.file_type().is_symlink() => {
                bail!("refusing symlink in host configuration path")
            }
            Ok(_) => (),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => (),
            Err(e) => return Err(e.into()),
        }
    }
    Ok(())
}

fn backup(path: &Path, source: &str) -> Result<PathBuf> {
    let timestamp = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
    let backup = path.with_file_name(format!(
        "{}.backup-{timestamp}",
        path.file_name()
            .context("missing filename")?
            .to_string_lossy()
    ));
    let mut options = fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    use std::io::Write;
    options.open(&backup)?.write_all(source.as_bytes())?;
    println!("backup: {}", backup.display());
    Ok(backup)
}

fn write_atomic(path: &Path, source: &str) -> Result<()> {
    use std::io::Write;
    let timestamp = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
    let temporary = path.with_file_name(format!(
        ".{}.registration-{timestamp}",
        path.file_name()
            .context("missing filename")?
            .to_string_lossy()
    ));
    let mut options = fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
        options.mode(fs::metadata(path).map_or(0o600, |m| m.permissions().mode() & 0o777));
    }
    let mut file = options.open(&temporary)?;
    let result = (|| -> Result<()> {
        file.write_all(source.as_bytes())?;
        file.sync_all()?;
        safe_path(path)?;
        fs::rename(&temporary, path)?;
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    result
}

fn diff(path: &Path, before: &str, after: &str, entry: Option<&Value>) -> String {
    // Never print source text, including old owned entries or neighboring inline fields.
    let old: Vec<_> = before.lines().collect();
    let new: Vec<_> = after.lines().collect();
    let prefix = old.iter().zip(&new).take_while(|(a, b)| a == b).count();
    let suffix = old[prefix..]
        .iter()
        .rev()
        .zip(new[prefix..].iter().rev())
        .take_while(|(a, b)| a == b)
        .count();
    // Redact line bodies: an existing owned entry may itself have acquired credentials.
    let additions = entry.map_or_else(
        || "+ [owned MCP entry removed]\n".into(),
        |v| {
            serde_json::to_string_pretty(&json!({NAME:v}))
                .unwrap()
                .lines()
                .map(|line| format!("+ {line}\n"))
                .collect::<String>()
        },
    );
    format!(
        "--- {}\n+++ {}\n@@ -{},{} +{},{} @@\n- [previous owned MCP entry redacted]\n{}",
        path.display(),
        path.display(),
        prefix + 1,
        old.len() - prefix - suffix,
        prefix + 1,
        new.len() - prefix - suffix,
        additions
    )
}

/// Replace comments and trailing commas by spaces; offsets remain identical to the original.
fn clean_jsonc(source: &str) -> Result<String> {
    let mut bytes = source.as_bytes().to_vec();
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'"' {
            i += 1;
            while i < bytes.len() {
                if bytes[i] == b'\\' {
                    i += 2;
                } else if bytes[i] == b'"' {
                    i += 1;
                    break;
                } else {
                    i += 1;
                }
            }
        } else if bytes[i..].starts_with(b"//") {
            while i < bytes.len() && bytes[i] != b'\n' {
                bytes[i] = b' ';
                i += 1;
            }
        } else if bytes[i..].starts_with(b"/*") {
            bytes[i] = b' ';
            bytes[i + 1] = b' ';
            i += 2;
            while i + 1 < bytes.len() && !bytes[i..].starts_with(b"*/") {
                if bytes[i] != b'\n' && bytes[i] != b'\r' {
                    bytes[i] = b' ';
                }
                i += 1;
            }
            if i + 1 >= bytes.len() {
                bail!("unterminated JSONC comment");
            }
            bytes[i] = b' ';
            bytes[i + 1] = b' ';
            i += 2;
        } else {
            i += 1;
        }
    }
    i = 0;
    while i < bytes.len() {
        if bytes[i] == b'"' {
            i += 1;
            while i < bytes.len() {
                if bytes[i] == b'\\' {
                    i += 2;
                } else if bytes[i] == b'"' {
                    i += 1;
                    break;
                } else {
                    i += 1;
                }
            }
        } else {
            if bytes[i] == b',' {
                let next = bytes[i + 1..]
                    .iter()
                    .copied()
                    .find(|b| !b.is_ascii_whitespace());
                if matches!(next, Some(b'}' | b']')) {
                    bytes[i] = b' ';
                }
            }
            i += 1;
        }
    }
    Ok(String::from_utf8(bytes)?)
}

fn parse_jsonc(source: &str) -> Result<Value> {
    let clean = clean_jsonc(source)?;
    let value: Value = serde_json::from_str(&clean)
        .map_err(|_| anyhow::anyhow!("invalid host JSON/JSONC (contents redacted)"))?;
    if !value.is_object() {
        bail!("host configuration must be an object");
    }
    let start = clean
        .as_bytes()
        .iter()
        .position(|b| !b.is_ascii_whitespace())
        .context("empty JSON")?;
    validate_members(&clean, start)?;
    Ok(value)
}

fn validate_members(clean: &str, start: usize) -> Result<()> {
    if clean.as_bytes()[start] == b'{' {
        for member in members(clean, start)?.0 {
            validate_members(clean, member.value.start)?;
        }
    } else if clean.as_bytes()[start] == b'[' {
        let mut i = start + 1;
        loop {
            skip(clean.as_bytes(), &mut i);
            if clean.as_bytes()[i] == b']' {
                break;
            }
            validate_members(clean, i)?;
            i = value_end(clean.as_bytes(), i);
            skip(clean.as_bytes(), &mut i);
            if clean.as_bytes()[i] == b',' {
                i += 1;
            }
        }
    }
    Ok(())
}

#[derive(Debug)]
struct Member {
    key: String,
    key_start: usize,
    value: Range<usize>,
    comma: Option<usize>,
}

fn skip(bytes: &[u8], i: &mut usize) {
    while *i < bytes.len() && bytes[*i].is_ascii_whitespace() {
        *i += 1;
    }
}

fn value_end(bytes: &[u8], start: usize) -> usize {
    let mut i = start;
    let mut depth = 0;
    while i < bytes.len() {
        match bytes[i] {
            b'"' => {
                i += 1;
                while i < bytes.len() {
                    if bytes[i] == b'\\' {
                        i += 2;
                    } else if bytes[i] == b'"' {
                        i += 1;
                        break;
                    } else {
                        i += 1;
                    }
                }
                if depth == 0 {
                    return i;
                }
                continue;
            }
            b'{' | b'[' => depth += 1,
            b'}' | b']' if depth == 0 => break,
            b'}' | b']' => {
                depth -= 1;
                if depth == 0 {
                    return i + 1;
                }
            }
            b',' if depth == 0 => break,
            b if b.is_ascii_whitespace() && depth == 0 => break,
            _ => (),
        }
        i += 1;
    }
    i
}

fn members(clean: &str, start: usize) -> Result<(Vec<Member>, usize)> {
    let bytes = clean.as_bytes();
    if bytes.get(start) != Some(&b'{') {
        bail!("MCP settings must be an object");
    }
    let mut i = start + 1;
    let mut result = Vec::new();
    loop {
        skip(bytes, &mut i);
        if bytes.get(i) == Some(&b'}') {
            return Ok((result, i));
        }
        let key_start = i;
        let key_end = value_end(bytes, i);
        let key: String = serde_json::from_str(&clean[i..key_end])?;
        i = key_end;
        skip(bytes, &mut i);
        if bytes.get(i) != Some(&b':') {
            bail!("missing JSON member colon");
        }
        i += 1;
        skip(bytes, &mut i);
        let start = i;
        i = value_end(bytes, i);
        let end = i;
        skip(bytes, &mut i);
        let comma = if bytes.get(i) == Some(&b',') {
            let pos = i;
            i += 1;
            Some(pos)
        } else {
            None
        };
        if result.iter().any(|m: &Member| m.key == key) {
            bail!("duplicate JSON member is unsafe to edit");
        }
        result.push(Member {
            key,
            key_start,
            value: start..end,
            comma,
        });
    }
}

fn splice(source: &str, range: Range<usize>, replacement: &str) -> String {
    format!(
        "{}{}{}",
        &source[..range.start],
        replacement,
        &source[range.end..]
    )
}

fn edit_jsonc(source: &str, container: &str, desired: Option<&Value>) -> Result<String> {
    parse_jsonc(source)?;
    let clean = clean_jsonc(source)?;
    let start = clean
        .as_bytes()
        .iter()
        .position(|b| !b.is_ascii_whitespace())
        .context("empty JSON")?;
    let (root, close) = members(&clean, start)?;
    let after = if let Some(parent) = root.iter().find(|m| m.key == container) {
        let (entries, end) = members(&clean, parent.value.start)?;
        if let Some(index) = entries.iter().position(|m| m.key == NAME) {
            let entry = &entries[index];
            if let Some(value) = desired {
                splice(
                    source,
                    entry.value.clone(),
                    &serde_json::to_string_pretty(value)?,
                )
            } else {
                // Remove tokens separately to retain comments around the owned member.
                let trivia: Vec<u8> = source.as_bytes()[entry.key_start..entry.value.end]
                    .iter()
                    .zip(&clean.as_bytes()[entry.key_start..entry.value.end])
                    .filter_map(|(original, sanitized)| {
                        sanitized.is_ascii_whitespace().then_some(*original)
                    })
                    .collect();
                let trivia = String::from_utf8(trivia)?;
                let after = splice(source, entry.key_start..entry.value.end, &trivia);
                let removed = entry.value.end - entry.key_start - trivia.len();
                let comma = entry.comma.or_else(|| {
                    trivia_comma(&source[entry.value.end..end]).map(|i| entry.value.end + i)
                });
                if let Some(comma) = comma {
                    splice(&after, comma - removed..comma - removed + 1, "")
                } else if index > 0 {
                    let comma = entries[index - 1]
                        .comma
                        .context("missing member separator")?;
                    splice(&after, comma..comma + 1, "")
                } else {
                    after
                }
            }
        } else if let Some(value) = desired {
            insert_member(source, &entries, end, NAME, value)?
        } else {
            source.into()
        }
    } else if let Some(value) = desired {
        insert_member(source, &root, close, container, &json!({NAME:value}))?
    } else {
        source.into()
    };
    parse_jsonc(&after).context("edited JSONC failed validation")?;
    Ok(after)
}

fn insert_member(
    source: &str,
    entries: &[Member],
    close: usize,
    name: &str,
    value: &Value,
) -> Result<String> {
    // The clean view erases a trailing comma; inspect original trivia for that comma.
    let trailing = entries
        .last()
        .is_some_and(|m| trivia_comma(&source[m.value.end..close]).is_some());
    let mut after = source.to_owned();
    let mut end = close;
    if let Some(last) = entries.last()
        && !trailing
    {
        after.insert(last.value.end, ',');
        end += 1;
    }
    let text = format!(
        "\n    {}: {}{}\n",
        serde_json::to_string(name)?,
        serde_json::to_string_pretty(value)?,
        if trailing { "," } else { "" }
    );
    after.insert_str(end, &text);
    Ok(after)
}

fn trivia_comma(source: &str) -> Option<usize> {
    // Wrapping in an object keeps a trivia comma from being treated as trailing.
    clean_jsonc(&format!("{{{source}\"sentinel\":0}}"))
        .ok()?
        .as_bytes()[1..source.len() + 1]
        .iter()
        .position(|b| *b == b',')
}

fn table_path(header: &str) -> Option<Vec<String>> {
    let parsed: toml::Value =
        toml::from_str(&format!("{header}\n__registration_probe = true\n")).ok()?;
    let mut node = &parsed;
    let mut path = Vec::new();
    loop {
        let table = node.as_table()?;
        if table.contains_key("__registration_probe") {
            return Some(path);
        }
        if table.len() != 1 {
            return None;
        }
        let (key, child) = table.iter().next()?;
        path.push(key.clone());
        node = child;
    }
}

fn toml_string_state(line: &str, state: &mut Option<(u8, bool)>) {
    let bytes = line.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        if let Some((quote, multiline)) = *state {
            if quote == b'"' && bytes[i] == b'\\' {
                i += 2;
                continue;
            }
            if bytes[i] == quote {
                let count = bytes[i..].iter().take_while(|b| **b == quote).count();
                if !multiline || count >= 3 {
                    *state = None;
                    i += if multiline { count } else { 1 };
                    continue;
                }
            }
        } else {
            match bytes[i] {
                b'#' => break,
                quote @ (b'\'' | b'"') => {
                    let multiline = bytes[i..].iter().take_while(|b| **b == quote).count() >= 3;
                    *state = Some((quote, multiline));
                    i += if multiline { 3 } else { 1 };
                    continue;
                }
                _ => (),
            }
        }
        i += 1;
    }
}

fn toml_boundary(source: &str, start: usize, end: usize, stops: &[u8]) -> usize {
    let b = source.as_bytes();
    let mut i = start;
    let mut depth = 0;
    while i < end {
        if depth == 0 && stops.contains(&b[i]) {
            break;
        }
        match b[i] {
            b'\'' | b'"' => {
                let quote = b[i];
                let triple = b[i..end].starts_with(&[quote; 3]);
                i += if triple { 3 } else { 1 };
                while i < end {
                    if quote == b'"' && b[i] == b'\\' {
                        i = (i + 2).min(end);
                        continue;
                    }
                    if b[i] == quote && (!triple || b[i..end].starts_with(&[quote; 3])) {
                        i += if triple { 3 } else { 1 };
                        break;
                    }
                    i += 1;
                }
                continue;
            }
            b'#' => {
                while i < end && b[i] != b'\n' {
                    i += 1;
                }
                continue;
            }
            b'{' | b'[' => depth += 1,
            b'}' | b']' => depth -= 1,
            _ => (),
        }
        i += 1;
    }
    i
}

struct TomlMember {
    path: Vec<String>,
    member: Range<usize>,
    value: Range<usize>,
    inline: bool,
}

fn toml_members(
    source: &str,
    range: Range<usize>,
    parent: &[String],
    inline: bool,
    out: &mut Vec<TomlMember>,
) -> Result<()> {
    let mut i = range.start;
    let mut table = parent.to_vec();
    while i < range.end {
        while i < range.end
            && (source.as_bytes()[i].is_ascii_whitespace() || source.as_bytes()[i] == b',')
        {
            i += 1;
        }
        if i == range.end {
            break;
        }
        if source.as_bytes()[i] == b'#' {
            i = source[i..range.end]
                .find('\n')
                .map_or(range.end, |n| i + n + 1);
            continue;
        }
        if !inline && source.as_bytes()[i] == b'[' {
            let end = source[i..range.end].find('\n').map_or(range.end, |n| i + n);
            table = table_path(&source[i..end])
                .unwrap_or_else(|| vec!["__unrelated_array_table".into()]);
            i = end;
            continue;
        }
        let eq = toml_boundary(source, i, range.end, b"=");
        if eq == range.end {
            bail!("cannot locate Codex assignment (contents redacted)");
        }
        let key = source[i..eq].trim();
        let path =
            table_path(&format!("[{key}]")).context("invalid Codex key (contents redacted)")?;
        let mut full = table.clone();
        full.extend(path);
        let start =
            eq + 1 + source[eq + 1..range.end].len() - source[eq + 1..range.end].trim_start().len();
        let end = toml_boundary(
            source,
            start,
            range.end,
            if inline { b",\n#" } else { b"\n#" },
        );
        let value_end = start + source[start..end].trim_end().len();
        if source.as_bytes().get(start) == Some(&b'{') {
            toml_members(source, start + 1..value_end - 1, &full, true, out)?;
        }
        out.push(TomlMember {
            path: full,
            member: i..value_end,
            value: start..value_end,
            inline,
        });
        i = end;
    }
    Ok(())
}

fn inline_toml(value: &Value) -> Result<String> {
    Ok(match value {
        Value::Object(map) => format!(
            "{{ {} }}",
            map.iter()
                .map(|(key, v)| Ok(format!(
                    "{} = {}",
                    serde_json::to_string(key)?,
                    inline_toml(v)?
                )))
                .collect::<Result<Vec<_>>>()?
                .join(", ")
        ),
        Value::Array(values) => format!(
            "[{}]",
            values
                .iter()
                .map(inline_toml)
                .collect::<Result<Vec<_>>>()?
                .join(", ")
        ),
        _ => serde_json::to_string(value)?,
    })
}

fn edit_toml(source: &str, desired: Option<&Value>) -> Result<String> {
    let parsed: toml::Value = toml::from_str(source)
        .map_err(|_| anyhow::anyhow!("invalid Codex TOML (contents redacted)"))?;
    let mut ranges = Vec::new();
    let mut offset = 0;
    let mut headers = Vec::new();
    let mut string_state = None;
    for line in source.split_inclusive('\n') {
        if string_state.is_none() && line.trim_start().starts_with('[') {
            if let Some(path) = table_path(line.trim()) {
                headers.push((offset, path));
            } else if toml::from_str::<toml::Value>(&format!(
                "{}\n__registration_probe=true",
                line.trim()
            ))
            .is_ok()
            {
                // Array-of-table headers are boundaries too, never part of the owned table.
                headers.push((offset, Vec::new()));
            }
        }
        toml_string_state(line, &mut string_state);
        offset += line.len();
    }
    for (index, (start, path)) in headers.iter().enumerate() {
        if path.len() >= 2 && path[0] == "mcp_servers" && path[1] == NAME {
            ranges.push(*start..headers.get(index + 1).map_or(source.len(), |(s, _)| *s));
        }
    }
    let mut after = source.to_owned();
    let mut members = Vec::new();
    toml_members(source, 0..source.len(), &[], false, &mut members)?;
    let owned = members.iter().find(|m| m.path == ["mcp_servers", NAME]);
    let container = members
        .iter()
        .find(|m| m.path == ["mcp_servers"] && source.as_bytes()[m.value.start] == b'{');
    let mut handled = false;
    if let Some(member) = owned {
        handled = true;
        if let Some(value) = desired {
            after.replace_range(member.value.clone(), &inline_toml(value)?);
        } else {
            let mut range = member.member.clone();
            if member.inline {
                let close = container
                    .context("missing Codex inline container")?
                    .value
                    .end
                    - 1;
                let following = toml_boundary(source, range.end, close, b",");
                if following < close {
                    after.remove(following);
                } else if let Some(previous) = members
                    .iter()
                    .filter(|m| {
                        m.inline
                            && m.path.len() == 2
                            && m.path[0] == "mcp_servers"
                            && m.value.end < range.start
                    })
                    .max_by_key(|m| m.value.end)
                {
                    let comma = toml_boundary(source, previous.value.end, range.start, b",");
                    if comma < range.start {
                        after.remove(comma);
                        range.start -= 1;
                        range.end -= 1;
                    }
                }
            }
            after.replace_range(range, "");
        }
    } else if let (Some(container), Some(value)) = (container, desired) {
        handled = true;
        let close = container.value.end - 1;
        let last = members
            .iter()
            .filter(|m| m.path.len() == 2 && m.path[0] == "mcp_servers")
            .max_by_key(|m| m.value.end);
        let (position, prefix, suffix) = if let Some(last) = last {
            let comma = toml_boundary(source, last.value.end, close, b",");
            if comma < close {
                (comma + 1, " ", ",")
            } else {
                (last.value.end, ", ", "")
            }
        } else {
            (container.value.start + 1, " ", " ")
        };
        after.insert_str(
            position,
            &format!(
                "{}{} = {}{}",
                prefix,
                serde_json::to_string(NAME)?,
                inline_toml(value)?,
                suffix
            ),
        );
    }
    for range in ranges.into_iter().rev() {
        after.replace_range(range, "");
    }
    if let Some(value) = desired.filter(|_| !handled) {
        if !after.is_empty() && !after.ends_with('\n') {
            after.push('\n');
        }
        let table: toml::Value = serde_json::from_value(json!({"mcp_servers":{NAME:value}}))?;
        after.push_str(&toml::to_string_pretty(&table)?);
    }
    let edited: toml::Value = toml::from_str(&after)
        .map_err(|_| anyhow::anyhow!("edited Codex TOML failed validation (contents redacted)"))?;
    let mut original = parsed;
    let mut preserved = edited;
    for value in [&mut original, &mut preserved] {
        if let Some(servers) = value
            .get_mut("mcp_servers")
            .and_then(toml::Value::as_table_mut)
        {
            servers.remove(NAME);
            if servers.is_empty() {
                value.as_table_mut().unwrap().remove("mcp_servers");
            }
        }
    }
    if original != preserved {
        bail!("Codex edit would change unrelated settings");
    }
    Ok(after)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_registration_does_not_override_runtime_home() {
        let (_dir, reg) = sandbox();
        for host in [Host::ClaudeCode, Host::OpenCode, Host::Codex, Host::Gemini] {
            let entry = reg.entry(host);
            let env = &entry[if host == Host::OpenCode {
                "environment"
            } else {
                "env"
            }];
            assert!(env.get("CODE_DIVER_HOME").is_none());
            assert_eq!(env["CODE_DIVER_CONFIG"], json!(reg.config));
            assert_eq!(env.as_object().unwrap().len(), 2);
        }
        assert!(
            !reg.display_command(&reg.claude_args(true))
                .contains("CODE_DIVER_HOME")
        );
    }

    #[test]
    fn runtime_root_separate_from_host_home_and_uninstall_identity() {
        for isolated in [false, true] {
            let (_dir, mut reg) = sandbox();
            let root = reg.home.join("runtime");
            reg.config = root.join("config.toml");
            reg.runtime_root = isolated.then(|| root.clone());
            let source = "# keep\nsecret='SECRET_SENTINEL'\n[mcp_servers.other]\ncommand='other'\n";
            let path = put(&reg, ".codex/config.toml", source);
            let report = reg.register().unwrap();
            let row = report.hosts.iter().find(|h| h.host == Host::Codex).unwrap();
            assert_eq!(row.path, path);
            assert_eq!(
                fs::read_to_string(row.backup.as_ref().unwrap()).unwrap(),
                source
            );
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                assert_eq!(
                    fs::metadata(row.backup.as_ref().unwrap())
                        .unwrap()
                        .permissions()
                        .mode()
                        & 0o777,
                    0o600
                );
            }
            assert!(!row.diff.contains("SECRET_SENTINEL"));
            assert!(!root.join(".codex").exists());
            assert!(reg.doctor().unwrap().healthy());
            let entry = reg.entry(Host::Codex);
            assert_eq!(
                entry["env"].get("CODE_DIVER_HOME"),
                isolated.then(|| json!(root)).as_ref()
            );
            let before = fs::read_to_string(&path).unwrap();
            reg.runtime_root = Some(reg.home.join("different-runtime"));
            assert!(!reg.unregister().unwrap().hosts.iter().any(|h| h.changed));
            assert_eq!(fs::read_to_string(&path).unwrap(), before);
            reg.runtime_root = isolated.then(|| root.clone());
            if !isolated {
                reg.config = root.join("different-config.toml");
                assert!(!reg.unregister().unwrap().hosts.iter().any(|h| h.changed));
                reg.config = root.join("config.toml");
            }
            reg.unregister().unwrap();
            assert_eq!(fs::read_to_string(&path).unwrap(), source);
        }
    }

    #[test]
    fn invalid_runtime_root_rejected_before_host_edits() {
        let (_dir, mut reg) = sandbox();
        let path = put(&reg, ".codex/config.toml", "# keep\n");
        for root in [PathBuf::from("relative"), reg.home.join("../escape")] {
            reg.runtime_root = Some(root);
            assert!(reg.register().is_err());
            assert!(reg.unregister().is_err());
            assert_eq!(fs::read_to_string(&path).unwrap(), "# keep\n");
        }
    }

    fn sandbox() -> (tempfile::TempDir, Registration) {
        // Canonicalization avoids macOS's /var -> /private/var symlink.
        let dir = tempfile::tempdir().unwrap();
        let home = fs::canonicalize(dir.path()).unwrap();
        let mut registration = Registration::new(
            &home,
            &home.join("bin/code diver"),
            &home.join("private/config.toml"),
            false,
        )
        .unwrap();
        registration.claude_cli = None;
        (dir, registration)
    }

    fn put(reg: &Registration, relative: &str, text: &str) -> PathBuf {
        let path = reg.home.join(relative);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(&path, text).unwrap();
        path
    }

    #[test]
    fn jsonc_difficult_cases_preserve_unrelated_bytes() {
        for source in [
            "{/* café , */\"url\":\"https://a/*b*/\\\"c\",\"list\":[1,2,],}",
            "{\"mcp\": {/* keep */ \"other\": {\"command\":[\"x\",],}, // keep too\n},\"theme\":\"夜\",}",
            "{\"mcp\":{\"other\":false /* , not a separator */},\"last\":true}",
            "{\"mcp\":{/* empty, */},\"arr\":[{},[1,],],}",
            "{\"mcp\":{\"other\":{} // comma, in comment\n}}",
        ] {
            let expected = parse_jsonc(source).unwrap();
            let inserted =
                edit_jsonc(source, "mcp", Some(&json!({"command":["/a","mcp"]}))).unwrap();
            assert_eq!(
                parse_jsonc(&inserted).unwrap()["mcp"][NAME]["command"][0],
                "/a"
            );
            let removed = edit_jsonc(&inserted, "mcp", None).unwrap();
            let mut actual = parse_jsonc(&removed).unwrap();
            if expected.get("mcp").is_none() {
                actual.as_object_mut().unwrap().remove("mcp");
            }
            assert_eq!(actual, expected);
            for comment in [
                "/* café , */",
                "/* keep */",
                "// keep too",
                "/* , not a separator */",
                "/* empty, */",
                "// comma, in comment",
            ] {
                if source.contains(comment) {
                    assert!(removed.contains(comment));
                }
            }
            assert!(removed.contains("\"theme\":\"夜\"") || !source.contains("\"theme\":\"夜\""));
        }
    }

    #[test]
    fn removal_first_middle_last_and_trailing_comma() {
        for body in [
            "\"code-diver\":{},\"a\":1",
            "\"a\":1,\"code-diver\":{},\"b\":2",
            "\"a\":1,\"code-diver\":{}",
            "\"a\":1,\"code-diver\":{}, /* tail */",
            "\"code-diver\":{}, /* tail */",
        ] {
            let source = format!("{{\"mcp\":{{{body}}}}}");
            let removed = edit_jsonc(&source, "mcp", None).unwrap();
            let actual = parse_jsonc(&removed).unwrap();
            assert!(actual["mcp"].get(NAME).is_none());
            if body.contains("\"a\"") {
                assert_eq!(actual["mcp"]["a"], 1);
            }
        }
    }

    #[test]
    fn files_additive_backup_idempotent_repair_doctor_uninstall() {
        let (_dir, mut reg) = sandbox();
        let oc = put(
            &reg,
            ".config/opencode/opencode.jsonc",
            "{/* keep */\"theme\":\"dark\",\"mcp\":{\"other\":{\"type\":\"remote\"},},}",
        );
        let codex = put(
            &reg,
            ".codex/config.toml",
            "# personal\nmodel = \"gpt\"\n[mcp_servers.other]\ncommand = \"other\"\n",
        );
        let gemini = put(
            &reg,
            ".gemini/settings.json",
            "{\"theme\":\"dark\",\"mcpServers\":{\"other\":{\"command\":\"x\"}}}",
        );
        assert!(!reg.doctor().unwrap().healthy());
        let result = reg.register().unwrap();
        assert_eq!(
            result.detected_hosts(),
            vec![Host::OpenCode, Host::Codex, Host::Gemini]
        );
        for row in result.hosts.iter().filter(|h| h.detected) {
            assert!(row.changed && row.registered);
            assert!(row.backup.as_ref().unwrap().is_file());
            assert!(!row.diff.is_empty());
        }
        assert!(reg.doctor().unwrap().healthy());
        let before = fs::read_to_string(&oc).unwrap();
        assert!(before.contains("/* keep */"));
        assert!(!reg.register().unwrap().hosts.iter().any(|h| h.changed));
        assert_eq!(before, fs::read_to_string(&oc).unwrap());
        reg.binary = reg.home.join("new-binary");
        assert!(!reg.doctor().unwrap().healthy());
        assert_eq!(
            reg.register()
                .unwrap()
                .hosts
                .iter()
                .filter(|h| h.changed)
                .count(),
            3
        );
        reg.unregister().unwrap();
        assert!(
            fs::read_to_string(&codex)
                .unwrap()
                .contains("[mcp_servers.other]\ncommand = \"other\"")
        );
        assert_eq!(
            parse_jsonc(&fs::read_to_string(&gemini).unwrap()).unwrap()["theme"],
            "dark"
        );
        assert!(
            parse_jsonc(&fs::read_to_string(&oc).unwrap()).unwrap()["mcp"]
                .get(NAME)
                .is_none()
        );
        assert!(!reg.unregister().unwrap().hosts.iter().any(|h| h.changed));
    }

    #[test]
    fn dry_run_no_backups_or_writes_or_cli() {
        let (_dir, mut reg) = sandbox();
        let path = put(
            &reg,
            ".config/opencode/opencode.jsonc",
            "{\"secret\":\"DO_NOT_PRINT\"}",
        );
        reg.dry_run = true;
        let result = reg.register().unwrap();
        assert!(
            result
                .hosts
                .iter()
                .all(|h| !h.changed && h.backup.is_none())
        );
        assert!(
            result
                .hosts
                .iter()
                .all(|h| !h.diff.contains("DO_NOT_PRINT"))
        );
        assert_eq!(
            fs::read_to_string(path).unwrap(),
            "{\"secret\":\"DO_NOT_PRINT\"}"
        );
        assert_eq!(
            fs::read_dir(reg.home.join(".config/opencode"))
                .unwrap()
                .count(),
            1
        );
        assert!(!reg.home.join(".claude.json").exists());
        let command = result.hosts[0].command.as_ref().unwrap();
        assert!(command.contains("'mcp' 'add' '--scope' 'user'"));
        assert!(command.contains("CLAUDE_CONFIG_DIR="));
        assert!(command.contains("'--'"));
    }

    #[test]
    fn unowned_entries_and_absent_hosts_untouched() {
        let (_dir, reg) = sandbox();
        let path = put(
            &reg,
            ".config/opencode/opencode.jsonc",
            "{\"mcp\":{\"code-diver\":{\"command\":[\"mine\"]}}}",
        );
        let before = fs::read_to_string(&path).unwrap();
        assert!(reg.register().unwrap().hosts[1].problem.is_some());
        reg.unregister().unwrap();
        assert_eq!(before, fs::read_to_string(path).unwrap());
        assert!(!reg.home.join(".codex").exists());
        assert!(!reg.home.join(".gemini").exists());
    }

    #[test]
    fn malformed_and_duplicate_jsonc_rejected() {
        for source in [
            "{ /* unfinished",
            "{\"mcp\":1}",
            "{\"mcp\":{},\"mcp\":{}}",
            "{\"mcp\":{\"x\":{},\"x\":{}}}",
        ] {
            assert!(
                edit_jsonc(source, "mcp", Some(&json!({}))).is_err(),
                "{source}"
            );
        }
    }

    #[test]
    fn toml_quoted_headers_and_unrelated_sections_preserved() {
        let entry = json!({"command":"/binary", "args":["mcp"], "env":{OWNER:OWNER_VALUE}});
        let source =
            "# user\nmodel='x'\n[mcp_servers.'other'] # comment\ncommand='y'\n[features]\na=true\n";
        let added = edit_toml(source, Some(&entry)).unwrap();
        assert!(added.starts_with(source));
        let repaired = edit_toml(&added, Some(&entry)).unwrap();
        assert_eq!(added, repaired);
        assert_eq!(edit_toml(&added, None).unwrap(), source);
    }

    #[test]
    fn codex_inline_tables_add_repair_remove_and_preserve_others() {
        let entry = json!({"command":"/binary", "args":["mcp"], "env":{OWNER:OWNER_VALUE}});
        for source in [
            "# keep\nsecret='SECRET_SENTINEL'\nmcp_servers = { other = { command = 'x,}=', token = 'SECRET_SENTINEL' } } # tail\n",
            "mcp_servers = {}\n",
            "mcp_servers = {\n# SECRET_SENTINEL\nother = { command = 'x' }, # keep\n}\n",
            "mcp_servers = {\n# keep\n}\n",
            "mcp_servers = { code-diver = { command = 'old' } # keep\n, other = { command = 'x' } }\n",
            "[mcp_servers]\n'code-diver' = { command = 'old', env = { CODE_DIVER_REGISTRATION_OWNER = 'code-diver-m5b' } } # keep\nother = { command = 'x' }\n",
            "mcp_servers.'code-diver' = { command = 'old' }\n[mcp_servers.other]\ncommand='x'\n",
            "mcp_servers = { 'code-diver' = { command = 'old' }, other = { command = 'x' } }\n",
            "mcp_servers = { other = { command = 'x' }, 'code-diver' = { command = 'old' } }\n",
        ] {
            let added = edit_toml(source, Some(&entry)).unwrap();
            assert_eq!(edit_toml(&added, Some(&entry)).unwrap(), added);
            let parsed: toml::Value = toml::from_str(&added).unwrap();
            assert_eq!(
                parsed["mcp_servers"][NAME]["command"].as_str(),
                Some("/binary")
            );
            let removed = edit_toml(&added, None).unwrap();
            let parsed: toml::Value = toml::from_str(&removed).unwrap();
            assert!(
                parsed
                    .get("mcp_servers")
                    .and_then(|v| v.get(NAME))
                    .is_none()
            );
            if source.contains("# keep") {
                assert!(removed.contains("# keep"));
            }
            assert!(
                !diff(Path::new("config.toml"), source, &added, Some(&entry))
                    .contains("SECRET_SENTINEL")
            );
        }
    }

    #[test]
    fn codex_inline_registration_backup_dry_run_and_negative_cases() {
        let (_dir, mut reg) = sandbox();
        let source = "secret='SECRET_SENTINEL'\nmcp_servers = { other = { command = 'x' } }\n";
        let path = put(&reg, ".codex/config.toml", source);
        reg.dry_run = true;
        let report = reg.register().unwrap();
        assert_eq!(fs::read_to_string(&path).unwrap(), source);
        assert!(report.hosts.iter().all(|h| h.backup.is_none()));
        reg.dry_run = false;
        let report = reg.register().unwrap();
        let row = report.hosts.iter().find(|h| h.host == Host::Codex).unwrap();
        assert_eq!(
            fs::read_to_string(row.backup.as_ref().unwrap()).unwrap(),
            source
        );
        assert!(!row.diff.contains("SECRET_SENTINEL"));
        assert!(!reg.register().unwrap().hosts.iter().any(|h| h.changed));
        reg.unregister().unwrap();
        for source in [
            "mcp_servers = { code-diver = { command = 'SECRET_SENTINEL' }",
            "mcp_servers = { x = {}, x = {} }",
            "mcp_servers = 'SECRET_SENTINEL'",
        ] {
            fs::write(&path, source).unwrap();
            assert!(reg.register().is_err());
            assert_eq!(fs::read_to_string(&path).unwrap(), source);
        }
        let source = "mcp_servers = { code-diver = { command = 'unowned' } }\n";
        fs::write(&path, source).unwrap();
        reg.register().unwrap();
        reg.unregister().unwrap();
        assert_eq!(fs::read_to_string(path).unwrap(), source);
    }

    #[test]
    fn diffs_never_expose_original_owned_or_unrelated_secrets() {
        let (_dir, reg) = sandbox();
        let source = "secret='UNRELATED_SECRET_SENTINEL'\nmcp_servers = { code-diver = { command = 'old', env = { CODE_DIVER_REGISTRATION_OWNER = 'code-diver-m5b', TOKEN = 'OWNED_SECRET_SENTINEL' } }, other = { token = 'OTHER_SECRET_SENTINEL' } } # COMMENT_SECRET_SENTINEL\n";
        let source = source.replace(
            "TOKEN =",
            &format!(
                "CODE_DIVER_CONFIG = {}, TOKEN =",
                serde_json::to_string(&reg.config).unwrap()
            ),
        );
        let path = put(&reg, ".codex/config.toml", &source);
        let report = reg.register().unwrap();
        let row = report.hosts.iter().find(|h| h.host == Host::Codex).unwrap();
        assert!(row.changed);
        assert!(!row.diff.contains("SECRET_SENTINEL"));
        let after = fs::read_to_string(&path).unwrap();
        for secret in [
            "UNRELATED_SECRET_SENTINEL",
            "OTHER_SECRET_SENTINEL",
            "COMMENT_SECRET_SENTINEL",
        ] {
            assert!(after.contains(secret));
        }
        let report = reg.unregister().unwrap();
        assert!(
            report
                .hosts
                .iter()
                .all(|h| !h.diff.contains("SECRET_SENTINEL"))
        );
    }

    #[test]
    fn doctor_collects_malformed_host_failures_without_exposing_secrets() {
        let (_dir, reg) = sandbox();
        put(&reg, ".codex/config.toml", "key = SECRET_SENTINEL invalid");
        put(
            &reg,
            ".gemini/settings.json",
            "{\"SECRET_SENTINEL\":broken}",
        );
        let report = reg.doctor().unwrap();
        assert!(!report.healthy());
        assert_eq!(
            report.hosts.iter().filter(|h| h.problem.is_some()).count(),
            2
        );
        assert!(
            !serde_json::to_string(&report)
                .unwrap()
                .contains("SECRET_SENTINEL")
        );
        assert!(reg.register().is_err());
    }

    #[test]
    fn jsonc_comments_in_member_and_no_empty_trailing_comma() {
        let source =
            "{\"mcp\":{\"code-diver\" /* keep colon */ : { /* keep inside */ }, /* keep tail */}}";
        let removed = edit_jsonc(source, "mcp", None).unwrap();
        assert!(removed.contains("/* keep colon */"));
        assert!(removed.contains("/* keep inside */"));
        assert!(removed.contains("/* keep tail */"));
        assert!(!removed.contains(','));
        assert!(
            parse_jsonc(&removed).unwrap()["mcp"]
                .as_object()
                .unwrap()
                .is_empty()
        );
    }

    #[test]
    fn codex_array_tables_and_multiline_strings_not_damaged() {
        let entry = json!({"command":"/binary", "args":["mcp"], "env":{OWNER:OWNER_VALUE}});
        let source = "[mcp_servers.'code-diver']\ncommand='old'\n[[unrelated]]\nname='kept'\n";
        let edited = edit_toml(source, Some(&entry)).unwrap();
        assert!(edited.contains("[[unrelated]]\nname='kept'"));
        let source =
            "prompt = '''\n[mcp_servers.code-diver]\nThis is a string, not a table.\n'''\n";
        let edited = edit_toml(source, Some(&entry)).unwrap();
        assert!(edited.starts_with(source));
        assert_eq!(edit_toml(&edited, None).unwrap(), source);
    }

    #[cfg(unix)]
    #[test]
    fn fake_claude_owned_removal_preserves_other_entries() {
        use std::os::unix::fs::PermissionsExt;
        let (_dir, mut reg) = sandbox();
        let other = json!({"command":"other"});
        put(
            &reg,
            ".claude.json",
            &serde_json::to_string(
                &json!({"mcpServers":{NAME:reg.entry(Host::ClaudeCode),"other":other}}),
            )
            .unwrap(),
        );
        put(
            &reg,
            "after.json",
            &serde_json::to_string(&json!({"mcpServers":{"other":other}})).unwrap(),
        );
        let cli = put(
            &reg,
            "bin/claude",
            "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$CLAUDE_CONFIG_DIR/remove-argv\"\ncp \"$CLAUDE_CONFIG_DIR/after.json\" \"$CLAUDE_CONFIG_DIR/.claude.json\"\n",
        );
        fs::set_permissions(&cli, fs::Permissions::from_mode(0o700)).unwrap();
        reg.claude_cli = Some(cli);
        let report = reg.unregister().unwrap();
        assert!(report.hosts[0].changed && !report.hosts[0].owned);
        assert!(report.hosts[0].backup.is_some());
        assert_eq!(
            parse_jsonc(&fs::read_to_string(reg.home.join(".claude.json")).unwrap()).unwrap()["mcpServers"]
                ["other"],
            other
        );
        assert!(
            fs::read_to_string(reg.home.join("remove-argv"))
                .unwrap()
                .contains("mcp\nremove\n--scope\nuser\ncode-diver")
        );
        assert!(!reg.unregister().unwrap().hosts[0].changed);
    }

    #[cfg(unix)]
    #[test]
    fn symlink_escape_rejected() {
        let (_dir, reg) = sandbox();
        let outside = tempfile::tempdir().unwrap();
        std::os::unix::fs::symlink(outside.path(), reg.home.join(".config")).unwrap();
        assert!(reg.register().is_err());
        assert_eq!(fs::read_dir(outside.path()).unwrap().count(), 0);
    }

    #[cfg(unix)]
    #[test]
    fn fake_claude_cli_isolated_argv_no_secret_and_failure() {
        use std::os::unix::fs::PermissionsExt;
        let (_dir, mut reg) = sandbox();
        reg.runtime_root = Some(reg.home.join("runtime-root"));
        let cli = put(
            &reg,
            "bin/claude",
            "#!/bin/sh\nprintf '%s\\n' \"$CLAUDE_CONFIG_DIR\" \"$CODE_DIVER_HOME\" \"$@\" > \"$CLAUDE_CONFIG_DIR/argv\"\ncp \"$CLAUDE_CONFIG_DIR/expected.json\" \"$CLAUDE_CONFIG_DIR/.claude.json\"\n",
        );
        fs::set_permissions(&cli, fs::Permissions::from_mode(0o700)).unwrap();
        put(
            &reg,
            "expected.json",
            &serde_json::to_string(&json!({"mcpServers":{NAME:reg.entry(Host::ClaudeCode)}}))
                .unwrap(),
        );
        put(&reg, "private/config.toml", "key = 'SECRET_NOT_IN_ARGV'");
        reg.claude_cli = Some(cli.clone());
        reg.dry_run = true;
        reg.register().unwrap();
        assert!(!reg.home.join("argv").exists());
        reg.dry_run = false;
        let result = reg.register().unwrap();
        assert!(result.hosts[0].registered && result.hosts[0].changed);
        let argv = fs::read_to_string(reg.home.join("argv")).unwrap();
        assert!(argv.starts_with(&format!(
            "{}\n{}\n",
            reg.home.display(),
            reg.runtime_root.as_ref().unwrap().display()
        )));
        assert!(argv.contains("mcp\nadd\n--scope\nuser"));
        assert!(!argv.contains("SECRET_NOT_IN_ARGV"));
        assert!(!reg.register().unwrap().hosts[0].changed);
        fs::write(&cli, "#!/bin/sh\nexit 4\n").unwrap();
        reg.binary = reg.home.join("changed");
        assert!(reg.register().is_err());
        assert!(reg.home.join(".claude.json").is_file());
    }
}
