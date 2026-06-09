from __future__ import annotations

import json
import subprocess

import pytest

from code_diver.config import AppConfig
from code_diver.config.generation_config import GenerationConfig
from code_diver.generation.gemini_cli_generation_provider import GeminiCliGenerationProvider
from code_diver.generation.generation_provider_factory import create_generation_provider


pytestmark = pytest.mark.unit


def test_gemini_cli_generation_provider_parses_noisy_json_output(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(command, **kwargs):
        calls.append({"command": command, "input": kwargs["input"]})
        payload = {
            "session_id": "session-1",
            "response": '{"ok":true}',
            "stats": {
                "models": {
                    "gemini-test": {
                        "tokens": {
                            "input": 11,
                            "candidates": 3,
                            "total": 14,
                        }
                    }
                }
            },
        }
        return subprocess.CompletedProcess(command, 0, stdout=f"warning before json\n{json.dumps(payload)}\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    provider = GeminiCliGenerationProvider(model="gemini-test", binary="gemini", timeout_seconds=7)

    result = provider.generate_json_result("Return JSON.")

    assert result.text == '{"ok":true}'
    assert result.model == "gemini-test"
    assert result.input_tokens == 11
    assert result.output_tokens == 3
    assert result.total_tokens == 14
    assert calls[0]["input"] == "Return JSON."
    assert calls[0]["command"] == [
        "gemini",
        "--model",
        "gemini-test",
        "--prompt",
        "",
        "--output-format",
        "json",
        "--approval-mode",
        "plan",
        "--skip-trust",
    ]


def test_gemini_cli_generation_provider_reports_cli_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 2, stdout="", stderr="not authenticated")

    monkeypatch.setattr(subprocess, "run", fake_run)
    provider = GeminiCliGenerationProvider(model="gemini-test")

    with pytest.raises(RuntimeError, match="not authenticated"):
        provider.generate_json("Return JSON.")


def test_generation_factory_creates_gemini_cli_provider() -> None:
    config = AppConfig(
        generation=GenerationConfig(
            provider="gemini_cli",
            model="gemini-test",
            timeout_ms=123000,
            extra_body={
                "binary": "custom-gemini",
                "approval_mode": "plan",
                "skip_trust": True,
                "extra_args": ["--screen-reader"],
            },
        )
    )

    provider = create_generation_provider(config)

    assert isinstance(provider, GeminiCliGenerationProvider)
    assert provider.binary == "custom-gemini"
    assert provider.timeout_seconds == 123
    assert provider.extra_args == ["--screen-reader"]
