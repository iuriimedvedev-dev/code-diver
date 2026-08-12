from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from code_diver.cli import (
    chat_prompt_and_session,
    cmd_init,
    cmd_monitor,
    cmd_provider_batch_test,
    cmd_provider_test,
    cmd_search,
    command_homoglyph_fold,
    config_for_indexing_hypothesis,
    current_repo_collection_prefix,
    direct_search_eval_result,
    direct_search_metrics,
    make_embedding_provider,
    make_ephemeral_search_tool_handler,
    make_search_agent_runner,
    make_search_tool_handler,
    normalize_command_homoglyphs,
    prepare_index_collection,
    search_agent_binary_available,
    search_agent_prompt,
)
from code_diver.config import AppConfig
from code_diver.config.embedding_config import EmbeddingConfig
from code_diver.config.graph_config import GraphConfig
from code_diver.config.pi_config import PiConfig
from code_diver.config.qdrant_config import QdrantConfig
from code_diver.config.scanner_config import ScannerConfig
from code_diver.config.storage_config import StorageConfig
from code_diver.config.trace_config import TraceConfig
from code_diver.domain import CodeItem, EvalCase, SearchResult
from code_diver.pi import AgyCliAgentRunner, GeminiCliAgentRunner, PiRunner
from code_diver.providers import ProviderCheckResult, VertexBatchTestResult

pytestmark = pytest.mark.unit


def test_normalize_command_homoglyphs_fixes_provider_typo_without_touching_query() -> (
    None
):
    tokens = ["--config", "cfg.yml", "proмider", "test", "мама"]

    assert normalize_command_homoglyphs(tokens) == [
        "--config",
        "cfg.yml",
        "provider",
        "test",
        "мама",
    ]
    assert command_homoglyph_fold("proмider") == "promider"


def test_make_search_agent_runner_uses_gemini_cli_provider() -> None:
    assert isinstance(
        make_search_agent_runner(AppConfig(pi=PiConfig(provider="gemini-cli"))),
        GeminiCliAgentRunner,
    )
    assert isinstance(
        make_search_agent_runner(AppConfig(pi=PiConfig(provider="gemini_cli"))),
        GeminiCliAgentRunner,
    )
    assert isinstance(make_search_agent_runner(AppConfig()), PiRunner)


def test_make_search_agent_runner_uses_agy_cli_provider() -> None:
    assert isinstance(
        make_search_agent_runner(AppConfig(pi=PiConfig(provider="agy-cli"))),
        AgyCliAgentRunner,
    )
    assert isinstance(
        make_search_agent_runner(AppConfig(pi=PiConfig(provider="antigravity"))),
        AgyCliAgentRunner,
    )


def test_search_agent_prompt_keeps_external_cli_queries_raw() -> None:
    assert (
        search_agent_prompt(
            AppConfig(pi=PiConfig(provider="agy-cli")), "where is auth?"
        )
        == "where is auth?"
    )
    assert (
        search_agent_prompt(
            AppConfig(pi=PiConfig(provider="gemini-cli")), "where is auth?"
        )
        == "where is auth?"
    )
    assert "code_diver_search" in search_agent_prompt(AppConfig(), "where is auth?")


def test_gemini_cli_agent_runner_strips_cli_noise() -> None:
    output = "e5dcb07510e112e2616de67083a7bd5c\nMCP issues detected. Run /mcp list for status.\nHook system message: e5dcb07510e112e2616de67083a7bd5c\n\nActual answer."

    assert GeminiCliAgentRunner()._clean_cli_noise(output) == "Actual answer."


class FakeStrategy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, limit: int) -> list[SearchResult]:
        self.calls.append((query, limit))
        return [
            SearchResult(
                item=CodeItem(
                    id="src/app.py#abc",
                    path="src/app.py",
                    title="src/app.py:1-10",
                    content="def app(): pass",
                    start_line=1,
                    end_line=10,
                    metadata={"index_kind": "chunk"},
                ),
                score=0.9,
            )
        ]


class FakeEmbeddingProvider:
    name = "test"
    model = "keyword"
    dimensions = 3

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, query: str) -> list[float]:
        return self._embed(query)

    def _embed(self, text: str) -> list[float]:
        lowered = text.lower()
        return [
            float("update" in lowered),
            float("delete" in lowered),
            float("user" in lowered),
        ]


class FakeClosableVectorStore:
    def __init__(self, exists: bool) -> None:
        self._exists = exists
        self.deleted_prefixes: list[str] = []
        self.closed = False

    def exists(self) -> bool:
        return self._exists

    def delete_collections_with_prefix(self, prefix: str) -> list[str]:
        self.deleted_prefixes.append(prefix)
        return [prefix]

    def close(self) -> None:
        self.closed = True


def test_config_for_indexing_hypothesis_isolates_qdrant_json_and_graph_artifacts(
    tmp_path: Path,
) -> None:
    config = AppConfig(
        artifact=tmp_path / "index.json",
        storage=StorageConfig(qdrant=QdrantConfig(collection="base_collection")),
        graph=GraphConfig(artifact=tmp_path / "graph.json"),
    )

    isolated = config_for_indexing_hypothesis(config, "ai_index_rg_only", "run123")

    assert (
        isolated.storage.qdrant.collection == "base_collection_ai_index_rg_only_run123"
    )
    assert isolated.artifact == tmp_path / "index_ai_index_rg_only_run123.json"
    assert isolated.graph.artifact == tmp_path / "graph_ai_index_rg_only_run123.json"
    assert config.artifact == tmp_path / "index.json"
    assert config.graph.artifact == tmp_path / "graph.json"


def test_prepare_index_collection_rejects_existing_collection_without_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeClosableVectorStore(exists=True)
    config = AppConfig(
        root=tmp_path,
        storage=StorageConfig(
            provider="qdrant",
            qdrant=QdrantConfig(collection="code_diver__repo_demo__emb_qwen"),
        ),
    )
    monkeypatch.setattr("code_diver.cli.make_vector_store", lambda config: store)

    with pytest.raises(RuntimeError, match="--update-index"):
        prepare_index_collection(
            Namespace(update_index=False, override_repo=False, reindex=False),
            config,
            progress=False,
        )

    assert store.closed is True


def test_prepare_index_collection_allows_update_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeClosableVectorStore(exists=True)
    config = AppConfig(root=tmp_path, storage=StorageConfig(provider="qdrant"))
    monkeypatch.setattr("code_diver.cli.make_vector_store", lambda config: store)

    prepare_index_collection(
        Namespace(update_index=True, override_repo=False, reindex=False),
        config,
        progress=False,
    )

    assert store.deleted_prefixes == []
    assert store.closed is True


def test_prepare_index_collection_override_deletes_repo_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeClosableVectorStore(exists=True)
    config = AppConfig(
        root=tmp_path,
        storage=StorageConfig(
            provider="qdrant",
            qdrant=QdrantConfig(collection="code_diver__repo_demo__emb_qwen"),
        ),
    )
    monkeypatch.setattr("code_diver.cli.make_vector_store", lambda config: store)

    prepare_index_collection(
        Namespace(update_index=False, override_repo=True, reindex=False),
        config,
        progress=False,
    )

    assert store.deleted_prefixes == ["code_diver__repo_demo"]
    assert store.closed is True


def test_current_repo_collection_prefix_falls_back_to_collection_name() -> None:
    config = AppConfig(
        storage=StorageConfig(qdrant=QdrantConfig(collection="manual_collection"))
    )

    assert current_repo_collection_prefix(config) == "manual_collection"


def test_cmd_init_installs_pi_runtime_before_runtime_wizard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class FakePiRuntimeManager:
        def install(self) -> None:
            calls.append("pi-install")

    class FakeRuntimeSetupWizard:
        def run(self, **kwargs) -> None:
            calls.append("runtime-wizard")

    monkeypatch.setattr("code_diver.cli.PiRuntimeManager", FakePiRuntimeManager)
    monkeypatch.setattr("code_diver.cli.RuntimeSetupWizard", FakeRuntimeSetupWizard)
    monkeypatch.setattr(
        "code_diver.cli.ensure_storage_runtime",
        lambda config, progress=True: calls.append("qdrant"),
    )

    result = cmd_init(
        Namespace(
            embedding="gemini",
            platform="api",
            runtime=None,
            skip_install=False,
            start=False,
            yes=True,
        ),
        AppConfig(),
    )

    assert result == 0
    assert calls == ["pi-install", "runtime-wizard", "qdrant"]


def test_cmd_init_warns_when_storage_runtime_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    class FakePiRuntimeManager:
        def install(self) -> None:
            pass

    class FakeRuntimeSetupWizard:
        def run(self, **kwargs) -> None:
            pass

    monkeypatch.setattr("code_diver.cli.PiRuntimeManager", FakePiRuntimeManager)
    monkeypatch.setattr("code_diver.cli.RuntimeSetupWizard", FakeRuntimeSetupWizard)

    def fail_storage(config, progress=True):
        raise RuntimeError("Docker CLI was not found")

    monkeypatch.setattr("code_diver.cli.ensure_storage_runtime", fail_storage)

    result = cmd_init(
        Namespace(
            embedding="gemini",
            platform="api",
            runtime=None,
            skip_install=False,
            start=False,
            yes=True,
        ),
        AppConfig(),
    )

    assert result == 0
    assert "storage runtime was not started during init" in capsys.readouterr().err


def test_make_search_tool_handler_reuses_injected_strategy() -> None:
    strategy = FakeStrategy()
    handler = make_search_tool_handler(strategy)

    payload = handler("where is app?", 5)
    second_payload = handler("where is cli?", 3)

    assert '"path": "src/app.py"' in payload
    assert '"indexKind": "chunk"' in payload
    assert '"score": 0.9' in second_payload
    assert strategy.calls == [("where is app?", 5), ("where is cli?", 3)]


def test_make_ephemeral_search_tool_handler_returns_timing_metrics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "src" / "users.py"
    source.parent.mkdir()
    source.write_text(
        "class UserController:\n"
        "    def update_user(self, user_id):\n"
        "        return user_id\n",
        encoding="utf-8",
    )
    config = AppConfig(
        root=tmp_path,
        scanner=ScannerConfig(
            include=["**/*.py"],
            line_chunks=False,
            structural_chunks=True,
            symbol_chunks=True,
        ),
    )
    monkeypatch.setattr(
        "code_diver.cli.make_embedding_provider",
        lambda config, metadata=None: FakeEmbeddingProvider(),
    )

    payload = make_ephemeral_search_tool_handler(config)(
        "update user", ["src/users.py"], 3, {}
    )

    assert payload["candidates"][0]["path"] == "src/users.py"
    assert payload["candidates"][0]["breadcrumb"].startswith("[file: src/users.py]")
    assert payload["metrics"]["temporary_vectors"] > 0
    assert payload["metrics"]["ephemeral_build_ms"] >= 0.0
    assert payload["metrics"]["ephemeral_query_ms"] >= 0.0


def test_direct_search_eval_result_classifies_query_bucket() -> None:
    result = direct_search_eval_result(
        EvalCase(
            id="case", query="where is command dispatched", expected=["src/commands.py"]
        ),
        ["src/commands.py#handler"],
        10,
    )

    assert result.bucket != "unknown"


def test_direct_search_eval_result_matches_glob_expected_file_patterns() -> None:
    result = direct_search_eval_result(
        EvalCase(
            id="case",
            query="where is plugin descriptor",
            expected=["glob:**/resources/META-INF/plugin.xml"],
        ),
        ["plugins/htmltools/resources/META-INF/plugin.xml"],
        10,
    )

    assert result.hit is True
    assert result.file_hit is True


def test_direct_search_eval_result_matches_symbol_id_prefixes() -> None:
    result = direct_search_eval_result(
        EvalCase(id="case", query="where is user editing", expected=["src/users.py"]),
        ["src/users.py::UserController#update_user"],
        10,
    )

    assert result.hit is True
    assert result.file_hit is True


def test_direct_search_metrics_report_file_hit_at_k_after_file_deduplication() -> None:
    result = direct_search_eval_result(
        EvalCase(id="case", query="find target", expected=["src/target.py"]),
        ["src/wrong.py#1", "src/wrong.py#2", "src/wrong.py#3", "src/target.py#1"],
        4,
    )

    metrics = direct_search_metrics([result], [1.0], 4)

    assert metrics["hit_rate@3"] == 0.0
    assert metrics["file_hit_rate@3"] == 1.0
    assert metrics["hit_rate@5"] == 1.0
    assert metrics["file_hit_rate@5"] == 1.0


def test_openai_compatible_provider_does_not_inherit_store_dimensions() -> None:
    config = AppConfig(
        embedding=EmbeddingConfig(
            provider="openai_compatible",
            model="local-embed",
            dimensions=None,
            api_key="local",
            url="http://127.0.0.1:8001/v1/embeddings",
        )
    )

    provider = make_embedding_provider(config, {"dimensions": 1024})

    assert provider.dimensions == 0
    assert provider.send_dimensions is False


def test_embedding_provider_rejects_stale_artifact_provider() -> None:
    config = AppConfig(
        embedding=EmbeddingConfig(
            provider="openai_compatible", model="qwen", dimensions=None
        )
    )

    with pytest.raises(ValueError, match="provider mismatch"):
        make_embedding_provider(
            config,
            {"provider": "sentence_transformers", "model": "qwen", "dimensions": 1024},
        )


def test_embedding_provider_rejects_stale_artifact_model() -> None:
    config = AppConfig(
        embedding=EmbeddingConfig(provider="hash", model="expected", dimensions=512)
    )

    with pytest.raises(ValueError, match="model mismatch"):
        make_embedding_provider(
            config, {"provider": "hash", "model": "actual", "dimensions": 512}
        )


def test_embedding_provider_rejects_stale_artifact_dimensions() -> None:
    config = AppConfig(
        embedding=EmbeddingConfig(
            provider="hash", model="hash-token-v1", dimensions=512
        )
    )

    with pytest.raises(ValueError, match="dimensions mismatch"):
        make_embedding_provider(
            config, {"provider": "hash", "model": "hash-token-v1", "dimensions": 768}
        )


def test_cmd_monitor_requires_explicit_trace_when_tracing_is_disabled(capsys) -> None:
    config = AppConfig(
        trace=TraceConfig(
            enabled=False, artifact=Path("old-trace.jsonl"), include_prompts=False
        )
    )

    exit_code = cmd_monitor(Namespace(trace=None, refresh=0.1, max_events=10), config)

    assert exit_code == 1
    assert "Tracing is disabled" in capsys.readouterr().out


def test_cmd_provider_test_outputs_json(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    class FakeProviderTestService:
        def run(self, config, options):
            assert options.generation is True
            assert options.embedding is True
            assert options.fallback_chain is True
            return [
                ProviderCheckResult(
                    name="generation.primary",
                    provider="vertex",
                    model="gemini-test",
                    status="ok",
                    latency_ms=12,
                    details='{"ok":true}',
                    total_tokens=5,
                )
            ]

    monkeypatch.setattr("code_diver.cli.ProviderTestService", FakeProviderTestService)
    config = AppConfig()

    exit_code = cmd_provider_test(
        Namespace(
            skip_generation=False, skip_embedding=False, fallback_chain=True, json=True
        ),
        config,
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["checks"][0]["name"] == "generation.primary"
    assert payload["checks"][0]["status"] == "ok"


def test_cmd_provider_batch_test_outputs_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    class FakeVertexBatchTestService:
        def run(self, config, options):
            assert options.submit is True
            assert options.gcs_uri == "gs://bucket/prefix"
            assert options.model == "gemini-test"
            return VertexBatchTestResult(
                status="ok",
                model="gemini-test",
                project=None,
                location="global",
                local_input=tmp_path / "batch.jsonl",
                request_count=1,
                gcs_input_uri="gs://bucket/prefix/batch.jsonl",
                gcs_output_uri="gs://bucket/prefix/out",
                job_name="batch-jobs/test",
                job_state="JOB_STATE_PENDING",
            )

    monkeypatch.setattr(
        "code_diver.cli.VertexBatchTestService", FakeVertexBatchTestService
    )

    exit_code = cmd_provider_batch_test(
        Namespace(
            submit=True, gcs_uri="gs://bucket/prefix", model="gemini-test", json=True
        ),
        AppConfig(),
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["status"] == "ok"
    assert payload["job_name"] == "batch-jobs/test"


def test_search_agent_binary_available_reports_missing_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("code_diver.cli.shutil.which", lambda _binary: None)

    assert (
        search_agent_binary_available(
            AppConfig(pi=PiConfig(binary="missing-code-diver-agent"))
        )
        is False
    )


def test_cmd_search_falls_back_to_deterministic_results_when_agent_binary_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rendered: list[tuple[str, list[SearchResult]]] = []
    config = AppConfig(root=tmp_path, pi=PiConfig(binary="missing-code-diver-agent"))

    class FakeSearchRenderer:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def render(self, query: str, results: list[SearchResult]) -> None:
            rendered.append((query, results))

    monkeypatch.setattr("code_diver.cli.shutil.which", lambda _binary: None)
    monkeypatch.setattr(
        "code_diver.cli.code_explorer_preflight", lambda _config, _config_path: True
    )
    monkeypatch.setattr("code_diver.cli.SearchRenderer", FakeSearchRenderer)
    monkeypatch.setattr(
        "code_diver.cli.run_search",
        lambda _config, _query, _limit: [
            SearchResult(
                item=CodeItem(
                    id="src/auth.py#1",
                    path="src/auth.py",
                    title="auth",
                    content="def auth(): pass",
                ),
                score=0.8,
            )
        ],
    )

    exit_code = cmd_search(
        Namespace(
            query=["where", "auth"], interactive=False, json=False, limit=1, config=None
        ),
        config,
    )

    assert exit_code == 0
    assert rendered[0][0] == "where auth"
    assert rendered[0][1][0].item.path == "src/auth.py"


def test_chat_prompt_and_session_supports_resume_sugar(tmp_path: Path) -> None:
    prompt, session = chat_prompt_and_session(
        Namespace(
            prompt=["resume", "abc123", "continue", "the", "search"],
            resume=False,
            continue_session=False,
            session=None,
            session_id=None,
            session_dir=None,
            name=None,
        ),
        AppConfig(root=tmp_path, pi=PiConfig(session_dir=Path(".code-diver/chats"))),
    )

    assert prompt == "continue the search"
    assert session.resume is True
    assert session.session == "abc123"
    assert session.session_dir == Path(".code-diver/chats")


def test_chat_prompt_and_session_starts_fresh_chat_without_user_message(
    tmp_path: Path,
) -> None:
    prompt, session = chat_prompt_and_session(
        Namespace(
            prompt=[],
            resume=False,
            continue_session=False,
            session=None,
            session_id=None,
            session_dir=None,
            name=None,
        ),
        AppConfig(root=tmp_path),
    )

    assert prompt is None
    assert session.resume is False
    assert session.continue_session is False


def test_chat_prompt_and_session_supports_continue_flag(tmp_path: Path) -> None:
    prompt, session = chat_prompt_and_session(
        Namespace(
            prompt=["what", "next"],
            resume=False,
            continue_session=True,
            session=None,
            session_id="stable-id",
            session_dir=tmp_path / "sessions",
            name="Investigation",
        ),
        AppConfig(root=tmp_path),
    )

    assert prompt == "what next"
    assert session.continue_session is True
    assert session.session_id == "stable-id"
    assert session.session_dir == tmp_path / "sessions"
    assert session.name == "Investigation"
