from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.config.app_config import AppConfig
from code_diver.config.pi_config import PiConfig
from code_diver.pi import PiCommandBuilder


pytestmark = pytest.mark.unit


def test_pi_command_builder_uses_configured_extension_prompt_and_tools() -> None:
    config = AppConfig(
        root=Path("/repo"),
        pi=PiConfig(
            binary="pi-dev",
            extension=Path(".pi/extensions/code-diver-rag.ts"),
            prompt_template=Path(".pi/prompts/code-diver-rag.md"),
            provider="google",
            model="gemini-3-flash-preview",
            tools=["read", "code_diver_search"],
            extra_args=["--no-session"],
        ),
    )

    command = PiCommandBuilder().build(config, prompt="Explain retrieval", print_mode=True)

    assert command == [
        "pi-dev",
        "-p",
        "--extension",
        ".pi/extensions/code-diver-rag.ts",
        "--prompt-template",
        ".pi/prompts/code-diver-rag.md",
        "--provider",
        "google",
        "--model",
        "gemini-3-flash-preview",
        "--tools",
        "read,code_diver_search",
        "--no-session",
        "Explain retrieval",
    ]
