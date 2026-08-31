from __future__ import annotations

from types import SimpleNamespace

from code_diver.runtime.search_runtime import SearchRuntime


def test_search_runtime_warm_is_idempotent(monkeypatch) -> None:
    calls = {"create_vs": 0, "create_provider": 0, "create_strategy": 0, "search": 0}

    class DummyStore:
        def metadata(self):
            return {}

        def close(self):
            return None

    class DummyStrategy:
        def search(self, query, limit):
            calls["search"] += 1
            return []

    def fake_vs(config):
        calls["create_vs"] += 1
        return DummyStore()

    def fake_provider(config, metadata=None):
        calls["create_provider"] += 1
        return object()

    def fake_factory_create(self, strategy_id, config, provider, vector_store):
        calls["create_strategy"] += 1
        return DummyStrategy()

    monkeypatch.setattr("code_diver.runtime.search_runtime.create_vector_store", fake_vs)
    monkeypatch.setattr(
        "code_diver.providers.embedding_provider_builder.make_embedding_provider",
        fake_provider,
    )
    monkeypatch.setattr(
        "code_diver.strategies.RetrievalStrategyFactory.create",
        fake_factory_create,
    )
    monkeypatch.setattr(
        "code_diver.runtime.search_runtime.inspection_exclude_patterns",
        lambda config: [],
    )

    class DummyH3:
        def __init__(self, *args, **kwargs):
            pass

        def search(self, query, limit, args=None):
            return {"candidates": [], "metrics": {}}

    monkeypatch.setattr("code_diver.runtime.search_runtime.H3SearchToolHandler", DummyH3)

    config = SimpleNamespace(
        root=".",
        search=SimpleNamespace(strategy="graph_file", persistent_runtime=True),
        cross_encoder_rerank=SimpleNamespace(enabled=False),
        scanner=SimpleNamespace(exclude=[]),
    )
    runtime = SearchRuntime(config)
    runtime.warm()
    runtime.warm()
    assert calls["create_vs"] == 1
    assert calls["create_provider"] == 1
    assert calls["search"] == 1
    assert runtime._warmed is True
