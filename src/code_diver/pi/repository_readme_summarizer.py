from __future__ import annotations

from ..generation import SUMMARY_SCHEMA, GenerationProvider
from ..generation.jsonish_parser import JsonishParser


class RepositoryReadmeSummarizer:
    def __init__(self, provider: GenerationProvider, max_input_chars: int = 24000):
        self.provider = provider
        self.max_input_chars = max_input_chars
        self.parser = JsonishParser()

    def summarize(self, source_name: str, text: str) -> str:
        prompt = f"""
Summarize this repository README for a code-search and code-explanation agent.

Keep exact project facts, package/module names, commands, routes, technology names,
configuration keys, and workflow names. Drop marketing prose and repetition.
Return JSON only: {{"summary":"compact markdown bullet summary"}}

Source: {source_name}

README:
{text[: self.max_input_chars]}
""".strip()
        result = self.provider.generate_json_result(prompt, schema=SUMMARY_SCHEMA)
        payload = self.parser.parse_object(result.text)
        summary = str(payload.get("summary") or "").strip()
        if not summary:
            raise ValueError("README summarizer returned an empty summary.")
        return summary
