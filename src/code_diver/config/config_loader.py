from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..settings import Defaults
from .app_config import AppConfig
from .cross_encoder_rerank_config import CrossEncoderRerankConfig
from .editor_config import EditorConfig
from .embedding_config import EmbeddingConfig
from .env_file_config import EnvFileConfig
from .experiment_hypothesis_config import ExperimentHypothesisConfig
from .evaluation_config import EvaluationConfig
from .experiments_config import ExperimentsConfig
from .generation_config import GenerationConfig
from .graph_config import GraphConfig
from .ai_index_config import AiIndexConfig
from .hybrid_search_config import HybridSearchConfig
from .indexing_config import IndexingConfig
from .llm_rerank_config import LlmRerankConfig
from .metrics_config import MetricsConfig
from .pi_config import PiConfig
from .qdrant_config import QdrantConfig
from .recursive_search_config import RecursiveSearchConfig
from .scanner_config import ScannerConfig
from .search_config import SearchConfig
from .storage_config import StorageConfig
from .trace_config import TraceConfig
from .ui_config import UiConfig


class ConfigLoader:
    def load(self, path: Path | None) -> AppConfig:
        config_path = path or Defaults.CONFIG_PATH
        data = self._load_yaml(config_path)
        generation = self._generation(data.get("generation"))
        hybrid_search = self._hybrid_search(data.get("hybrid_search"))
        llm_rerank = self._llm_rerank(data.get("llm_rerank"))
        cross_encoder_rerank = self._cross_encoder_rerank(data.get("cross_encoder_rerank"))
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
            hybrid_search=hybrid_search,
            llm_rerank=llm_rerank,
            cross_encoder_rerank=cross_encoder_rerank,
            graph=self._graph(data.get("graph")),
            trace=self._trace(data.get("trace")),
            ui=self._ui(data.get("ui")),
            evaluation=self._evaluation(data.get("evaluation")),
            experiments=self._experiments(
                data.get("experiments"),
                generation=generation,
                hybrid_search=hybrid_search,
                llm_rerank=llm_rerank,
                cross_encoder_rerank=cross_encoder_rerank,
            ),
            metrics=self._metrics(data.get("metrics")),
            plugins=self._string_list(data.get("plugins")),
        )

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        if loaded is None:
            return {}
        if not isinstance(loaded, dict):
            raise ValueError(f"Config must be a YAML mapping: {path}")
        return loaded

    def _storage(self, data: Any) -> StorageConfig:
        mapping = self._mapping(data)
        return StorageConfig(
            provider=str(mapping.get("provider", Defaults.STORAGE_PROVIDER)),
            qdrant=self._qdrant(mapping.get("qdrant")),
        )

    def _env_file(self, data: Any) -> EnvFileConfig:
        if isinstance(data, str):
            return EnvFileConfig(path=Path(data))
        mapping = self._mapping(data)
        return EnvFileConfig(
            path=Path(mapping.get("path", Defaults.ENV_FILE)),
            override=bool(mapping.get("override", False)),
        )

    def _qdrant(self, data: Any) -> QdrantConfig:
        mapping = self._mapping(data)
        return QdrantConfig(
            url=str(mapping.get("url", Defaults.QDRANT_URL)),
            location=mapping.get("location"),
            collection=str(mapping.get("collection", Defaults.QDRANT_COLLECTION)),
            api_key=mapping.get("api_key"),
            api_key_env=mapping.get("api_key_env", Defaults.QDRANT_API_KEY_ENV),
            batch_size=int(mapping.get("batch_size", Defaults.QDRANT_BATCH_SIZE)),
        )

    def _embedding(self, data: Any) -> EmbeddingConfig:
        mapping = self._mapping(data)
        provider = str(mapping.get("provider", Defaults.EMBEDDING_PROVIDER))
        default_model = Defaults.EMBEDDING_MODEL if provider == Defaults.EMBEDDING_PROVIDER else None
        return EmbeddingConfig(
            provider=provider,
            model=mapping.get("model", default_model),
            dimensions=self._optional_int(mapping.get("dimensions", Defaults.EMBEDDING_DIMENSIONS)),
            api_key=mapping.get("api_key", Defaults.EMBEDDING_API_KEY),
            project=mapping.get("project"),
            location=mapping.get("location"),
            url=mapping.get("url", Defaults.EMBEDDING_URL),
            batch_size=int(mapping.get("batch_size", Defaults.EMBEDDING_BATCH_SIZE)),
            workers=int(mapping.get("workers", Defaults.EMBEDDING_WORKERS)),
            max_input_chars=self._optional_int(mapping.get("max_input_chars", Defaults.EMBEDDING_MAX_INPUT_CHARS)),
            retry_attempts=int(mapping.get("retry_attempts", Defaults.EMBEDDING_RETRY_ATTEMPTS)),
            retry_delay_seconds=float(mapping.get("retry_delay_seconds", Defaults.EMBEDDING_RETRY_DELAY_SECONDS)),
            document_prefix=self._optional_raw_string(
                mapping.get("document_prefix", Defaults.EMBEDDING_DOCUMENT_PREFIX)
            ),
            query_prefix=self._optional_raw_string(mapping.get("query_prefix", Defaults.EMBEDDING_QUERY_PREFIX)),
        )

    def _generation(self, data: Any, base: GenerationConfig | None = None) -> GenerationConfig:
        mapping = self._mapping(data)
        fallback_models = (
            self._string_list(mapping.get("fallback_models"))
            if "fallback_models" in mapping
            else list(base.fallback_models if base is not None else Defaults.GENERATION_FALLBACK_MODELS)
        )
        return GenerationConfig(
            provider=str(mapping.get("provider", base.provider if base is not None else Defaults.GENERATION_PROVIDER)),
            model=str(mapping.get("model", base.model if base is not None else Defaults.GENERATION_MODEL)),
            fallback_models=fallback_models,
            api_key=mapping.get("api_key", base.api_key if base is not None else None),
            project=mapping.get("project", base.project if base is not None else None),
            location=mapping.get("location", base.location if base is not None else None),
            url=mapping.get("url", base.url if base is not None else None),
            temperature=float(
                mapping.get("temperature", base.temperature if base is not None else Defaults.GENERATION_TEMPERATURE)
            ),
            thinking_budget=self._optional_int(
                mapping.get(
                    "thinking_budget",
                    base.thinking_budget if base is not None else Defaults.GENERATION_THINKING_BUDGET,
                )
            ),
            api_version=mapping.get(
                "api_version",
                base.api_version if base is not None else Defaults.GENERATION_API_VERSION,
            ),
            timeout_ms=int(
                mapping.get("timeout_ms", base.timeout_ms if base is not None else Defaults.GENERATION_TIMEOUT_MS)
            ),
            max_tokens=self._optional_int(
                mapping.get("max_tokens", base.max_tokens if base is not None else Defaults.GENERATION_MAX_TOKENS)
            ),
            response_format=self._response_format(
                mapping.get("response_format", base.response_format if base is not None else True)
            ),
            extra_body=dict(mapping.get("extra_body", base.extra_body if base is not None else {})),
            retry_attempts=int(
                mapping.get(
                    "retry_attempts",
                    base.retry_attempts if base is not None else Defaults.GENERATION_RETRY_ATTEMPTS,
                )
            ),
            retry_base_delay_seconds=float(
                mapping.get(
                    "retry_base_delay_seconds",
                    base.retry_base_delay_seconds
                    if base is not None
                    else Defaults.GENERATION_RETRY_BASE_DELAY_SECONDS,
                )
            ),
            retry_max_delay_seconds=float(
                mapping.get(
                    "retry_max_delay_seconds",
                    base.retry_max_delay_seconds
                    if base is not None
                    else Defaults.GENERATION_RETRY_MAX_DELAY_SECONDS,
                )
            ),
        )

    def _response_format(self, value: Any) -> bool | str | dict[str, object]:
        if isinstance(value, bool):
            return value
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "yes", "on"}:
                return True
            if normalized in {"false", "no", "off", "none"}:
                return False
            return normalized
        return bool(value)

    def _indexing(self, data: Any) -> IndexingConfig:
        mapping = self._mapping(data)
        return IndexingConfig(
            mode=str(mapping.get("mode", Defaults.INDEXING_MODE)),
            ai=self._ai_index(mapping.get("ai")),
        )

    def _ai_index(self, data: Any) -> AiIndexConfig:
        mapping = self._mapping(data)
        return AiIndexConfig(
            max_files=int(mapping.get("max_files", Defaults.AI_INDEX_MAX_FILES)),
            max_items=int(mapping.get("max_items", Defaults.AI_INDEX_MAX_ITEMS)),
            max_context_chars=int(mapping.get("max_context_chars", Defaults.AI_INDEX_MAX_CONTEXT_CHARS)),
            tree_depth=int(mapping.get("tree_depth", Defaults.AI_INDEX_TREE_DEPTH)),
            tree_limit=int(mapping.get("tree_limit", Defaults.AI_INDEX_TREE_LIMIT)),
            discovery_limit=int(mapping.get("discovery_limit", Defaults.AI_INDEX_DISCOVERY_LIMIT)),
            discovery_patterns=self._string_list(mapping.get("discovery_patterns"))
            or list(Defaults.AI_INDEX_DISCOVERY_PATTERNS),
        )

    def _pi(self, data: Any) -> PiConfig:
        mapping = self._mapping(data)
        return PiConfig(
            binary=str(mapping.get("binary", Defaults.PI_BINARY)),
            launcher_args=self._string_list(mapping.get("launcher_args")),
            extension=Path(mapping.get("extension", Defaults.PI_EXTENSION)),
            prompt_template=self._optional_path(mapping.get("prompt_template", Defaults.PI_PROMPT_TEMPLATE)),
            provider=mapping.get("provider", Defaults.PI_PROVIDER),
            model=mapping.get("model", Defaults.PI_MODEL),
            fallback_models=self._string_list(mapping.get("fallback_models")),
            timeout_seconds=int(mapping.get("timeout_seconds", Defaults.PI_TIMEOUT_SECONDS)),
            session_dir=Path(mapping.get("session_dir", Defaults.PI_SESSION_DIR)),
            tools=self._string_list(mapping.get("tools")),
            toolsets={
                str(name): self._string_list(tools)
                for name, tools in self._mapping(mapping.get("toolsets")).items()
            },
            extra_args=self._string_list(mapping.get("extra_args")),
            env={str(key): str(value) for key, value in self._mapping(mapping.get("env")).items()},
        )

    def _scanner(self, data: Any) -> ScannerConfig:
        mapping = self._mapping(data)
        return ScannerConfig(
            include=self._string_list(mapping.get("include")),
            exclude=self._string_list(mapping.get("exclude")),
            max_file_bytes=int(mapping.get("max_file_bytes", Defaults.MAX_FILE_BYTES)),
            line_chunks=bool(mapping.get("line_chunks", Defaults.LINE_CHUNKS)),
            chunk_lines=int(mapping.get("chunk_lines", Defaults.CHUNK_LINES)),
            structural_chunks=bool(mapping.get("structural_chunks", Defaults.STRUCTURAL_CHUNKS)),
            symbol_chunks=bool(mapping.get("symbol_chunks", Defaults.SYMBOL_CHUNKS)),
            symbol_body=bool(mapping.get("symbol_body", Defaults.SYMBOL_BODY)),
            file_summary_chunks=bool(mapping.get("file_summary_chunks", Defaults.FILE_SUMMARY_CHUNKS)),
            file_manifest_chunks=bool(mapping.get("file_manifest_chunks", Defaults.FILE_MANIFEST_CHUNKS)),
            max_symbols_per_file=self._optional_int(mapping.get("max_symbols_per_file")),
        )

    def _search(self, data: Any) -> SearchConfig:
        mapping = self._mapping(data)
        return SearchConfig(
            limit=int(mapping.get("limit", Defaults.SEARCH_LIMIT)),
            preview_lines=int(mapping.get("preview_lines", Defaults.PREVIEW_LINES)),
            strategy=str(mapping.get("strategy", Defaults.SEARCH_STRATEGY)),
        )

    def _recursive_search(self, data: Any) -> RecursiveSearchConfig:
        mapping = self._mapping(data)
        return RecursiveSearchConfig(
            rounds=int(mapping.get("rounds", Defaults.RECURSIVE_ROUNDS)),
            branch_limit=int(mapping.get("branch_limit", Defaults.RECURSIVE_BRANCH_LIMIT)),
            limit=int(mapping.get("limit", Defaults.RECURSIVE_PER_ROUND_LIMIT)),
        )

    def _hybrid_search(self, data: Any, base: HybridSearchConfig | None = None) -> HybridSearchConfig:
        mapping = self._mapping(data)
        return HybridSearchConfig(
            candidate_limit=int(
                mapping.get(
                    "candidate_limit",
                    base.candidate_limit if base is not None else Defaults.HYBRID_CANDIDATE_LIMIT,
                )
            ),
            lexical_candidate_limit=int(
                mapping.get(
                    "lexical_candidate_limit",
                    base.lexical_candidate_limit if base is not None else Defaults.HYBRID_LEXICAL_CANDIDATE_LIMIT,
                )
            ),
            vector_weight=float(
                mapping.get(
                    "vector_weight",
                    base.vector_weight if base is not None else Defaults.HYBRID_VECTOR_WEIGHT,
                )
            ),
            lexical_weight=float(
                mapping.get(
                    "lexical_weight",
                    base.lexical_weight if base is not None else Defaults.HYBRID_LEXICAL_WEIGHT,
                )
            ),
            path_weight=float(
                mapping.get("path_weight", base.path_weight if base is not None else Defaults.HYBRID_PATH_WEIGHT)
            ),
            symbol_weight=float(
                mapping.get("symbol_weight", base.symbol_weight if base is not None else Defaults.HYBRID_SYMBOL_WEIGHT)
            ),
            symbol_match_weight=float(
                mapping.get(
                    "symbol_match_weight",
                    base.symbol_match_weight if base is not None else Defaults.HYBRID_SYMBOL_MATCH_WEIGHT,
                )
            ),
            graph_weight=float(
                mapping.get("graph_weight", base.graph_weight if base is not None else Defaults.HYBRID_GRAPH_WEIGHT)
            ),
            file_vote_weight=float(
                mapping.get(
                    "file_vote_weight",
                    base.file_vote_weight if base is not None else Defaults.HYBRID_FILE_VOTE_WEIGHT,
                )
            ),
            vector_kind_limits=self._int_mapping(
                mapping.get(
                    "vector_kind_limits",
                    base.vector_kind_limits if base is not None else Defaults.HYBRID_VECTOR_KIND_LIMITS,
                )
            ),
            vector_kind_multipliers=self._float_mapping(
                mapping.get(
                    "vector_kind_multipliers",
                    base.vector_kind_multipliers if base is not None else Defaults.HYBRID_VECTOR_KIND_MULTIPLIERS,
                )
            ),
            graph_depth=int(
                mapping.get(
                    "graph_depth",
                    base.graph_depth if base is not None else Defaults.HYBRID_GRAPH_DEPTH,
                )
            ),
            graph_neighbor_limit=int(
                mapping.get(
                    "graph_neighbor_limit",
                    base.graph_neighbor_limit if base is not None else Defaults.HYBRID_GRAPH_NEIGHBOR_LIMIT,
                )
            ),
            lexical_scoring=str(
                mapping.get(
                    "lexical_scoring",
                    base.lexical_scoring if base is not None else Defaults.HYBRID_LEXICAL_SCORING,
                )
            ),
            fusion=str(mapping.get("fusion", base.fusion if base is not None else Defaults.HYBRID_FUSION)),
            rrf_k=int(mapping.get("rrf_k", base.rrf_k if base is not None else Defaults.HYBRID_RRF_K)),
            bm25_k1=float(mapping.get("bm25_k1", base.bm25_k1 if base is not None else Defaults.HYBRID_BM25_K1)),
            bm25_b=float(mapping.get("bm25_b", base.bm25_b if base is not None else Defaults.HYBRID_BM25_B)),
            routing_enabled=bool(
                mapping.get(
                    "routing_enabled",
                    base.routing_enabled if base is not None else Defaults.HYBRID_ROUTING_ENABLED,
                )
            ),
            preserve_vector_top=bool(
                mapping.get(
                    "preserve_vector_top",
                    base.preserve_vector_top if base is not None else Defaults.HYBRID_PRESERVE_VECTOR_TOP,
                )
            ),
            vector_top_score_margin=float(
                mapping.get(
                    "vector_top_score_margin",
                    base.vector_top_score_margin if base is not None else Defaults.HYBRID_VECTOR_TOP_SCORE_MARGIN,
                )
            ),
            item_kind_weights=self._float_mapping(
                mapping.get(
                    "item_kind_weights",
                    base.item_kind_weights if base is not None else Defaults.HYBRID_ITEM_KIND_WEIGHTS,
                )
            ),
            min_token_length=int(
                mapping.get(
                    "min_token_length",
                    base.min_token_length if base is not None else Defaults.HYBRID_MIN_TOKEN_LENGTH,
                )
            ),
            stop_words=self._string_list(mapping.get("stop_words"))
            or list(base.stop_words if base is not None else Defaults.HYBRID_STOP_WORDS),
        )

    def _llm_rerank(self, data: Any, base: LlmRerankConfig | None = None) -> LlmRerankConfig:
        mapping = self._mapping(data)
        return LlmRerankConfig(
            candidate_limit=int(
                mapping.get(
                    "candidate_limit",
                    base.candidate_limit if base is not None else Defaults.LLM_RERANK_CANDIDATE_LIMIT,
                )
            ),
            rerank_limit=int(
                mapping.get(
                    "rerank_limit",
                    base.rerank_limit if base is not None else Defaults.LLM_RERANK_RERANK_LIMIT,
                )
            ),
            max_preview_chars=int(
                mapping.get(
                    "max_preview_chars",
                    base.max_preview_chars if base is not None else Defaults.LLM_RERANK_MAX_PREVIEW_CHARS,
                )
            ),
            mode=str(mapping.get("mode", base.mode if base is not None else Defaults.LLM_RERANK_MODE)),
            include_reasons=bool(
                mapping.get(
                    "include_reasons",
                    base.include_reasons if base is not None else Defaults.LLM_RERANK_INCLUDE_REASONS,
                )
            ),
            preserve_top_candidate=bool(
                mapping.get(
                    "preserve_top_candidate",
                    base.preserve_top_candidate if base is not None else Defaults.LLM_RERANK_PRESERVE_TOP_CANDIDATE,
                )
            ),
            preserve_top_score_margin=float(
                mapping.get(
                    "preserve_top_score_margin",
                    base.preserve_top_score_margin
                    if base is not None
                    else Defaults.LLM_RERANK_PRESERVE_TOP_SCORE_MARGIN,
                )
            ),
            retry_attempts=int(
                mapping.get(
                    "retry_attempts",
                    base.retry_attempts if base is not None else Defaults.LLM_RERANK_RETRY_ATTEMPTS,
                )
            ),
            retry_base_delay_seconds=float(
                mapping.get(
                    "retry_base_delay_seconds",
                    base.retry_base_delay_seconds
                    if base is not None
                    else Defaults.LLM_RERANK_RETRY_BASE_DELAY_SECONDS,
                )
            ),
            retry_max_delay_seconds=float(
                mapping.get(
                    "retry_max_delay_seconds",
                    base.retry_max_delay_seconds
                    if base is not None
                    else Defaults.LLM_RERANK_RETRY_MAX_DELAY_SECONDS,
                )
            ),
        )

    def _cross_encoder_rerank(
        self,
        data: Any,
        base: CrossEncoderRerankConfig | None = None,
    ) -> CrossEncoderRerankConfig:
        mapping = self._mapping(data)
        return CrossEncoderRerankConfig(
            provider=str(
                mapping.get(
                    "provider",
                    base.provider if base is not None else Defaults.CROSS_ENCODER_RERANK_PROVIDER,
                )
            ),
            model=str(mapping.get("model", base.model if base is not None else Defaults.CROSS_ENCODER_RERANK_MODEL)),
            url=str(mapping.get("url", base.url if base is not None else Defaults.CROSS_ENCODER_RERANK_URL)),
            api_key=mapping.get("api_key", base.api_key if base is not None else None),
            candidate_limit=int(
                mapping.get(
                    "candidate_limit",
                    base.candidate_limit if base is not None else Defaults.CROSS_ENCODER_RERANK_CANDIDATE_LIMIT,
                )
            ),
            max_document_chars=int(
                mapping.get(
                    "max_document_chars",
                    base.max_document_chars if base is not None else Defaults.CROSS_ENCODER_RERANK_MAX_DOCUMENT_CHARS,
                )
            ),
            timeout_ms=int(
                mapping.get(
                    "timeout_ms",
                    base.timeout_ms if base is not None else Defaults.CROSS_ENCODER_RERANK_TIMEOUT_MS,
                )
            ),
            preserve_top_candidate=bool(
                mapping.get(
                    "preserve_top_candidate",
                    base.preserve_top_candidate
                    if base is not None
                    else Defaults.CROSS_ENCODER_RERANK_PRESERVE_TOP_CANDIDATE,
                )
            ),
            preserve_top_score_margin=float(
                mapping.get(
                    "preserve_top_score_margin",
                    base.preserve_top_score_margin
                    if base is not None
                    else Defaults.CROSS_ENCODER_RERANK_PRESERVE_TOP_SCORE_MARGIN,
                )
            ),
        )

    def _graph(self, data: Any) -> GraphConfig:
        mapping = self._mapping(data)
        return GraphConfig(
            enabled=bool(mapping.get("enabled", True)),
            artifact=Path(mapping.get("artifact", Defaults.GRAPH_ARTIFACT)),
            expansion_depth=int(mapping.get("expansion_depth", Defaults.GRAPH_EXPANSION_DEPTH)),
            neighbor_limit=int(mapping.get("neighbor_limit", Defaults.GRAPH_NEIGHBOR_LIMIT)),
            ast_enabled=bool(mapping.get("ast_enabled", Defaults.GRAPH_AST_ENABLED)),
            reference_edges_enabled=bool(
                mapping.get("reference_edges_enabled", Defaults.GRAPH_REFERENCE_EDGES_ENABLED)
            ),
            call_edges_enabled=bool(mapping.get("call_edges_enabled", Defaults.GRAPH_CALL_EDGES_ENABLED)),
        )

    def _trace(self, data: Any) -> TraceConfig:
        mapping = self._mapping(data)
        return TraceConfig(
            enabled=bool(mapping.get("enabled", Defaults.TRACE_ENABLED)),
            artifact=Path(mapping.get("artifact", Defaults.TRACE_ARTIFACT)),
            include_prompts=bool(mapping.get("include_prompts", Defaults.TRACE_INCLUDE_PROMPTS)),
        )

    def _ui(self, data: Any) -> UiConfig:
        mapping = self._mapping(data)
        return UiConfig(
            color=bool(mapping.get("color", Defaults.UI_COLOR)),
            pager=str(mapping.get("pager", Defaults.UI_PAGER)),
            links=bool(mapping.get("links", Defaults.UI_LINKS)),
            editor=self._editor(mapping.get("editor")),
        )

    def _editor(self, data: Any) -> EditorConfig:
        mapping = self._mapping(data)
        return EditorConfig(
            command=str(mapping.get("command", Defaults.EDITOR_COMMAND)),
            args=self._string_list(mapping.get("args")) or list(Defaults.EDITOR_ARGS),
        )

    def _evaluation(self, data: Any) -> EvaluationConfig:
        mapping = self._mapping(data)
        return EvaluationConfig(
            dataset=Path(mapping.get("dataset", Defaults.DATASET)),
            limit=int(mapping.get("limit", Defaults.SEARCH_LIMIT)),
            workers=int(mapping.get("workers", Defaults.EVALUATION_WORKERS)),
        )

    def _experiments(
        self,
        data: Any,
        *,
        generation: GenerationConfig,
        hybrid_search: HybridSearchConfig,
        llm_rerank: LlmRerankConfig,
        cross_encoder_rerank: CrossEncoderRerankConfig,
    ) -> ExperimentsConfig:
        mapping = self._mapping(data)
        return ExperimentsConfig(
            suite=str(mapping.get("suite", Defaults.EXPERIMENT_SUITE)),
            strategies=self._string_list(mapping.get("strategies")) or list(Defaults.EXPERIMENT_STRATEGIES),
            hypotheses=self._experiment_hypotheses(
                mapping.get("hypotheses"),
                generation=generation,
                hybrid_search=hybrid_search,
                llm_rerank=llm_rerank,
                cross_encoder_rerank=cross_encoder_rerank,
            ),
        )

    def _experiment_hypotheses(
        self,
        data: Any,
        *,
        generation: GenerationConfig,
        hybrid_search: HybridSearchConfig,
        llm_rerank: LlmRerankConfig,
        cross_encoder_rerank: CrossEncoderRerankConfig,
    ) -> list[ExperimentHypothesisConfig]:
        if data is None:
            return []
        if not isinstance(data, list):
            raise ValueError("experiments.hypotheses must be a YAML list.")
        hypotheses: list[ExperimentHypothesisConfig] = []
        for value in data:
            mapping = self._mapping(value)
            name = str(mapping.get("name") or "").strip()
            if not name:
                raise ValueError("Each experiment hypothesis requires a name.")
            hypotheses.append(
                ExperimentHypothesisConfig(
                    name=name,
                    strategy=self._optional_string(mapping.get("strategy")),
                    toolset=self._optional_string(mapping.get("toolset")),
                    tools=self._string_list(mapping.get("tools")),
                    generation=self._generation(mapping.get("generation"), base=generation)
                    if mapping.get("generation") is not None
                    else None,
                    rerank_generation=self._generation(mapping.get("rerank_generation"), base=generation)
                    if mapping.get("rerank_generation") is not None
                    else None,
                    hybrid_search=self._hybrid_search(mapping.get("hybrid_search"), base=hybrid_search)
                    if mapping.get("hybrid_search") is not None
                    else None,
                    llm_rerank=self._llm_rerank(mapping.get("llm_rerank"), base=llm_rerank)
                    if mapping.get("llm_rerank") is not None
                    else None,
                    cross_encoder_rerank=self._cross_encoder_rerank(
                        mapping.get("cross_encoder_rerank"),
                        base=cross_encoder_rerank,
                    )
                    if mapping.get("cross_encoder_rerank") is not None
                    else None,
                    description=self._optional_string(mapping.get("description")),
                )
            )
        return hypotheses

    def _metrics(self, data: Any) -> MetricsConfig:
        mapping = self._mapping(data)
        return MetricsConfig(
            enabled=bool(mapping.get("enabled", Defaults.METRICS_ENABLED)),
            url=str(mapping.get("url", Defaults.CLICKHOUSE_URL)),
            database=str(mapping.get("database", Defaults.CLICKHOUSE_DATABASE)),
            username=str(mapping.get("username", Defaults.CLICKHOUSE_USERNAME)),
            password=str(mapping.get("password", Defaults.CLICKHOUSE_PASSWORD)),
            docker_container=mapping.get("docker_container"),
            metrics_table=str(mapping.get("metrics_table", Defaults.CLICKHOUSE_METRICS_TABLE)),
            cases_table=str(mapping.get("cases_table", Defaults.CLICKHOUSE_CASES_TABLE)),
            timeout_seconds=float(mapping.get("timeout_seconds", Defaults.CLICKHOUSE_TIMEOUT_SECONDS)),
            retention_days=int(mapping.get("retention_days", Defaults.CLICKHOUSE_RETENTION_DAYS)),
        )

    def _mapping(self, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("Expected a YAML mapping.")
        return value

    def _string_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("Expected a YAML list.")
        return [str(item) for item in value]

    def _float_mapping(self, value: Any) -> dict[str, float]:
        return {str(key): float(item) for key, item in self._mapping(value).items()}

    def _int_mapping(self, value: Any) -> dict[str, int]:
        return {str(key): int(item) for key, item in self._mapping(value).items()}

    def _optional_int(self, value: Any) -> int | None:
        if value is None:
            return None
        return int(value)

    def _optional_string(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _optional_raw_string(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value)
        return text if text else None

    def _optional_path(self, value: Any) -> Path | None:
        if value is None:
            return None
        return Path(value)
