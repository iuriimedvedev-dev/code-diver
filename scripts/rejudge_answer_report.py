from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from typing import Any

from code_diver.answering.answer_case import AnswerCase
from code_diver.answering.answer_judge import AnswerJudge
from code_diver.config import ConfigLoader
from code_diver.generation import create_generation_provider


def main() -> int:
    args = parse_args()
    source = json.loads(args.input.read_text(encoding="utf-8"))

    # Build per-case context lookup from report rows
    contexts: dict[str, str] = {}
    for row in source.get("results") or []:
        case_id = str(row.get("case_id") or "")
        if not case_id:
            continue
        context = str(row.get("context_text") or "")
        if not context:
            cfiles = row.get("context_files") or []
            if cfiles:
                if isinstance(cfiles[0], dict):
                    context = "\n\n".join(
                        f"=== {f.get('path', 'unknown')} ===\n{f.get('content', '')}"
                        for f in cfiles
                    )
                elif isinstance(cfiles[0], str):
                    context = "\n".join(cfiles)
        contexts[case_id] = context

    config = ConfigLoader().load(args.judge_config)
    if args.judge_model:
        config = replace(
            config,
            generation=replace(config.generation, model=args.judge_model),
        )
    judge = AnswerJudge(
        create_generation_provider(config),
        prompt_path=args.judge_prompt,
    )

    rows = list(source.get("results") or [])
    output_rows: list[dict[str, Any] | None] = [None] * len(rows)
    partial_rows: list[dict[str, Any] | None] = [None] * len(rows)
    usage = empty_usage()
    judge_error_count = 0
    started = perf_counter()

    worker_count = max(1, int(args.workers or 1))

    def process(index: int, row: dict[str, Any]) -> dict[str, Any]:
        updated = dict(row)
        metrics = dict(updated.get("metrics") or {})
        updated["metrics"] = metrics
        updated.pop("judge", None)
        updated.pop("judge_error", None)
        prediction = str(updated.get("prediction") or "").strip()
        case_id = str(updated.get("case_id") or "")
        if not prediction or updated.get("error"):
            return {"index": index, "row": updated, "usage": None, "model": None, "judge_error": 0}
        context = contexts.get(case_id, "")
        if not context:
            updated["judge_error"] = f"no context for case: {case_id}"
            return {"index": index, "row": updated, "usage": None, "model": None, "judge_error": 1}
        try:
            acase = AnswerCase(
                id=case_id,
                question=str(updated.get("question", "")),
                reference=str(updated.get("reference", "")),
                metadata=updated.get("metadata", {}),
            )
            judged = judge.judge(acase, prediction, context)
            updated["judge"] = judged
            metrics.update(judged["scores"])
            return {"index": index, "row": updated, "usage": judged["usage"], "model": judged["model"], "judge_error": 0}
        except Exception as exc:
            updated["judge_error"] = str(exc)
            return {"index": index, "row": updated, "usage": None, "model": getattr(judge.provider, "model", None), "judge_error": 1}

    if worker_count == 1:
        completed = 0
        for index, row in enumerate(rows):
            result = process(index, row)
            completed += 1
            output_rows[result["index"]] = result["row"]
            partial_rows[result["index"]] = result["row"]
            if result["usage"]:
                merge_usage(usage, result["usage"], result["model"])
            judge_error_count += int(result["judge_error"])
            write_partial(args.partial_output, args.output, completed, rows, partial_rows, usage, judge_error_count)
            print(f"rejudged {completed}/{len(rows)} {row.get('case_id')}", flush=True)
    else:
        completed = 0
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {executor.submit(process, index, row): index for index, row in enumerate(rows)}
            for future in as_completed(futures):
                index = futures[future]
                result = future.result()
                completed += 1
                output_rows[result["index"]] = result["row"]
                partial_rows[result["index"]] = result["row"]
                if result["usage"]:
                    merge_usage(usage, result["usage"], result["model"])
                judge_error_count += int(result["judge_error"])
                write_partial(args.partial_output, args.output, completed, rows, partial_rows, usage, judge_error_count)
                print(f"rejudged {completed}/{len(rows)} {rows[index].get('case_id')}", flush=True)

    final_rows = [row for row in output_rows if row is not None]
    judge_keys = sorted({
        key for row in final_rows for key in (row.get("metrics") or {}) if key.startswith("judge_")
    })
    metrics: dict[str, Any] = {}
    for key in judge_keys:
        vals = [float((row.get("metrics") or {}).get(key, 0.0)) for row in final_rows]
        metrics[key] = sum(vals) / max(len(vals), 1)
    metrics["cases"] = float(len(final_rows))
    metrics["duration_ms"] = (perf_counter() - started) * 1000

    payload: dict[str, Any] = {**source, "judge": {
        "config": str(args.judge_config),
        "prompt": str(args.judge_prompt or AnswerJudge.DEFAULT_PROMPT_PATH),
        "model": args.judge_model or config.generation.model,
        "mode": "posthoc_existing_predictions",
    }}
    payload["metrics"] = metrics
    payload["judge_usage"] = usage
    payload["judge_error_count"] = judge_error_count
    payload["results"] = final_rows
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"saved rejudged answer report: {args.output}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rejudge an answer eval report without regenerating answers.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--judge-config", type=Path, required=True)
    parser.add_argument("--judge-model", default=None)
    parser.add_argument("--judge-prompt", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--partial-output", type=Path, default=None)
    parser.add_argument("--workers", type=int, default=1)
    return parser.parse_args()


def empty_usage() -> dict[str, Any]:
    return {"model_calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "models": []}


def merge_usage(target: dict[str, Any], usage: dict[str, Any] | None, model: str | None) -> None:
    if usage is None:
        return
    target["model_calls"] += 1
    target["input_tokens"] += int(usage.get("input_tokens") or 0)
    target["output_tokens"] += int(usage.get("output_tokens") or 0)
    target["total_tokens"] += int(usage.get("total_tokens") or 0)
    if model and model not in target["models"]:
        target["models"].append(model)


def write_partial(
    partial_output: Path | None, output: Path, completed: int,
    source_rows: list[dict[str, Any]], partial_rows: list[dict[str, Any] | None],
    usage: dict[str, Any], judge_error_count: int,
) -> None:
    if partial_output is None:
        return
    partial_output.parent.mkdir(parents=True, exist_ok=True)
    partial_output.write_text(json.dumps({
        "partial": True, "completed": completed, "total": len(source_rows),
        "output": str(output), "judge_usage": usage, "judge_error_count": judge_error_count,
        "results": [row for row in partial_rows if row is not None],
    }, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
