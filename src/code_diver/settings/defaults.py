from __future__ import annotations

from pathlib import Path
from typing import ClassVar


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

    EMBEDDING_PROVIDER = "openai_compatible"
    EMBEDDING_MODEL = "google/embeddinggemma-300m"
    EMBEDDING_DIMENSIONS = 768
    EMBEDDING_BATCH_SIZE = 96
    EMBEDDING_WORKERS = 4
    EMBEDDING_MAX_INPUT_CHARS = 1200
    EMBEDDING_URL = "http://127.0.0.1:8001/v1/embeddings"
    EMBEDDING_API_KEY = None
    EMBEDDING_RETRY_ATTEMPTS = 3
    EMBEDDING_RETRY_DELAY_SECONDS = 20.0
    EMBEDDING_DOCUMENT_PREFIX = "title: none | text: "
    EMBEDDING_QUERY_PREFIX = "task: code retrieval | query: "
    OPENAI_EMBEDDING_MODEL = "text-embedding-3-large"
    OPENAI_EMBEDDING_DIMENSIONS = 3072
    HASH_DIMENSIONS = 256
    HASH_MODEL = "hash-token-v1"

    PI_BINARY = "npm"
    PI_LAUNCHER_ARGS: ClassVar[list[str]] = ["exec", "--", "pi"]
    PI_EXTENSION = Path(".pi/extensions/code-diver-rag.ts")
    PI_PROMPT_TEMPLATE = Path(".pi/prompts/code-diver-rag.md")
    PI_PROVIDER = "code-diver-local"
    PI_MODEL = "mlx-community/Qwen3.5-4B-OptiQ-4bit"
    PI_TIMEOUT_SECONDS = 180
    PI_SESSION_DIR = Path(".code-diver/pi-sessions")
    PI_REPO_CONTEXT_ENABLED = True
    PI_REPO_CONTEXT_MODE = "readme_summary"
    PI_REPO_CONTEXT_OUTPUT = Path(".code-diver/context/repository-context.md")
    PI_REPO_CONTEXT_INCLUDE_DOCS = True
    PI_REPO_CONTEXT_MAX_CHARS = 16_000
    PI_REPO_CONTEXT_DOCS_LIMIT = 8

    GENERATION_PROVIDER = "openai_compatible"
    GENERATION_MODEL = "mlx-community/Qwen3.5-4B-OptiQ-4bit"
    GENERATION_FALLBACK_MODELS: ClassVar[list[str]] = []
    GENERATION_TEMPERATURE = 0.0
    GENERATION_THINKING_BUDGET = None
    GENERATION_API_VERSION = None
    GENERATION_TIMEOUT_MS = 480_000
    GENERATION_MAX_TOKENS = 2048
    GENERATION_RETRY_ATTEMPTS = 5
    GENERATION_RETRY_BASE_DELAY_SECONDS = 2.0
    GENERATION_RETRY_MAX_DELAY_SECONDS = 45.0
    VERTEX_PROVIDER = "vertex"
    VERTEX_LOCATION = "global"
    VERTEX_BATCH_MODEL = "gemini-3.1-flash-lite"
    VERTEX_BATCH_LOCAL_DIR = Path(".code-diver/provider-tests")
    GEMINI_CLI_PROVIDER = "gemini_cli"
    GEMINI_CLI_BINARY = "gemini"
    GEMINI_CLI_APPROVAL_MODE = "plan"
    AGY_CLI_PROVIDER = "agy_cli"
    AGY_CLI_BINARY = "agy"
    AGY_CLI_MODEL = "Gemini 3.5 Flash (Low)"
    AGY_CLI_PRINT_TIMEOUT = "5m"
    ANTIGRAVITY_SDK_PROVIDER = "antigravity_sdk"
    ANTIGRAVITY_SDK_MODEL = "gemini-3.5-flash"
    ANTIGRAVITY_SDK_APP_DATA_DIR = Path("~/.gemini/antigravity-cli")
    OPENAI_GENERATION_MODEL = "gpt-5.1"
    OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
    OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
    OPENAI_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"
    LOCAL_OPENAI_BASE_URL = "http://127.0.0.1:8012/v1"
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
    AI_INDEX_DISCOVERY_PATTERNS: ClassVar[list[str]] = [
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
    LINE_CHUNKS = False
    CHUNK_LINES = 220
    STRUCTURAL_CHUNKS = False
    SYMBOL_CHUNKS = False
    SYMBOL_BODY = False
    FILE_SUMMARY_CHUNKS = True
    FILE_SUMMARY_HEAD_LINE_MAX_CHARS = 200
    FILE_SUMMARY_HEAD_BLOCK_MAX_CHARS = 4000
    FILE_MANIFEST_CHUNKS = True
    FILE_API_MANIFEST_CHUNKS = False
    FILE_BODY_EVIDENCE_CHUNKS = False
    DOCUMENTATION_SUMMARY_CHUNKS = False
    DOCUMENTATION_MANIFEST_CHUNKS = False
    DOCUMENTATION_CHUNK_CHUNKS = False
    MAX_SYMBOLS_PER_FILE = 96
    SEARCH_LIMIT = 10
    PREVIEW_LINES = 8
    SEARCH_STRATEGY = "hybrid"
    RECURSIVE_ROUNDS = 2
    RECURSIVE_BRANCH_LIMIT = 3
    RECURSIVE_PER_ROUND_LIMIT = 5
    HYBRID_CANDIDATE_LIMIT = 280
    HYBRID_LEXICAL_CANDIDATE_LIMIT = 900
    HYBRID_VECTOR_WEIGHT = 0.5625
    HYBRID_LEXICAL_WEIGHT = 0.1875
    HYBRID_PATH_WEIGHT = 0.08333333333333334
    HYBRID_SYMBOL_WEIGHT = 0.04166666666666667
    HYBRID_SYMBOL_MATCH_WEIGHT = 0.04166666666666667
    HYBRID_GRAPH_WEIGHT = 0.08333333333333334
    HYBRID_FILE_VOTE_WEIGHT = 0.0
    HYBRID_GRAPH_SCOPE = "item"
    HYBRID_VECTOR_KIND_LIMITS: ClassVar[dict[str, int]] = {"file_summary": 170, "file_manifest": 170}
    HYBRID_VECTOR_KIND_MULTIPLIERS: ClassVar[dict[str, float]] = {"file_summary": 1.0, "file_manifest": 1.08}
    HYBRID_GRAPH_DEPTH = 0
    HYBRID_GRAPH_NEIGHBOR_LIMIT = 0
    HYBRID_LEXICAL_SCORING = "bm25"
    HYBRID_FUSION = "weighted"
    HYBRID_RRF_K = 60
    HYBRID_BM25_K1 = 1.2
    HYBRID_BM25_B = 0.75
    HYBRID_ROUTING_ENABLED = True
    HYBRID_PRESERVE_VECTOR_TOP = True
    HYBRID_VECTOR_TOP_SCORE_MARGIN = 0.03
    HYBRID_ITEM_KIND_WEIGHTS: ClassVar[dict[str, float]] = {"file_summary": 1.0, "file_manifest": 1.08}
    HYBRID_MIN_TOKEN_LENGTH = 3
    HYBRID_QUERY_EXPANSION_ENABLED = False
    HYBRID_QUERY_EXPANSION_ALIASES: ClassVar[dict[str, list[str]]] = {
        "auth": ["authorization", "authenticate", "authentication", "token", "permission"],
        "authorization": ["auth", "authenticate", "authentication", "token", "permission"],
        "config": ["configuration", "settings", "options", "env"],
        "configuration": ["config", "settings", "options", "env"],
        "db": ["database", "sql", "query", "session"],
        "database": ["db", "sql", "query", "session"],
        "http": ["url", "uri", "request", "response", "api"],
        "url": ["uri", "http", "request", "api"],
        "command": ["cmd", "handler", "execute", "run"],
        "handler": ["handle", "command", "dispatch"],
        "init": ["initialize", "initialise", "setup", "create"],
        "delete": ["del", "remove", "drop"],
        "remove": ["delete", "del", "drop"],
        "file": ["path", "read", "write", "upload", "download"],
        "stream": ["download", "upload", "read", "write"],
    }
    HYBRID_STOP_WORDS: ClassVar[list[str]] = [
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
    GRAPH_FILE_SEED_LIMIT = 120
    GRAPH_FILE_LEXICAL_SEED_LIMIT = 240
    GRAPH_FILE_VECTOR_WEIGHT = 0.25
    GRAPH_FILE_LEXICAL_WEIGHT = 0.25
    GRAPH_FILE_PATH_WEIGHT = 0.20
    GRAPH_FILE_SYMBOL_WEIGHT = 0.10
    GRAPH_FILE_GRAPH_WEIGHT = 0.45
    GRAPH_FILE_DEPTH = 2
    GRAPH_FILE_NEIGHBOR_LIMIT = 40
    GRAPH_FILE_DECAY = 0.65
    GRAPH_FILE_MIN_TOKEN_LENGTH = 3
    GRAPH_FILE_STOP_WORDS = HYBRID_STOP_WORDS
    LLM_RERANK_CANDIDATE_LIMIT = 30
    LLM_RERANK_RERANK_LIMIT = 10
    LLM_RERANK_MAX_PREVIEW_CHARS = 700
    LLM_RERANK_MODE = "precision"
    LLM_RERANK_INCLUDE_REASONS = False
    LLM_RERANK_PRESERVE_TOP_CANDIDATE = False
    LLM_RERANK_PRESERVE_TOP_SCORE_MARGIN = 0.0
    LLM_RERANK_RETRY_ATTEMPTS = 3
    LLM_RERANK_RETRY_BASE_DELAY_SECONDS = 1.0
    LLM_RERANK_RETRY_MAX_DELAY_SECONDS = 8.0
    LLM_RERANK_REPOSITORY_CONTEXT_PATH = None
    LLM_RERANK_REPOSITORY_CONTEXT_MAX_CHARS = 16_000
    CROSS_ENCODER_RERANK_PROVIDER = "llama_cpp"
    CROSS_ENCODER_RERANK_MODEL = "Qwen3-Reranker-0.6B"
    CROSS_ENCODER_RERANK_URL = "http://127.0.0.1:8080/v1/rerank"
    CROSS_ENCODER_RERANK_CANDIDATE_LIMIT = 40
    CROSS_ENCODER_RERANK_MAX_DOCUMENT_CHARS = 900
    CROSS_ENCODER_RERANK_TIMEOUT_MS = 20_000
    CROSS_ENCODER_RERANK_PRESERVE_TOP_CANDIDATE = False
    CROSS_ENCODER_RERANK_PRESERVE_TOP_SCORE_MARGIN = 0.0
    CROSS_ENCODER_RERANK_SKIP_WHEN_TOP_MARGIN_AT_LEAST = None
    GRAPH_EXPANSION_DEPTH = 0
    GRAPH_NEIGHBOR_LIMIT = 0
    GRAPH_AST_ENABLED = False
    GRAPH_REFERENCE_EDGES_ENABLED = False
    GRAPH_CALL_EDGES_ENABLED = False

    UI_COLOR = True
    UI_PAGER = "auto"
    UI_LINKS = True
    EDITOR_COMMAND = "code"
    EDITOR_ARGS: ClassVar[list[str]] = ["-g", "{path}:{line}"]

    EXPERIMENT_SUITE = "local"
    EXPERIMENT_STRATEGIES: ClassVar[list[str]] = ["vector", "recursive", "graph"]

    METRICS_ENABLED = False
    CLICKHOUSE_URL = "http://localhost:8123"
    CLICKHOUSE_DATABASE = "code_diver"
    CLICKHOUSE_USERNAME = "code_diver"
    CLICKHOUSE_PASSWORD = "code_diver"
    CLICKHOUSE_METRICS_TABLE = "rag_eval_metrics"
    CLICKHOUSE_CASES_TABLE = "rag_eval_cases"
    CLICKHOUSE_TIMEOUT_SECONDS = 10.0
    CLICKHOUSE_RETENTION_DAYS = 30
