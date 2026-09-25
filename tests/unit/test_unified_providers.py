from __future__ import annotations

import json
from pathlib import Path

import pytest

from code_diver.config import AppConfig
from code_diver.config.generation_config import GenerationConfig
from code_diver.generation.generation_provider_factory import create_generation_provider
from code_diver.providers.provider_factory import create_embedding_provider
from code_diver.runtime.hf_downloader import is_huggingface_repo_id
from code_diver.settings import (
    Defaults,
    EmbeddingProviderId,
    GenerationProviderId,
    ProviderResolver,
    read_jbcentral_config,
)


def test_is_huggingface_repo_id() -> None:
    assert is_huggingface_repo_id("mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ") is True
    assert is_huggingface_repo_id("google/embeddinggemma-300m") is True
    assert is_huggingface_repo_id("gemini-embedding-2") is False
    assert is_huggingface_repo_id("http://localhost:8000/model") is False
    assert is_huggingface_repo_id("") is False


def test_read_jbcentral_config_custom_file(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(
        json.dumps({"proxy_port": 19517, "proxy_secret": "test_secret_123"}),
        encoding="utf-8",
    )
    loaded = read_jbcentral_config(cfg_file)
    assert loaded is not None
    assert loaded.port == 19517
    assert loaded.secret == "test_secret_123"


def test_provider_resolver_jbcentral(monkeypatch, tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(
        json.dumps({"proxy_port": 19517, "proxy_secret": "abc_secret"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(Defaults, "JBCENTRAL_CONFIG_PATH", cfg_file)

    gen_res = ProviderResolver.resolve_generation("jbcentral", model="gpt-4o")
    assert gen_res.url == "http://127.0.0.1:19517/wire/abc_secret/codex/openai/v1/responses"
    assert gen_res.api_key == "abc_secret"
    assert gen_res.headers["Authorization"] == "Bearer abc_secret"

    # Agent overrides: antigravity / gemini
    gen_res_gemini = ProviderResolver.resolve_generation(
        "jbcentral", model="gemini-3.5-flash-lite", jbcentral_agent="gemini"
    )
    assert gen_res_gemini.url == "http://127.0.0.1:19517/wire/abc_secret/gemini/openai/v1/chat/completions"
    assert gen_res_gemini.model == "gemini-3.5-flash-lite"

    # Env agent override
    monkeypatch.setenv("JBCENTRAL_AGENT", "antigravity")
    gen_res_env = ProviderResolver.resolve_generation("jbcentral", model="gemini-3.5-flash-lite")
    assert gen_res_env.url == "http://127.0.0.1:19517/wire/abc_secret/antigravity/openai/v1/chat/completions"
    monkeypatch.delenv("JBCENTRAL_AGENT", raising=False)

    emb_res = ProviderResolver.resolve_embedding("jbcentral")
    assert emb_res.url == "http://127.0.0.1:19517/wire/abc_secret/codex/openai/v1/embeddings"
    assert emb_res.api_key == "abc_secret"


def test_provider_resolver_litellm(monkeypatch) -> None:
    monkeypatch.setenv("LITE_LLM_KEY", "custom_litellm_key")
    gen_res = ProviderResolver.resolve_generation("litellm")
    assert gen_res.url == "https://litellm.labs.jb.gg/v1/chat/completions"
    assert gen_res.api_key == "custom_litellm_key"
    assert gen_res.headers["Authorization"] == "Bearer custom_litellm_key"

    emb_res = ProviderResolver.resolve_embedding("litellm")
    assert emb_res.url == "https://litellm.labs.jb.gg/v1/embeddings"
    assert emb_res.api_key == "custom_litellm_key"


def test_provider_resolver_local() -> None:
    gen_res = ProviderResolver.resolve_generation("local")
    assert gen_res.url == "http://127.0.0.1:8012/v1/chat/completions"
    assert gen_res.api_key == "local"

    emb_res = ProviderResolver.resolve_embedding("local")
    assert emb_res.url == "http://127.0.0.1:8012/v1/embeddings"
    assert emb_res.api_key == "local"


def test_provider_resolver_openai(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test_openai_key")
    gen_res = ProviderResolver.resolve_generation("openai")
    assert gen_res.url == Defaults.OPENAI_RESPONSES_URL
    assert gen_res.api_key == "test_openai_key"

    emb_res = ProviderResolver.resolve_embedding("openai")
    assert emb_res.url == Defaults.OPENAI_EMBEDDINGS_URL
    assert emb_res.api_key == "test_openai_key"


def test_create_generation_provider_unified(monkeypatch, tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(
        json.dumps({"proxy_port": 19517, "proxy_secret": "jb_secret"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(Defaults, "JBCENTRAL_CONFIG_PATH", cfg_file)

    config = AppConfig(
        generation=GenerationConfig(
            provider="jbcentral",
            model="gpt-5",
        )
    )
    provider = create_generation_provider(config)
    assert provider is not None


def test_create_embedding_provider_unified(monkeypatch, tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(
        json.dumps({"proxy_port": 19517, "proxy_secret": "jb_secret"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(Defaults, "JBCENTRAL_CONFIG_PATH", cfg_file)

    emb = create_embedding_provider(
        provider=EmbeddingProviderId.JBCENTRAL.value,
        model="text-embedding-3-small",
    )
    assert emb is not None
    assert emb.url == "http://127.0.0.1:19517/wire/jb_secret/codex/openai/v1/embeddings"
    assert emb.api_key == "jb_secret"
