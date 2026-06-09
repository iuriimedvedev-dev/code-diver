from __future__ import annotations

import subprocess

import pytest

from code_diver.config import AppConfig
from code_diver.config.generation_config import GenerationConfig
from code_diver.generation.agy_cli_generation_provider import AgyCliGenerationProvider
from code_diver.generation.generation_provider_factory import create_generation_provider


pytestmark = pytest.mark.unit


def test_agy_cli_generation_provider_runs_sandboxed_print(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        assert kwargs["text"] is True
        assert kwargs["capture_output"] is True
        assert kwargs["timeout"] == 7
        return subprocess.CompletedProcess(
            command, 0, stdout='{"ok":true}\n', stderr=""
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    provider = AgyCliGenerationProvider(
        model="Gemini 3.5 Flash (Low)",
        binary="agy",
        timeout_seconds=7,
        print_timeout="30s",
        sandbox=True,
    )

    result = provider.generate_json_result("Return JSON.")

    assert result.text == '{"ok":true}'
    assert result.model == "Gemini 3.5 Flash (Low)"
    assert result.total_tokens == 0
    assert calls[0] == [
        "agy",
        "--print",
        "Return JSON.",
        "--model",
        "Gemini 3.5 Flash (Low)",
        "--print-timeout",
        "30s",
        "--sandbox",
    ]


def test_agy_cli_generation_provider_reports_cli_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            command, 2, stdout="", stderr="not authenticated"
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    provider = AgyCliGenerationProvider(model="Gemini 3.5 Flash (Low)")

    with pytest.raises(RuntimeError, match="not authenticated"):
        provider.generate_json("Return JSON.")


def test_generation_factory_creates_agy_cli_provider() -> None:
    config = AppConfig(
        generation=GenerationConfig(
            provider="agy_cli",
            model="Gemini 3.5 Flash (Low)",
            timeout_ms=123000,
            extra_body={
                "binary": "custom-agy",
                "print_timeout": "45s",
                "sandbox": True,
                "extra_args": ["--log-file", "/tmp/agy.log"],
            },
        )
    )

    provider = create_generation_provider(config)

    assert isinstance(provider, AgyCliGenerationProvider)
    assert provider.binary == "custom-agy"
    assert provider.timeout_seconds == 123
    assert provider.print_timeout == "45s"
    assert provider.sandbox is True
    assert provider.extra_args == ["--log-file", "/tmp/agy.log"]
