from __future__ import annotations

import logging
from types import ModuleType, SimpleNamespace

import pytest

from code_diver.config import AppConfig
from code_diver.config.generation_config import GenerationConfig
from code_diver.generation.antigravity_sdk_generation_provider import (
    AntigravitySdkGenerationProvider,
)
from code_diver.generation.generation_provider_factory import create_generation_provider


pytestmark = pytest.mark.unit


def test_antigravity_sdk_generation_provider_runs_read_only_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeBuiltinTools:
        LIST_DIR = "list_directory"
        SEARCH_DIR = "search_directory"
        FIND_FILE = "find_file"
        VIEW_FILE = "view_file"
        FINISH = "finish"

    class FakeCapabilitiesConfig:
        def __init__(self, **kwargs):
            captured["capabilities"] = kwargs

    class FakeLocalAgentConfig:
        def __init__(self, **kwargs):
            captured["config"] = kwargs

    class FakeResponse:
        usage_metadata = SimpleNamespace(
            prompt_token_count=11,
            candidates_token_count=3,
            total_token_count=14,
        )

        async def text(self) -> str:
            return '{"ok": true}'

    class FakeAgent:
        def __init__(self, config):
            captured["agent_config"] = config

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return None

        async def chat(self, prompt):
            captured["prompt"] = prompt
            return FakeResponse()

    fake_policy = SimpleNamespace(
        deny=lambda tool: ("deny", tool),
        allow=lambda tool: ("allow", tool),
    )
    google_module = ModuleType("google")
    antigravity_module = ModuleType("google.antigravity")
    antigravity_module.Agent = FakeAgent
    antigravity_module.CapabilitiesConfig = FakeCapabilitiesConfig
    antigravity_module.LocalAgentConfig = FakeLocalAgentConfig
    hooks_module = ModuleType("google.antigravity.hooks")
    hooks_module.policy = fake_policy
    types_module = ModuleType("google.antigravity.types")
    types_module.BuiltinTools = FakeBuiltinTools
    monkeypatch.setitem(__import__("sys").modules, "google", google_module)
    monkeypatch.setitem(
        __import__("sys").modules, "google.antigravity", antigravity_module
    )
    monkeypatch.setitem(
        __import__("sys").modules, "google.antigravity.hooks", hooks_module
    )
    monkeypatch.setitem(
        __import__("sys").modules, "google.antigravity.types", types_module
    )

    provider = AntigravitySdkGenerationProvider(
        model="gemini-3.5-flash",
        timeout_seconds=7,
        app_data_dir="~/.gemini/antigravity-cli",
        workspace=".",
    )

    result = provider.generate_json_result("Return JSON.")

    config = captured["config"]
    assert result.text == '{"ok": true}'
    assert result.input_tokens == 11
    assert result.output_tokens == 3
    assert result.total_tokens == 14
    assert captured["prompt"] == "Return JSON."
    assert config["model"] == "gemini-3.5-flash"
    assert config["capabilities"] is not None
    assert ("deny", "edit_file") in config["policies"]
    assert ("deny", "run_command") in config["policies"]
    assert ("allow", "*") in config["policies"]
    assert captured["capabilities"]["enable_subagents"] is False
    assert captured["capabilities"]["enabled_tools"] == [
        "list_directory",
        "search_directory",
        "find_file",
        "view_file",
        "finish",
    ]


def test_generation_factory_creates_antigravity_sdk_provider() -> None:
    config = AppConfig(
        generation=GenerationConfig(
            provider="antigravity_sdk",
            model="gemini-3.5-flash",
            timeout_ms=123000,
            extra_body={
                "vertex": False,
                "app_data_dir": "~/.gemini/antigravity-cli",
                "workspace": ".",
                "system_instructions": "Return JSON only.",
            },
        )
    )

    provider = create_generation_provider(config)

    assert isinstance(provider, AntigravitySdkGenerationProvider)
    assert provider.model == "gemini-3.5-flash"
    assert provider.timeout_seconds == 123
    assert provider.vertex is False
    assert provider.app_data_dir == "~/.gemini/antigravity-cli"
    assert provider.system_instructions == "Return JSON only."


def test_antigravity_sdk_generation_provider_reports_sdk_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_antigravity(monkeypatch, text="", warning="quota exhausted")

    provider = AntigravitySdkGenerationProvider(
        model="gemini-3.5-flash",
        retry_attempts=1,
    )

    with pytest.raises(RuntimeError, match="quota exhausted"):
        provider.generate_json_result("Return JSON.")


def _install_fake_antigravity(
    monkeypatch: pytest.MonkeyPatch,
    *,
    text: str = '{"ok": true}',
    warning: str | None = None,
) -> None:
    class FakeBuiltinTools:
        LIST_DIR = "list_directory"
        SEARCH_DIR = "search_directory"
        FIND_FILE = "find_file"
        VIEW_FILE = "view_file"
        FINISH = "finish"

    class FakeCapabilitiesConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeLocalAgentConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeResponse:
        usage_metadata = SimpleNamespace(
            prompt_token_count=11,
            candidates_token_count=3,
            total_token_count=14,
        )

        async def text(self) -> str:
            if warning:
                logging.warning(warning)
            return text

    class FakeAgent:
        def __init__(self, config):
            self.config = config

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return None

        async def chat(self, prompt):
            return FakeResponse()

    fake_policy = SimpleNamespace(
        deny=lambda tool: ("deny", tool),
        allow=lambda tool: ("allow", tool),
    )
    google_module = ModuleType("google")
    antigravity_module = ModuleType("google.antigravity")
    antigravity_module.Agent = FakeAgent
    antigravity_module.CapabilitiesConfig = FakeCapabilitiesConfig
    antigravity_module.LocalAgentConfig = FakeLocalAgentConfig
    hooks_module = ModuleType("google.antigravity.hooks")
    hooks_module.policy = fake_policy
    types_module = ModuleType("google.antigravity.types")
    types_module.BuiltinTools = FakeBuiltinTools
    monkeypatch.setitem(__import__("sys").modules, "google", google_module)
    monkeypatch.setitem(
        __import__("sys").modules, "google.antigravity", antigravity_module
    )
    monkeypatch.setitem(
        __import__("sys").modules, "google.antigravity.hooks", hooks_module
    )
    monkeypatch.setitem(
        __import__("sys").modules, "google.antigravity.types", types_module
    )
