from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..config import AppConfig
from ..settings import Defaults, EnvironmentVariable
from .pi_session_options import PiSessionOptions


class GeminiCliAgentRunner:
    PROVIDERS = {"gemini-cli", "gemini_cli"}

    def run_interactive(
        self,
        config: AppConfig,
        config_path: Path | None,
        prompt: str | None = None,
        toolset: str | None = None,
        hypothesis: str | None = None,
        session: PiSessionOptions | None = None,
    ) -> int:
        command = self._command(
            config,
            prompt=self._agent_prompt(config, prompt),
            interactive=True,
            session=session,
        )
        self._print_launch_status(config, command, toolset, hypothesis)
        return subprocess.call(
            command,
            env=self._env(config, config_path, toolset, hypothesis),
            cwd=str(config.root.resolve()),
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
        code, output = self.run_print_capture(
            config, config_path, prompt, toolset, hypothesis, session
        )
        if output:
            print(output)
        return code

    def run_print_capture(
        self,
        config: AppConfig,
        config_path: Path | None,
        prompt: str,
        toolset: str | None = None,
        hypothesis: str | None = None,
        session: PiSessionOptions | None = None,
    ) -> tuple[int, str]:
        command = self._command(
            config,
            prompt=self._agent_prompt(config, prompt),
            interactive=False,
            session=session,
        )
        self._print_launch_status(config, command, toolset, hypothesis)
        try:
            completed = subprocess.run(
                command,
                env=self._env(config, config_path, toolset, hypothesis),
                cwd=str(config.root.resolve()),
                capture_output=True,
                text=True,
                timeout=config.pi.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            if stderr:
                sys.stderr.write(stderr)
            print(
                f"[code-diver] error: Gemini CLI agent timed out after {config.pi.timeout_seconds}s",
                file=sys.stderr,
                flush=True,
            )
            return 124, stdout
        stderr = self._clean_cli_noise(completed.stderr)
        if stderr:
            sys.stderr.write(stderr)
            if not stderr.endswith("\n"):
                sys.stderr.write("\n")
        return completed.returncode, self._clean_cli_noise(completed.stdout)

    def _clean_cli_noise(self, output: str) -> str:
        lines: list[str] = []
        for line in output.splitlines():
            stripped = line.strip()
            if not stripped:
                lines.append(line)
                continue
            if stripped.startswith("MCP issues detected."):
                continue
            if stripped.startswith("Hook system message:"):
                continue
            if re.fullmatch(r"[0-9a-f]{32}", stripped):
                continue
            lines.append(line)
        return "\n".join(lines).strip() + (
            "\n" if output.endswith("\n") and lines else ""
        )

    def _command(
        self,
        config: AppConfig,
        prompt: str,
        interactive: bool,
        session: PiSessionOptions | None,
    ) -> list[str]:
        command = [self._binary(config)]
        if config.pi.model:
            command.extend(["--model", config.pi.model])
        command.extend(["--approval-mode", "plan", "--skip-trust"])
        command.extend(["--include-directories", str(config.root.resolve())])
        command.extend(self._session_args(session))
        command.extend(config.pi.extra_args)
        if interactive:
            command.extend(["--prompt-interactive", prompt])
        else:
            command.extend(["--prompt", prompt, "--output-format", "text"])
        return command

    def _binary(self, config: AppConfig) -> str:
        if config.pi.binary and config.pi.binary != Defaults.PI_BINARY:
            return config.pi.binary
        return Defaults.GEMINI_CLI_BINARY

    def _session_args(self, session: PiSessionOptions | None) -> list[str]:
        if session is None:
            return []
        args: list[str] = []
        if session.resume:
            args.extend(["--resume", session.session or "latest"])
        elif session.continue_session:
            args.extend(["--resume", "latest"])
        elif session.session:
            args.extend(["--resume", session.session])
        if session.session_id:
            args.extend(["--session-id", session.session_id])
        return args

    def _env(
        self,
        config: AppConfig,
        config_path: Path | None,
        toolset: str | None,
        hypothesis: str | None,
    ) -> dict[str, str]:
        env = os.environ.copy()
        env.update(config.pi.env)
        env[EnvironmentVariable.CODE_DIVER_CONFIG.value] = str(
            (config_path or Defaults.CONFIG_PATH).resolve()
        )
        env[EnvironmentVariable.CODE_DIVER_ROOT.value] = str(config.root.resolve())
        if toolset:
            env["CODE_DIVER_TOOLSET"] = toolset
        if hypothesis:
            env["CODE_DIVER_HYPOTHESIS"] = hypothesis
        return env

    def _agent_prompt(self, config: AppConfig, user_prompt: str | None) -> str:
        sections = [
            "You are Code Diver's Search agent for the current repository.",
            "You answer code questions by inspecting the repository in read-only mode.",
            "Use Gemini CLI built-in read, search, grep, and file inspection tools when needed.",
            "Do not edit, write, delete, move, format, or patch source files.",
            "Prefer targeted searches first, then bounded reads around the most relevant files.",
            "Cite relative file paths and line numbers for important claims.",
            "Before the final answer, challenge whether the files you found are owners of the behavior or only weak lexical matches.",
        ]
        context = self._repo_context(config)
        if context:
            sections.append("Repository context:\n" + context)
        if user_prompt:
            sections.append("User question:\n" + user_prompt)
        else:
            sections.append(
                "Start by briefly introducing yourself as the Search agent and state that this session is read-only."
            )
        return "\n\n".join(sections)

    def _repo_context(self, config: AppConfig) -> str:
        if not config.pi.repo_context.enabled:
            return ""
        path = config.pi.repo_context.output
        if not path.is_absolute():
            path = config.root / path
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""

    def _print_launch_status(
        self,
        config: AppConfig,
        _command: list[str],
        toolset: str | None,
        hypothesis: str | None,
    ) -> None:
        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold cyan", no_wrap=True)
        table.add_column()
        table.add_row("backend", "Gemini CLI")
        table.add_row("model", config.pi.model or "default")
        table.add_row("mode", "read-only plan")
        table.add_row("repo", str(config.root.resolve()))
        if toolset:
            table.add_row("toolset", toolset)
        if hypothesis:
            table.add_row("hypothesis", hypothesis)
        Console(stderr=True, color_system="auto").print(
            Panel(
                table,
                title="[bold]Launching Search Agent[/bold]",
                border_style="cyan",
                padding=(0, 1),
            )
        )
