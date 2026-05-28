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
    EMBEDDING_MODEL = "gemini-embedding-2"
    EMBEDDING_DIMENSIONS = 768
    EMBEDDING_BATCH_SIZE = 32
    HASH_DIMENSIONS = 256
    HASH_MODEL = "hash-token-v1"

    PI_BINARY = "pi"
    PI_EXTENSION = Path(".pi/extensions/code-diver-rag.ts")
    PI_PROMPT_TEMPLATE = Path(".pi/prompts/code-diver-rag.md")
    PI_PROVIDER = "google"
    PI_MODEL = "gemini-3.5-flash"

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
