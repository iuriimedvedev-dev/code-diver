from __future__ import annotations

import sys
from pathlib import Path

from rich.console import Console
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table

from ..config.embedding_profile_registry import EmbeddingProfileRegistry
from .embedding_runtime_manager import EmbeddingRuntimeManager
from .runtime_config import RuntimeConfig
from .runtime_config_store import RuntimeConfigStore


class RuntimeSetupWizard:
    def __init__(
        self,
        store: RuntimeConfigStore | None = None,
        registry: EmbeddingProfileRegistry | None = None,
        console: Console | None = None,
    ) -> None:
        self.store = store or RuntimeConfigStore()
        self.registry = registry or EmbeddingProfileRegistry()
        self.console = console or Console(stderr=True)

    def run(
        self,
        *,
        profile_key: str | None = None,
        platform: str | None = None,
        backend: str | None = None,
        install: bool | None = None,
        start: bool = False,
        yes: bool = False,
    ) -> RuntimeConfig:
        platform = platform or self._default_platform(profile_key, yes)
        profile_key = profile_key or self._ask_profile(platform)
        profile = self.registry.get(profile_key)
        if platform not in profile.platforms and profile.config.provider == "openai_compatible":
            raise ValueError(f"Embedding profile {profile_key} is not compatible with platform {platform}.")
        if backend is None:
            if platform == "external":
                backend = "external"
            else:
                backend = "host-uv" if yes and profile.config.provider == "openai_compatible" else self._ask_backend(
                    profile.config.provider
                )
        port = 8001 if yes else IntPrompt.ask("Embedding server port", default=8001, console=self.console)
        config = RuntimeConfig(
            embedding_profile=profile_key,
            install_dir=Path(".code-diver/runtime/vllm"),
            backend=backend,
            platform=platform,
            port=port,
            auto_start=backend == "host-uv",
        )
        self.store.save(config)
        self.console.print(f"[green]saved runtime config[/green] {self.store.path}")

        if profile.config.provider != "openai_compatible":
            self.console.print("[yellow]selected API embedding profile; no local runtime install is needed[/yellow]")
            return config
        if backend == "external":
            self.console.print(
                "[yellow]external runtime selected; start a compatible /v1/embeddings server yourself[/yellow]"
            )
            if start:
                EmbeddingRuntimeManager(config, self.registry).ensure_running(timeout_seconds=5)
            return config

        should_install = install if install is not None else yes or Confirm.ask(
            "Install/update local vLLM runtime with uv now?",
            default=True,
            console=self.console,
        )
        manager = EmbeddingRuntimeManager(config, self.registry)
        if should_install:
            self.console.print("[cyan]installing local embedding runtime with uv[/cyan]")
            manager.install()
        if start:
            self.console.print("[cyan]starting local embedding server[/cyan]")
            manager.ensure_running()
            self.console.print(f"[green]embedding server ready[/green] {config.url}")
        return config

    def _ask_platform(self) -> str:
        if not sys.stdin.isatty():
            raise RuntimeError("Non-interactive init requires --platform and --embedding.")
        choices = ["apple-metal", "nvidia-cuda", "amd-rocm", "cpu", "api", "external"]
        table = Table(title="Runtime Platform", show_header=True, header_style="bold magenta")
        table.add_column("#", justify="right", style="cyan")
        table.add_column("Platform", style="bold")
        table.add_column("Use when")
        descriptions = {
            "apple-metal": "Mac Apple Silicon with Metal/MLX",
            "nvidia-cuda": "Linux/WSL workstation with Nvidia CUDA",
            "amd-rocm": "Linux workstation with AMD ROCm",
            "cpu": "No GPU; useful for smoke tests only",
            "api": "Remote API embeddings such as Gemini",
            "external": "Already managed Docker/remote OpenAI-compatible endpoint",
        }
        for index, choice in enumerate(choices, start=1):
            table.add_row(str(index), choice, descriptions[choice])
        self.console.print(table)
        selected = Prompt.ask(
            "Select runtime platform",
            choices=[str(index) for index in range(1, len(choices) + 1)],
            default="1",
            console=self.console,
        )
        return choices[int(selected) - 1]

    def _default_platform(self, profile_key: str | None, yes: bool) -> str:
        if profile_key:
            profile = self.registry.get(profile_key)
            for platform in profile.platforms:
                if platform not in {"external", "api"}:
                    return platform
            return profile.platforms[0]
        if yes:
            return "apple-metal"
        return self._ask_platform()

    def _ask_profile(self, platform: str) -> str:
        if not sys.stdin.isatty():
            raise RuntimeError("Non-interactive init requires --embedding.")
        profiles = self.registry.profiles_for_platform(platform) or self.registry.profiles()
        table = Table(title="Embedding Extractor Setup", show_header=True, header_style="bold magenta")
        table.add_column("#", justify="right", style="cyan")
        table.add_column("Profile", style="bold")
        table.add_column("Notes")
        for index, profile in enumerate(profiles, start=1):
            table.add_row(str(index), profile.label, profile.description)
        self.console.print(table)
        choices = [str(index) for index in range(1, len(profiles) + 1)]
        selected = Prompt.ask("Select default embedding extractor", choices=choices, default="1", console=self.console)
        return profiles[int(selected) - 1].key

    def _ask_backend(self, provider: str) -> str:
        if provider != "openai_compatible":
            return "external"
        return Prompt.ask(
            "Runtime backend",
            choices=["host-uv", "external"],
            default="host-uv",
            console=self.console,
        )
