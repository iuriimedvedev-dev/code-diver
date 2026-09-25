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
