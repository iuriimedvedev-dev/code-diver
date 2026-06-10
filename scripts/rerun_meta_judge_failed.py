from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from statistics import mean

from code_diver.config import ConfigLoader
from code_diver.explanation import ExplanationDatasetLoader
from code_diver.explanation.explanation_judge_rubric import ExplanationJudgeRubric
from code_diver.explanation.jsonish_parser import JsonishParser
from code_diver.generation import create_generation_provider

META_JUDGE_PATH = Path(__file__).resolve().parent / "meta_judge_explainer_candidates.py"
spec = importlib.util.spec_from_file_location("meta_judge", META_JUDGE_PATH)
meta_judge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(meta_judge)

SLOTS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def main() -> int:
    report_path = Path(sys.argv[1])
    dataset_path = Path(sys.argv[2])
    judge_config_path = Path(sys.argv[3])
    output_path = Path(sys.argv[4])

    old = json.loads(report_path.read_text(encoding="utf-8"))
    old_results = old.get("results") or []

    failed_indices = []
    for i, row in enumerate(old_results):
        scores = row.get("scores") or {}
        if scores and all(v.get("judge_overall", 0) < 0.1 for v in scores.values()):
            failed_indices.append(i)

    print(f"Found {len(failed_indices)} failed cases out of {len(old_results)}")

    all_cases = ExplanationDatasetLoader().load(dataset_path)
    cases = [all_cases[i] for i in failed_indices]

    provider = create_generation_provider(ConfigLoader().load(judge_config_path))
    rubric = ExplanationJudgeRubric()
    parser = JsonishParser()

    candidates = []
    for cr in old.get("candidate_reports", []):
        cp = json.loads(Path(cr["path"]).read_text(encoding="utf-8"))
        rows = {
            str(r.get("case_id")): r
            for r in cp.get("results") or []
            if isinstance(r, dict)
        }
        candidates.append({"label": cr["label"], "path": cr["path"], "payload": cp, "rows": rows})

    labels = [c["label"] for c in candidates]
    permutations = meta_judge.balanced_permutations(labels, total=len(all_cases), seed=old.get("seed", 17))

    rerun_rows = []
    for idx, case_idx in enumerate(failed_indices):
        case = all_cases[case_idx]
        perm = permutations[case_idx]
        row = meta_judge.judge_case(case=case, candidates=candidates, permutation=perm, provider=provider, rubric=rubric, parser=parser)
        rerun_rows.append(row)
        print(f"reran {idx+1}/{len(failed_indices)} {case.id} errors={row.get('judge_error')}")

    merged_results = list(old_results)
    for i, case_idx in enumerate(failed_indices):
        merged_results[case_idx] = rerun_rows[i]

    new_summary = meta_judge.summarize(merged_results, labels, old.get("bootstrap_samples", 2000))
    old["results"] = merged_results
    old["summary"] = new_summary
    old["position_counts"] = meta_judge.position_counts(merged_results)

    old["usage"]["model_calls"] += sum(1 for r in rerun_rows if not r.get("judge_error"))
    old["judge_error_count"] = sum(1 for r in merged_results if r.get("judge_error"))
    old["rerun_failed_cases"] = len(failed_indices)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(old, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=== META-JUDGE RESULTS (scores only, random order) ===\n")
    print(meta_judge.markdown_summary({**old, "summary": new_summary}))

    total_duration_ms = sum(r.get("duration_ms", 0) for r in merged_results if r)
    mean_dur = total_duration_ms / len(merged_results) if merged_results else 0
    print(f"\nTotal meta-judge duration: {total_duration_ms:.0f}ms across {len(merged_results)} cases")
    print(f"Mean per-case meta-judge duration: {mean_dur:.0f}ms")

    print("\n=== PER-CANDIDATE LATENCY (from individual judge reports) ===\n")
    for cr in old.get("candidate_reports", []):
        cp = json.loads(Path(cr["path"]).read_text(encoding="utf-8"))
        source_metrics = cp.get("metrics") or {}
        cases_total = len(cp.get("results") or [])
        dur = float(source_metrics.get("duration_ms", 0) or 0)
        mean_lat = dur / cases_total if cases_total else 0
        print(f"  {cr['label']:15s} total_dur={dur:>8.0f}ms  cases={cases_total:3d}  mean_latency={mean_lat:>7.0f}ms")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
