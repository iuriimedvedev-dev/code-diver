
import sys
from pathlib import Path
from time import perf_counter
from code_diver.config import ConfigLoader
from code_diver.env import EnvFileLoader
from code_diver.cli import make_vector_store, make_embedding_provider, make_retrieval_strategy

def main():
    config_path = Path("configs/intellij/intellij-h46-preserve-top.yml")
    config = ConfigLoader().load(config_path)
    EnvFileLoader().load(config.env_file.path, config.env_file.override)
    
    print("Making vector store...")
    vector_store = make_vector_store(config)
    
    print("Making embedding provider...")
    provider = make_embedding_provider(config, vector_store.metadata())
    
    print("Making retrieval strategy...")
    strategy = make_retrieval_strategy(config, provider, vector_store)
    
    print("Running search 1...")
    start = perf_counter()
    results = strategy.search("Where is the main entry point?", limit=20)
    end = perf_counter()
    print(f"Found {len(results)} results in {end - start:.2f}s")

    print("Running search 2...")
    start = perf_counter()
    results = strategy.search("How to handle project opening?", limit=20)
    end = perf_counter()
    print(f"Found {len(results)} results in {end - start:.2f}s")

if __name__ == "__main__":
    main()
