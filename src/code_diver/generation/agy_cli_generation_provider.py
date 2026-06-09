from __future__ import annotations

import subprocess

from ..settings import Defaults
from .generation_result import GenerationResult
from .transient_generation_retry import TransientGenerationRetry


class AgyCliGenerationProvider:
    def __init__(
        self,
        model: str = Defaults.AGY_CLI_MODEL,
        binary: str = Defaults.AGY_CLI_BINARY,
        timeout_seconds: float = Defaults.GENERATION_TIMEOUT_MS / 1000,
        print_timeout: str = Defaults.AGY_CLI_PRINT_TIMEOUT,
        sandbox: bool = True,
        extra_args: list[str] | None = None,
        retry_attempts: int = Defaults.GENERATION_RETRY_ATTEMPTS,
        retry_base_delay_seconds: float = Defaults.GENERATION_RETRY_BASE_DELAY_SECONDS,
        retry_max_delay_seconds: float = Defaults.GENERATION_RETRY_MAX_DELAY_SECONDS,
    ):
        self.name = Defaults.AGY_CLI_PROVIDER
        self.model = model
        self.binary = binary
        self.timeout_seconds = timeout_seconds
        self.print_timeout = print_timeout
        self.sandbox = sandbox
        self.extra_args = extra_args or []
        self.retry = TransientGenerationRetry(
            attempts=retry_attempts,
            base_delay_seconds=retry_base_delay_seconds,
            max_delay_seconds=retry_max_delay_seconds,
        )

    def generate_json(self, prompt: str) -> str:
        return self.generate_json_result(prompt).text

    def generate_json_result(self, prompt: str) -> GenerationResult:
        text = self.retry.run(lambda: self._run(prompt)).strip()
        if not text:
            raise RuntimeError("Antigravity CLI returned an empty response.")
        return GenerationResult(text=text, model=self.model)

    def _run(self, prompt: str) -> str:
        command = [
            self.binary,
            "--print",
            prompt,
            "--model",
            self.model,
            "--print-timeout",
            self.print_timeout,
        ]
        if self.sandbox:
            command.append("--sandbox")
        command.extend(self.extra_args)
        try:
            completed = subprocess.run(
                command,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"Antigravity CLI binary was not found: {self.binary}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Antigravity CLI timed out after {self.timeout_seconds:.1f}s"
            ) from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise RuntimeError(
                f"Antigravity CLI failed with exit code {completed.returncode}: {detail[:1000]}"
            )
        return completed.stdout
