from __future__ import annotations

from pathlib import Path

from .benchmark_profile import BenchmarkProfile


class BenchmarkProfileRegistry:
    def __init__(self) -> None:
        self._profiles = {
            profile.name: profile
            for profile in [
                BenchmarkProfile(
                    name="sample",
                    dataset=Path("datasets/sample_eval.jsonl"),
                    description="Tiny built-in smoke benchmark for CLI wiring.",
                ),
                BenchmarkProfile(
                    name="open-protogen-hash-vector-30",
                    dataset=Path("datasets/protogen_eval_30.jsonl"),
                    config_path=Path("configs/protogen-baseline.yml"),
                    description="Deterministic 30-case protogen hash/vector benchmark for local reproducibility checks.",
                    setup_hint="Place the protogen repository at ../protogen, then run evaluate with --reindex.",
                ),
                BenchmarkProfile(
                    name="protogen-open",
                    dataset=Path("datasets/protogen_eval_100.jsonl"),
                    config_path=Path("configs/protogen-baseline.yml"),
                    description="Small open-style code search benchmark used for quick local verification.",
                    setup_hint="Place the protogen repository at ../protogen, then run index/evaluate.",
                ),
                BenchmarkProfile(
                    name="intellij-1000-answer-sets",
                    dataset=Path("datasets/intellij_eval_1000.answer_sets.jsonl"),
                    config_path=Path("configs/intellij-postrank-h3-manifest.yml"),
                    description="Heavy 1000-case IntelliJ IDEA Community benchmark with multi-answer sets.",
                    external_repo="https://github.com/JetBrains/intellij-community",
                    setup_hint="Clone intellij-community next to this repo as ../intellij-community and run the configured index first.",
                ),
            ]
        }

    def get(self, name: str) -> BenchmarkProfile:
        try:
            return self._profiles[name]
        except KeyError as exc:
            available = ", ".join(self.names())
            raise ValueError(f"Unknown benchmark profile '{name}'. Available profiles: {available}") from exc

    def names(self) -> list[str]:
        return sorted(self._profiles)
