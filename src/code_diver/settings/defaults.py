from __future__ import annotations

from pathlib import Path


class Defaults:
    CONFIG_PATH = Path("code-diver.yml")
    ENV_FILE = Path(".env")
    ROOT = Path(".")
    ARTIFACT = Path(".code-diver/index.json")
    GRAPH_ARTIFACT = Path(".code-diver/graph.json")
    TRACE_ARTIFACT = Path(".code-diver/traces/indexing.jsonl")
    DATASET = Path("datasets/sample_eval.jsonl")
    EVALUATION_WORKERS = 1

    STORAGE_PROVIDER = "json"
    QDRANT_URL = "http://localhost:6333"
    QDRANT_COLLECTION = "code_diver"
    QDRANT_API_KEY_ENV = "QDRANT_API_KEY"
    QDRANT_BATCH_SIZE = 256

    EMBEDDING_PROVIDER = "gemini"
    EMBEDDING_MODEL = "gemini-embedding-2"
    EMBEDDING_DIMENSIONS = 768
    EMBEDDING_BATCH_SIZE = 32
    EMBEDDING_WORKERS = 1
    EMBEDDING_MAX_INPUT_CHARS = None
    EMBEDDING_RETRY_ATTEMPTS = 3
    EMBEDDING_RETRY_DELAY_SECONDS = 20.0
    EMBEDDING_DOCUMENT_PREFIX = None
    EMBEDDING_QUERY_PREFIX = "task: code retrieval | query: "
    OPENAI_EMBEDDING_MODEL = "text-embedding-3-large"
    OPENAI_EMBEDDING_DIMENSIONS = 3072
    HASH_DIMENSIONS = 256
    HASH_MODEL = "hash-token-v1"

    PI_BINARY = "pi"
    PI_EXTENSION = Path(".pi/extensions/code-diver-rag.ts")
    PI_PROMPT_TEMPLATE = Path(".pi/prompts/code-diver-rag.md")
    PI_PROVIDER = "google"
    PI_MODEL = "google/gemini-3.5-flash"
    PI_TIMEOUT_SECONDS = 180
    PI_SESSION_DIR = Path(".code-diver/pi-sessions")

    GENERATION_PROVIDER = "gemini"
    GENERATION_MODEL = "gemini-3.5-flash"
    GENERATION_FALLBACK_MODELS = ["gemini-3-flash-preview", "gemini-2.5-flash"]
    GENERATION_TEMPERATURE = 0.1
    GENERATION_THINKING_BUDGET = 1024
    GENERATION_API_VERSION = "v1alpha"
    GENERATION_TIMEOUT_MS = 20_000
    GENERATION_MAX_TOKENS = None
    GENERATION_RETRY_ATTEMPTS = 5
    GENERATION_RETRY_BASE_DELAY_SECONDS = 2.0
    GENERATION_RETRY_MAX_DELAY_SECONDS = 45.0
    VERTEX_PROVIDER = "vertex"
    VERTEX_LOCATION = "global"
    OPENAI_GENERATION_MODEL = "gpt-5.1"
    OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
    OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
    OPENAI_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"
    LOCAL_OPENAI_BASE_URL = "http://127.0.0.1:1234/v1"
    OPENAI_TIMEOUT_SECONDS = 60.0

    INDEXING_MODE = "scanner"
    INDEXING_PROGRESS = False
    TRACE_ENABLED = True
    TRACE_INCLUDE_PROMPTS = True
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
    LINE_CHUNKS = True
    CHUNK_LINES = 120
    STRUCTURAL_CHUNKS = False
    SYMBOL_CHUNKS = False
    SYMBOL_BODY = True
    FILE_SUMMARY_CHUNKS = False
    FILE_MANIFEST_CHUNKS = False
    MAX_SYMBOLS_PER_FILE = None
    SEARCH_LIMIT = 10
    PREVIEW_LINES = 8
    RECURSIVE_ROUNDS = 2
    RECURSIVE_BRANCH_LIMIT = 3
    RECURSIVE_PER_ROUND_LIMIT = 5
    HYBRID_CANDIDATE_LIMIT = 80
    HYBRID_LEXICAL_CANDIDATE_LIMIT = 80
    HYBRID_VECTOR_WEIGHT = 0.6
    HYBRID_LEXICAL_WEIGHT = 0.18
    HYBRID_PATH_WEIGHT = 0.12
    HYBRID_SYMBOL_WEIGHT = 0.05
    HYBRID_SYMBOL_MATCH_WEIGHT = 0.0
    HYBRID_GRAPH_WEIGHT = 0.05
    HYBRID_FILE_VOTE_WEIGHT = 0.0
    HYBRID_VECTOR_KIND_LIMITS = {}
    HYBRID_VECTOR_KIND_MULTIPLIERS = {}
    HYBRID_GRAPH_DEPTH = 1
    HYBRID_GRAPH_NEIGHBOR_LIMIT = 20
    HYBRID_LEXICAL_SCORING = "coverage"
    HYBRID_FUSION = "weighted"
    HYBRID_RRF_K = 60
    HYBRID_BM25_K1 = 1.2
    HYBRID_BM25_B = 0.75
    HYBRID_ROUTING_ENABLED = False
    HYBRID_PRESERVE_VECTOR_TOP = False
    HYBRID_VECTOR_TOP_SCORE_MARGIN = 0.0
    HYBRID_ITEM_KIND_WEIGHTS = {}
    HYBRID_MIN_TOKEN_LENGTH = 3
    HYBRID_STOP_WORDS = [
        "where",
        "what",
        "which",
        "this",
        "that",
        "there",
        "here",
        "with",
        "from",
        "into",
        "code",
        "file",
        "files",
        "class",
        "function",
        "method",
        "handled",
        "created",
        "creates",
        "used",
        "uses",
    ]
    LLM_RERANK_CANDIDATE_LIMIT = 40
    LLM_RERANK_MAX_PREVIEW_CHARS = 700
    LLM_RERANK_MODE = "file_first"
    LLM_RERANK_INCLUDE_REASONS = True
    LLM_RERANK_PRESERVE_TOP_CANDIDATE = False
    LLM_RERANK_PRESERVE_TOP_SCORE_MARGIN = 0.0
    LLM_RERANK_RETRY_ATTEMPTS = 3
    LLM_RERANK_RETRY_BASE_DELAY_SECONDS = 1.0
    LLM_RERANK_RETRY_MAX_DELAY_SECONDS = 8.0
    CROSS_ENCODER_RERANK_PROVIDER = "llama_cpp"
    CROSS_ENCODER_RERANK_MODEL = "Qwen3-Reranker-0.6B"
    CROSS_ENCODER_RERANK_URL = "http://127.0.0.1:8080/v1/rerank"
    CROSS_ENCODER_RERANK_CANDIDATE_LIMIT = 40
    CROSS_ENCODER_RERANK_MAX_DOCUMENT_CHARS = 900
    CROSS_ENCODER_RERANK_TIMEOUT_MS = 20_000
    CROSS_ENCODER_RERANK_PRESERVE_TOP_CANDIDATE = False
    CROSS_ENCODER_RERANK_PRESERVE_TOP_SCORE_MARGIN = 0.0
    GRAPH_EXPANSION_DEPTH = 1
    GRAPH_NEIGHBOR_LIMIT = 20
    GRAPH_AST_ENABLED = True
    GRAPH_REFERENCE_EDGES_ENABLED = True
    GRAPH_CALL_EDGES_ENABLED = True

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
