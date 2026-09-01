from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from code_diver.config.config_loader import ConfigLoader
from code_diver.providers.openai_compatible_embedding_provider import (
    OpenAICompatibleEmbeddingProvider,
)
from code_diver.services.embedding_text_preparer import (
    EmbeddingTextPreparer,
    truncate_embedding_text,
)
from code_diver.settings import Defaults


class StubTokenizer:
    """One token per whitespace-separated word, decoded back with spaces."""

    def encode(self, text: str, add_special_tokens: bool = False) -> list[int]:
        self._words = text.split(" ")
        return list(range(len(self._words)))

    def decode(self, token_ids: list[int], skip_special_tokens: bool = True) -> str:
        return " ".join(self._words[: len(token_ids)])


def _write_config(tmp_path: Path, embedding: dict[str, object]) -> Path:
    path = tmp_path / "config.yml"
    path.write_text(yaml.safe_dump({"embedding": embedding}), encoding="utf-8")
    return path


def test_defaults_reproduce_previous_hard_coded_window():
    assert Defaults.EMBEDDING_MAX_INPUT_TOKENS == 512
    assert Defaults.EMBEDDING_TOKEN_SAFETY_MARGIN == 32


def test_config_loader_defaults_when_option_absent(tmp_path: Path):
    config = ConfigLoader().load(_write_config(tmp_path, {"provider": "hash"}))
    assert config.embedding.max_input_tokens == Defaults.EMBEDDING_MAX_INPUT_TOKENS
    assert config.embedding.token_safety_margin == Defaults.EMBEDDING_TOKEN_SAFETY_MARGIN


def test_config_loader_reads_token_window_options(tmp_path: Path):
    config = ConfigLoader().load(
        _write_config(
            tmp_path,
            {"provider": "hash", "max_input_tokens": 512, "token_safety_margin": 8},
        )
    )
    assert config.embedding.max_input_tokens == 512
    assert config.embedding.token_safety_margin == 8


def test_provider_token_budget_follows_configured_window():
    provider = OpenAICompatibleEmbeddingProvider(
        model="stub-model",
        dimensions=None,
        api_key="local",
        max_input_tokens=512,
        token_safety_margin=32,
    )
    assert provider._effective_token_budget() == 480

    tight = OpenAICompatibleEmbeddingProvider(
        model="stub-model",
        dimensions=None,
        api_key="local",
        max_input_tokens=512,
        token_safety_margin=12,
    )
    assert tight._effective_token_budget() == 500


def test_provider_token_budget_never_drops_below_one():
    provider = OpenAICompatibleEmbeddingProvider(
        model="stub-model",
        dimensions=None,
        api_key="local",
        max_input_tokens=4,
        token_safety_margin=99,
    )
    assert provider._effective_token_budget() == 1


def test_provider_truncates_to_configured_token_budget():
    provider = OpenAICompatibleEmbeddingProvider(
        model="stub-model",
        dimensions=None,
        api_key="local",
        max_input_chars=10_000,
        max_input_tokens=10,
        token_safety_margin=2,
    )
    provider.tokenizer = StubTokenizer()
    provider._tokenizer_load_attempted = True
    text = " ".join(f"w{index}" for index in range(50))
    assert provider._bounded_prefixed(None, text).split(" ") == [
        f"w{index}" for index in range(8)
    ]


def test_char_cap_still_applies_after_token_truncation():
    provider = OpenAICompatibleEmbeddingProvider(
        model="stub-model",
        dimensions=None,
        api_key="local",
        max_input_chars=5,
        max_input_tokens=512,
        token_safety_margin=32,
    )
    provider.tokenizer = StubTokenizer()
    provider._tokenizer_load_attempted = True
    assert len(provider._bounded_prefixed(None, "a b c d e f g h")) == 5


@pytest.mark.parametrize(
    ("max_input_tokens", "token_safety_margin", "expected_words"),
    [(10, 2, 8), (512, 32, 20)],
)
def test_truncate_embedding_text_honours_token_window(
    max_input_tokens: int, token_safety_margin: int, expected_words: int
):
    text = " ".join(f"w{index}" for index in range(20))
    result = truncate_embedding_text(
        text,
        10_000,
        StubTokenizer(),
        max_input_tokens=max_input_tokens,
        token_safety_margin=token_safety_margin,
    )
    assert len(result.split(" ")) == expected_words


def test_preparer_defaults_match_previous_behaviour():
    preparer = EmbeddingTextPreparer(500)
    assert preparer.max_input_tokens == Defaults.EMBEDDING_MAX_INPUT_TOKENS
    assert preparer.token_safety_margin == Defaults.EMBEDDING_TOKEN_SAFETY_MARGIN
