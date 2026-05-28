from __future__ import annotations

from pathlib import Path

from ..config.ai_index_config import AiIndexConfig
from ..domain import CodeItem
from ..generation import GenerationProvider
from ..services import CodebaseScanner
from .ai_index_context_collector import AiIndexContextCollector
from .ai_index_prompt_builder import AiIndexPromptBuilder
from .ai_index_response_parser import AiIndexResponseParser


class AiCodebaseScanner:
    def __init__(
        self,
        scanner: CodebaseScanner,
        generation_provider: GenerationProvider,
        config: AiIndexConfig,
    ):
        self.scanner = scanner
        self.generation_provider = generation_provider
        self.config = config

    def scan(self, root: Path) -> list[CodeItem]:
        context = AiIndexContextCollector(self.scanner, self.config).collect(root)
        prompt = AiIndexPromptBuilder(self.config).build(context)
        response = self.generation_provider.generate_json(prompt)
        return AiIndexResponseParser().parse(response, self.config.max_items)
