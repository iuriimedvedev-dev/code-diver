## multi_query_config.py

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class MultiQueryConfig:
    """H-84: deterministic multi-query expansion with reciprocal-rank fusion.

    The original query is always retained and receives an optional score weight;
    generated variants are bounded and can be searched concurrently. Disabled by
    default so existing retrieval behavior is unchanged.
    """

    enabled: bool = False
    max_variants: int = 4
    rrf_k: int = 60
    original_query_weight: float = 2.0
    llm_rewrites_enabled: bool = False
    parallel_variants: bool = True
    max_variant_workers: int = 4
    union_rerank: bool = False
```

## config_loader.py (relevant excerpt)

```python
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from ..settings import Defaults
from .ai_index_config import AiIndexConfig
from .app_config import AppConfig
from .cross_encoder_rerank_config import CrossEncoderRerankConfig
from .editor_config import EditorConfig
from .embedding_config import EmbeddingConfig
from .env_file_config import EnvFileConfig
from .evaluation_config import EvaluationConfig
from .experiment_hypothesis_config import ExperimentHypothesisConfig
from .experiments_config import ExperimentsConfig
from .fan_out_fusion_config import FanOutFusionConfig
from .generation_config import GenerationConfig
from .graph_config import GraphConfig
from .graph_file_search_config import GraphFileSearchConfig
from .hybrid_search_config import HybridSearchConfig
from .indexing_config import IndexingConfig
from .llm_rerank_config import LlmRerankConfig
from .metrics_config import MetricsConfig
from .multi_query_config import MultiQueryConfig
from .pi_config import PiConfig
from .pi_repo_context_config import PiRepoContextConfig
from .qdrant_config import QdrantConfig
from .recursive_search_config import RecursiveSearchConfig
from .scanner_config import ScannerConfig
from .search_config import SearchConfig
from .storage_config import StorageConfig
from .trace_config import TraceConfig
from .ui_config import UiConfig
```

```python
    def load(self, path: Path | None) -> AppConfig:
        config_path = path or Defaults.CONFIG_PATH
        data = self._load_yaml(config_path)
        generation = self._generation(data.get("generation"))
        graph_file_search = self._graph_file_search(data.get("graph_file_search"))
        hybrid_search = self._hybrid_search(data.get("hybrid_search"))
        llm_rerank = self._llm_rerank(data.get("llm_rerank"), generation=generation)
        cross_encoder_rerank = self._cross_encoder_rerank(data.get("cross_encoder_rerank"))
        multi_query = self._multi_query(data.get("multi_query"))
        return AppConfig(
            root=Path(data.get("root", Defaults.ROOT)),
            artifact=Path(data.get("artifact", Defaults.ARTIFACT)),
            env_file=self._env_file(data.get("env_file")),
            storage=self._storage(data.get("storage")),
            embedding=self._embedding(data.get("embedding")),
            generation=generation,
            indexing=self._indexing(data.get("indexing")),
            pi=self._pi(data.get("pi")),
            scanner=self._scanner(data.get("scanner")),
            search=self._search(data.get("search")),
            recursive_search=self._recursive_search(data.get("recursive_search")),
            graph_file_search=graph_file_search,
            hybrid_search=hybrid_search,
            llm_rerank=llm_rerank,
            cross_encoder_rerank=cross_encoder_rerank,
            multi_query=multi_query,
            graph=self._graph(data.get("graph")),
            trace=self._trace(data.get("trace")),
            ui=self._ui(data.get("ui")),
            evaluation=self._evaluation(data.get("evaluation")),
            experiments=self._experiments(
                data.get("experiments"),
                generation=generation,
                graph_file_search=graph_file_search,
                hybrid_search=hybrid_search,
                llm_rerank=llm_rerank,
                cross_encoder_rerank=cross_encoder_rerank,
            ),
            metrics=self._metrics(data.get("metrics")),
            plugins=self._string_list(data.get("plugins")),
        )
```

```python
    def _fan_out_fusion(self, data: Any) -> FanOutFusionConfig:
        mapping = self._mapping(data)
        base = FanOutFusionConfig()
        return FanOutFusionConfig(
            enabled=bool(mapping.get("enabled", base.enabled)),
            queries=int(mapping.get("queries", base.queries)),
            search_limit=int(mapping.get("search_limit", base.search_limit)),
            rrf_k=int(mapping.get("rrf_k", base.rrf_k)),
            rerank=bool(mapping.get("rerank", base.rerank)),
            rerank_pool=int(mapping.get("rerank_pool", base.rerank_pool)),
            monotonic=bool(mapping.get("monotonic", base.monotonic)),
            baseline_head=int(mapping.get("baseline_head", base.baseline_head)),
            union_rerank=bool(mapping.get("union_rerank", base.union_rerank)),
            union_candidate_limit=int(mapping.get("union_candidate_limit", base.union_candidate_limit)),
            probe_search_limit=int(mapping.get("probe_search_limit", base.probe_search_limit)),
            parallel_probes=bool(mapping.get("parallel_probes", base.parallel_probes)),
            max_probe_workers=int(mapping.get("max_probe_workers", base.max_probe_workers)),
        )

    def _multi_query(self, data: Any) -> MultiQueryConfig:
        mapping = self._mapping(data)
        base = MultiQueryConfig()
        return MultiQueryConfig(
            enabled=bool(mapping.get("enabled", base.enabled)),
            union_rerank=bool(mapping.get("union_rerank", base.union_rerank)),
            max_variants=int(mapping.get("max_variants", base.max_variants)),
            rrf_k=int(mapping.get("rrf_k", base.rrf_k)),
            original_query_weight=float(mapping.get("original_query_weight", base.original_query_weight)),
            llm_rewrites_enabled=bool(mapping.get("llm_rewrites_enabled", base.llm_rewrites_enabled)),
            parallel_variants=bool(mapping.get("parallel_variants", base.parallel_variants)),
            max_variant_workers=int(mapping.get("max_variant_workers", base.max_variant_workers)),
        )
```

## defaults.py (relevant excerpt or note)

The requested source file `src/code_diver/config/defaults.py` does not exist. No defaults excerpt was available at that exact path.
