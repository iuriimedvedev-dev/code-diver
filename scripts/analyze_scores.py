from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import mean, median, stdev


CRITERIA = [
    "judge_purpose_accuracy",
    "judge_behavior_accuracy",
    "judge_api_contract",
    "judge_groundedness",
    "judge_specificity",
    "judge_completeness",
    "judge_clarity",
]

CRITERIA_LABELS = {
    "judge_purpose_accuracy": "Purpose",
    "judge_behavior_accuracy": "Behavior",
    "judge_api_contract": "API",
    "judge_groundedness": "Ground",
    "judge_specificity": "Specific",
    "judge_completeness": "Complete",
    "judge_clarity": "Clarity",
}


def analyze_report(path: str) -> dict:
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    results = report.get("results", [])
    valid = [r for r in results if r.get("prediction") and str(r["prediction"]).strip() and not r.get("error")]

    # Per-criterion scores across all valid cases
    per_criterion: dict[str, list[float]] = {k: [] for k in CRITERIA}
    sums: list[float] = []
    overalls: list[float] = []

    for r in valid:
        metrics = r.get("metrics", {})
        s = 0.0
        for k in CRITERIA:
            v = float(metrics.get(k, 0) or 0)
            per_criterion[k].append(v)
            s += v
        sums.append(s)
        overalls.append(float(metrics.get("judge_overall", 0) or 0))

    # Latency — duration_ms is at result top level, not inside metrics
    durations = [float(r.get("duration_ms", 0) or 0) for r in results]
    durations = [d for d in durations if d > 0]

    top_metrics = report.get("metrics", {})
    agg_duration = float(top_metrics.get("duration_ms", 0) or 0)

    return {
        "valid": len(valid),
        "total": len(results),
        "sums": sums,
        "overalls": overalls,
        "per_criterion": per_criterion,
        "per_case_durations": durations,
        "agg_duration_ms": agg_duration,
    }


def format_table(candidates: list[dict]) -> None:
    print("\n=== РАНЖИРОВАНИЕ ПО СУММЕ КРИТЕРИЕВ (7×4.0 = max 28) ===\n")

    header = ["Candidate", "Valid", "Σ µ", "Σ σ", "Σ min", "Σ max"]
    for k in CRITERIA:
        header.append(CRITERIA_LABELS[k])
    header.append("Overall µ")
    header.append("Lat µ")
    header.append("Lat med")

    sep = ["---:"] * len(header)
    print("| " + " | ".join(header) + " |")
    print("| " + " | ".join(sep) + " |")

    for cand in candidates:
        row = [
            cand["label"],
            str(cand["valid"]),
            f"{cand['sum_mean']:.3f}",
            f"{cand['sum_std']:.3f}",
            f"{cand['sum_min']:.1f}",
            f"{cand['sum_max']:.1f}",
        ]
        for k in CRITERIA:
            row.append(f"{cand['criterion_means'][k]:.3f}")
        row.append(f"{cand['overall_mean']:.3f}")
        row.append(f"{cand['lat_mean_ms']:.0f}")
        row.append(f"{cand['lat_med_ms']:.0f}")
        print("| " + " | ".join(row) + " |")

    print("\n=== ДЕТАЛЬНАЯ СТАТИСТИКА ПО КРИТЕРИЯМ ===\n")
    detail_header = ["Candidate"] + [CRITERIA_LABELS[k] for k in CRITERIA] + ["Sum"]
    print("| " + " | ".join(detail_header) + " |")
    print("| " + " | ".join(["---:"] * len(detail_header)) + " |")

    for cand in candidates:
        row = [cand["label"]]
        for k in CRITERIA:
            vals = cand["per_criterion"][k]
            p = sum(1 for v in vals if v >= 4.0) / len(vals) * 100 if vals else 0
            row.append(f"{cand['criterion_means'][k]:.3f}")
        row.append(f"{cand['sum_mean']:.3f}")
        print("| " + " | ".join(row) + " |")

    print("\n=== ПРОЦЕНТ ИДЕАЛЬНЫХ ОЦЕНОК (4.0) ПО КРИТЕРИЯМ ===\n")
    print("| " + " | ".join(["Candidate"] + [CRITERIA_LABELS[k] for k in CRITERIA]) + " |")
    print("| " + " | ".join(["---:"] * (len(CRITERIA) + 1)) + " |")

    for cand in candidates:
        row = [cand["label"]]
        for k in CRITERIA:
            vals = cand["per_criterion"][k]
            p = sum(1 for v in vals if v >= 4.0) / len(vals) * 100 if vals else 0
            row.append(f"{p:.0f}%")
        print("| " + " | ".join(row) + " |")

    print("\n=== РАСПРЕДЕЛЕНИЕ СУММ (box-like, перцентили) ===\n")
    print("| Candidate | P5 | P25 | P50 | P75 | P95 |")
    print("| ---: | ---: | ---: | ---: | ---: | ---: |")
    for cand in candidates:
        s = sorted(cand["sums"])
        n = len(s)
        row = [
            cand["label"],
            f"{s[int(n*0.05)]:.1f}",
            f"{s[int(n*0.25)]:.1f}",
            f"{s[int(n*0.5)]:.1f}",
            f"{s[int(n*0.75)]:.1f}",
            f"{s[int(n*0.95)]:.1f}",
        ]
        print("| " + " | ".join(row) + " |")


def main() -> int:
    meta_path = Path(sys.argv[1])
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    crs = meta.get("candidate_reports", [])

    candidates = []
    for cr in crs:
        label = cr["label"]
        report_path = cr["path"]
        if not Path(report_path).exists():
            print(f"SKIP {label}: {report_path} not found", file=sys.stderr)
            continue
        data = analyze_report(report_path)

        sums = data["sums"]
        overalls = data["overalls"]
        durations = data["per_case_durations"]

        candidates.append({
            "label": label,
            "valid": data["valid"],
            "sums": sums,
            "overalls": overalls,
            "per_criterion": data["per_criterion"],
            "sum_mean": mean(sums) if sums else 0,
            "sum_std": stdev(sums) if len(sums) > 1 else 0,
            "sum_min": min(sums) if sums else 0,
            "sum_max": max(sums) if sums else 0,
            "overall_mean": mean(overalls) if overalls else 0,
            "criterion_means": {
                k: mean(data["per_criterion"][k]) if data["per_criterion"][k] else 0
                for k in CRITERIA
            },
            "lat_mean_ms": mean(durations) if durations else 0,
            "lat_med_ms": median(durations) if durations else 0,
            "agg_duration_ms": data["agg_duration_ms"],
        })

    # Sort by sum_mean descending
    candidates.sort(key=lambda c: -c["sum_mean"])

    format_table(candidates)

    print("\n=== ИТОГОВЫЙ РЕЙТИНГ (по сумме 7 критериев) ===\n")
    for i, c in enumerate(candidates, 1):
        print(f"  {i}. {c['label']:15s}  Σ={c['sum_mean']:.2f}/28  Overall={c['overall_mean']:.3f}/5  Lat={c['lat_mean_ms']:.0f}ms  Valid={c['valid']}")

    print("\n=== ПРОМПТ: почему все так хорошо? ===")
    print("  Prompt: prompts/code-explanation-judge.md")
    print("  7 criteria, each 0-4 (max sum = 28)")
    print("  Scoring: 4='excellent; materially correct and useful'")
    print("  Проблема: дескрипторы размытые, нет penalty за мелкие недочеты.")
    print("  Judge-модель (Gemini Flash Lite) — того же класса, что candidates,")
    print("  поэтому склонна ставить 4.0 даже при небольших неточностях.")
    print("  Референс — короткая docstring (1 предложение), трудно ошибиться.")
    print("  Реальные различия видны ТОЛЬКО по сумме (µ ≠ 28) и по P5/P25.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
