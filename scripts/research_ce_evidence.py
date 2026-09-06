"""Bounded, sequential CE research; never changes production configuration."""
from __future__ import annotations

import argparse
import faulthandler
import hashlib
import json
import math
import re
import signal
import time
from dataclasses import replace
from pathlib import Path

BUDGET = 850
CAP = 24
FLOOR = 0.3
EXPANDED = 2400
STOP = set("where is are does the a an of for and in to implemented managed handled".split())


def tokens(text):
    return set(re.findall(r"[a-z0-9]+", re.sub(r"([a-z])([A-Z])", r"\1 \2", text).lower())) - STOP


def document(path, source, query, fragment=False, budget=BUDGET):
    if budget < 1:
        raise ValueError("budget must be positive")
    signature = next((line.strip() for line in source.splitlines()
                      if re.search(r"\b(class|interface|object|fun|enum)\b", line)), "")[:160]
    prefix = f"path: {path}\nsignature: {signature}\nsource:\n"
    room = max(0, budget - len(prefix))
    start = 0
    if fragment and room:
        terms = tokens(query)
        offsets = [0] + [m.end() for m in re.finditer("\n", source)]
        start = max(offsets, key=lambda pos: len(terms & tokens(source[pos:pos + room])))
    return (prefix + source[start:start + room])[:budget], start


def retry_indices(scores, cap=CAP):
    return [i for i, score in enumerate(scores) if score < FLOOR][:cap]


def merge_scores(first, indices, second):
    merged = list(first)
    for i, score in zip(indices, second, strict=True):
        merged[i] = max(first[i], score)
    return merged


def metrics(paths, scores, expected):
    order = sorted(range(len(paths)), key=lambda i: (-scores[i], i))[:10]
    ranked = [paths[i] for i in order]
    gold = {p for p in expected if not p.startswith("glob:") and not any(ch in p for ch in "*?[")}
    relevant = [int(p in gold) for p in ranked]
    ranks = [i + 1 for i, hit in enumerate(relevant) if hit]
    ideal = sum(1 / math.log2(i + 2) for i in range(min(10, len(gold))))
    return {"hit10": int(bool(ranks)), "hit1": relevant[0] if relevant else 0,
            "mrr10": 1 / ranks[0] if ranks else 0,
            "recall10": len(set(ranked) & gold) / len(gold) if gold else None,
            "ndcg10": sum(h / math.log2(i + 2) for i, h in enumerate(relevant)) / ideal if ideal else None,
            "ranked": ranked}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cases", type=int, choices=(1, 2, 8, 10, 12), default=2)
    parser.add_argument("--seconds", type=int, default=240)
    parser.add_argument("--experiment", choices=("R1", "R2", "both"), default="both")
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("refusing to overwrite output")
    args.out.mkdir(parents=True)
    faulthandler.dump_traceback_later(min(args.seconds + 5, 300), exit=True)
    print("initializing imports", flush=True)
    from replay_pool_recall import build_probe_strategy, close_vector_store, load_config
    from code_diver.reranking import RerankProviderFactory
    from code_diver.reranking.cross_encoder_document_builder import build_cross_encoder_document

    started = time.perf_counter()
    def expired(*_):
        raise TimeoutError("research wall-time budget exhausted")
    signal.signal(signal.SIGALRM, expired)
    signal.alarm(min(args.seconds, 300))
    datasets = [Path("datasets/intellij_eval_where_only.jsonl"), Path("datasets/intellij_eval_mech150.jsonl")]
    rows = []
    for dataset in datasets:
        cases = [json.loads(line) for line in dataset.read_text().splitlines() if line.strip()]
        for row in cases[:args.cases // 2 or 1]:
            rows.append(dict(row, dataset=str(dataset)))
    rows = rows[:args.cases]
    configs = [Path("configs/intellij/intellij-h66b-champion.yml"), Path("configs/intellij/intellij-h55-ce-file-head.yml")]
    model = Path(".code-diver/models/rerankers/qwen3-reranker-0.6b/Qwen3-Reranker-0.6B-Q4_K_M.gguf")
    hashes = {str(p): digest(p) for p in datasets + configs + [Path("uv.lock"), Path(__file__)]}
    print("hashing model", flush=True)
    if model.exists():
        hashes[str(model)] = digest(model)
    report = {"hashes": hashes, "selection": rows, "results": [], "errors": [],
              "policy": "exact_only; raw CE top10; no preserve-top intervention",
              "budget": {"candidates": 34, "chars": BUDGET, "retry_chars": EXPANDED, "retry_cap": CAP}}
    (args.out / "results.json").write_text(json.dumps(report, indent=2))
    try:
        for experiment, config_path in zip(("R1", "R2"), configs):
            if args.experiment not in (experiment, "both"):
                continue
            config = load_config(config_path)
            ce = replace(config.cross_encoder_rerank, second_pass_enabled=False, timeout_ms=15000)
            config = replace(config, cross_encoder_rerank=ce)
            print("building strategy", experiment, flush=True)
            strategy, _, store = build_probe_strategy(config)
            provider = RerankProviderFactory().create(ce)
            try:
                for row in rows:
                    case = {"experiment": experiment, "case_id": row["id"], "dataset": row["dataset"], "calls": []}
                    report["results"].append(case)
                    query = row["query"]
                    tick = time.perf_counter()
                    print("retrieving", experiment, row["id"], flush=True)
                    candidates = strategy.search(query, 34)[:34]
                    case["retrieval_seconds"] = time.perf_counter() - tick
                    paths = [str(c.item.path) for c in candidates]
                    case["pool"] = paths
                    case["expected"] = row["expected"]
                    case["arms"] = {}
                    if not candidates:
                        raise RuntimeError("empty candidate pool")
                    def score(arm, docs):
                        tick = time.perf_counter()
                        call = {"arm": arm, "documents": docs, "chars": sum(map(len, docs)), "tokens": None}
                        case["calls"].append(call)
                        try:
                            result = provider.rerank(query, docs, len(docs))
                            values = {s.index: s.score for s in result}
                            if set(values) != set(range(len(docs))):
                                raise RuntimeError("incomplete CE scores")
                            call["scores"] = [values[i] for i in range(len(docs))]
                            return call["scores"]
                        except Exception as exc:
                            call["error"] = repr(exc)
                            raise
                        finally:
                            call["seconds"] = time.perf_counter() - tick
                    if experiment == "R1":
                        docs = [build_cross_encoder_document(c, ce, config.root) for c in candidates]
                        first = score("single", docs)
                        case["arms"]["single"] = metrics(paths, first, row["expected"])
                        indices = retry_indices(first)
                        case["retry_indices"] = indices
                        expanded = replace(ce, max_document_chars=EXPANDED)
                        for arm, selected in (("selective", indices), ("base_rank_budget_control", list(range(len(indices))))):
                            docs = [build_cross_encoder_document(candidates[i], expanded, config.root) for i in selected]
                            second = score(arm, docs) if docs else []
                            case["arms"][arm] = metrics(paths, merge_scores(first, selected, second), row["expected"])
                    else:
                        sources = []
                        case["provenance"] = []
                        for path in paths:
                            file = (config.root / path).resolve()
                            file.relative_to(config.root.resolve())
                            source = file.read_text(encoding="utf-8", errors="replace")
                            sources.append(source)
                            case["provenance"].append({"path": path, "sha256": digest(file)})
                        for arm in ("head", "fragment"):
                            built = [document(p, s, query, arm == "fragment") for p, s in zip(paths, sources)]
                            case[arm + "_offsets"] = [offset for _, offset in built]
                            case["arms"][arm] = metrics(paths, score(arm, [doc for doc, _ in built]), row["expected"])
                    (args.out / "results.json").write_text(json.dumps(report, indent=2))
                    print(experiment, row["id"], case["arms"], flush=True)
            finally:
                close_vector_store(store)
    except Exception as exc:
        report["errors"].append(repr(exc))
        print(repr(exc), flush=True)
    finally:
        signal.alarm(0)
        faulthandler.cancel_dump_traceback_later()
        report["seconds"] = time.perf_counter() - started
        (args.out / "results.json").write_text(json.dumps(report, indent=2))
    return int(bool(report["errors"]))


if __name__ == "__main__":
    raise SystemExit(main())