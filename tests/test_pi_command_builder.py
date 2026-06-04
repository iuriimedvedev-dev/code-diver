from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.config.app_config import AppConfig
from code_diver.config.experiment_hypothesis_config import ExperimentHypothesisConfig
from code_diver.config.experiments_config import ExperimentsConfig
from code_diver.config.pi_config import PiConfig
from code_diver.config.qdrant_config import QdrantConfig
from code_diver.config.storage_config import StorageConfig
from code_diver.pi import PiCommandBuilder, PiSessionOptions


pytestmark = pytest.mark.unit


def test_pi_command_builder_uses_configured_extension_prompt_and_tools() -> None:
    config = AppConfig(
        root=Path("/repo"),
        pi=PiConfig(
            binary="npx",
            launcher_args=["-y", "@earendil-works/pi-coding-agent"],
            extension=Path(".pi/extensions/code-diver-rag.ts"),
            prompt_template=Path(".pi/prompts/code-diver-rag.md"),
            provider="google",
            model="google/gemini-3.5-flash",
            tools=["read", "code_diver_search"],
            extra_args=["--no-session"],
        ),
    )

    command = PiCommandBuilder().build(config, prompt="Explain retrieval", print_mode=True)

    assert command == [
        "npx",
        "-y",
        "@earendil-works/pi-coding-agent",
        "-p",
        "--extension",
        ".pi/extensions/code-diver-rag.ts",
        "--prompt-template",
        ".pi/prompts/code-diver-rag.md",
        "--provider",
        "google",
        "--model",
        "google/gemini-3.5-flash",
        "--tools",
        "read,code_diver_search",
        "--no-session",
        "Explain retrieval",
    ]


def test_pi_command_builder_uses_hypothesis_tools() -> None:
    config = AppConfig(
        root=Path("/repo"),
        experiments=ExperimentsConfig(
            hypotheses=[
                ExperimentHypothesisConfig(
                    name="grep_only",
                    tools=["code_diver_tree", "code_diver_rg", "code_diver_read"],
                )
            ]
        ),
        pi=PiConfig(
            tools=["code_diver_search"],
            toolsets={"vector": ["code_diver_search", "code_diver_read"]},
        ),
    )

    command = PiCommandBuilder().build(config, prompt="Find auth", print_mode=True, hypothesis="grep_only")
    env = PiCommandBuilder().env(config, Path("code-diver.yml"), hypothesis="grep_only")

    assert "--tools" in command
    assert command[command.index("--tools") + 1] == "code_diver_tree,code_diver_rg,code_diver_read"
    assert env["CODE_DIVER_HYPOTHESIS"] == "grep_only"


def test_pi_command_builder_uses_configured_toolset() -> None:
    config = AppConfig(
        root=Path("/repo"),
        pi=PiConfig(
            tools=["code_diver_search"],
            toolsets={"indexing": ["code_diver_tree", "code_diver_index_selected"]},
        ),
    )

    command = PiCommandBuilder().build(config, prompt="Index", print_mode=True, toolset="indexing")
    env = PiCommandBuilder().env(config, Path("code-diver.yml"), toolset="indexing")

    assert command[command.index("--tools") + 1] == "code_diver_tree,code_diver_index_selected"
    assert env["CODE_DIVER_TOOLSET"] == "indexing"


def test_pi_command_builder_exports_qdrant_collection() -> None:
    config = AppConfig(
        root=Path("/repo"),
        storage=StorageConfig(provider="qdrant", qdrant=QdrantConfig(collection="hypothesis_collection")),
    )

    env = PiCommandBuilder().env(config, Path("code-diver.yml"))

    assert env["CODE_DIVER_QDRANT_COLLECTION"] == "hypothesis_collection"


def test_pi_command_builder_adds_project_scoped_session_options() -> None:
    config = AppConfig(
        root=Path("/repo"),
        pi=PiConfig(
            binary="pi",
            session_dir=Path(".code-diver/chats"),
            tools=["code_diver_search"],
        ),
    )

    command = PiCommandBuilder().build(
        config,
        prompt="Find auth",
        session=PiSessionOptions(resume=True, session="abc123", name="Auth search"),
    )

    assert command[command.index("--session-dir") + 1] == "/repo/.code-diver/chats"
    assert "--resume" in command
    assert command[command.index("--session") + 1] == "abc123"
    assert command[command.index("--name") + 1] == "Auth search"
