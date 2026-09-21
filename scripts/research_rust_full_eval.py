#!/usr/bin/env python3
"""Resumable, sequential paired production evaluation; no builds or service management."""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import platform
import random
import select
import signal
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlsplit, urlunsplit
from unittest.mock import patch

from code_diver.services.dataset_loader import DatasetLoader
from code_diver.services.expected_path_matcher import ExpectedPathMatcher

OUT = Path("artifacts/research/2026-09-07_rust-full-eval")
CONFIG = Path("configs/intellij/intellij-h91a-meta-ranker.yml")
BIN = "native/code_diver_search_bin/target/release/code_diver_search_bin"
MODEL = "artifacts/ce_meta_ranker/ce_meta_ranker.lgb.txt"
DATASETS = {
    "full1065": "datasets/intellij_eval_1000.answer_sets.jsonl",
    "WHERE78": "datasets/intellij_eval_where_only.jsonl",
    "mech150": "datasets/intellij_eval_mech150.jsonl",
}
COMMAND = [BIN, "--server", "--catalog", "/tmp/rust_catalog.jsonl", "--graph",
           "/tmp/rust_graph.jsonl", "--model", MODEL, "--embedding-url",
           "http://localhost:8001/v1/embeddings", "--qdrant-url", "http://localhost:6333",
           "--ce-url", "http://localhost:18081/v1/rerank", "--retrieval-limit", "360",
           "--candidate-limit", "34", "--limit", "10"]
REQUEST_TIMEOUT = 180


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, default=str, ensure_ascii=False)


def append(path, row):
    with path.open("a", encoding="utf-8") as stream:
        stream.write(encoded(row) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def exclusive(path, value):
    with path.open("x", encoding="utf-8") as stream:
        stream.write(encoded(value) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def case_key(case):
    return hashlib.sha256(encoded([case.id, case.query, sorted(case.expected)]).encode()).hexdigest()


def workload():
    cases, memberships = {}, {}
    for label, path in DATASETS.items():
        loaded = DatasetLoader().load(Path(path))
        if label == "mech150":
            if len(loaded) != 229:
                raise ValueError("Expected mech file composition: 150 mechanical plus 79 WHERE")
            memberships["mech_file229"] = [case_key(case) for case in loaded]
            cases.update((case_key(case), dataclasses.asdict(case)) for case in loaded)
            loaded = [case for case in loaded if case.id.startswith(("config-", "path-", "symbol-"))]
        expected_count = {"full1065": 1065, "WHERE78": 78, "mech150": 150}[label]
        if len(loaded) != expected_count:
            raise ValueError(f"{label}: expected {expected_count}, got {len(loaded)}")
        memberships[label] = [case_key(case) for case in loaded]
        if len(set(memberships[label])) != len(loaded):
            raise ValueError(f"Duplicate exact cases in {label}")
        cases.update((case_key(case), dataclasses.asdict(case)) for case in loaded)
    return cases, memberships


def schedule(keys):
    rng = random.Random(42)
    keys = list(keys)
    rng.shuffle(keys)
    result = []
    for key in keys:
        arms = ["python", "rust"]
        rng.shuffle(arms)
        result.extend((key, arm) for arm in arms)
    return result


def quality(paths, expected, failed=False):
    labels = [int(ExpectedPathMatcher().matches_any(path, expected)) for path in paths[:10]]
    rank = next((i + 1 for i, label in enumerate(labels) if label), None)
    return {"labels": labels, "first_relevant_rank": rank, "quality": int(not failed),
            "hit_at_10": int(rank is not None and not failed),
            "rr": 1 / rank if rank is not None and not failed else 0.0}


def load_completed(path, planned):
    rows, pending = {}, {}
    if not path.exists():
        return rows, pending
    for line in path.read_text().splitlines():
        event = json.loads(line)
        index = event["index"]
        if tuple(event["pair"]) != tuple(planned[index]):
            raise ValueError("Checkpoint schedule mismatch")
        if event["event"] == "begin":
            if index in pending or index in rows:
                raise ValueError("Duplicate attempt")
            pending[index] = event
        else:
            if index not in pending or index in rows:
                raise ValueError("Result without unique begin")
            pending.pop(index)
            rows[index] = event
    return rows, pending


def percentile(values, q):
    values = sorted(values)
    return values[max(0, math.ceil(q * len(values)) - 1)] if values else None


def summarize(rows, memberships):
    output = {}
    for label, keys in memberships.items():
        arms = {}
        for arm in ("python", "rust"):
            selected = [r for r in rows.values() if r["pair"][0] in keys and r["pair"][1] == arm]
            n = len(selected)
            latency = [r["wall_ms"] for r in selected if r["wall_ms"] is not None]
            arms[arm] = {"attempted": n, "expected": len(keys),
                         "failures": sum(not r["quality"] for r in selected),
                         "hit_at_10": sum(r["hit_at_10"] for r in selected) / n if n else None,
                         "mrr_at_10": sum(r["rr"] for r in selected) / n if n else None,
                         "latency_observed": len(latency),
                         "p50_ms": percentile(latency, .5), "p95_ms": percentile(latency, .95)}
        paired = {}
        for r in rows.values():
            if r["pair"][0] in keys:
                paired.setdefault(r["pair"][0], {})[r["pair"][1]] = r
        complete = [p for p in paired.values() if len(p) == 2]
        arms["paired"] = {"n": len(complete), **{
            f"rust_minus_python_{metric}": sum(p["rust"][metric] - p["python"][metric] for p in complete) / len(complete) if complete else None
            for metric in ("hit_at_10", "rr")}}
        output[label] = arms
    return output


def get_json(url):
    with urllib.request.urlopen(url, timeout=15) as response:
        return json.load(response)


def config(args=None):
    from code_diver.config import ConfigLoader
    if args is None:
        args = parse_args(["--run", "defaults"])
    c = ConfigLoader().load(CONFIG)
    return dataclasses.replace(
        c, embedding=dataclasses.replace(c.embedding, url=args.embedding_url, runtime_mode=args.embedding_runtime_mode),
        storage=dataclasses.replace(c.storage, qdrant=dataclasses.replace(c.storage.qdrant, url=args.qdrant_url)),
        cross_encoder_rerank=dataclasses.replace(c.cross_encoder_rerank, url=args.python_ce_url),
        graph=dataclasses.replace(c.graph, artifact=Path(".code-diver/intellij-h37-jvm-graph.json")))


def native_command(c, rust_ce_url):
    command = list(COMMAND)
    for flag, value in (("--embedding-url", c.embedding.url), ("--qdrant-url", c.storage.qdrant.url),
                        ("--ce-url", rust_ce_url)):
        command[command.index(flag) + 1] = value
    return command


def freeze(c, cases, memberships, command=None):
    files = [str(CONFIG), BIN, MODEL, "artifacts/ce_meta_ranker/ranker.json",
             "/tmp/rust_catalog.jsonl", "/tmp/rust_graph.jsonl", str(c.graph.artifact),
             "scripts/research_rust_full_eval.py", "uv.lock", *DATASETS.values()]
    source = subprocess.check_output(["git", "ls-files", "src", "native/code_diver_search_bin/src"], text=True).splitlines()
    hashes = {path: digest(path) for path in files + source if Path(path).is_file()}
    if hashes[BIN] != "ab54768cac4cc91955ee0e0a7319f4dcbe6174bf1ad343f2c6a37a358721b58c":
        raise ValueError("Unexpected native binary")
    if hashes[MODEL] != "8dcadfdc02b050fd35ebafca7f436c822859ff38cfeba4f9bd1203abc90e5010":
        raise ValueError("Unexpected model")
    return {"hashes": hashes, "effective_config": json.loads(encoded(dataclasses.asdict(c))),
            "native_command": list(COMMAND if command is None else command), "python": sys.version, "platform": platform.platform(),
            "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            "cases": cases, "memberships": memberships, "schedule": schedule(cases),
            "seed": 42, "boundary": "persistent request wall excluding both initializations"}


def reject_start(*args, **kwargs):
    raise RuntimeError("Evaluation forbids service starts")


def validate_runtime(c):
    from code_diver.providers.embedding_provider_builder import local_embedding_profile_key
    c.embedding.validate_runtime_mode()
    if c.embedding.runtime_mode != "external" and local_embedding_profile_key(c) is not None:
        raise RuntimeError("Embedding config would invoke runtime management; use --embedding-runtime-mode external")


def check_manifest(path, identity):
    if path.exists():
        if json.loads(path.read_text()) != json.loads(encoded(identity)):
            raise ValueError("Frozen identities changed; refusing mixed evidence")
    else:
        exclusive(path, identity)


def endpoint_urls(c, rust_ce_url):
    def models(url):
        parts = urlsplit(url)
        return urlunsplit(parts._replace(path=parts.path.rsplit("/", 1)[0] + "/models"))
    return {"qdrant": c.storage.qdrant.url.rstrip("/") + "/collections/" + c.storage.qdrant.collection,
            "embedding": models(c.embedding.url), "python_ce": models(c.cross_encoder_rerank.url),
            "rust_ce": models(rust_ce_url)}


class Native:
    def __init__(self, directory, segment, command=None):
        log_path = directory / f"native-{segment}.stderr"
        self.writer = log_path.open("x")
        self.log = log_path.open()
        self.offset = 0
        started = time.perf_counter()
        self.proc = subprocess.Popen(COMMAND if command is None else command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=self.writer, text=True, bufsize=1)
        deadline = time.monotonic() + REQUEST_TIMEOUT
        while time.monotonic() < deadline:
            text = self.messages()
            if "Server mode: reading queries" in text:
                self.init_ms = (time.perf_counter() - started) * 1000
                return
            if self.proc.poll() is not None:
                raise RuntimeError(f"Native init failed: {text}")
            time.sleep(.02)
        self.close()
        raise TimeoutError("Native initialization timed out")

    def messages(self):
        self.log.seek(self.offset)
        text = self.log.read()
        self.offset = self.log.tell()
        return text

    def search(self, query):
        self.proc.stdin.write(encoded({"query": query, "limit": 10}) + "\n")
        self.proc.stdin.flush()
        if not select.select([self.proc.stdout], [], [], REQUEST_TIMEOUT)[0]:
            self.close()
            raise TimeoutError("Native request timed out")
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("Native server exited: " + self.messages())
        result = json.loads(line)
        if result["query"] != query:
            raise ValueError("Native protocol query mismatch")
        return [r["path"] for r in result["results"]], result["timings"]

    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()


def timed_out(signum, frame):
    raise TimeoutError("Python request exceeded 180 seconds")


class Warnings(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def endpoint_url(value):
    try:
        parts = urlsplit(value)
        if (parts.scheme not in ("http", "https") or not parts.hostname or parts.username is not None
                or parts.password is not None or parts.query or parts.fragment
                or "?" in value or "#" in value or any(char.isspace() for char in value)
                or (parts.port is not None and parts.port < 1)):
            raise ValueError()
    except ValueError:
        raise argparse.ArgumentTypeError("Expected an HTTP(S) URL without credentials, query or fragment") from None
    return value


def positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("Must be positive")
    return number


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--seconds", type=positive_int, default=3000)
    parser.add_argument("--max-pairs", type=positive_int)
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--embedding-url", type=endpoint_url, default="http://localhost:8001/v1/embeddings")
    parser.add_argument("--qdrant-url", type=endpoint_url, default="http://localhost:6333")
    parser.add_argument("--python-ce-url", type=endpoint_url, default="http://localhost:18081/v1/rerank")
    parser.add_argument("--rust-ce-url", type=endpoint_url, default="http://localhost:18081/v1/rerank")
    parser.add_argument("--embedding-runtime-mode", choices=("managed", "external"), default="managed")
    args = parser.parse_args(argv)
    if Path(args.run).name != args.run or args.run in (".", ".."):
        parser.error("Run must be a directory name other than '.' or '..'")
    return args


def main():
    args = parse_args()
    c = config(args)
    validate_runtime(c)
    command = native_command(c, args.rust_ce_url)
    directory = OUT / args.run
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "manifest.json"
    cases, memberships = workload()
    identity = freeze(c, cases, memberships, command)
    check_manifest(manifest_path, identity)
    planned = identity["schedule"]
    journal = directory / "results.jsonl"
    rows, pending = load_completed(journal, planned)
    for index, event in pending.items():
        row = {**event, "event": "result", "paths": [], "wall_ms": None,
               "internal_timings": {}, "error": "Interrupted attempt; unknown latency",
               **quality([], cases[event["pair"][0]]["expected"], True)}
        append(journal, row)
        rows[index] = row
    segment = str(time.time_ns())
    if args.summary_only:
        summary = summarize(rows, memberships)
        exclusive(directory / f"summary-{segment}.json", summary)
        print(encoded(summary), flush=True)
        return
    urls = endpoint_urls(c, args.rust_ce_url)
    endpoint_info = {"urls": urls, "qdrant": get_json(urls["qdrant"])}
    for name in ("embedding", "python_ce", "rust_ce"):
        try:
            endpoint_info[name] = get_json(urls[name])
        except Exception as exc:
            endpoint_info[name] = {"identity_error": str(exc)}
    exclusive(directory / f"endpoints-{segment}.json", endpoint_info)
    from code_diver.cli import make_vector_store
    from code_diver.providers.embedding_provider_builder import make_embedding_provider
    from code_diver.strategies.retrieval_strategy_builder import make_retrieval_strategy
    start = time.perf_counter()
    with patch("code_diver.runtime.qdrant_runtime_manager.QdrantRuntimeManager._compose_up", reject_start):
        store = make_vector_store(c)
    provider = make_embedding_provider(c)
    strategy = make_retrieval_strategy(c, provider, store)
    python_init_ms = (time.perf_counter() - start) * 1000
    if getattr(strategy, "_ce_meta_ranker_booster", None) is None:
        raise RuntimeError("Python meta-ranker did not load")
    native = Native(directory, segment, command)
    exclusive(directory / f"init-{segment}.json", {"python_ms": python_init_ms, "rust_ms": native.init_ms,
                                                    "command": sys.argv, "timestamp": time.time()})
    signal.signal(signal.SIGALRM, timed_out)
    warnings = Warnings()
    logging.getLogger("code_diver").addHandler(warnings)

    def execute(key, arm):
        case = cases[key]
        paths, internal, error, messages = [], {}, None, ""
        warnings.messages.clear()
        before = getattr(strategy, "rerank_failure_count", 0)
        started = time.perf_counter()
        try:
            if arm == "rust":
                paths, internal = native.search(case["query"])
            else:
                signal.alarm(REQUEST_TIMEOUT)
                paths = [str(r.item.path) for r in strategy.search(case["query"], 10)]
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        finally:
            signal.alarm(0)
        wall = (time.perf_counter() - started) * 1000
        if arm == "rust":
            messages = native.messages()
            if "WARNING" in messages or "failed" in messages.lower():
                error = error or "Native fallback: " + messages
        elif getattr(strategy, "rerank_failure_count", 0) != before:
            error = error or "Python rerank fallback detected"
        if arm == "python" and any("fail" in m.lower() or "falling back" in m.lower() for m in warnings.messages):
            error = error or "Python fallback warning: " + "; ".join(warnings.messages)
        return {"paths": paths[:10], "internal_timings": internal, "wall_ms": wall,
                "error": error, "native_messages": messages, "python_warnings": list(warnings.messages),
                **quality(paths, case["expected"], error is not None)}

    try:
        warm_key = next(iter(cases))
        for arm in ("rust", "python"):
            warm = execute(warm_key, arm)
            append(directory / "warmup.jsonl", {"segment": segment, "pair": [warm_key, arm], **warm})
            if warm["error"]:
                raise RuntimeError("Warmup failed: " + warm["error"])
        deadline = time.monotonic() + args.seconds
        completed_pairs = 0
        for pair_start in range(0, len(planned), 2):
            if all(index in rows for index in (pair_start, pair_start + 1)):
                continue
            if time.monotonic() >= deadline or (args.max_pairs is not None and completed_pairs >= args.max_pairs):
                break
            for index in (pair_start, pair_start + 1):
                if index in rows:
                    continue
                key, arm = planned[index]
                event = {"event": "begin", "index": index, "pair": [key, arm], "segment": segment,
                         "id": cases[key]["id"], "query": cases[key]["query"], "started_at": time.time()}
                append(journal, event)
                row = {**event, "event": "result", **execute(key, arm)}
                append(journal, row)
                rows[index] = row
                print(f"{len(rows)}/{len(planned)} {arm} {row['id']} hit={row['hit_at_10']} rr={row['rr']:.3f} ms={row['wall_ms']:.0f} error={row['error']}", flush=True)
                if native.proc.poll() is not None:
                    raise RuntimeError("Native process exited; stop chunk, resume remaining attempts")
            completed_pairs += 1
    finally:
        native.close()
        store.close()
        summary = summarize(rows, memberships)
        exclusive(directory / f"summary-{segment}.json", summary)
        append(directory / "checkpoints.jsonl", {"segment": segment, "completed": len(rows),
                                                "total": len(planned), "next_indices": [i for i in range(len(planned)) if i not in rows][:2]})
        print(encoded(summary), flush=True)


if __name__ == "__main__":
    main()