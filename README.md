# Code Diver

`code-diver` is a small CLI sandbox for codebase RAG experiments. The CLI is the entrypoint, while Pi is the assistant backbone: `chat` and `ask` launch Pi with a local Code Diver extension that exposes indexing, search, open, and evaluation as Pi tools.

## Setup

```bash
uv sync
export GEMINI_API_KEY="..."
```

Pi must also be installed and available as `pi` on `PATH`.

Gemini-backed defaults:

- Pi model: `gemini-3.5-flash`
- embedding model: `gemini-embedding-2`
- embedding dimensions: `768`

Configuration lives in `code-diver.yml`. For local, reproducible experiments without an API key, set:

```yaml
embedding:
  provider: hash
  dimensions: 256
```

## Commands

```bash
uv run code-diver index
uv run code-diver search "where is authentication configured?"
uv run code-diver open "where is authentication configured?"
uv run code-diver chat
uv run code-diver ask "summarize the retrieval pipeline"
uv run code-diver evaluate
```

`chat` starts interactive Pi. `ask` runs Pi in print mode. Both load `.pi/extensions/code-diver-rag.ts`, which registers:

- `code_diver_index`
- `code_diver_search`
- `code_diver_open`
- `code_diver_evaluate`

Pi arguments and the active tool allowlist are configured in `code-diver.yml`:

```yaml
pi:
  binary: pi
  extension: .pi/extensions/code-diver-rag.ts
  prompt_template: .pi/prompts/code-diver-rag.md
  provider: google
  model: gemini-3.5-flash
  tools:
    - read
    - grep
    - find
    - ls
    - bash
    - code_diver_search
```

`search` renders colored, syntax-highlighted snippets and uses a pager for larger result sets. Editor opening is configured in `code-diver.yml`:

```yaml
ui:
  pager: auto
  links: true
  editor:
    command: code
    args: ["-g", "{path}:{line}"]
```

## Dataset Format

Evaluation datasets are JSONL. Each line is one retrieval task:

```json
{"id":"scanner-basic","query":"code that scans repository files","expected":["src/code_diver/services/codebase_scanner.py"]}
```

`expected` entries can match an indexed item id exactly, or be a path prefix such as `src/code_diver/services/codebase_scanner.py`.

## Plugin Hooks

Add one or more plugin files to `code-diver.yml`. A plugin can define any of these functions:

```yaml
plugins:
  - path/to/plugin.py
```

```python
def collect_items(root, config):
    yield {"id": "docs:intro", "path": "README.md", "title": "Intro", "content": "...", "metadata": {}}

def transform_item(item):
    item["content"] = item["content"].strip()
    return item

def prepare_query(query):
    return query
```

The core scanner always runs first. Plugins can add extra items, transform all items, and normalize queries.
