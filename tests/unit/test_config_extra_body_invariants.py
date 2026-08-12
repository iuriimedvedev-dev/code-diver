"""Static invariants over the shipped configs.

The bug this guards: `extra_body` is spliced into the chat-completions request body, so a
chat-template option placed there is accepted by every OpenAI-compatible server and
applied by none. `enable_thinking: false` sat directly under `extra_body` in 16 config
files. Every affected run left thinking mode enabled, and the two Qwen3.5 runs spent
their token budget on reasoning traces and returned empty answers ~10% of the time --
which was then read as those models being weak at the task.

`OpenAICompatibleGenerationProvider` now rejects the flat form at construction, but that
only fires when a run actually starts. This test fails on the repository instead.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from code_diver.generation.openai_compatible_generation_provider import (
    OpenAICompatibleGenerationProvider,
)

pytestmark = pytest.mark.unit

CONFIG_ROOT = Path(__file__).resolve().parents[2] / "configs"


def _extra_body_blocks(node: Any, trail: tuple[str, ...] = ()) -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "extra_body" and isinstance(value, dict):
                found.append((".".join([*trail, str(key)]), value))
            found.extend(_extra_body_blocks(value, (*trail, str(key))))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(_extra_body_blocks(value, (*trail, f"[{index}]")))
    return found


def _config_paths() -> list[Path]:
    paths = sorted(CONFIG_ROOT.rglob("*.yml"))
    if not paths:
        raise AssertionError(f"No configs found under {CONFIG_ROOT}")
    return paths


@pytest.mark.parametrize("path", _config_paths(), ids=lambda path: str(path.relative_to(CONFIG_ROOT)))
def test_config_never_places_chat_template_options_directly_in_extra_body(path: Path) -> None:
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    misplaced = [
        f"{location}.{key}"
        for location, block in _extra_body_blocks(document)
        for key in sorted(OpenAICompatibleGenerationProvider.CHAT_TEMPLATE_OPTIONS & block.keys())
    ]
    assert not misplaced, (
        f"{path.relative_to(CONFIG_ROOT)} places chat-template options in the request body, "
        f"where they are silently ignored: {misplaced}. Nest them under "
        "extra_body.chat_template_kwargs instead."
    )


@pytest.mark.parametrize("path", _config_paths(), ids=lambda path: str(path.relative_to(CONFIG_ROOT)))
def test_config_never_lets_extra_body_clobber_provider_owned_request_keys(path: Path) -> None:
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    clobbered = [
        f"{location}.{key}"
        for location, block in _extra_body_blocks(document)
        for key in sorted(OpenAICompatibleGenerationProvider.RESERVED_PAYLOAD_KEYS & block.keys())
    ]
    assert not clobbered, (
        f"{path.relative_to(CONFIG_ROOT)} overrides request keys the provider owns: {clobbered}. "
        "Use the dedicated generation settings instead."
    )
