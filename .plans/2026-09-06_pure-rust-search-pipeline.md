# Pure Rust Search Pipeline

## Goal
Replace the Python search pipeline with a standalone Rust binary that performs the full search: retrieval (vector + BM25 + graph), CE rerank orchestration, and meta-ranker prediction.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Rust Binary (code-diver-search)          │
│                                                             │
│  ┌──────────────────┐  ┌──────────────────────────────────┐ │
│  │  DataLoader       │  │  SearchPipeline                 │ │
│  │  - load_catalog() │  │  - embed_query() → HTTP         │ │
│  │  - build_bm25()   │  │  - vector_search() → Qdrant HTTP│ │
│  │  - load_graph()   │  │  - bm25_score()                 │ │
│  │  - load_vectors() │  │  - graph_propagate()            │ │
│  │                   │  │  - fuse_scores()                │ │
│  └──────────────────┘  │  - ce_rerank() → llama.cpp HTTP  │ │
│                         │  - meta_ranker_predict()         │ │
│                         │  - rank_and_return()             │ │
│                         └──────────────────────────────────┘ │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  MetaRanker: LightGBM model in pure Rust             │   │
│  │  - parse TXT model format (200 trees, 15 leaves,     │   │
│  │    16 features)                                      │   │
│  │  - predict() — tree traversal in Rust                │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
         │
         ▼ HTTP POST /v1/rerank
    ┌────────────┐
    │ llama.cpp  │  (unchanged — separate process)
    │ CE server  │
    └────────────┘
         │
         ▼ HTTP POST /v1/embeddings
    ┌────────────┐
    │ Embedding  │  (unchanged — separate process)
    │ Provider   │
    └────────────┘
         │
         ▼ gRPC / REST
    ┌────────────┐
    │  Qdrant    │  (unchanged — separate process)
    │  Vector DB │
    └────────────┘
```

## Data Flow

```
1. Query string → Rust binary (stdin or socket)
2. Rust sends HTTP POST to embedding provider → gets query vector
3. Rust sends HTTP search to Qdrant → gets vector candidates
4. Rust computes BM25 scores from loaded index
5. Rust computes graph propagation scores from loaded graph
6. Rust fuses scores (weighted sum)
7. Rust truncates to candidate_limit (34)
8. For each candidate: build CE document string
9. Rust sends HTTP POST to llama.cpp CE server → gets CE scores
10. Rust computes second pass for low-scoring candidates
11. Rust applies ranking adjustments (logit, tie-break)
12. Rust computes hub prior scores
13. Rust extracts 16 meta-ranker features
14. Rust runs LightGBM prediction (pure Rust, no Python)
15. Rust returns top-N ranked results
```

## Components

### 1. Rust Binary (new `native/code_diver_search_bin/`)
- Standalone binary, not PyO3
- Cargo.toml with dependencies: `serde`, `serde_json`, `reqwest` (HTTP), `rustc-hash`
- No Python dependency, no PyO3

### 2. DataLoader
- `load_catalog(path: &str) -> Catalog` — reads JSONL catalog files
- `build_bm25_index(catalog: &Catalog) -> Bm25Index` — builds posting lists, term frequencies
- `load_graph_adjacency(path: &str) -> AdjacencyMap` — loads graph edges
- `load_lightgbm_model(path: &str) -> LgbModel` — parses LightGBM TXT format

### 3. SearchPipeline
- `embed_query(query: &str, endpoint: &str) -> Vec<f64>` — HTTP call to embedding provider
- `vector_search(query_vec: &[f64], qdrant_url: &str, limit: usize) -> Vec<SearchResult>` — HTTP to Qdrant
- `bm25_score(query: &str, index: &Bm25Index, candidates: &[String]) -> HashMap<String, f64>` — pure Rust
- `graph_propagate(scores: &HashMap<String, f64>, adjacency: &AdjacencyMap, depth: usize) -> HashMap<String, f64>` — pure Rust
- `fuse_scores(...) -> Vec<Candidate>` — weighted sum
- `ce_rerank(query: &str, documents: &[String], endpoint: &str) -> Vec<f64>` — HTTP to llama.cpp
- `meta_ranker_predict(features: &[Vec<f64>], model: &LgbModel) -> Vec<f64>` — pure Rust

### 4. LightGBM Model Parser (pure Rust)
- Parse LightGBM TXT format: `tree`, `split_feature`, `split_gain`, `threshold`, `leaf_value`
- 200 trees, 15 leaves, 16 features
- Prediction: traverse each tree, sum leaf values

### 5. Feature Extraction (pure Rust)
- Port `CeMetaFeatureExtractor` from Python to Rust
- 16 features: ce_score, ce_rank, base_fused_score, base_fused_rank, path_depth, file_name_tokens, dir_name_tokens, path_dir_overlap, path_token_overlap, is_test, is_source, fan_in_degree, role_score, extension_match, symbol_match, name_match

## Implementation Status

### Phase 1: Core Data Structures + BM25 + Fuse ✅ DONE
- Rust binary project created
- Catalog loading, BM25 index, BM25 scoring implemented
- Score fusion implemented
- 16 tests passing

### Phase 2: Graph + Vector Search ✅ DONE
- Graph adjacency loading
- Graph propagation (BFS with decay)
- Qdrant HTTP client
- Embedding HTTP client
- CE rerank HTTP client

### Phase 3: CE Rerank Orchestration ✅ DONE
- llama.cpp HTTP client
- Document building (truncation at max_document_chars)
- First pass + second pass logic
- Ranking adjustments (logit, tie-break)

### Phase 4: Meta-Ranker ✅ DONE
- LightGBM TXT parser (flat tree format)
- 16 feature extractors ported from Python
- Pure Rust prediction (no C++/Python dependency)

### Phase 5: Integration + E2E 🚧 PARTIAL
- Full pipeline orchestration
- 4 CLI modes: single, interactive, server, benchmark
- Per-stage timings (SearchTimings)
- Pending: parity validation on WHERE78

### Phase 6: Validation ⏳ PENDING
- Run on WHERE78, mech229, full 1065
- Compare hit@10, MRR, recall
- Benchmark latency

### Phase 2: Graph + Vector Search (day 3)
- Graph adjacency loading
- Graph propagation
- Qdrant HTTP client
- Embedding HTTP client
- Test: parity with Python retrieval on 10 queries

### Phase 3: CE Rerank Orchestration (day 4)
- llama.cpp HTTP client
- Document building (truncation at max_document_chars)
- First pass + second pass logic
- Ranking adjustments (logit, tie-break, hub prior)
- Test: parity with Python CE rerank on 10 queries

### Phase 4: Meta-Ranker (day 5)
- Parse LightGBM TXT model
- Implement 16 feature extractors
- Prediction
- Test: parity with Python LightGBM predict on 34x16 matrix

### Phase 5: Integration + E2E (day 6)
- Full pipeline orchestration
- Socket listener (stdin for now)
- E2E test: full search on 10 queries, compare with Python champion

### Phase 6: Validation (day 7)
- Run on WHERE78, mech229, full 1065
- Compare hit@10, MRR, recall
- Benchmark latency

## File Structure
```
native/code_diver_search_bin/
├── Cargo.toml
└── src/
    ├── main.rs           — CLI entry point + socket listener
    ├── catalog.rs        — Catalog loading, item storage
    ├── bm25.rs           — BM25 index building + scoring
    ├── graph.rs          — Graph adjacency + propagation
    ├── vector.rs         — Qdrant HTTP client
    ├── embedding.rs      — Embedding provider HTTP client
    ├── ce_rerank.rs      — llama.cpp HTTP client + document building
    ├── fusion.rs         — Score fusion
    ├── features.rs       — 16 meta-ranker features
    ├── lightgbm.rs       — LightGBM TXT parser + predictor
    ├── pipeline.rs       — Full search pipeline orchestration
    ├── config.rs         — Configuration
    └── types.rs          — Common types (SearchResult, Candidate, etc.)
```

## Key Decisions

1. **No PyO3** — standalone binary, not a Python extension
2. **HTTP to external services** — Qdrant, embedding, llama.cpp all via HTTP
3. **LightGBM in pure Rust** — parse TXT model format, no C++ dependency
4. **Data loaded once at startup** — catalog, BM25 index, graph, model all loaded at init
5. **stdin/socket protocol** — accept query, return JSON results
6. **CE server unchanged** — llama.cpp stays as separate process

## Migration Strategy
1. Build Rust binary alongside existing Python code
2. Validate parity on WHERE78 dataset
3. Once validated, replace Python search with Rust binary call
4. Keep Python for: research scripts, eval harness, config management