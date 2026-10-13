use serde_json::{Value, json};
use std::collections::HashMap;
use std::future::Future;
use std::path::PathBuf;
use std::sync::{Arc, RwLock};
use std::time::Duration;
use tokio::io::{AsyncBufRead, AsyncBufReadExt, AsyncWrite, AsyncWriteExt};
use tokio::sync::{Mutex, Semaphore};
use tokio::task::{AbortHandle, JoinSet};

use crate::SearchArgs;
use crate::pipeline::{SearchContext, init_search_context, search_with_options};
use crate::types::SearchOptions;

pub(crate) const MAX_REQUEST_BYTES: usize = 1_048_576;
const MAX_ACTIVE_CALLS: usize = 128;
const PROTOCOLS: &[&str] = &["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"];

pub struct McpConfig {
    pub args: SearchArgs,
    pub root_dir: PathBuf,
    pub max_concurrent_searches: usize,
}

/// How a session treats the MCP handshake.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub(crate) enum SessionMode {
    /// One session per process: initialize and notifications/initialized come first.
    Handshake,
    /// Every request stands alone (daemon connections opened by the stateless shim).
    #[cfg(unix)]
    Stateless,
}

/// Bounds applied to one session; `None` disables a bound (stdio keeps the original behavior).
#[derive(Clone, Copy, Default, Debug)]
pub(crate) struct SessionLimits {
    /// Close a session that sends nothing while no request is in flight.
    pub idle_timeout: Option<Duration>,
    /// Give up on a request line that stops arriving before its newline.
    pub stall_timeout: Option<Duration>,
    /// Give up on a peer that stops reading responses.
    pub write_timeout: Option<Duration>,
}

/// The context currently serving requests. Requests clone the `Arc`, so replacing it never
/// disturbs a call that already holds the previous generation.
#[derive(Default)]
pub(crate) struct ContextSlot {
    current: RwLock<Option<Arc<SearchContext>>>,
    init: Mutex<()>,
}

impl ContextSlot {
    pub(crate) fn peek(&self) -> Option<Arc<SearchContext>> {
        self.current.read().unwrap().clone()
    }

    pub(crate) fn replace(&self, context: Arc<SearchContext>) -> Option<Arc<SearchContext>> {
        self.current.write().unwrap().replace(context)
    }
}

pub(crate) type HealthExtra = Box<dyn Fn() -> Value + Send + Sync>;

pub(crate) struct Server {
    config: McpConfig,
    context: Arc<ContextSlot>,
    searches: Semaphore,
    health_extra: Option<HealthExtra>,
}

/// Load the catalog, graph and models once for the given engine flags.
pub(crate) async fn build_context(args: &SearchArgs) -> Result<Arc<SearchContext>, String> {
    let args = args.clone();
    let runtime = tokio::runtime::Handle::current();
    tokio::task::spawn_blocking(move || {
        let (config, _) = crate::build_search_config_default(&args, true, true)?;
        runtime.block_on(init_search_context(config)).map(Arc::new)
    })
    .await
    .map_err(|_| "Search initialization worker failed".to_string())?
}

/// Answer to `initialize`, shared by the stdio server, the daemon and the shim.
pub(crate) fn initialize_result(params: &Value) -> Result<Value, (i64, &'static str)> {
    if !params["protocolVersion"].is_string()
        || !params["capabilities"].is_object()
        || !params["clientInfo"]["name"].is_string()
        || !params["clientInfo"]["version"].is_string()
    {
        return Err((
            -32602,
            "initialize requires protocolVersion, capabilities and clientInfo",
        ));
    }
    let requested = params["protocolVersion"].as_str().unwrap();
    let version = if PROTOCOLS.contains(&requested) {
        requested
    } else {
        PROTOCOLS[0]
    };
    Ok(
        json!({"protocolVersion":version,"capabilities":{"tools":{},"resources":{},"prompts":{}},"serverInfo":{"name":"code-diver","version":env!("CARGO_PKG_VERSION")}}),
    )
}

pub(crate) fn error(id: Value, code: i64, message: &str) -> Value {
    json!({"jsonrpc":"2.0","id":id,"error":{"code":code,"message":message}})
}

pub(crate) fn response(id: Value, result: Value) -> Value {
    json!({"jsonrpc":"2.0","id":id,"result":result})
}

fn text_result(text: String, is_error: bool) -> Value {
    json!({"content":[{"type":"text","text":text}],"isError":is_error})
}

pub(crate) fn tools(max_limit: usize) -> Value {
    let tool = |name: &str, description: &str, properties: Value, required: Value| json!({"name":name,"description":description,"inputSchema":{"type":"object","properties":properties,"required":required,"additionalProperties":false}});
    json!({"tools":[
        tool("code_diver_search", "Search repository code and return matching files with path, relevance score, preview of matched content, and line range. Use read to open a file.", json!({"query":{"type":"string","minLength":1},"limit":{"type":"integer","minimum":1,"maximum":max_limit,"default":10},"preview_chars":{"type":"integer","minimum":0,"default":400},"path_prefix":{"type":"string","minLength":1}}), json!(["query"])),
        tool("code_diver_read", "Read sandboxed numbered lines", json!({"file":{"type":"string"},"start_line":{"type":"integer","minimum":1,"default":1},"lines":{"type":"integer","minimum":1,"maximum":400,"default":100}}), json!(["file"])),
        tool("code_diver_grep", "Gitignore-aware text search", json!({"pattern":{"type":"string"},"path":{"type":"string"},"limit":{"type":"integer","minimum":1,"default":50},"regex":{"type":"boolean","default":false}}), json!(["pattern"])),
        tool("code_diver_symbols", "List source symbols", json!({"path":{"type":"string"},"limit":{"type":"integer","minimum":1,"default":100}}), json!([])),
        tool("code_diver_tree", "Gitignore-aware directory tree", json!({"path":{"type":"string"},"depth":{"type":"integer","minimum":1,"default":3},"limit":{"type":"integer","minimum":1,"default":100}}), json!([])),
        tool("code_diver_info", "Configured collection and artifacts", json!({}), json!([]))
    ]})
}

impl Server {
    /// `context` is shared with whoever may swap it later (hot reload); an empty slot is filled
    /// lazily on first use.
    pub(crate) fn new(
        config: McpConfig,
        context: Arc<ContextSlot>,
        health_extra: Option<HealthExtra>,
    ) -> Result<Arc<Self>, String> {
        if config.max_concurrent_searches == 0 {
            return Err("max-concurrent-searches must be positive".into());
        }
        Ok(Arc::new(Server {
            searches: Semaphore::new(config.max_concurrent_searches),
            config,
            context,
            health_extra,
        }))
    }


    async fn health(&self) -> Result<Value, String> {
        let ctx = self.context().await?;
        let mut health = json!({
            "pid": std::process::id(),
            "version": env!("CARGO_PKG_VERSION"),
            "items": ctx.catalog.items.len(),
        });
        if let Some(extra) = &self.health_extra
            && let (Some(base), Value::Object(extra)) = (health.as_object_mut(), extra())
        {
            base.extend(extra);
        }
        Ok(health)
    }

    async fn context(&self) -> Result<Arc<SearchContext>, String> {
        if let Some(ctx) = self.context.peek() {
            return Ok(ctx);
        }
        let _init = self.context.init.lock().await;
        if let Some(ctx) = self.context.peek() {
            return Ok(ctx);
        }
        let ctx = build_context(&self.config.args).await?;
        self.context.replace(ctx.clone());
        Ok(ctx)
    }

    async fn call(&self, name: &str, args: Value) -> Result<Value, String> {
        if name == "code_diver_search" {
            let query = args["query"]
                .as_str()
                .filter(|q| !q.trim().is_empty())
                .ok_or("query must be a nonempty string")?;
            let limit = integer(&args, "limit", 10, false)?;
            let preview = integer(&args, "preview_chars", 400, true)?;
            let path_prefix = args
                .get("path_prefix")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string());
            if args.as_object().is_some_and(|m| {
                m.keys().any(|k| {
                    !matches!(
                        k.as_str(),
                        "query" | "limit" | "preview_chars" | "path_prefix"
                    )
                })
            }) {
                return Err("Unknown search argument".into());
            }
            let _permit = self
                .searches
                .acquire()
                .await
                .map_err(|_| "Search queue closed")?;
            let ctx = self.context().await?;
            let (search_response, _timings) = search_with_options(
                &ctx,
                query,
                &SearchOptions {
                    limit,
                    preview_chars: preview,
                    path_prefix,
                },
            )
            .await?;
            let mut results =
                serde_json::to_value(search_response.results).map_err(|e| e.to_string())?;
            if let Some(results) = results.as_array_mut() {
                for result in results {
                    if result.get("ce_score").is_none() {
                        result["ce_score"] = Value::Null;
                    }
                }
            }
            let mut result = text_result(
                serde_json::to_string(&results).map_err(|e| e.to_string())?,
                false,
            );
            result["structuredContent"] = json!({
                "results": results,
                "rerank_applied": search_response.rerank_applied,
                "rerank_second_pass_failed": search_response.rerank_second_pass_failed,
                "rerank_error": search_response.rerank_error,
                "meta_ranker_applied": search_response.meta_ranker_applied,
            });
            if !search_response.notices.is_empty() {
                result["content"].as_array_mut().unwrap().push(json!({"type":"text","text":format!("WARNING: {}", search_response.notices.join("; "))}));
            }
            return Ok(result);
        }
        if name == "code_diver_info" {
            if !args.as_object().is_some_and(|m| m.is_empty()) {
                return Err("info accepts no arguments".into());
            }
            let info = crate::configured_info(&self.config.args).await?;
            return Ok(text_result(
                serde_json::to_string(&info).map_err(|e| e.to_string())?,
                false,
            ));
        }
        let root = self.config.root_dir.clone();
        let name = name.to_owned();
        tokio::task::spawn_blocking(move || {
            crate::inspection::call(&root, &name, &args).map_err(|e| e.to_string())
        })
        .await
        .map_err(|_| "Inspection worker failed".to_string())?
    }
}

fn integer(args: &Value, key: &str, default: usize, zero: bool) -> Result<usize, String> {
    match args.get(key) {
        None => Ok(default),
        Some(v) => v
            .as_u64()
            .and_then(|n| usize::try_from(n).ok())
            .filter(|n| zero || *n > 0)
            .ok_or_else(|| {
                format!(
                    "{key} must be {} integer",
                    if zero { "a nonnegative" } else { "a positive" }
                )
            }),
    }
}

async fn write(stdout: &tokio::sync::mpsc::Sender<Value>, value: Value) -> Result<(), String> {
    stdout
        .send(value)
        .await
        .map_err(|_| "stdout writer closed".to_string())
}

type Active = Arc<Mutex<HashMap<String, AbortHandle>>>;

// Run a request off the read loop so slow work never blocks other requests or cancellation.
async fn spawn_request<F>(
    tasks: &mut JoinSet<Result<(), String>>,
    active: &Active,
    stdout: &tokio::sync::mpsc::Sender<Value>,
    id: Value,
    work: F,
) where
    F: Future<Output = Result<Value, (i64, String)>> + Send + 'static,
{
    let stdout = stdout.clone();
    let key = id.to_string();
    let task_key = key.clone();
    let task_active = active.clone();
    let (ready, start) = tokio::sync::oneshot::channel();
    let handle = tasks.spawn(async move {
        let _ = start.await;
        let result = work.await;
        task_active.lock().await.remove(&task_key);
        write(
            &stdout,
            match result {
                Ok(result) => response(id, result),
                Err((code, message)) => error(id, code, &message),
            },
        )
        .await
    });
    active.lock().await.insert(key, handle);
    let _ = ready.send(());
}

// Retain at most one bounded record, but always consume through its delimiter.
// A `stall` timeout bounds the wait for the rest of a record once its first bytes arrived.
pub(crate) async fn record<R: AsyncBufRead + Unpin>(
    reader: &mut R,
    stall: Option<Duration>,
) -> Result<Option<Vec<u8>>, String> {
    let mut data = Vec::new();
    let mut oversized = false;
    let mut started = false;
    loop {
        let filled = reader.fill_buf();
        let buf = match stall.filter(|_| started) {
            Some(limit) => tokio::time::timeout(limit, filled)
                .await
                .map_err(|_| "Request line stalled before its newline".to_string())?,
            None => filled.await,
        }
        .map_err(|e| e.to_string())?;
        started = true;
        if buf.is_empty() {
            return if data.is_empty() && !oversized {
                Ok(None)
            } else if oversized {
                Ok(Some(Vec::new()))
            } else {
                Ok(Some(data))
            };
        }
        let newline = buf.iter().position(|b| *b == b'\n');
        let n = newline.map_or(buf.len(), |i| i + 1);
        if !oversized {
            if data.len().saturating_add(n) > MAX_REQUEST_BYTES {
                oversized = true;
                data.clear();
            } else {
                data.extend_from_slice(&buf[..n]);
            }
        }
        reader.consume(n);
        if newline.is_some() {
            return Ok(Some(data));
        }
    }
}

pub async fn run_mcp_server(config: McpConfig) -> Result<(), String> {
    let server = Server::new(config, Arc::default(), None)?;
    run_session(
        server,
        tokio::io::BufReader::new(tokio::io::stdin()),
        tokio::io::stdout(),
        SessionMode::Handshake,
        SessionLimits::default(),
    )
    .await
}

/// Serve one MCP session over any line-oriented transport until the peer closes it.
pub(crate) async fn run_session<R, W>(
    server: Arc<Server>,
    mut reader: R,
    mut output: W,
    mode: SessionMode,
    limits: SessionLimits,
) -> Result<(), String>
where
    R: AsyncBufRead + Unpin,
    W: AsyncWrite + Unpin + Send + 'static,
{
    let (stdout, mut responses) = tokio::sync::mpsc::channel::<Value>(MAX_ACTIVE_CALLS);
    let write_timeout = limits.write_timeout;
    let writer = tokio::spawn(async move {
        while let Some(value) = responses.recv().await {
            let mut bytes = serde_json::to_vec(&value).map_err(|e| e.to_string())?;
            bytes.push(b'\n');
            let flush = async {
                output.write_all(&bytes).await?;
                output.flush().await
            };
            match write_timeout {
                Some(limit) => tokio::time::timeout(limit, flush)
                    .await
                    .map_err(|_| "Peer stopped reading responses".to_string())?,
                None => flush.await,
            }
            .map_err(|e| e.to_string())?;
        }
        Ok::<_, String>(())
    });
    let mut tasks = JoinSet::new();
    let active: Active = Arc::new(Mutex::new(HashMap::new()));
    let stateless = mode != SessionMode::Handshake;
    let mut initialized = stateless;
    let mut ready = stateless;
    loop {
        if let Some(idle) = limits.idle_timeout {
            match tokio::time::timeout(idle, reader.fill_buf()).await {
                Err(_) if active.lock().await.is_empty() => break,
                Err(_) => continue,
                Ok(Err(e)) => return Err(e.to_string()),
                Ok(Ok(_)) => {}
            }
        }
        let Some(bytes) = record(&mut reader, limits.stall_timeout).await? else {
            break;
        };
        while let Some(done) = tasks.try_join_next() {
            if let Ok(result) = done {
                result?;
            }
        }
        let value: Value = match serde_json::from_slice(&bytes) {
            Ok(v) => v,
            Err(_) => {
                write(
                    &stdout,
                    error(Value::Null, -32700, "Invalid JSON or request exceeds 1 MiB"),
                )
                .await?;
                continue;
            }
        };
        let id = value.get("id").cloned();
        let valid_id = id
            .as_ref()
            .is_none_or(|v| v.is_string() || v.is_i64() || v.is_u64());
        let method = value["method"].as_str();
        if !value.is_object() || value["jsonrpc"] != "2.0" || method.is_none() || !valid_id {
            write(
                &stdout,
                error(
                    if valid_id {
                        id.unwrap_or(Value::Null)
                    } else {
                        Value::Null
                    },
                    -32600,
                    "Invalid JSON-RPC request",
                ),
            )
            .await?;
            continue;
        }
        let method = method.unwrap();
        let params = value.get("params").cloned().unwrap_or_else(|| json!({}));
        if !params.is_object() {
            if let Some(id) = id {
                write(&stdout, error(id, -32602, "params must be an object")).await?;
            }
            continue;
        }
        if method == "notifications/cancelled" && id.is_none() {
            if let Some(id) = params.get("requestId")
                && let Some(handle) = active.lock().await.remove(&id.to_string())
            {
                handle.abort();
            }
            continue;
        }
        let Some(id) = id else {
            if method == "notifications/initialized" && initialized {
                ready = true;
            }
            continue;
        };
        if active.lock().await.contains_key(&id.to_string()) {
            write(&stdout, error(id, -32600, "Duplicate active request id")).await?;
            continue;
        }
        let result = match method {
            "initialize" => {
                if initialized && !stateless {
                    Err((-32600, "Already initialized"))
                } else {
                    let result = initialize_result(&params);
                    initialized |= result.is_ok();
                    result
                }
            }
            "ping" => Ok(json!({})),
            "health" => {
                if active.lock().await.len() >= MAX_ACTIVE_CALLS {
                    Err((-32603, "Too many active requests; retry later"))
                } else {
                    let server = server.clone();
                    spawn_request(&mut tasks, &active, &stdout, id, async move {
                        server.health().await.map_err(|message| {
                            eprintln!("Health check failed: {message}");
                            (
                                -32603,
                                "Health check failed: search context unavailable".to_string(),
                            )
                        })
                    })
                    .await;
                    continue;
                }
            }
            _ if !ready => Err((
                -32600,
                "Complete initialize and notifications/initialized first",
            )),
            "tools/list" => Ok(tools(crate::configured_candidate_limit(
                &server.config.args,
            )?)),
            "resources/list" => Ok(json!({"resources":[]})),
            "resources/templates/list" => Ok(json!({"resourceTemplates":[]})),
            "prompts/list" => Ok(json!({"prompts":[]})),
            "tools/call" => {
                let args = params
                    .get("arguments")
                    .cloned()
                    .unwrap_or_else(|| json!({}));
                if !params["name"].is_string() || !args.is_object() {
                    Err((-32602, "tools/call requires name and object arguments"))
                } else if active.lock().await.len() >= MAX_ACTIVE_CALLS {
                    Err((-32603, "Too many active requests; retry later"))
                } else {
                    let name = params["name"].as_str().unwrap().to_string();
                    let server = server.clone();
                    spawn_request(&mut tasks, &active, &stdout, id, async move {
                        Ok(server
                            .call(&name, args)
                            .await
                            .unwrap_or_else(|e| text_result(e, true)))
                    })
                    .await;
                    continue;
                }
            }
            _ => Err((-32601, "Method not found")),
        };
        write(
            &stdout,
            match result {
                Ok(result) => response(id, result),
                Err((code, message)) => error(id, code, message),
            },
        )
        .await?;
    }
    while let Some(done) = tasks.join_next().await {
        if let Ok(result) = done {
            result?;
        }
    }
    drop(stdout);
    writer
        .await
        .map_err(|_| "stdout writer failed".to_string())?
}
