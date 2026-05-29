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

Current config:
- include: {config.scanner.include}
- exclude: {config.scanner.exclude}
- chunk_lines: {config.scanner.chunk_lines}
- symbol_chunks: {config.scanner.symbol_chunks}

Read-only observations:
{inventory}
""".strip()
