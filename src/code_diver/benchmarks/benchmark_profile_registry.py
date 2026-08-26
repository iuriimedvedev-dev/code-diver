from __future__ import annotations

from pathlib import Path

from .benchmark_preparation import BenchmarkPreparation
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
                    name="codesearchnet-mteb-python-1000",
                    dataset=Path(
                        ".code-diver/benchmarks/mteb-codesearchnet-python/codesearchnet_python_1000.jsonl"
                    ),
                    config_path=Path(
                        "configs/codesearchnet-mteb-python-h5-embeddinggemma-quality.yml"
                    ),
                    description=(
                        "Public MTEB CodeSearchNetRetrieval Python benchmark with the default "
                        "H6.1 EmbeddingGemma quality profile."
                    ),
                    external_repo="https://huggingface.co/datasets/mteb/CodeSearchNetRetrieval",
                    setup_hint=(
                        "Run `uv run code-diver init --platform apple-metal --embedding embeddinggemma-300m --yes --start` first, "
                        "then evaluate with this benchmark profile. Code Diver asks before downloading missing assets."
                    ),
                    preparation=BenchmarkPreparation(
                        kind="mteb_codesearchnet",
                        dataset_name="mteb/CodeSearchNetRetrieval",
                        language="python",
                        limit=1000,
                        output_root=Path(
                            ".code-diver/benchmarks/mteb-codesearchnet-python"
                        ),
                        estimated_download_mb=25,
                    ),
                ),
                BenchmarkProfile(
                    name="codesearchnet-mteb-python-hash-smoke",
                    dataset=Path(
                        ".code-diver/benchmarks/mteb-codesearchnet-python/codesearchnet_python_1000.jsonl"
                    ),
                    config_path=Path("configs/codesearchnet-mteb-python-hash.yml"),
                    description="No-key deterministic smoke profile; not a quality benchmark.",
                    external_repo="https://huggingface.co/datasets/mteb/CodeSearchNetRetrieval",
                    setup_hint="Use only to verify benchmark plumbing without local/API embedding models.",
                    preparation=BenchmarkPreparation(
                        kind="mteb_codesearchnet",
                        dataset_name="mteb/CodeSearchNetRetrieval",
                        language="python",
                        limit=1000,
                        output_root=Path(
                            ".code-diver/benchmarks/mteb-codesearchnet-python"
                        ),
                        estimated_download_mb=25,
                    ),
                ),
                BenchmarkProfile(
                    name="codesearchnet-h10-graph-file-vertex-1000",
                    dataset=Path(
                        ".code-diver/benchmarks/mteb-codesearchnet-python/codesearchnet_python_1000.jsonl"
                    ),
                    config_path=Path(
                        "configs/benchmarks/codesearchnet-h10-graph-file-vertex-1000.yml"
                    ),
                    description=(
                        "Public MTEB CodeSearchNetRetrieval Python benchmark for the paid H10 lane: "
                        "local Qwen file metadata index + GraphRAG file propagation + Vertex Gemini Lite rerank."
                    ),
                    external_repo="https://huggingface.co/datasets/mteb/CodeSearchNetRetrieval",
                    setup_hint=(
                        "Run the local embedding runtime first. Vertex project and credentials must come from ADC or env, "
                        "not from the checked-in config."
                    ),
                    preparation=BenchmarkPreparation(
                        kind="mteb_codesearchnet",
                        dataset_name="mteb/CodeSearchNetRetrieval",
                        language="python",
                        limit=1000,
                        output_root=Path(
                            ".code-diver/benchmarks/mteb-codesearchnet-python"
                        ),
                        estimated_download_mb=25,
                    ),
                ),
                BenchmarkProfile(
                    name="codesearchnet-h6-hybrid-vertex-1000",
                    dataset=Path(
                        ".code-diver/benchmarks/mteb-codesearchnet-python/codesearchnet_python_1000.jsonl"
                    ),
                    config_path=Path(
                        "configs/benchmarks/codesearchnet-h6-hybrid-vertex-1000.yml"
                    ),
                    description=(
                        "GraphRAG control for H10: same local Qwen file metadata index and "
                        "same Vertex Gemini Lite rerank, but calibrated hybrid retrieval without graph-file propagation."
                    ),
                    external_repo="https://huggingface.co/datasets/mteb/CodeSearchNetRetrieval",
                    setup_hint=(
                        "Run the local embedding runtime first. Vertex project and credentials must come from ADC or env, "
                        "not from the checked-in config."
                    ),
                    preparation=BenchmarkPreparation(
                        kind="mteb_codesearchnet",
                        dataset_name="mteb/CodeSearchNetRetrieval",
                        language="python",
                        limit=1000,
                        output_root=Path(
                            ".code-diver/benchmarks/mteb-codesearchnet-python"
                        ),
                        estimated_download_mb=25,
                    ),
                ),
                BenchmarkProfile(
                    name="codesearchnet-h12-graph-context-vertex-1000",
                    dataset=Path(
                        ".code-diver/benchmarks/mteb-codesearchnet-python/codesearchnet_python_1000.jsonl"
                    ),
                    config_path=Path(
                        "configs/benchmarks/codesearchnet-h12-graph-context-vertex-1000.yml"
                    ),
                    description=(
                        "H12 graph-context lane: same H10 GraphRAG candidate generator and Vertex Gemini Lite rerank, "
                        "plus repository context in the rerank prompt."
                    ),
                    external_repo="https://huggingface.co/datasets/mteb/CodeSearchNetRetrieval",
                    setup_hint=(
                        "Run the local embedding runtime first. Vertex project and credentials must come from ADC or env, "
                        "not from the checked-in config."
                    ),
                    preparation=BenchmarkPreparation(
                        kind="mteb_codesearchnet",
                        dataset_name="mteb/CodeSearchNetRetrieval",
                        language="python",
                        limit=1000,
                        output_root=Path(
                            ".code-diver/benchmarks/mteb-codesearchnet-python"
                        ),
                        estimated_download_mb=25,
                    ),
                ),
                BenchmarkProfile(
                    name="swebench-verified-mteb-500",
                    dataset=Path(
                        ".code-diver/benchmarks/mteb-swebench-verified-500/swebench_code_retrieval_621.jsonl"
                    ),
                    config_path=Path(
                        "configs/benchmarks/swebench-verified-mteb-500.yml"
                    ),
                    description=(
                        "Public MTEB SWEbenchCodeRetrieval Python benchmark: all 621 positive "
                        "qrels from SWE-bench Verified (500 GitHub-issue instances), retrieved "
                        "against the FULL ~58k-file corpus split (every candidate file across "
                        "all instances), not just the gold-answer files."
                    ),
                    external_repo="https://huggingface.co/datasets/mteb/SWEbenchCodeRetrieval",
                    setup_hint=(
                        "Run `uv run code-diver init --platform apple-metal --embedding embeddinggemma-300m --yes --start` "
                        "first, then evaluate with this benchmark profile. Preparing it downloads and writes the full "
                        "~58k-file (~1.3 GB) corpus split, so the first run takes a few minutes. Code Diver asks before "
                        "downloading missing assets."
                    ),
                    preparation=BenchmarkPreparation(
                        kind="mteb_swebench",
                        dataset_name="mteb/SWEbenchCodeRetrieval",
                        language="python",
                        limit=621,
                        output_root=Path(
                            ".code-diver/benchmarks/mteb-swebench-verified-500"
                        ),
                        estimated_download_mb=1300,
                    ),
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
            raise ValueError(
                f"Unknown benchmark profile '{name}'. Available profiles: {available}"
            ) from exc

    def names(self) -> list[str]:
        return sorted(self._profiles)
