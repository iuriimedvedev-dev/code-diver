from __future__ import annotations

from dataclasses import dataclass, field

from .generation_config import GenerationConfig
from .hybrid_search_config import HybridSearchConfig
from .llm_rerank_config import LlmRerankConfig


@dataclass(slots=True)
class ExperimentHypothesisConfig:
    name: str
    strategy: str | None = None
    toolset: str | None = None
    tools: list[str] = field(default_factory=list)
    generation: GenerationConfig | None = None
    hybrid_search: HybridSearchConfig | None = None
    llm_rerank: LlmRerankConfig | None = None
    description: str | None = None
