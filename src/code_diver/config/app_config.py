from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..settings import Defaults
from .embedding_config import EmbeddingConfig
from .env_file_config import EnvFileConfig
from .evaluation_config import EvaluationConfig
from .experiments_config import ExperimentsConfig
from .generation_config import GenerationConfig
from .graph_config import GraphConfig
from .hybrid_search_config import HybridSearchConfig
from .indexing_config import IndexingConfig
from .metrics_config import MetricsConfig
from .pi_config import PiConfig
from .recursive_search_config import RecursiveSearchConfig
from .scanner_config import ScannerConfig
from .search_config import SearchConfig
from .storage_config import StorageConfig
from .trace_config import TraceConfig
from .ui_config import UiConfig


@dataclass(slots=True)
class AppConfig:
    root: Path = Defaults.ROOT
    artifact: Path = Defaults.ARTIFACT
    env_file: EnvFileConfig = field(default_factory=EnvFileConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    generation: GenerationConfig = field(default_factory=GenerationConfig)
    indexing: IndexingConfig = field(default_factory=IndexingConfig)
    pi: PiConfig = field(default_factory=PiConfig)
    scanner: ScannerConfig = field(default_factory=ScannerConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    recursive_search: RecursiveSearchConfig = field(default_factory=RecursiveSearchConfig)
    hybrid_search: HybridSearchConfig = field(default_factory=HybridSearchConfig)
    graph: GraphConfig = field(default_factory=GraphConfig)
    trace: TraceConfig = field(default_factory=TraceConfig)
    ui: UiConfig = field(default_factory=UiConfig)
    evaluation: EvaluationConfig = field(default_factory=EvaluationConfig)
    experiments: ExperimentsConfig = field(default_factory=ExperimentsConfig)
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    plugins: list[str] = field(default_factory=list)
