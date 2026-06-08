from __future__ import annotations

from dataclasses import dataclass, field

from .cross_encoder_rerank_config import CrossEncoderRerankConfig
from .generation_config import GenerationConfig
from .graph_file_search_config import GraphFileSearchConfig
from .hybrid_search_config import HybridSearchConfig
from .llm_rerank_config import LlmRerankConfig


@dataclass(slots=True)
class ExperimentHypothesisConfig:
    name: str
    strategy: str | None = None
    toolset: str | None = None
    tools: list[str] = field(default_factory=list)
    generation: GenerationConfig | None = None
    rerank_generation: GenerationConfig | None = None
    graph_file_search: GraphFileSearchConfig | None = None
    hybrid_search: HybridSearchConfig | None = None
    llm_rerank: LlmRerankConfig | None = None
    cross_encoder_rerank: CrossEncoderRerankConfig | None = None
    description: str | None = None
