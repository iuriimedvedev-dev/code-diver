"""Dump WHERE-79 retrieval pool from the H-53 token-budget collection."""
import json
from pathlib import Path
from time import perf_counter
from code_diver.config import ConfigLoader
from code_diver.env import EnvFileLoader
from code_diver.cli import make_vector_store, make_embedding_provider, make_retrieval_strategy

CONFIG_PATH = Path("configs/intellij/intellij-h53-token-budget.yml")
DATASET_PATH = Path("datasets/intellij_eval_where_only.jsonl")
OUTPUT_PATH = Path("/tmp/where79_h53_pool.jsonl")

def main():
    config = ConfigLoader().load(CONFIG_PATH)
    EnvFileLoader().load(config.env_file.path, config.env_file.override)

    print(f"Making retrieval strategy for {config.search.strategy}...")
    vector_store = make_vector_store(config)
    provider = make_embedding_provider(config, vector_store.metadata())
    strategy = make_retrieval_strategy(config, provider, vector_store)

    print(f"Loading dataset from {DATASET_PATH}...")
    cases = []
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                cases.append(json.loads(line))

    print(f"Processing {len(cases)} cases...")
    start_all = perf_counter()

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for i, case in enumerate(cases):
            query_id = case.get("id")
            query_text = case.get("query")
            gold_paths = case.get("expected", [])

            print(f"[{i+1}/{len(cases)}] {query_text[:60]}...")
            start_case = perf_counter()
            results = strategy.search(query_text, limit=20)
            end_case = perf_counter()

            candidates = [{"path": res.item.path, "score": float(res.score)} for res in results]

            out_row = {
                "query_id": query_id,
                "query_text": query_text,
                "candidates": candidates,
                "gold_paths": gold_paths,
                "duration_ms": (end_case - start_case) * 1000
            }
            f.write(json.dumps(out_row) + "\n")
            f.flush()

    end_all = perf_counter()
    print(f"Finished in {end_all - start_all:.2f}s")
    print(f"Dump written to {OUTPUT_PATH}")

if __name__ == "__main__":
    main()