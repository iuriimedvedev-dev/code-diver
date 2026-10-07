use serde_json::{Value, json};
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::sync::{Mutex, OnceCell, Semaphore};
use tokio::task::{AbortHandle, JoinSet};

use crate::SearchArgs;
use crate::pipeline::{SearchContext, init_search_context, search_with_options};
use crate::types::SearchOptions;

const MAX_REQUEST_BYTES: usize = 1_048_576;
const MAX_ACTIVE_CALLS: usize = 128;
const PROTOCOLS: &[&str] = &["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"];

pub struct McpConfig {
    pub args: SearchArgs,
    pub root_dir: PathBuf,
    pub max_concurrent_searches: usize,
}

struct Server {
    config: McpConfig,
    context: OnceCell<Arc<SearchContext>>,
    searches: Semaphore,
}

fn error(id: Value, code: i64, message: &str) -> Value {
    json!({"jsonrpc":"2.0","id":id,"error":{"code":code,"message":message}})
}

fn response(id: Value, result: Value) -> Value {
    json!({"jsonrpc":"2.0","id":id,"result":result})
}

fn text_result(text: String, is_error: bool) -> Value {
    json!({"content":[{"type":"text","text":text}],"isError":is_error})
}

fn tools(max_limit: usize) -> Value {
    let tool = |name: &str, description: &str, properties: Value, required: Value| json!({"name":name,"description":description,"inputSchema":{"type":"object","properties":properties,"required":required,"additionalProperties":false}});
    json!({"tools":[
        tool("code_diver_search", "Search repository code", json!({"query":{"type":"string","minLength":1},"limit":{"type":"integer","minimum":1,"maximum":max_limit,"default":10},"preview_chars":{"type":"integer","minimum":0,"default":0}}), json!(["query"])),
        tool("code_diver_read", "Read sandboxed numbered lines", json!({"file":{"type":"string"},"start_line":{"type":"integer","minimum":1,"default":1},"lines":{"type":"integer","minimum":1,"maximum":400,"default":100}}), json!(["file"])),
        tool("code_diver_grep", "Gitignore-aware text search", json!({"pattern":{"type":"string"},"path":{"type":"string"},"limit":{"type":"integer","minimum":1,"default":50},"regex":{"type":"boolean","default":false}}), json!(["pattern"])),
        tool("code_diver_symbols", "List source symbols", json!({"path":{"type":"string"},"limit":{"type":"integer","minimum":1,"default":100}}), json!([])),
        tool("code_diver_tree", "Gitignore-aware directory tree", json!({"path":{"type":"string"},"depth":{"type":"integer","minimum":1,"default":3},"limit":{"type":"integer","minimum":1,"default":100}}), json!([])),
        tool("code_diver_info", "Configured collection and artifacts", json!({}), json!([]))
    ]})
}

impl Server {
    async fn context(&self) -> Result<&Arc<SearchContext>, String> {
        self.context
            .get_or_try_init(|| async {
                let args = self.config.args.clone();
                let runtime = tokio::runtime::Handle::current();
                tokio::task::spawn_blocking(move || {
                    let (config, _) = crate::build_search_config_default(&args, true, true)?;
                    runtime.block_on(init_search_context(config)).map(Arc::new)
                })
                .await
                .map_err(|_| "Search initialization worker failed".to_string())?
            })
            .await
    }

    async fn call(&self, name: &str, args: Value) -> Result<Value, String> {
        if name == "code_diver_search" {
            let query = args["query"]
                .as_str()
                .filter(|q| !q.trim().is_empty())
                .ok_or("query must be a nonempty string")?;
            let limit = integer(&args, "limit", 10, false)?;
            let preview = integer(&args, "preview_chars", 0, true)?;
            if args.as_object().is_some_and(|m| {
                m.keys()
                    .any(|k| !matches!(k.as_str(), "query" | "limit" | "preview_chars"))
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
                ctx,
                query,
                &SearchOptions {
                    limit,
                    preview_chars: preview,
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

// Retain at most one bounded record, but always consume through its delimiter.
async fn record<R: tokio::io::AsyncBufRead + Unpin>(
    reader: &mut R,
) -> Result<Option<Vec<u8>>, String> {
    let mut data = Vec::new();
    let mut oversized = false;
    loop {
        let buf = reader.fill_buf().await.map_err(|e| e.to_string())?;
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
    if config.max_concurrent_searches == 0 {
        return Err("max-concurrent-searches must be positive".into());
    }
    let server = Arc::new(Server {
        searches: Semaphore::new(config.max_concurrent_searches),
        config,
        context: OnceCell::new(),
    });
    let (stdout, mut responses) = tokio::sync::mpsc::channel::<Value>(MAX_ACTIVE_CALLS);
    let writer = tokio::spawn(async move {
        let mut output = tokio::io::stdout();
        while let Some(value) = responses.recv().await {
            let mut bytes = serde_json::to_vec(&value).map_err(|e| e.to_string())?;
            bytes.push(b'\n');
            output.write_all(&bytes).await.map_err(|e| e.to_string())?;
            output.flush().await.map_err(|e| e.to_string())?;
        }
        Ok::<_, String>(())
    });
    let mut reader = BufReader::new(tokio::io::stdin());
    let mut tasks = JoinSet::new();
    let active: Arc<Mutex<HashMap<String, AbortHandle>>> = Arc::new(Mutex::new(HashMap::new()));
    let mut initialized = false;
    let mut ready = false;
    while let Some(bytes) = record(&mut reader).await? {
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
                if initialized {
                    Err((-32600, "Already initialized"))
                } else if !params["protocolVersion"].is_string()
                    || !params["capabilities"].is_object()
                    || !params["clientInfo"]["name"].is_string()
                    || !params["clientInfo"]["version"].is_string()
                {
                    Err((
                        -32602,
                        "initialize requires protocolVersion, capabilities and clientInfo",
                    ))
                } else {
                    initialized = true;
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
            }
            "ping" => Ok(json!({})),
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
                    let stdout = stdout.clone();
                    let key = id.to_string();
                    let task_key = key.clone();
                    let task_active = active.clone();
                    let (ready, start) = tokio::sync::oneshot::channel();
                    let handle = tasks.spawn(async move {
                        let _ = start.await;
                        let result = server
                            .call(&name, args)
                            .await
                            .unwrap_or_else(|e| text_result(e, true));
                        task_active.lock().await.remove(&task_key);
                        write(&stdout, response(id, result)).await
                    });
                    active.lock().await.insert(key, handle);
                    let _ = ready.send(());
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
