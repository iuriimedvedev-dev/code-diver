from __future__ import annotations

import sys
from pathlib import Path

import questionary
from rich.console import Console
from rich.prompt import IntPrompt

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
        profile_key = profile_key or (self._default_profile(platform) if yes else self._ask_profile(platform))
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

        should_install = install if install is not None else yes or self._confirm_install()
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
        descriptions = {
            "apple-metal": "Mac Apple Silicon with Metal/MLX",
            "nvidia-cuda": "Linux/WSL workstation with Nvidia CUDA",
            "amd-rocm": "Linux workstation with AMD ROCm",
            "cpu": "No GPU; useful for smoke tests only",
            "api": "Remote API embeddings such as Gemini",
            "external": "Already managed Docker/remote OpenAI-compatible endpoint",
        }
        return self._select(
            "Select runtime platform",
            [(choice, f"{choice} - {descriptions[choice]}") for choice in choices],
        )

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

    def _default_profile(self, platform: str) -> str:
        profiles = self.registry.profiles_for_platform(platform) or self.registry.profiles()
        return profiles[0].key

    def _ask_profile(self, platform: str) -> str:
        if not sys.stdin.isatty():
            raise RuntimeError("Non-interactive init requires --embedding.")
        profiles = self.registry.profiles_for_platform(platform) or self.registry.profiles()
        return self._select(
            "Select default embedding extractor",
            [(profile.key, f"{profile.label} - {profile.description}") for profile in profiles],
        )

    def _ask_backend(self, provider: str) -> str:
        if provider != "openai_compatible":
            return "external"
        return self._select(
            "Runtime backend",
            [
                ("host-uv", "host-uv - install and run a local server managed by Code Diver"),
                ("external", "external - use an already running Docker/remote endpoint"),
            ],
        )

    def _confirm_install(self) -> bool:
        answer = questionary.confirm(
            "Install/update local vLLM runtime with uv now?",
            default=True,
            style=self._prompt_style(),
        ).ask()
        if answer is None:
            raise KeyboardInterrupt
        return bool(answer)

    def _select(self, message: str, choices: list[tuple[str, str]]) -> str:
        answer = questionary.select(
            message,
            choices=[questionary.Choice(title=label, value=value) for value, label in choices],
            use_indicator=True,
            use_shortcuts=False,
            style=self._prompt_style(),
        ).ask()
        if answer is None:
            raise KeyboardInterrupt
        return str(answer)

    def _prompt_style(self) -> questionary.Style:
        return questionary.Style(
            [
                ("qmark", "fg:#00bcd4 bold"),
                ("question", "bold"),
                ("pointer", "fg:#00e676 bold"),
                ("highlighted", "fg:#00e676 bold"),
                ("selected", "fg:#00bcd4"),
                ("answer", "fg:#00e676 bold"),
            ]
        )
