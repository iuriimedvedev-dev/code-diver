
import json
import sys
from pathlib import Path
from time import perf_counter
from code_diver.config import ConfigLoader
from code_diver.env import EnvFileLoader
from code_diver.cli import make_vector_store, make_embedding_provider, make_retrieval_strategy

def main():
    config_path = Path("configs/intellij/intellij-h46-preserve-top.yml")
    dataset_path = Path("datasets/intellij_eval_where_only.jsonl")
    output_path = Path("/tmp/where79_h46_pool.jsonl")
    
    config = ConfigLoader().load(config_path)
    EnvFileLoader().load(config.env_file.path, config.env_file.override)
    
    print(f"Making retrieval strategy for {config.search.strategy}...")
    vector_store = make_vector_store(config)
    provider = make_embedding_provider(config, vector_store.metadata())
    strategy = make_retrieval_strategy(config, provider, vector_store)
    
    print(f"Loading dataset from {dataset_path}...")
    cases = []
    with open(dataset_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                cases.append(json.loads(line))
    
    print(f"Processing {len(cases)} cases...")
    start_all = perf_counter()
    
    with open(output_path, "w", encoding="utf-8") as f:
        for i, case in enumerate(cases):
            query_id = case.get("id")
            query_text = case.get("query")
            gold_paths = case.get("expected", [])
            
            print(f"[{i+1}/{len(cases)}] Query: {query_text[:50]}...")
            start_case = perf_counter()
            results = strategy.search(query_text, limit=20)
            end_case = perf_counter()
            
            candidates = []
            for res in results:
                candidates.append({
                    "path": res.item.path,
                    "score": float(res.score)
                })
            
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
    print(f"Dump written to {output_path}")

if __name__ == "__main__":
    main()
