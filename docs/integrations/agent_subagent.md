# Code Diver Subagent Configuration

Code Diver includes a ready-to-use subagent definition designed for **OpenCode**, **Claude Desktop / Claude Code**, and other multi-agent frameworks.

This subagent equips the AI system with dedicated code-search tools, structural AST navigation, and targeted excerpt retrieval, isolating large code search tasks from main reasoning loops.

---

## Installation

### In OpenCode

Copy or symlink the definition file into your OpenCode agents directory:

```bash
# Option A: Global user-level agent
mkdir -p ~/.config/opencode/agent
cp integrations/opencode/code-diver.md ~/.config/opencode/agent/code-diver.md

# Option B: Project-level agent (committed with your repo)
mkdir -p .opencode/agents
cp integrations/opencode/code-diver.md .opencode/agents/code-diver.md
```

Ensure Code Diver MCP server is declared in your `opencode.json`:

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

---

## How It Works

The subagent follows a 4-step disciplined retrieval loop:
1. **Subsecond Search**: Uses `code_diver_search` or submits non-blocking background searches with `code_diver_submit_agent_search`.
2. **Structural Inspection**: Queries `code_diver_symbols` to inspect classes, methods, and functions in candidates without loading full source files.
3. **Bounded Reading**: Reads exact line spans with `code_diver_read` to verify logic and implementation details.
4. **Synthesized Report**: Returns exact file paths (`path:start_line-end_line`), concise architecture summaries, and exact findings back to the main agent.
