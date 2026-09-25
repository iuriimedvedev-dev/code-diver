use std::io::{self, BufRead, Write};
use std::path::Path;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use crate::pipeline::{search, SearchContext};

#[derive(Debug, Deserialize)]
#[allow(dead_code)]
struct JsonRpcRequest {
    jsonrpc: String,
    id: Option<Value>,
    method: String,
    params: Option<Value>,
}

#[derive(Debug, Serialize)]
struct JsonRpcResponse {
    jsonrpc: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    id: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    result: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<Value>,
}

pub struct McpConfig<'a> {
    pub ctx: &'a SearchContext,
    pub root_dir: &'a Path,
}

impl<'a> McpConfig<'a> {
    pub fn new(ctx: &'a SearchContext, root_dir: &'a Path) -> Self {
        Self { ctx, root_dir }
    }
}

pub async fn run_mcp_server(config: McpConfig<'_>) -> Result<(), String> {
    run_mcp_server_raw(config.ctx, config.root_dir).await
}

pub async fn run_mcp_server_raw(ctx: &SearchContext, root_dir: &Path) -> Result<(), String> {
    eprintln!("[code-diver-mcp] Starting native Rust MCP stdio server...");
    let stdin = io::stdin();
    let mut reader = stdin.lock();
    let mut stdout = io::stdout();

    let mut line = String::new();
    loop {
        line.clear();
        let bytes = reader.read_line(&mut line).map_err(|e| e.to_string())?;
        if bytes == 0 {
            break;
        }

        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }

        let req: JsonRpcRequest = match serde_json::from_str(trimmed) {
            Ok(r) => r,
            Err(e) => {
                let err_resp = JsonRpcResponse {
                    jsonrpc: "2.0".to_string(),
                    id: None,
                    result: None,
                    error: Some(json!({
                        "code": -32700,
                        "message": format!("Parse error: {}", e)
                    })),
                };
                let out = serde_json::to_string(&err_resp).unwrap_or_default();
                writeln!(stdout, "{}", out).map_err(|e| e.to_string())?;
                stdout.flush().map_err(|e| e.to_string())?;
                continue;
            }
        };

        let resp = handle_request(ctx, root_dir, &req).await;
        if let Some(r) = resp {
            let out = serde_json::to_string(&r).unwrap_or_default();
            writeln!(stdout, "{}", out).map_err(|e| e.to_string())?;
            stdout.flush().map_err(|e| e.to_string())?;
        }
    }

    Ok(())
}

async fn handle_request(
    ctx: &SearchContext,
    root_dir: &Path,
    req: &JsonRpcRequest,
) -> Option<JsonRpcResponse> {
    // If it's a notification (no id), we might not send response, except for certain flows.
    let id = req.id.clone();

    match req.method.as_str() {
        "initialize" => Some(JsonRpcResponse {
            jsonrpc: "2.0".to_string(),
            id,
            result: Some(json!({
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "serverInfo": {
                    "name": "code-diver",
                    "version": "0.1.0"
                }
            })),
            error: None,
        }),
        "notifications/initialized" => None,
        "tools/list" => Some(JsonRpcResponse {
            jsonrpc: "2.0".to_string(),
            id,
            result: Some(json!({
                "tools": [
                    {
                        "name": "code_diver_search",
                        "description": "High-precision neural + BM25 + LightGBM meta-ranker code search.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "query": { "type": "string", "description": "Search query describing function or subsystem" },
                                "limit": { "type": "integer", "description": "Max results to return", "default": 10 }
                            },
                            "required": ["query"]
                        }
                    },
                    {
                        "name": "code_diver_read",
                        "description": "Read bounded file excerpt with line numbers.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "file": { "type": "string", "description": "Relative file path" },
                                "start_line": { "type": "integer", "default": 1 },
                                "lines": { "type": "integer", "default": 80 }
                            },
                            "required": ["file"]
                        }
                    }
                ]
            })),
            error: None,
        }),
        "tools/call" => {
            let params = req.params.as_ref().cloned().unwrap_or(Value::Null);
            let name = params["name"].as_str().unwrap_or_default();
            let args = &params["arguments"];

            let call_res = match name {
                "code_diver_search" => {
                    let query = args["query"].as_str().unwrap_or_default();
                    let limit = args["limit"].as_u64().unwrap_or(10) as usize;
                    match search(ctx, query, limit).await {
                        Ok((results, _timings)) => {
                            let text = serde_json::to_string_pretty(&results).unwrap_or_default();
                            Ok(json!({
                                "content": [{ "type": "text", "text": text }]
                            }))
                        }
                        Err(e) => Err(format!("Search failed: {}", e)),
                    }
                }
                "code_diver_read" => {
                    let file = args["file"].as_str().unwrap_or_default();
                    let start_line = args["start_line"].as_u64().unwrap_or(1) as usize;
                    let lines_count = args["lines"].as_u64().unwrap_or(80) as usize;

                    let file_path = root_dir.join(file);
                    match std::fs::read_to_string(&file_path) {
                        Ok(content) => {
                            let all_lines: Vec<&str> = content.lines().collect();
                            let start_idx = if start_line > 0 { start_line - 1 } else { 0 };
                            let end_idx = (start_idx + lines_count).min(all_lines.len());
                            let mut excerpt = String::new();
                            for i in start_idx..end_idx {
                                excerpt.push_str(&format!("{:4}: {}\n", i + 1, all_lines[i]));
                            }
                            Ok(json!({
                                "content": [{ "type": "text", "text": excerpt }]
                            }))
                        }
                        Err(e) => Err(format!("Could not read file {}: {}", file, e)),
                    }
                }
                _ => Err(format!("Unknown tool: {}", name)),
            };

            match call_res {
                Ok(val) => Some(JsonRpcResponse {
                    jsonrpc: "2.0".to_string(),
                    id,
                    result: Some(val),
                    error: None,
                }),
                Err(err_msg) => Some(JsonRpcResponse {
                    jsonrpc: "2.0".to_string(),
                    id,
                    result: None,
                    error: Some(json!({
                        "code": -32603,
                        "message": err_msg
                    })),
                }),
            }
        }
        _ => Some(JsonRpcResponse {
            jsonrpc: "2.0".to_string(),
            id,
            result: None,
            error: Some(json!({
                "code": -32601,
                "message": format!("Method not found: {}", req.method)
            })),
        }),
    }
}
