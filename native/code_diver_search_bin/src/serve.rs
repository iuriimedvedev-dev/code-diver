//! `code-diver serve`: one long-lived process that loads the catalog, graph and models once and
//! answers newline-delimited JSON-RPC from many agent sessions on a unix socket.
//!
//! This is not the model supervisor (`code-diver daemon`, which runs llama-server children for
//! the embedder and reranker). `serve` is the search engine itself; it only talks to the model
//! runtime like `mcp` does. The request handling is shared with the stdio server in `mcp.rs`;
//! this module adds the socket, connection limits and graceful shutdown.
//!
//! The first version of this transport was written by Angkira against v0.4.5; it is ported here
//! onto the current MCP server with the hardening listed in the commit history.

use std::os::unix::fs::{DirBuilderExt, FileTypeExt, MetadataExt, PermissionsExt};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Duration, Instant};

use serde_json::{Value, json};
use tokio::io::{AsyncWriteExt, BufReader};
use tokio::net::{UnixListener, UnixStream};
use tokio::sync::Semaphore;
use tokio::task::JoinSet;

use crate::mcp::{McpConfig, Server, SessionLimits, SessionMode, build_context, error};

pub(crate) const DEFAULT_MAX_CONNECTIONS: usize = 32;
/// JSON-RPC error code the daemon uses when it is at its connection limit; the shim retries it.
pub(crate) const BUSY_CODE: i64 = -32001;

const IDLE_TIMEOUT: Duration = Duration::from_secs(300);
const STALL_TIMEOUT: Duration = Duration::from_secs(10);
const WRITE_TIMEOUT: Duration = Duration::from_secs(30);
const SHUTDOWN_GRACE: Duration = Duration::from_secs(10);
const PROBE_TIMEOUT: Duration = Duration::from_secs(2);
const REJECT_WRITE_TIMEOUT: Duration = Duration::from_secs(1);
const ACCEPT_ERROR_PAUSE: Duration = Duration::from_millis(100);
const SOCKET_MODE: u32 = 0o600;
/// `sun_path` holds 104 bytes on macOS and 108 on Linux, including the terminating NUL.
const MAX_SOCKET_PATH_BYTES: usize = 100;
const LOG: &str = "[code-diver-serve]";

pub(crate) struct ServeConfig {
    pub mcp: McpConfig,
    pub listen: String,
    pub max_connections: usize,
}

pub(crate) fn parse_listen(spec: &str) -> Result<PathBuf, String> {
    spec.strip_prefix("unix:")
        .filter(|path| !path.is_empty())
        .map(PathBuf::from)
        .ok_or_else(|| format!("--listen expects unix:PATH, got '{spec}'"))
}

fn session_limits() -> SessionLimits {
    SessionLimits {
        idle_timeout: Some(IDLE_TIMEOUT),
        stall_timeout: Some(STALL_TIMEOUT),
        write_timeout: Some(WRITE_TIMEOUT),
    }
}

// ---------------------------------------------------------------------------------------------
// Socket file handling
// ---------------------------------------------------------------------------------------------

/// A socket directory is acceptable when the current user owns it and nobody else can add,
/// rename or remove entries in it (anyone who can could swap in an impostor socket).
fn check_directory(owner: u32, mode: u32, current_user: u32) -> Result<(), String> {
    if owner != current_user {
        return Err(format!("is owned by uid {owner}, not by the current user"));
    }
    if mode & 0o022 != 0 {
        return Err(format!(
            "is writable by group or others (mode {:o}); run chmod go-w on it",
            mode & 0o7777
        ));
    }
    Ok(())
}

fn current_user() -> u32 {
    // SAFETY: geteuid(2) has no preconditions and cannot fail.
    unsafe { libc::geteuid() }
}

fn ensure_private_directory(dir: &Path) -> Result<(), String> {
    if !dir.exists() {
        std::fs::DirBuilder::new()
            .recursive(true)
            .mode(0o700)
            .create(dir)
            .map_err(|e| format!("create {}: {e}", dir.display()))?;
    }
    let meta = std::fs::metadata(dir).map_err(|e| format!("inspect {}: {e}", dir.display()))?;
    if !meta.is_dir() {
        return Err(format!("{} is not a directory", dir.display()));
    }
    check_directory(meta.uid(), meta.mode(), current_user())
        .map_err(|why| format!("socket directory {} {why}", dir.display()))
}

/// Validate the socket location and clear a stale socket file. A path that holds anything other
/// than a socket, or a socket somebody still answers on, is never touched.
pub(crate) async fn prepare_socket_path(path: &Path) -> Result<PathBuf, String> {
    let path = std::path::absolute(path).map_err(|e| format!("resolve {}: {e}", path.display()))?;
    let dir = path
        .parent()
        .ok_or_else(|| format!("socket path {} has no directory", path.display()))?;
    // The socket is staged in a sibling directory first, so that path must fit as well.
    if path.as_os_str().len() > MAX_SOCKET_PATH_BYTES
        || staging_directory(dir).join("s").as_os_str().len() > MAX_SOCKET_PATH_BYTES
    {
        return Err(format!(
            "socket path {} is too long (unix socket paths are limited to about {MAX_SOCKET_PATH_BYTES} bytes)",
            path.display()
        ));
    }
    ensure_private_directory(dir)?;
    match std::fs::symlink_metadata(&path) {
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(path),
        Err(e) => Err(format!("inspect {}: {e}", path.display())),
        Ok(meta) if !meta.file_type().is_socket() => Err(format!(
            "{} exists and is not a socket; refusing to replace it",
            path.display()
        )),
        Ok(_) => {
            match tokio::time::timeout(PROBE_TIMEOUT, UnixStream::connect(&path)).await {
                Ok(Ok(_)) | Err(_) => {
                    return Err(format!(
                        "another process is already serving on {}",
                        path.display()
                    ));
                }
                Ok(Err(e)) if e.kind() == std::io::ErrorKind::ConnectionRefused => {}
                Ok(Err(e)) => {
                    return Err(format!(
                        "cannot probe existing socket {}: {e}",
                        path.display()
                    ));
                }
            }
            std::fs::remove_file(&path)
                .map_err(|e| format!("remove stale socket {}: {e}", path.display()))?;
            eprintln!("{LOG} removed stale socket {}", path.display());
            Ok(path)
        }
    }
}

/// Removes the socket file on drop, but only while it is still the file this process created.
pub(crate) struct SocketGuard {
    path: PathBuf,
    inode: u64,
}

impl SocketGuard {
    fn new(path: &Path) -> Result<Self, String> {
        let meta = std::fs::symlink_metadata(path)
            .map_err(|e| format!("inspect {}: {e}", path.display()))?;
        Ok(Self {
            path: path.to_path_buf(),
            inode: meta.ino(),
        })
    }
}

impl Drop for SocketGuard {
    fn drop(&mut self) {
        if std::fs::symlink_metadata(&self.path).is_ok_and(|meta| meta.ino() == self.inode) {
            let _ = std::fs::remove_file(&self.path);
        }
    }
}

fn staging_directory(dir: &Path) -> PathBuf {
    dir.join(format!(".cd-{}", std::process::id()))
}

/// Bind a socket that is never reachable by group or others, not even for an instant.
///
/// bind(2) creates the socket file with the process umask, and changing the umask would race
/// with every other thread creating files. Instead the socket is bound inside a fresh 0700
/// directory, chmodded to 0600, and only then linked to its final name. The link fails if the
/// name has appeared in the meantime, so a socket somebody else is serving on is never replaced.
pub(crate) fn bind_socket(path: &Path) -> Result<(UnixListener, SocketGuard), String> {
    let dir = path
        .parent()
        .ok_or_else(|| format!("socket path {} has no directory", path.display()))?;
    let staging = staging_directory(dir);
    let temporary = staging.join("s");
    if temporary.as_os_str().len() > MAX_SOCKET_PATH_BYTES {
        return Err(format!(
            "socket directory {} is too long to stage a socket in",
            dir.display()
        ));
    }
    match std::fs::remove_dir_all(&staging) {
        Ok(()) => {}
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
        Err(e) => return Err(format!("clear {}: {e}", staging.display())),
    }
    std::fs::DirBuilder::new()
        .mode(0o700)
        .create(&staging)
        .map_err(|e| format!("create {}: {e}", staging.display()))?;
    let bound = (|| {
        let listener = UnixListener::bind(&temporary)
            .map_err(|e| format!("bind {}: {e}", path.display()))?;
        std::fs::set_permissions(&temporary, std::fs::Permissions::from_mode(SOCKET_MODE))
            .map_err(|e| format!("chmod {}: {e}", path.display()))?;
        std::fs::hard_link(&temporary, path).map_err(|e| {
            if e.kind() == std::io::ErrorKind::AlreadyExists {
                format!("another process is already serving on {}", path.display())
            } else {
                format!("publish {}: {e}", path.display())
            }
        })?;
        Ok::<_, String>(listener)
    })();
    let _ = std::fs::remove_file(&temporary);
    let _ = std::fs::remove_dir(&staging);
    let listener = bound?;
    Ok((listener, SocketGuard::new(path)?))
}

// ---------------------------------------------------------------------------------------------
// Connections
// ---------------------------------------------------------------------------------------------

async fn reject_busy(mut stream: UnixStream) {
    let line = error(Value::Null, BUSY_CODE, "Too many connections; retry later").to_string();
    let _ = tokio::time::timeout(REJECT_WRITE_TIMEOUT, async {
        stream.write_all(line.as_bytes()).await?;
        stream.write_all(b"\n").await?;
        stream.flush().await
    })
    .await;
}

/// Accept connections until `shutdown` resolves, then stop listening, remove the socket file and
/// give in-flight sessions a bounded time to finish.
pub(crate) async fn accept_loop(
    listener: UnixListener,
    guard: SocketGuard,
    server: Arc<Server>,
    connections: Arc<Semaphore>,
    shutdown: impl Future<Output = ()>,
) {
    let mut sessions: JoinSet<()> = JoinSet::new();
    tokio::pin!(shutdown);
    loop {
        tokio::select! {
            accepted = listener.accept() => {
                let stream = match accepted {
                    Ok((stream, _)) => stream,
                    Err(e) => {
                        eprintln!("{LOG} accept error: {e}");
                        tokio::time::sleep(ACCEPT_ERROR_PAUSE).await;
                        continue;
                    }
                };
                while sessions.try_join_next().is_some() {}
                let Ok(permit) = connections.clone().try_acquire_owned() else {
                    sessions.spawn(reject_busy(stream));
                    continue;
                };
                let server = server.clone();
                sessions.spawn(async move {
                    let _permit = permit;
                    let (reader, writer) = stream.into_split();
                    if let Err(e) = crate::mcp::run_session(
                        server,
                        BufReader::new(reader),
                        writer,
                        SessionMode::Stateless,
                        session_limits(),
                    )
                    .await
                    {
                        eprintln!("{LOG} connection closed: {e}");
                    }
                });
            }
            _ = &mut shutdown => break,
        }
    }
    eprintln!("{LOG} shutting down");
    drop(listener);
    drop(guard);
    let drain = async { while sessions.join_next().await.is_some() {} };
    if tokio::time::timeout(SHUTDOWN_GRACE, drain).await.is_err() {
        eprintln!(
            "{LOG} aborting {} session(s) still running after {}s",
            sessions.len(),
            SHUTDOWN_GRACE.as_secs()
        );
        sessions.abort_all();
    }
}

async fn termination() {
    use tokio::signal::unix::{SignalKind, signal};
    let (Ok(mut term), Ok(mut interrupt)) = (
        signal(SignalKind::terminate()),
        signal(SignalKind::interrupt()),
    ) else {
        return std::future::pending().await;
    };
    tokio::select! {
        _ = term.recv() => {}
        _ = interrupt.recv() => {}
    }
}

pub(crate) async fn run_serve(config: ServeConfig) -> Result<(), String> {
    if config.max_connections == 0 {
        return Err("max-connections must be positive".into());
    }
    let socket = parse_listen(&config.listen)?;
    let socket = prepare_socket_path(&socket).await?;
    eprintln!("{LOG} starting (pid {}), loading context", std::process::id());
    let context = build_context(&config.mcp.args).await?;
    let connections = Arc::new(Semaphore::new(config.max_connections));
    let started = Instant::now();
    let health_connections = connections.clone();
    let max_connections = config.max_connections;
    let server = Server::new(
        config.mcp,
        Some(context),
        Some(Box::new(move || -> Value {
            json!({
                "connections": max_connections - health_connections.available_permits(),
                "max_connections": max_connections,
                "uptime_s": started.elapsed().as_secs(),
            })
        })),
    )?;
    let (listener, guard) = bind_socket(&socket)?;
    eprintln!("{LOG} listening on {}", socket.display());
    accept_loop(listener, guard, server, connections, termination()).await;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::net::UnixListener as StdListener;

    #[test]
    fn listen_spec_requires_unix_scheme_and_path() {
        assert_eq!(
            parse_listen("unix:/run/x.sock").unwrap(),
            PathBuf::from("/run/x.sock")
        );
        for bad in ["", "unix:", "/run/x.sock", "tcp:127.0.0.1:1"] {
            assert!(parse_listen(bad).unwrap_err().contains("unix:PATH"), "{bad}");
        }
    }

    #[test]
    fn directory_must_be_owned_and_closed_to_others() {
        assert!(check_directory(1000, 0o40700, 1000).is_ok());
        assert!(check_directory(1000, 0o40755, 1000).is_ok());
        assert!(check_directory(0, 0o40700, 1000).unwrap_err().contains("owned by uid 0"));
        assert!(check_directory(1000, 0o40770, 1000).unwrap_err().contains("group or others"));
        assert!(check_directory(1000, 0o41777, 1000).unwrap_err().contains("group or others"));
    }

    #[tokio::test]
    async fn bound_socket_is_0600_and_removed_by_its_guard() {
        let dir = tempfile::tempdir().unwrap();
        let path = prepare_socket_path(&dir.path().join("s.sock")).await.unwrap();
        let (listener, guard) = bind_socket(&path).unwrap();
        let mode = std::fs::metadata(&path).unwrap().permissions().mode();
        assert_eq!(mode & 0o777, SOCKET_MODE);
        let leftovers = std::fs::read_dir(dir.path()).unwrap().count();
        assert_eq!(leftovers, 1, "the staging directory must be cleaned up");
        drop(listener);
        drop(guard);
        assert!(!path.exists());
    }

    #[tokio::test]
    async fn guard_leaves_a_replaced_socket_alone() {
        let dir = tempfile::tempdir().unwrap();
        let path = prepare_socket_path(&dir.path().join("s.sock")).await.unwrap();
        let (listener, guard) = bind_socket(&path).unwrap();
        std::fs::remove_file(&path).unwrap();
        let _other = StdListener::bind(&path).unwrap();
        drop(listener);
        drop(guard);
        assert!(path.exists(), "another process's socket must survive our cleanup");
    }

    #[tokio::test]
    async fn live_socket_is_refused_and_stale_socket_is_removed() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("s.sock");
        let live = StdListener::bind(&path).unwrap();
        let error = prepare_socket_path(&path).await.unwrap_err();
        assert!(error.contains("already serving"), "{error}");
        assert!(path.exists());
        drop(live);
        // The file stays behind after the listener is gone: nobody answers on it any more.
        assert!(path.exists());
        prepare_socket_path(&path).await.unwrap();
        assert!(!path.exists());
    }

    #[tokio::test]
    async fn non_socket_path_is_never_replaced() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("s.sock");
        std::fs::write(&path, "precious").unwrap();
        let error = prepare_socket_path(&path).await.unwrap_err();
        assert!(error.contains("not a socket"), "{error}");
        assert_eq!(std::fs::read_to_string(&path).unwrap(), "precious");
    }

    #[tokio::test]
    async fn missing_directory_is_created_private_and_open_directory_is_refused() {
        let dir = tempfile::tempdir().unwrap();
        let nested = dir.path().join("a/b/s.sock");
        prepare_socket_path(&nested).await.unwrap();
        let mode = std::fs::metadata(nested.parent().unwrap()).unwrap().mode();
        assert_eq!(mode & 0o077, 0);
        let open = dir.path().join("open");
        std::fs::create_dir(&open).unwrap();
        std::fs::set_permissions(&open, std::fs::Permissions::from_mode(0o777)).unwrap();
        let error = prepare_socket_path(&open.join("s.sock")).await.unwrap_err();
        assert!(error.contains("group or others"), "{error}");
    }

    #[tokio::test]
    async fn overlong_socket_path_is_rejected_with_a_clear_message() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("x".repeat(MAX_SOCKET_PATH_BYTES));
        let error = prepare_socket_path(&path).await.unwrap_err();
        assert!(error.contains("too long"), "{error}");
    }
}
