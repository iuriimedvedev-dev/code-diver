from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.config.app_config import AppConfig
from code_diver.config.embedding_config import EmbeddingConfig
from code_diver.config.experiment_hypothesis_config import ExperimentHypothesisConfig
from code_diver.config.experiments_config import ExperimentsConfig
from code_diver.config.generation_config import GenerationConfig
from code_diver.config.pi_config import PiConfig
from code_diver.config.pi_repo_context_config import PiRepoContextConfig
from code_diver.config.qdrant_config import QdrantConfig
from code_diver.config.storage_config import StorageConfig
from code_diver.pi import PiCommandBuilder, PiSessionOptions

pytestmark = pytest.mark.unit


def test_pi_command_builder_uses_configured_extension_prompt_and_tools() -> None:
    config = AppConfig(
        root=Path("/repo"),
        pi=PiConfig(
            binary="npm",
            launcher_args=["exec", "--", "pi"],
            extension=Path(".pi/extensions/code-diver-rag.ts"),
            prompt_template=Path(".pi/prompts/code-diver-rag.md"),
            provider="google",
            model="google/gemini-3.5-flash",
            tools=["read", "code_diver_search"],
            extra_args=["--no-session"],
            repo_context=PiRepoContextConfig(enabled=False),
        ),
    )

    command = PiCommandBuilder().build(config, prompt="Explain retrieval", print_mode=True)

    assert command == [
        "npm",
        "exec",
        "--",
        "pi",
        "-p",
        "--extension",
        ".pi/extensions/code-diver-rag.ts",
        "--prompt-template",
        ".pi/prompts/code-diver-rag.md",
        "--append-system-prompt",
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


def test_pi_command_builder_appends_repository_context_prompt() -> None:
    config = AppConfig(
        root=Path("/repo"),
        pi=PiConfig(
            prompt_template=Path(".pi/prompts/code-diver-rag.md"),
            repo_context=PiRepoContextConfig(
                enabled=True,
                output=Path(".code-diver/context/repository-context.md"),
            ),
        ),
    )

    command = PiCommandBuilder().build(config)

    append_values = [
        command[index + 1]
        for index, value in enumerate(command)
        if value == "--append-system-prompt"
    ]
    assert append_values == [
        ".pi/prompts/code-diver-rag.md",
        "/repo/.code-diver/context/repository-context.md",
    ]


def test_pi_command_builder_exports_qdrant_collection() -> None:
    config = AppConfig(
        root=Path("/repo"),
        storage=StorageConfig(provider="qdrant", qdrant=QdrantConfig(collection="hypothesis_collection")),
    )

    env = PiCommandBuilder().env(config, Path("code-diver.yml"))

    assert env["CODE_DIVER_QDRANT_COLLECTION"] == "hypothesis_collection"
    assert env["PI_SKIP_VERSION_CHECK"] == "1"


def test_pi_command_builder_adds_vertex_adc_environment(monkeypatch) -> None:
    config = AppConfig(
        root=Path("/repo"),
        pi=PiConfig(provider="google-vertex", env={}),
        generation=GenerationConfig(provider="vertex", project="project-from-generation", location="europe-west1"),
    )
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)
    monkeypatch.setattr(PiCommandBuilder, "_adc_quota_project", lambda self: "project-from-adc")
    monkeypatch.setattr(PiCommandBuilder, "_gcloud_project", lambda self: "project-from-gcloud")

    env = PiCommandBuilder().env(config, Path("code-diver.yml"))

    assert env["GOOGLE_CLOUD_PROJECT"] == "project-from-generation"
    assert env["GOOGLE_CLOUD_LOCATION"] == "europe-west1"


def test_pi_command_builder_uses_embedding_vertex_project_when_generation_is_local(monkeypatch) -> None:
    config = AppConfig(
        root=Path("/repo"),
        pi=PiConfig(provider="google-vertex", env={}),
        generation=GenerationConfig(provider="openai_compatible"),
        embedding=EmbeddingConfig(provider="vertex", project="project-from-embedding", location="global"),
    )
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)
    monkeypatch.setattr(PiCommandBuilder, "_adc_quota_project", lambda self: "project-from-adc")
    monkeypatch.setattr(PiCommandBuilder, "_gcloud_project", lambda self: "project-from-gcloud")

    env = PiCommandBuilder().env(config, Path("code-diver.yml"))

    assert env["GOOGLE_CLOUD_PROJECT"] == "project-from-embedding"
    assert env["GOOGLE_CLOUD_LOCATION"] == "global"


def test_pi_command_builder_uses_adc_project_before_gcloud(monkeypatch) -> None:
    config = AppConfig(
        root=Path("/repo"),
        pi=PiConfig(provider="google-vertex", env={}),
    )
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)
    monkeypatch.setattr(PiCommandBuilder, "_adc_quota_project", lambda self: "project-from-adc")
    monkeypatch.setattr(PiCommandBuilder, "_gcloud_project", lambda self: "project-from-gcloud")

    env = PiCommandBuilder().env(config, Path("code-diver.yml"))

    assert env["GOOGLE_CLOUD_PROJECT"] == "project-from-adc"
    assert env["GOOGLE_CLOUD_LOCATION"] == "global"


def test_pi_command_builder_keeps_explicit_vertex_environment(monkeypatch) -> None:
    config = AppConfig(
        root=Path("/repo"),
        pi=PiConfig(
            provider="google-vertex",
            env={"GOOGLE_CLOUD_PROJECT": "project-from-config", "GOOGLE_CLOUD_LOCATION": "europe-west4"},
        ),
    )
    monkeypatch.setattr(PiCommandBuilder, "_gcloud_project", lambda self: "project-from-gcloud")

    env = PiCommandBuilder().env(config, Path("code-diver.yml"))

    assert env["GOOGLE_CLOUD_PROJECT"] == "project-from-config"
    assert env["GOOGLE_CLOUD_LOCATION"] == "europe-west4"


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
