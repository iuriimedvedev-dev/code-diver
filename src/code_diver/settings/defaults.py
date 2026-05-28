from __future__ import annotations

from pathlib import Path


class Defaults:
    CONFIG_PATH = Path("code-diver.yml")
    ROOT = Path(".")
    ARTIFACT = Path(".code-diver/index.json")
    GRAPH_ARTIFACT = Path(".code-diver/graph.json")
    DATASET = Path("datasets/sample_eval.jsonl")

    STORAGE_PROVIDER = "json"
    QDRANT_URL = "http://localhost:6333"
    QDRANT_COLLECTION = "code_diver"
    QDRANT_API_KEY_ENV = "QDRANT_API_KEY"
    QDRANT_BATCH_SIZE = 64

    EMBEDDING_PROVIDER = "gemini"
    EMBEDDING_MODEL = "gemini-embedding-001"
    EMBEDDING_DIMENSIONS = 768
    EMBEDDING_BATCH_SIZE = 32
    HASH_DIMENSIONS = 256
    HASH_MODEL = "hash-token-v1"

    PI_BINARY = "pi"
    PI_EXTENSION = Path(".pi/extensions/code-diver-rag.ts")
    PI_PROMPT_TEMPLATE = Path(".pi/prompts/code-diver-rag.md")
    PI_PROVIDER = "google"
    PI_MODEL = "gemini-3-flash-preview"

    GENERATION_PROVIDER = "gemini"
    GENERATION_MODEL = "gemini-3-flash-preview"
    GENERATION_TEMPERATURE = 0.1
    GENERATION_THINKING_BUDGET = 1024

    INDEXING_MODE = "scanner"
    AI_INDEX_MAX_FILES = 40
    AI_INDEX_MAX_ITEMS = 80
    AI_INDEX_MAX_CONTEXT_CHARS = 60000
    AI_INDEX_TREE_DEPTH = 4
    AI_INDEX_TREE_LIMIT = 500
    AI_INDEX_DISCOVERY_LIMIT = 200
    AI_INDEX_DISCOVERY_PATTERNS = [
        "class ",
        "def ",
        "async def ",
        "function ",
        "interface ",
        "type ",
        "struct ",
        "enum ",
        "impl ",
        "fn ",
        "export ",
        "module ",
        "package ",
    ]

    MAX_FILE_BYTES = 1_000_000
    CHUNK_LINES = 120
    SEARCH_LIMIT = 10
    PREVIEW_LINES = 8
    RECURSIVE_ROUNDS = 2
    RECURSIVE_BRANCH_LIMIT = 3
    RECURSIVE_PER_ROUND_LIMIT = 5
    GRAPH_EXPANSION_DEPTH = 1
    GRAPH_NEIGHBOR_LIMIT = 20

    UI_COLOR = True
    UI_PAGER = "auto"
    UI_LINKS = True
    EDITOR_COMMAND = "code"
    EDITOR_ARGS = ["-g", "{path}:{line}"]

    EXPERIMENT_SUITE = "local"
    EXPERIMENT_STRATEGIES = ["vector", "recursive", "graph"]

    METRICS_ENABLED = False
    CLICKHOUSE_URL = "http://localhost:8123"
    CLICKHOUSE_DATABASE = "code_diver"
    CLICKHOUSE_USERNAME = "code_diver"
    CLICKHOUSE_PASSWORD = "code_diver"
    CLICKHOUSE_METRICS_TABLE = "rag_eval_metrics"
    CLICKHOUSE_CASES_TABLE = "rag_eval_cases"
    CLICKHOUSE_TIMEOUT_SECONDS = 10.0
    CLICKHOUSE_RETENTION_DAYS = 30
