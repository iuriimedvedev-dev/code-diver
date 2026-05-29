from __future__ import annotations

from pathlib import Path

from ..config import AppConfig
from ..services import CodebaseScanner
from .repository_inventory import RepositoryInventory


class IndexPlanPromptBuilder:
    def build(self, root: Path, config: AppConfig, scanner: CodebaseScanner) -> str:
        inventory = RepositoryInventory(
            scanner,
            config.indexing.ai.tree_depth,
            config.indexing.ai.tree_limit,
        ).render(root)
        return f"""
You are the indexing orchestrator for a code retrieval system.
You choose a repository-agnostic indexing plan. You do not inspect function bodies or write files.
Use only the collected read-only observations below: repository tree, indexable file stats, sample paths, and symbol signatures.

Return JSON only with this shape:
{{
  "rationale": "one short reason for the plan",
  "include": ["additional glob patterns to index, empty means no additions"],
  "exclude": ["glob patterns to exclude in addition to current config"],
  "chunk_lines": 120,
  "symbol_chunks": true
}}

Selection rules:
- Preserve broad coverage for any language stack; do not hardcode project-specific guesses.
- Current include patterns are always preserved; return only extra include patterns when coverage is missing.
- Keep source, tests, docs, manifests, config, migrations, and operational entrypoints unless they are generated or vendored.
- Exclude caches, generated output, vendored dependencies, binary assets, logs, and local tool state.
- Prefer symbol_chunks=true for source-heavy repositories with classes, functions, APIs, commands, or services.
- Prefer symbol_chunks=false only for documentation/config-heavy repositories where fixed line windows are more useful.
- Use chunk_lines as a fallback window for files without symbols; 80-180 is usually better for dense code, 180-360 for prose/config.
- Do not return paths that are not visible in the observations.
- Favor a plan that helps downstream AST GraphRAG: preserve files with import graphs, public APIs, routing, CLI commands, schemas, and tests.
- Do not include secrets, local state, generated folders, dependency caches, or build artifacts.

Read-only toolkit available to the Pi assistant after an index exists:
- code_diver_index: build or refresh the index artifact.
- code_diver_search: vector, recursive, orchestrated, or graph-backed query retrieval.
- code_diver_inspect: run independent search, rg, grep, tree, read, and symbols probes concurrently.
- code_diver_tree: gitignore-aware repository tree.
- code_diver_symbols: language-agnostic symbol signatures.
- code_diver_read: bounded file excerpts.
- code_diver_grep: literal gitignore-aware search.
- code_diver_rg: regex gitignore-aware search.
- code_diver_open: open a retrieved result in the configured editor.
- code_diver_evaluate and code_diver_experiment: reproducible retrieval metrics.
This planning response cannot call more tools; reason from the observations below.

Current config:
- include: {config.scanner.include}
- exclude: {config.scanner.exclude}
- chunk_lines: {config.scanner.chunk_lines}
- symbol_chunks: {config.scanner.symbol_chunks}

Read-only observations:
{inventory}
""".strip()
