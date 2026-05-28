from __future__ import annotations

from ..config.ai_index_config import AiIndexConfig
from .ai_index_context import AiIndexContext
from .ai_index_tool_manifest import AiIndexToolManifest


class AiIndexPromptBuilder:
    def __init__(self, config: AiIndexConfig):
        self.config = config

    def build(self, context: AiIndexContext) -> str:
        body = "\n\n".join(
            [
                self._instructions(),
                f"READ-ONLY TOOLS AVAILABLE TO YOU:\n{AiIndexToolManifest().render()}",
                f"REPOSITORY TREE:\n{context.tree}",
                f"DISCOVERY OUTPUT:\n{self._join_discoveries(context.discoveries)}",
                f"CANDIDATE EXCERPTS:\n{self._join_candidates(context)}",
            ]
        )
        return body[: self.config.max_context_chars]

    def _instructions(self) -> str:
        return f"""
You are building a high-quality semantic code index for retrieval.
Select the most useful code items from the observations. Prefer real architectural units:
entrypoints, public APIs, data models, configuration, dependency boundaries, workflows, tests, docs, and cross-cutting modules.
Return only JSON with this shape:
{{
  "items": [
    {{
      "path": "relative/path.py",
      "title": "short searchable title",
      "summary": "what this code does, when to retrieve it, important identifiers",
      "kind": "entrypoint|api|model|config|workflow|test|doc|module|other",
      "start_line": 1,
      "end_line": 120,
      "keywords": ["identifier", "domain term"]
    }}
  ]
}}
Rules:
- Do not invent files or behavior.
- Use relative paths exactly as shown.
- Make summaries dense and query-oriented.
- Produce at most {self.config.max_items} items.
""".strip()

    def _join_discoveries(self, discoveries: list[str]) -> str:
        return "\n".join(discoveries) if discoveries else "(none)"

    def _join_candidates(self, context: AiIndexContext) -> str:
        chunks: list[str] = []
        for candidate in context.candidates:
            location = candidate.path
            if candidate.start_line is not None:
                location = f"{location}:{candidate.start_line}-{candidate.end_line}"
            chunks.append(f"--- {location}\n{candidate.content}")
        return "\n\n".join(chunks)
