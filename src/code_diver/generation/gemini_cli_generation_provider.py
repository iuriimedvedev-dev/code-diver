from __future__ import annotations

import json
import subprocess
from typing import Any

from ..settings import Defaults
from .generation_result import GenerationResult
from .transient_generation_retry import TransientGenerationRetry


class GeminiCliGenerationProvider:
    def __init__(
        self,
        model: str,
        binary: str = Defaults.GEMINI_CLI_BINARY,
        timeout_seconds: float = Defaults.GENERATION_TIMEOUT_MS / 1000,
        approval_mode: str = Defaults.GEMINI_CLI_APPROVAL_MODE,
        skip_trust: bool = True,
        output_format: str = "json",
        extra_args: list[str] | None = None,
        retry_attempts: int = Defaults.GENERATION_RETRY_ATTEMPTS,
        retry_base_delay_seconds: float = Defaults.GENERATION_RETRY_BASE_DELAY_SECONDS,
        retry_max_delay_seconds: float = Defaults.GENERATION_RETRY_MAX_DELAY_SECONDS,
    ):
        self.name = Defaults.GEMINI_CLI_PROVIDER
        self.model = model
        self.binary = binary
        self.timeout_seconds = timeout_seconds
        self.approval_mode = approval_mode
        self.skip_trust = skip_trust
        self.output_format = output_format
        self.extra_args = extra_args or []
        self.retry = TransientGenerationRetry(
            attempts=retry_attempts,
            base_delay_seconds=retry_base_delay_seconds,
            max_delay_seconds=retry_max_delay_seconds,
        )

    def generate_json(self, prompt: str) -> str:
        return self.generate_json_result(prompt).text

    def generate_json_result(self, prompt: str) -> GenerationResult:
        payload = self.retry.run(lambda: self._run(prompt))
        response = payload.get("response")
        if not isinstance(response, str) or not response.strip():
            raise RuntimeError("Gemini CLI returned an empty response.")
        stats = payload.get("stats") if isinstance(payload.get("stats"), dict) else {}
        model = self._reported_model(stats) or self.model
        tokens = self._tokens(stats, model)
        return GenerationResult(
            text=response,
            model=model,
            input_tokens=tokens["input"],
            output_tokens=tokens["output"],
            total_tokens=tokens["total"],
        )

    def _run(self, prompt: str) -> dict[str, Any]:
        command = [
            self.binary,
            "--model",
            self.model,
            "--prompt",
            "",
            "--output-format",
            self.output_format,
            "--approval-mode",
            self.approval_mode,
        ]
        if self.skip_trust:
            command.append("--skip-trust")
        command.extend(self.extra_args)
        try:
            completed = subprocess.run(
                command,
                input=prompt,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"Gemini CLI binary was not found: {self.binary}") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Gemini CLI timed out after {self.timeout_seconds:.1f}s") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise RuntimeError(f"Gemini CLI failed with exit code {completed.returncode}: {detail[:1000]}")
        return self._parse_json_output(completed.stdout)

    def _parse_json_output(self, output: str) -> dict[str, Any]:
        decoder = json.JSONDecoder()
        parsed: dict[str, Any] | None = None
        index = 0
        while index < len(output):
            brace = output.find("{", index)
            if brace < 0:
                break
            try:
                value, end = decoder.raw_decode(output[brace:])
            except json.JSONDecodeError:
                index = brace + 1
                continue
            if isinstance(value, dict):
                parsed = value
            index = brace + end
        if parsed is None:
            raise RuntimeError(f"Gemini CLI did not return JSON output: {output[:1000]}")
        return parsed

    def _reported_model(self, stats: dict[str, Any]) -> str | None:
        models = stats.get("models")
        if not isinstance(models, dict) or not models:
            return None
        if self.model in models:
            return self.model
        return str(next(iter(models.keys())))

    def _tokens(self, stats: dict[str, Any], model: str) -> dict[str, int]:
        models = stats.get("models")
        model_stats = models.get(model) if isinstance(models, dict) else None
        token_stats = model_stats.get("tokens") if isinstance(model_stats, dict) else None
        if not isinstance(token_stats, dict):
            return {"input": 0, "output": 0, "total": 0}
        input_tokens = int(token_stats.get("input") or token_stats.get("prompt") or 0)
        output_tokens = int(token_stats.get("candidates") or 0)
        total_tokens = int(token_stats.get("total") or input_tokens + output_tokens)
        return {"input": input_tokens, "output": output_tokens, "total": total_tokens}
