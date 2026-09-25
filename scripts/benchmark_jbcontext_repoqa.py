#!/usr/bin/env python3
"""Benchmark JetBrains Context CLI (jbcontext) on RepoQA needles: psf/black & google/gson.

Compares retrieval accuracy and latency side-by-side against code-diver:
1. Unpacks repository files into .benchmarks/repoqa/<lang>/<repo_slug>
2. Ensures isolated git repo inside target directory (required by jbcontext)
3. Indexes with `jbcontext index --project-path <repo_dir>`
4. Executes the 10 needles for psf/black and 10 needles for google/gson
5. Computes:
   - File Hit@1, Hit@3, Hit@5
   - File MRR
   - Line Overlap@1, Overlap@3
   - Query Latency (mean, median, p95)
6. Compares side-by-side with code-diver's results!
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

DEFAULT_JBCONTEXT_BIN = str(Path.home() / ".jbcontext" / "bin" / "jbcontext")
DEFAULT_DATASET = Path("artifacts/repoqa/repoqa.json.gz")
DEFAULT_BENCHMARKS_DIR = Path(".benchmarks/repoqa")
DEFAULT_CODEDIVER_REPORT = Path(".benchmarks/repoqa/codediver_results.json")

EVAL_TARGETS_DEFAULT = [
    {"repo": "psf/black", "language": "python", "slug": "psf_black"},
    {"repo": "google/gson", "language": "java", "slug": "google_gson"},
]

EVAL_TARGETS_100 = [
    # Python (2 repos = 20 needles)
    {"repo": "psf/black", "language": "python", "slug": "psf_black"},
    {"repo": "python-poetry/poetry", "language": "python", "slug": "python_poetry"},
    # Java (2 repos = 20 needles)
    {"repo": "google/gson", "language": "java", "slug": "google_gson"},
    {"repo": "square/retrofit", "language": "java", "slug": "square_retrofit"},
    # TypeScript / JavaScript (2 repos = 20 needles)
    {"repo": "expressjs/express", "language": "typescript", "slug": "expressjs_express"},
    {"repo": "axios/axios", "language": "typescript", "slug": "axios_axios"},
    # Rust (2 repos = 20 needles)
    {"repo": "rust-bakery/nom", "language": "rust", "slug": "rust_bakery_nom"},
    {"repo": "tokio-rs/tracing", "language": "rust", "slug": "tokio_rs_tracing"},
    # Go (2 repos = 20 needles)
    {"repo": "junegunn/fzf", "language": "go", "slug": "junegunn_fzf"},
    {"repo": "caddyserver/caddy", "language": "go", "slug": "caddyserver_caddy"},
]


def normalize_path(path: str) -> str:
    """Normalize file paths for consistent comparison."""
    p = path.strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    p = p.lstrip("/")
    if p.startswith("corpus/"):
        p = p[len("corpus/"):]
    return p


def intervals_overlap(s1: int, e1: int, s2: int, e2: int) -> bool:
    """Check if two 1D integer intervals [s1, e1] and [s2, e2] overlap."""
    return max(s1, s2) <= min(e1, e2)


def dedupe_files(paths: list[str]) -> list[str]:
    """Deduplicate file paths preserving rank order."""
    seen: set[str] = set()
    files: list[str] = []
    for p in paths:
        norm = normalize_path(p)
        if norm not in seen:
            seen.add(norm)
            files.append(norm)
    return files


def unpack_repo(repo_entry: dict[str, Any], target_dir: Path, force: bool = False) -> int:
    """Unpack repository files from dataset into target_dir."""
    files_dict: dict[str, str] = repo_entry.get("content", {})
    if not force and target_dir.exists() and any(target_dir.iterdir()):
        # If corpus exists, count files
        count = sum(1 for p in target_dir.rglob("*") if p.is_file() and ".git" not in p.parts)
        if count > 0:
            return count

    target_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for rel_path, content in files_dict.items():
        dest = target_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        count += 1
    return count


def ensure_git_repo(corpus_dir: Path, repo_name: str) -> None:
    """Ensure the corpus directory is an isolated git repository.

    jbcontext traverses parent directories looking for git repositories. If the corpus
    has its own .git folder, jbcontext treats corpus_dir as the project root, so
    relative file paths in search results match RepoQA relative paths.
    """
    git_dir = corpus_dir / ".git"
    if git_dir.exists():
        return

    print(f"  [Git] Initializing isolated git repository in {corpus_dir}...")
    subprocess.run(["git", "init", "-b", "main"], cwd=corpus_dir, check=True, capture_output=True)
    gitignore = corpus_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(".code-diver/\n", encoding="utf-8")
    subprocess.run(["git", "config", "user.email", "benchmark@repoqa.local"], cwd=corpus_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "RepoQA Benchmark"], cwd=corpus_dir, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=corpus_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", f"Initial commit for {repo_name} corpus"], cwd=corpus_dir, check=True, capture_output=True)


def get_jbcontext_env() -> dict[str, str]:
    """Get environment for running jbcontext with keychain disabled."""
    env = dict(os.environ)
    env["JBCONTEXT_NO_KEYCHAIN"] = "1"
    return env


def index_repo_jbcontext(
    jbcontext_bin: str,
    corpus_dir: Path,
    reindex: bool = False,
    timeout_s: float = 180.0,
) -> float:
    """Index repository using jbcontext index."""
    env = get_jbcontext_env()

    # Check status first if not forcing reindex
    if not reindex:
        status_proc = subprocess.run(
            [jbcontext_bin, "status", "--project-path", str(corpus_dir)],
            capture_output=True,
            text=True,
            env=env,
            timeout=30.0,
        )
        if "No indices found" not in status_proc.stdout and status_proc.returncode == 0:
            print(f"  [Index] Reusing existing jbcontext index for {corpus_dir}")
            return 0.0

    print(f"  [Index] Running `jbcontext index --project-path {corpus_dir}`...")
    t0 = time.perf_counter()
    proc = subprocess.run(
        [jbcontext_bin, "index", "--project-path", str(corpus_dir)],
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout_s,
    )
    duration = time.perf_counter() - t0
    if proc.returncode != 0:
        raise RuntimeError(f"jbcontext index failed (exit {proc.returncode}):\n{proc.stderr}\n{proc.stdout}")

    print(f"  [Index] Completed indexing in {duration:.2f}s")
    return duration


def search_jbcontext(
    jbcontext_bin: str,
    corpus_dir: Path,
    query: str,
    limit: int = 20,
    timeout_s: float = 60.0,
) -> tuple[list[dict[str, Any]], float, str | None]:
    """Execute a semantic search query with jbcontext."""
    env = get_jbcontext_env()
    cmd = [
        jbcontext_bin,
        "search",
        "--project-path",
        str(corpus_dir),
        "--limit",
        str(limit),
        "--json-output",
        query,
    ]

    t0 = time.perf_counter()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        duration_ms = (time.perf_counter() - t0) * 1000.0
        return [], duration_ms, "timeout"

    duration_ms = (time.perf_counter() - t0) * 1000.0
    if proc.returncode != 0:
        return [], duration_ms, f"exit {proc.returncode}: {proc.stderr.strip()[:200]}"

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return [], duration_ms, f"json parse error: {exc}"

    if data.get("type") == "error":
        return [], duration_ms, data.get("message", "unknown error")

    results = []
    for r in data.get("results", []):
        res_info = r.get("result", {})
        source_pos = res_info.get("sourcePosition", {})
        rel_path = normalize_path(source_pos.get("relativePath", ""))
        start_line = r.get("contentStartLine")
        content = r.get("content", "")
        line_count = max(content.count("\n"), 1)
        end_line = (start_line + line_count - 1) if start_line is not None else None
        similarity = res_info.get("scoredText", {}).get("similarity", 0.0)

        results.append({
            "path": rel_path,
            "start_line": start_line,
            "end_line": end_line,
            "similarity": similarity,
            "content": content[:200],
        })

    return results, duration_ms, None


def evaluate_jbcontext_repo(
    jbcontext_bin: str,
    corpus_dir: Path,
    repo_name: str,
    lang: str,
    needles: list[dict[str, Any]],
    limit: int = 20,
) -> dict[str, Any]:
    """Evaluate all needles for a repository with jbcontext."""
    results_detail = []
    file_hit1_list: list[bool] = []
    file_hit3_list: list[bool] = []
    file_hit5_list: list[bool] = []
    file_mrr_list: list[float] = []
    line_overlap1_list: list[bool] = []
    line_overlap3_list: list[bool] = []
    line_overlap5_list: list[bool] = []
    latencies_ms: list[float] = []

    for idx, needle in enumerate(needles):
        query = needle.get("description", "").strip()
        target_file = normalize_path(needle.get("path", ""))
        n_start = int(needle.get("start_line", 0))
        n_end = int(needle.get("end_line", 0))
        func_name = needle.get("name", "")

        search_results, latency_ms, error = search_jbcontext(
            jbcontext_bin=jbcontext_bin,
            corpus_dir=corpus_dir,
            query=query,
            limit=limit,
        )

        latencies_ms.append(latency_ms)

        if error:
            print(f"    [Error] Needle {idx} ({func_name}): {error}")
            file_hit1_list.append(False)
            file_hit3_list.append(False)
            file_hit5_list.append(False)
            file_mrr_list.append(0.0)
            line_overlap1_list.append(False)
            line_overlap3_list.append(False)
            line_overlap5_list.append(False)
            continue

        retrieved_paths = [r["path"] for r in search_results]
        unique_files = dedupe_files(retrieved_paths)

        hit1 = bool(unique_files and unique_files[0] == target_file)
        hit3 = target_file in unique_files[:3]
        hit5 = target_file in unique_files[:5]
        mrr = (1.0 / (unique_files.index(target_file) + 1)) if target_file in unique_files else 0.0

        file_hit1_list.append(hit1)
        file_hit3_list.append(hit3)
        file_hit5_list.append(hit5)
        file_mrr_list.append(mrr)

        def chunk_overlaps(item: dict[str, Any], target: str, start: int, end: int) -> bool:
            if item["path"] != target:
                return False
            if item.get("start_line") is None or item.get("end_line") is None:
                return False
            return intervals_overlap(int(item["start_line"]), int(item["end_line"]), start, end)

        top_overlap = chunk_overlaps(search_results[0], target_file, n_start, n_end) if search_results else False
        overlap3 = any(chunk_overlaps(r, target_file, n_start, n_end) for r in search_results[:3])
        overlap5 = any(chunk_overlaps(r, target_file, n_start, n_end) for r in search_results[:5])

        line_overlap1_list.append(top_overlap)
        line_overlap3_list.append(overlap3)
        line_overlap5_list.append(overlap5)

        results_detail.append({
            "needle_index": idx,
            "function": func_name,
            "target_file": target_file,
            "lines": [n_start, n_end],
            "file_hit1": hit1,
            "file_hit3": hit3,
            "file_hit5": hit5,
            "file_mrr": mrr,
            "line_overlap1": top_overlap,
            "line_overlap3": overlap3,
            "line_overlap5": overlap5,
            "latency_ms": latency_ms,
            "unique_retrieved_files": unique_files[:5],
        })

    n_count = len(needles) or 1
    return {
        "repo": repo_name,
        "language": lang,
        "needles_count": len(needles),
        "file_hit1": sum(file_hit1_list) / n_count,
        "file_hit3": sum(file_hit3_list) / n_count,
        "file_hit5": sum(file_hit5_list) / n_count,
        "file_mrr": sum(file_mrr_list) / n_count,
        "line_overlap1": sum(line_overlap1_list) / n_count,
        "line_overlap3": sum(line_overlap3_list) / n_count,
        "line_overlap5": sum(line_overlap5_list) / n_count,
        "mean_latency_ms": sum(latencies_ms) / n_count,
        "latencies_ms": sorted(latencies_ms),
        "needles": results_detail,
    }


def load_or_run_codediver(
    codediver_report_path: Path,
    dataset_path: Path,
    benchmarks_dir: Path,
) -> list[dict[str, Any]] | None:
    """Load pre-computed code-diver benchmark results or run benchmark_repoqa.py."""
    if codediver_report_path.exists():
        try:
            data = json.loads(codediver_report_path.read_text(encoding="utf-8"))
            repos = data.get("repositories", [])
            if repos:
                return repos
        except Exception:
            pass

    # Attempt to run code-diver benchmark script via .venv/bin/python
    venv_python = Path(".venv/bin/python")
    bench_script = Path("scripts/benchmark_repoqa.py")
    if venv_python.exists() and bench_script.exists():
        print("\n[code-diver] Running code-diver benchmark for side-by-side comparison...")
        codediver_report_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                str(venv_python),
                str(bench_script),
                "--dataset", str(dataset_path),
                "--benchmarks-dir", str(benchmarks_dir),
                "--repos", "psf/black", "google/gson",
                "--output", str(codediver_report_path),
            ],
            check=False,
        )
        if codediver_report_path.exists():
            try:
                data = json.loads(codediver_report_path.read_text(encoding="utf-8"))
                return data.get("repositories", [])
            except Exception:
                pass
    return None


def print_side_by_side_comparison(
    jb_results: list[dict[str, Any]],
    cd_results: list[dict[str, Any]] | None,
) -> None:
    """Print side-by-side comparison tables between code-diver and jbcontext."""
    print("\n" + "=" * 90)
    print("  REPOQA BENCHMARK: JETBRAINS CONTEXT vs CODE-DIVER (SIDE-BY-SIDE)")
    print("=" * 90)

    # 1. Summary comparison table
    cd_map = {r["repo"]: r for r in (cd_results or [])}

    headers = [
        "System",
        "Repository",
        "Needles",
        "File Hit@1",
        "File Hit@3",
        "File Hit@5",
        "File MRR",
        "Line Overlap@1",
        "Line Overlap@3",
        "Avg Latency",
    ]
    col_fmt = "| {:<18} | {:<14} | {:>7} | {:>10} | {:>10} | {:>10} | {:>8} | {:>14} | {:>14} | {:>11} |"
    sep = "|" + "|".join(["-" * (len(h) + 2) for h in headers]) + "|"

    print("\n### Side-by-Side Performance Comparison\n")
    print(col_fmt.format(*headers))
    print(sep)

    for jb in jb_results:
        repo = jb["repo"]
        cd = cd_map.get(repo)

        # Print code-diver row if available
        if cd:
            print(col_fmt.format(
                "code-diver (vec)",
                f"`{repo}`",
                str(cd["needles_count"]),
                f"{cd['file_hit1']:.1%}",
                f"{cd['file_hit3']:.1%}",
                f"{cd['file_hit5']:.1%}",
                f"{cd['file_mrr']:.3f}",
                f"{cd.get('line_overlap1', 0.0):.1%}",
                f"{cd.get('line_overlap3', 0.0):.1%}",
                f"{cd['mean_latency_ms']:.1f} ms",
            ))

        # Print jbcontext row
        print(col_fmt.format(
            "JetBrains Context",
            f"`{repo}`",
            str(jb["needles_count"]),
            f"{jb['file_hit1']:.1%}",
            f"{jb['file_hit3']:.1%}",
            f"{jb['file_hit5']:.1%}",
            f"{jb['file_mrr']:.3f}",
            f"{jb['line_overlap1']:.1%}",
            f"{jb['line_overlap3']:.1%}",
            f"{jb['mean_latency_ms']:.1f} ms",
        ))
        print(sep)

    # Overall rows
    total_jb_needles = sum(r["needles_count"] for r in jb_results) or 1
    jb_avg_h1 = sum(r["file_hit1"] * r["needles_count"] for r in jb_results) / total_jb_needles
    jb_avg_h3 = sum(r["file_hit3"] * r["needles_count"] for r in jb_results) / total_jb_needles
    jb_avg_h5 = sum(r["file_hit5"] * r["needles_count"] for r in jb_results) / total_jb_needles
    jb_avg_mrr = sum(r["file_mrr"] * r["needles_count"] for r in jb_results) / total_jb_needles
    jb_avg_l1 = sum(r["line_overlap1"] * r["needles_count"] for r in jb_results) / total_jb_needles
    jb_avg_l3 = sum(r["line_overlap3"] * r["needles_count"] for r in jb_results) / total_jb_needles
    jb_avg_lat = sum(r["mean_latency_ms"] * r["needles_count"] for r in jb_results) / total_jb_needles

    if cd_results:
        total_cd_needles = sum(r["needles_count"] for r in cd_results) or 1
        cd_avg_h1 = sum(r["file_hit1"] * r["needles_count"] for r in cd_results) / total_cd_needles
        cd_avg_h3 = sum(r["file_hit3"] * r["needles_count"] for r in cd_results) / total_cd_needles
        cd_avg_h5 = sum(r["file_hit5"] * r["needles_count"] for r in cd_results) / total_cd_needles
        cd_avg_mrr = sum(r["file_mrr"] * r["needles_count"] for r in cd_results) / total_cd_needles
        cd_avg_l1 = sum(r.get("line_overlap1", 0.0) * r["needles_count"] for r in cd_results) / total_cd_needles
        cd_avg_l3 = sum(r.get("line_overlap3", 0.0) * r["needles_count"] for r in cd_results) / total_cd_needles
        cd_avg_lat = sum(r["mean_latency_ms"] * r["needles_count"] for r in cd_results) / total_cd_needles

        print(col_fmt.format(
            "**code-diver (vec)**",
            "**OVERALL**",
            str(total_cd_needles),
            f"**{cd_avg_h1:.1%}**",
            f"**{cd_avg_h3:.1%}**",
            f"**{cd_avg_h5:.1%}**",
            f"**{cd_avg_mrr:.3f}**",
            f"**{cd_avg_l1:.1%}**",
            f"**{cd_avg_l3:.1%}**",
            f"**{cd_avg_lat:.1f} ms**",
        ))

    print(col_fmt.format(
        "**JetBrains Context**",
        "**OVERALL**",
        str(total_jb_needles),
        f"**{jb_avg_h1:.1%}**",
        f"**{jb_avg_h3:.1%}**",
        f"**{jb_avg_h5:.1%}**",
        f"**{jb_avg_mrr:.3f}**",
        f"**{jb_avg_l1:.1%}**",
        f"**{jb_avg_l3:.1%}**",
        f"**{jb_avg_lat:.1f} ms**",
    ))
    print(sep)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate jbcontext on RepoQA needles and compare with code-diver.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET, help="Path to repoqa.json.gz dataset.")
    parser.add_argument("--benchmarks-dir", type=Path, default=DEFAULT_BENCHMARKS_DIR, help="Root directory for unpacked corpora.")
    parser.add_argument("--jbcontext-bin", default=DEFAULT_JBCONTEXT_BIN, help="Path to jbcontext CLI binary.")
    parser.add_argument("--limit", type=int, default=20, help="Number of retrieved results per query from jbcontext.")
    parser.add_argument("--reindex", action="store_true", help="Force re-indexing via jbcontext index.")
    parser.add_argument("--force-unpack", action="store_true", help="Force re-unpacking files from archive.")
    parser.add_argument("--output", type=Path, default=Path(".benchmarks/repoqa/jbcontext_results.json"), help="Output path for jbcontext results JSON.")
    parser.add_argument("--all-100", action="store_true", help="Run 100-needle benchmark across 10 multilingual repos.")
    parser.add_argument("--repos", nargs="+", help="Specific repo names to evaluate (e.g. psf/black google/gson)")
    parser.add_argument("--no-codediver", action="store_true", help="Skip loading / comparing with code-diver.")
    args = parser.parse_args()

    # Verify jbcontext binary
    if not shutil.which(args.jbcontext_bin) and not Path(args.jbcontext_bin).exists():
        print(f"Error: jbcontext binary not found at '{args.jbcontext_bin}'.", file=sys.stderr)
        return 1

    if not args.dataset.exists():
        print(f"Error: dataset file not found at '{args.dataset}'.", file=sys.stderr)
        return 1

    print(f"Loading RepoQA dataset from {args.dataset}...")
    with gzip.open(args.dataset, "rt", encoding="utf-8") as f:
        data: dict[str, list[dict[str, Any]]] = json.load(f)

    # Build repo map
    repo_map: dict[str, tuple[str, dict[str, Any]]] = {}
    for lang, repos in data.items():
        for r in repos:
            repo_map[r["repo"]] = (lang, r)

    selected_targets = EVAL_TARGETS_DEFAULT
    if args.all_100:
        selected_targets = EVAL_TARGETS_100
    elif args.repos:
        repo_set = set(args.repos)
        selected_targets = [r for r in EVAL_TARGETS_100 if r["repo"] in repo_set]

    jb_results: list[dict[str, Any]] = []
    total_start = time.perf_counter()

    for target in selected_targets:
        repo_name = target["repo"]
        lang = target["language"]
        slug = target["slug"]

        if repo_name not in repo_map:
            print(f"Warning: {repo_name} not found in dataset, skipping.")
            continue

        _, entry = repo_map[repo_name]
        corpus_dir = (args.benchmarks_dir / lang / slug).resolve()

        print(f"\nProcessing `{repo_name}` ({lang}):")
        file_count = unpack_repo(entry, corpus_dir, force=args.force_unpack)
        print(f"  [Corpus] {file_count} files in {corpus_dir}")

        ensure_git_repo(corpus_dir, repo_name)

        idx_time = index_repo_jbcontext(
            jbcontext_bin=args.jbcontext_bin,
            corpus_dir=corpus_dir,
            reindex=args.reindex,
        )

        needles = entry.get("needles", [])
        print(f"  [Eval] Running {len(needles)} needles with jbcontext search (limit={args.limit})...")
        eval_result = evaluate_jbcontext_repo(
            jbcontext_bin=args.jbcontext_bin,
            corpus_dir=corpus_dir,
            repo_name=repo_name,
            lang=lang,
            needles=needles,
            limit=args.limit,
        )
        eval_result["index_time_s"] = idx_time
        jb_results.append(eval_result)

        print(f"  -> File Hit@1: {eval_result['file_hit1']:.1%}, Hit@3: {eval_result['file_hit3']:.1%}, Hit@5: {eval_result['file_hit5']:.1%}")
        print(f"  -> File MRR:   {eval_result['file_mrr']:.3f}")
        print(f"  -> Line Overlap@1: {eval_result['line_overlap1']:.1%}, Overlap@3: {eval_result['line_overlap3']:.1%}")
        print(f"  -> Mean Latency:  {eval_result['mean_latency_ms']:.1f} ms")

    total_time = time.perf_counter() - total_start

    # Load or run code-diver results for comparison
    cd_results = None
    if not args.no_codediver:
        cd_results = load_or_run_codediver(
            codediver_report_path=DEFAULT_CODEDIVER_REPORT,
            dataset_path=args.dataset,
            benchmarks_dir=args.benchmarks_dir,
        )

    # Print comparison
    print_side_by_side_comparison(jb_results, cd_results)
    print(f"\nTotal benchmark wall-clock time: {total_time:.2f}s\n")

    # Save output JSON
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "system": "jbcontext",
            "cli_binary": args.jbcontext_bin,
            "limit": args.limit,
            "total_time_s": total_time,
            "repositories": jb_results,
            "comparison_codediver": cd_results,
        }
        args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Saved jbcontext results to {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
