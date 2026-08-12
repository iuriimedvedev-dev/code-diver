from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..config import AppConfig
from .pi_command_builder import PiCommandBuilder
from .pi_runtime_manager import PiRuntimeManager
from .pi_session_options import PiSessionOptions


class PiRunner:
    def __init__(self, command_builder: PiCommandBuilder | None = None):
        self.command_builder = command_builder or PiCommandBuilder()
        self.runtime_manager = PiRuntimeManager()

    def run_interactive(
        self,
        config: AppConfig,
        config_path: Path | None,
        prompt: str | None = None,
        toolset: str | None = None,
        hypothesis: str | None = None,
        session: PiSessionOptions | None = None,
    ) -> int:
        return self._run_with_fallbacks(
            config,
            config_path,
            lambda model: self.command_builder.build(
                config,
                prompt=prompt,
                print_mode=False,
                toolset=toolset,
                hypothesis=hypothesis,
                model=model,
                session=session,
            ),
            toolset,
            hypothesis,
        )

    def run_print(
        self,
        config: AppConfig,
        config_path: Path | None,
        prompt: str,
        toolset: str | None = None,
        hypothesis: str | None = None,
        session: PiSessionOptions | None = None,
    ) -> int:
        return self._run_with_fallbacks(
            config,
            config_path,
            lambda model: self.command_builder.build(
                config,
                prompt=prompt,
                print_mode=True,
                toolset=toolset,
                hypothesis=hypothesis,
                model=model,
                session=session,
            ),
            toolset,
            hypothesis,
        )

    def run_print_capture(
        self,
        config: AppConfig,
        config_path: Path | None,
        prompt: str,
        toolset: str | None = None,
        hypothesis: str | None = None,
        session: PiSessionOptions | None = None,
    ) -> tuple[int, str]:
        return self._run_with_fallbacks_capture(
            config,
            config_path,
            lambda model: self.command_builder.build(
                config,
                prompt=prompt,
                print_mode=True,
                toolset=toolset,
                hypothesis=hypothesis,
                model=model,
                session=session,
            ),
            toolset,
            hypothesis,
        )

    def run_print_logged(
        self,
        config: AppConfig,
        config_path: Path | None,
        prompt: str,
        log_path: Path,
        toolset: str | None = None,
        hypothesis: str | None = None,
        session: PiSessionOptions | None = None,
    ) -> int:
        return self._run_with_fallbacks_logged(
            config,
            config_path,
            lambda model: self._json_command(
                config,
                prompt,
                toolset,
                hypothesis,
                model,
                session,
            ),
            toolset,
            hypothesis,
            log_path,
        )

    def _env(
        self,
        config: AppConfig,
        config_path: Path | None,
        toolset: str | None = None,
        hypothesis: str | None = None,
    ) -> dict[str, str]:
        env = os.environ.copy()
        env.update(self.command_builder.env(config, config_path, toolset, hypothesis))
        env["CODE_DIVER_PACKAGE_ROOT"] = str(self.runtime_manager.package_root.resolve())
        return env

    def _run_with_fallbacks(
        self,
        config: AppConfig,
        config_path: Path | None,
        command_factory: Callable[[str | None], list[str]],
        toolset: str | None,
        hypothesis: str | None,
    ) -> int:
        env = self._env(config, config_path, toolset, hypothesis)
        last_code = 1
        for index, model in enumerate(self._models(config)):
            if index:
                print(f"Search agent model fallback: {model}", file=sys.stderr, flush=True)
            command = self._prepare_command(command_factory(model))
            self._print_launch_status(config, command, model, toolset, hypothesis)
            last_code = subprocess.call(command, env=env, **self._subprocess_kwargs(config))
            if last_code == 0:
                return 0
        return last_code

    def _run_with_fallbacks_capture(
        self,
        config: AppConfig,
        config_path: Path | None,
        command_factory: Callable[[str | None], list[str]],
        toolset: str | None,
        hypothesis: str | None,
    ) -> tuple[int, str]:
        env = self._env(config, config_path, toolset, hypothesis)
        last_code = 1
        last_output = ""
        for index, model in enumerate(self._models(config)):
            if index:
                print(f"Search agent model fallback: {model}", file=sys.stderr, flush=True)
            command = self._prepare_command(command_factory(model))
            self._print_launch_status(config, command, model, toolset, hypothesis)
            try:
                completed = subprocess.run(
                    command,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=config.pi.timeout_seconds,
                    check=False,  # returncode drives the model-fallback loop below
                    **self._subprocess_kwargs(config),
                )
            except subprocess.TimeoutExpired as exc:
                self._write_captured_stderr(self._text(exc.stderr))
                last_output = self._text(exc.stdout)
                print(
                    f"[code-diver] error: search agent timed out after {config.pi.timeout_seconds}s",
                    file=sys.stderr,
                    flush=True,
                )
                last_code = 124
                continue
            self._write_captured_stderr(completed.stderr)
            last_code = completed.returncode
            last_output = completed.stdout
            if last_code == 0:
                return 0, last_output
        return last_code, last_output

    def _print_launch_status(
        self,
        config: AppConfig,
        command: list[str],
        model: str | None,
        toolset: str | None,
        hypothesis: str | None,
    ) -> None:
        console = Console(stderr=True, color_system="auto")
        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold cyan", no_wrap=True)
        table.add_column()
        table.add_row("model", model or "default")
        table.add_row("repo", str(config.root.resolve()))
        if toolset:
            table.add_row("toolset", toolset)
        if hypothesis:
            table.add_row("hypothesis", hypothesis)
        session_dir = self._flag_value(command, "--session-dir")
        if session_dir:
            table.add_row("sessions", session_dir)
        console.print(
            Panel(table, title="[bold]Launching Search Agent[/bold]", border_style="cyan", padding=(0, 1))
        )

    def _flag_value(self, command: list[str], flag: str) -> str | None:
        try:
            index = command.index(flag)
        except ValueError:
            return None
        if index + 1 >= len(command):
            return None
        return command[index + 1]

    def _prepare_command(self, command: list[str]) -> list[str]:
        if self.runtime_manager.cwd_for_command(command) is not None:
            self.runtime_manager.ensure_available()
        return self.runtime_manager.command_for_execution(command)

    def _subprocess_kwargs(self, config: AppConfig) -> dict[str, str]:
        return {"cwd": str(config.root.resolve())}

    def _write_captured_stderr(self, text: str) -> None:
        if not text:
            return
        sys.stderr.write(text)
        if not text.endswith("\n"):
            sys.stderr.write("\n")
        sys.stderr.flush()

    def _run_with_fallbacks_logged(
        self,
        config: AppConfig,
        config_path: Path | None,
        command_factory: Callable[[str | None], list[str]],
        toolset: str | None,
        hypothesis: str | None,
        log_path: Path,
    ) -> int:
        env = self._env(config, config_path, toolset, hypothesis)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("", encoding="utf-8")
        last_code = 1
        for index, model in enumerate(self._models(config)):
            if index:
                self._write_log_event(log_path, {"type": "runner_fallback", "model": model})
            command = self._prepare_command(command_factory(model))
            self._write_log_event(
                log_path,
                {
                    "type": "runner_command_start",
                    "model": model,
                    "command": command,
                    "timestamp": self._timestamp(),
                },
            )
            try:
                completed = subprocess.run(
                    command,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=config.pi.timeout_seconds,
                    check=False,  # returncode drives the model-fallback loop below
                    **self._subprocess_kwargs(config),
                )
            except subprocess.TimeoutExpired as exc:
                self._append_stdout(log_path, self._text(exc.stdout))
                self._append_stderr(log_path, self._text(exc.stderr))
                self._write_log_event(
                    log_path,
                    {
                        "type": "runner_timeout",
                        "model": model,
                        "timeout_seconds": config.pi.timeout_seconds,
                        "timestamp": self._timestamp(),
                    },
                )
                last_code = 124
                continue
            self._append_stdout(log_path, completed.stdout)
            self._append_stderr(log_path, completed.stderr)
            self._write_log_event(
                log_path,
                {
                    "type": "runner_command_end",
                    "model": model,
                    "returncode": completed.returncode,
                    "timestamp": self._timestamp(),
                },
            )
            last_code = completed.returncode
            if last_code == 0:
                return 0
        return last_code

    def _models(self, config: AppConfig) -> list[str | None]:
        models: list[str | None] = []
        if config.pi.model:
            models.append(config.pi.model)
        for model in config.pi.fallback_models:
            if model not in models:
                models.append(model)
        return models or [None]

    def _json_command(
        self,
        config: AppConfig,
        prompt: str,
        toolset: str | None,
        hypothesis: str | None,
        model: str | None,
        session: PiSessionOptions | None = None,
    ) -> list[str]:
        command = self.command_builder.build(
            config,
            prompt=None,
            print_mode=True,
            toolset=toolset,
            hypothesis=hypothesis,
            model=model,
            session=session,
        )
        command.extend(["--mode", "json", prompt])
        return command

    def _append_stdout(self, log_path: Path, text: str) -> None:
        if not text:
            return
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(text)
            if not text.endswith("\n"):
                handle.write("\n")

    def _append_stderr(self, log_path: Path, text: str) -> None:
        if not text:
            return
        for line in text.splitlines():
            self._write_log_event(log_path, {"type": "runner_stderr", "text": line, "timestamp": self._timestamp()})

    def _text(self, value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

    def _write_log_event(self, log_path: Path, event: dict[str, object]) -> None:
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True))
            handle.write("\n")

    def _timestamp(self) -> str:
        return datetime.now(UTC).isoformat()
