# Code Diver MCP Server

Code Diver provides a Model Context Protocol (MCP) server over standard I/O (`stdio`). This allows AI agents in **OpenCode**, **Claude Desktop**, **Cursor**, **Windsurf**, and other MCP-compliant hosts to search, explore, and retrieve repository code with high precision.

---

## Capabilities

The MCP server exposes both **instant synchronous tools** and an **asynchronous Task API** (following the MCP background task pattern):

### 1. Synchronous Tools (Subsecond)
| Tool | Description |
|---|---|
| `code_diver_search` | Subsecond hybrid semantic & vector retrieval over indexed chunks. |
| `code_diver_symbols` | AST symbol navigation (classes, functions, methods, line spans). |
| `code_diver_read` | Bounded line reader for reading files without overflowing agent context. |
| `code_diver_grep` | High-speed regex / literal text search across project source files. |
| `code_diver_tree` | Gitignore-aware repository hierarchy viewer. |
| `code_diver_info` | Metadata on index items, vector store backend, and model footprint. |

### 2. Asynchronous Agent Task API
For non-blocking searches, deep multi-query exploration, or multi-agent orchestration without timeouts:
| Tool | Description |
|---|---|
| `code_diver_submit_agent_search` | Submits a search task to a background worker pool and immediately returns `task_id`. |
| `code_diver_task_status` | Checks status (`working`, `completed`, `failed`, `cancelled`). |
| `code_diver_task_result` | Returns search results and symbol outlines once finished. |
| `code_diver_task_cancel` | Cancels a running background task. |
| `code_diver_tasks_list` | Lists recent background tasks. |

---

## Configuration

### OpenCode (`~/.config/opencode/opencode.json` or project `.opencode/opencode.json`)

```json
{
  "mcp": {
    "code-diver": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/code-diver", "code-diver", "mcp"]
    }
  }
}
```

Or when installed as a CLI globally:
```json
{
  "mcp": {
    "code-diver": {
      "command": "code-diver",
      "args": ["mcp", "--config", "code-diver.yml"]
    }
  }
}
```

### Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "code-diver": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/absolute/path/to/code-diver",
        "code-diver",
        "mcp",
        "/absolute/path/to/target/repo/code-diver.yml"
      ]
    }
  }
}
```

### Cursor (`.cursor/mcp.json`)

```json
{
  "mcpServers": {
    "code-diver": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/code-diver", "code-diver", "mcp"]
    }
  }
}
```

---

## Running Standalone

You can test the MCP server directly via stdio:
```bash
uv run code-diver mcp code-diver.yml
```

---

## Sharing one process between agent sessions: `serve` and `shim`

> **Two different `serve` commands.** The commands on this page are the native
> Rust engine (`code-diver-search serve|shim`, exposed by
> `code-diver-project <project> daemon`) and share one process over a **unix
> socket** for stdio-only clients. The Python CLI's `code-diver serve` instead
> runs the **network** MCP Streamable HTTP server (TLS + OAuth 2.1); see
> [`docs/http-mcp.md`](../http-mcp.md).

Code-Diver offers two ways to run the MCP server. Both answer the same methods
(`initialize`, `tools/list`, `tools/call`, `ping`, `health`) with the same tools.

| Command | Process model | Use it when |
|---|---|---|
| `code-diver mcp` | One process per MCP client, speaks MCP on stdio | You run one agent session, or each client may load its own copy of the catalog and graph. This is the simplest setup. |
| `code-diver serve` | One long-lived process that listens on a unix socket | Several agent sessions share one machine and you want to load the catalog, graph and models once and reload them without restarting clients. |
| `code-diver shim` | Stateless stdio process that forwards to a `serve` socket | The MCP client can only launch stdio servers and you run `serve`. |
| `code-diver daemon` | Supervises the local embedder and reranker (`llama-server`) | Not an MCP server. It is the model runtime that `mcp` and `serve` talk to. |

`serve` and `shim` are available on unix systems only.

### Start the shared process

`serve` takes the same engine flags as `mcp` (`--catalog`, `--graph`, `--root`,
`--config`, `--qdrant-collection`, ...) plus `--listen`:

```sh
code-diver serve --listen unix:<socket> --catalog <catalog> --graph <graph> --root <project-root>
```

The socket is created with mode `0600`, so only the same user can connect. Put it
in a directory that only you can access. Optional limits:
`--max-connections <n>` (default 32), `--reload-poll-secs <n>` (default 10, `0`
disables polling) and `--reload-debounce-secs <n>` (default 2).

### Connect a client

Point the MCP client at `shim`:

```json
{
  "mcpServers": {
    "code-diver": {
      "command": "code-diver",
      "args": ["shim", "--socket", "<socket>"]
    }
  }
}
```

The same entry as a command line: `code-diver shim --socket <socket>`. The shim
keeps no state and loads no index. It answers `initialize` and `ping` itself, so a
client can always start; `tools/list` falls back to a built-in list while `serve`
is away, and other requests are retried for a short time and then fail with an
error that names the socket.

### Hot reload

`serve` reloads the catalog and graph without dropping connections:

- when either file changes on disk (checked every `--reload-poll-secs`, applied
  after the files stay unchanged for `--reload-debounce-secs`), and
- on `SIGHUP`: `kill -HUP <serve-pid>`.

If a reload fails, the previous data stays active and the error is reported by
`health`.

### Health check

Send the `health` method to see whether the process is alive and which data it
serves. `mcp` and `serve` report `pid`, `version` and `items` (the number of
catalog items). `serve` adds `connections`, `max_connections`, `uptime_s` and the
reload state: `generation`, `reload_count`, `catalog_stale` and
`last_reload_error`. `ping` returns an empty result.

### Read confinement

`code_diver_read` and the other inspection tools are confined to the project root
(`--root`, or `--base-path`, or the working directory of the process). Use relative
paths; absolute paths, `..` components and symlinks that leave the root are refused.
