use crate::runtime_config::{Platform, RuntimePaths};
use anyhow::{Result, bail};
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

pub const SERVICE_LABEL: &str = "dev.code-diver.daemon";
const OWNER: &str = "code-diver-m5b-owned";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CommandPlan {
    pub program: PathBuf,
    pub args: Vec<String>,
    pub env: BTreeMap<String, String>,
}
impl CommandPlan {
    pub fn execute(&self) -> Result<bool> {
        Ok(Command::new(&self.program)
            .args(&self.args)
            .envs(&self.env)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map_err(|_| anyhow::anyhow!("cannot execute runtime command"))?
            .success())
    }
}

pub fn validate_path(path: &Path) -> Result<()> {
    if !path.is_absolute()
        || path.to_str().is_none()
        || path
            .components()
            .any(|c| matches!(c, std::path::Component::ParentDir))
    {
        bail!("runtime path must be absolute UTF-8 without traversal");
    }
    if path.to_string_lossy().chars().any(char::is_control) {
        bail!("invalid runtime path");
    }
    Ok(())
}
pub fn safe_path(path: &Path) -> Result<()> {
    validate_path(path)?;
    for ancestor in path.ancestors() {
        match fs::symlink_metadata(ancestor) {
            Ok(m) if m.file_type().is_symlink() => bail!("refusing symlink in runtime path"),
            Ok(_) => (),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => (),
            Err(_) => bail!("cannot inspect runtime path"),
        }
    }
    Ok(())
}

#[derive(Clone, Debug)]
pub struct ServiceOptions {
    pub platform: Platform,
    pub paths: RuntimePaths,
    pub executable: PathBuf,
    pub config: PathBuf,
    pub manager: PathBuf,
    pub uid: u32,
}
#[derive(Clone, Debug)]
pub struct ServicePlan {
    pub path: PathBuf,
    pub contents: String,
    pub owner: String,
    pub probe: CommandPlan,
    pub start: Vec<CommandPlan>,
    pub stop: Vec<CommandPlan>,
}
fn xml(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
        .replace('\'', "&apos;")
}
fn systemd(s: &str) -> String {
    format!(
        "\"{}\"",
        s.replace('\\', "\\\\")
            .replace('"', "\\\"")
            .replace('%', "%%")
            .replace('$', "$$")
    )
}
pub fn plan(options: &ServiceOptions) -> Result<ServicePlan> {
    use sha2::{Digest, Sha256};
    let owner = format!(
        "{OWNER}-{:x}",
        Sha256::digest(options.config.as_os_str().as_encoded_bytes())
    );
    let owner_tag = owner.as_str();
    for p in [
        &options.executable,
        &options.config,
        &options.paths.services,
        &options.paths.logs,
    ] {
        validate_path(p)?;
    }
    let mut env = BTreeMap::new();
    if options.paths.isolated {
        let base = options
            .paths
            .config
            .parent()
            .ok_or_else(|| anyhow::anyhow!("isolated config has no parent"))?;
        env.insert("CODE_DIVER_HOME".into(), base.display().to_string());
    }
    let command = |args: Vec<String>| CommandPlan {
        program: options.manager.clone(),
        args,
        env: env.clone(),
    };
    let exe = options.executable.to_str().unwrap();
    let config = options.config.to_str().unwrap();
    match options.platform {
        Platform::MacOs => {
            let path = options
                .paths
                .services
                .join(format!("{SERVICE_LABEL}.plist"));
            let domain = format!("gui/{}", options.uid);
            let target = format!("{domain}/{SERVICE_LABEL}");
            let environment = env
                .iter()
                .map(|(k, v)| format!("<key>{}</key><string>{}</string>", xml(k), xml(v)))
                .collect::<String>();
            let contents = format!(
                "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n<!-- {owner_tag} -->\n<plist version=\"1.0\"><dict><key>Label</key><string>{SERVICE_LABEL}</string><key>ProgramArguments</key><array><string>{}</string><string>daemon</string><string>--foreground</string><string>--config</string><string>{}</string></array><key>EnvironmentVariables</key><dict>{environment}</dict><key>RunAtLoad</key><true/><key>KeepAlive</key><true/></dict></plist>\n",
                xml(exe),
                xml(config)
            );
            Ok(ServicePlan {
                owner: owner.clone(),
                path: path.clone(),
                contents,
                probe: command(vec!["print".into(), target.clone()]),
                start: vec![command(vec![
                    "bootstrap".into(),
                    domain,
                    path.display().to_string(),
                ])],
                stop: vec![command(vec!["bootout".into(), target])],
            })
        }
        Platform::Linux => {
            let unit = "code-diver.service";
            let environment = env
                .iter()
                .map(|(k, v)| format!("Environment={}\n", systemd(&format!("{k}={v}"))))
                .collect::<String>();
            let contents = format!(
                "# {owner_tag}\n[Unit]\nDescription=Code Diver local runtime\n[Service]\nExecStart={} daemon --foreground --config {}\n{environment}Restart=on-failure\n[Install]\nWantedBy=default.target\n",
                systemd(exe),
                systemd(config)
            );
            Ok(ServicePlan {
                owner: owner.clone(),
                path: options.paths.services.join(unit),
                contents,
                probe: command(vec![
                    "--user".into(),
                    "is-active".into(),
                    "--quiet".into(),
                    unit.into(),
                ]),
                start: vec![
                    command(vec!["--user".into(), "daemon-reload".into()]),
                    command(vec![
                        "--user".into(),
                        "enable".into(),
                        "--now".into(),
                        unit.into(),
                    ]),
                ],
                stop: vec![
                    command(vec![
                        "--user".into(),
                        "disable".into(),
                        "--now".into(),
                        unit.into(),
                    ]),
                    command(vec!["--user".into(), "daemon-reload".into()]),
                ],
            })
        }
    }
}
pub fn apply(plan: &ServicePlan, uninstall: bool, dry_run: bool) -> Result<bool> {
    safe_path(&plan.path)?;
    let before = match fs::read_to_string(&plan.path) {
        Ok(v) => Some(v),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => None,
        Err(_) => bail!("cannot read user service"),
    };
    if before.as_ref().is_some_and(|s| !s.contains(&plan.owner)) {
        bail!("user service is not owned; left unchanged");
    }
    if dry_run {
        return Ok(false);
    }
    if uninstall {
        if before.is_none() {
            return Ok(false);
        }
        if (plan.stop.len() > 1 || plan.probe.execute()?) && !plan.stop[0].execute()? {
            bail!("cannot stop user service");
        }
        fs::remove_file(&plan.path)?;
        for cmd in plan.stop.iter().skip(1) {
            if !cmd.execute()? {
                bail!("cannot reload user services");
            }
        }
        return Ok(true);
    }
    let changed = before.as_deref() != Some(&plan.contents);
    if changed {
        if before.is_some() && plan.probe.execute()? && !plan.stop[0].execute()? {
            bail!("cannot stop stale service");
        }
        write_private(&plan.path, plan.contents.as_bytes())?;
    }
    if changed || !plan.probe.execute()? {
        for cmd in &plan.start {
            if !cmd.execute()? {
                bail!("cannot start user service; check user service manager");
            }
        }
    }
    Ok(changed)
}
pub fn write_private(path: &Path, bytes: &[u8]) -> Result<()> {
    use std::io::Write;
    safe_path(path)?;
    let parent = path
        .parent()
        .ok_or_else(|| anyhow::anyhow!("missing runtime parent"))?;
    fs::create_dir_all(parent)?;
    let temporary = parent.join(format!(
        ".setup-{}-{}.tmp",
        std::process::id(),
        uuid::Uuid::new_v5(
            &uuid::Uuid::NAMESPACE_OID,
            format!("{:?}", std::time::SystemTime::now()).as_bytes()
        )
    ));
    let mut options = fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let result = (|| -> Result<()> {
        let mut file = options.open(&temporary)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        safe_path(path)?;
        fs::rename(&temporary, path)?;
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(temporary);
    }
    result.map_err(|_| anyhow::anyhow!("cannot save private runtime file"))
}
