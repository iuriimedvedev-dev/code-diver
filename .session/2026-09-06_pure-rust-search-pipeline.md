# Pure Rust Search Pipeline — Session 2026-09-06

## Решение
Создан standalone Rust binary (`native/code_diver_search_bin/`) — полная замена Python search pipeline.

## Что сделано

### Phase 1: Core Data Structures + BM25 + Fuse ✅
- `types.rs` — Catalog, Bm25Index, GraphAdjacency, Candidate, SearchConfig, MetaFeatures, LgbModel/LgbTree, SearchResult
- `catalog.rs` — load_catalog из JSONL, normalize_path, tokenize
- `bm25.rs` — build_bm25_index, bm25_scores, coverage_score
- `fusion.rs` — fuse_scores, normalize_scores, l2_normalize, dot, logit, сортировки, tie_break_by_fused
- **16 тестов проходят**

### Phase 2: Graph + Vector Search ✅
- `graph.rs` — load_graph_adjacency, propagate_scores (BFS с decay)
- `embedding.rs` — HTTP клиенты: embed_query, vector_search (Qdrant), ce_rerank (llama.cpp)

### Phase 3: CE Rerank Orchestration ✅
- `pipeline.rs` — full search() pipeline: embed → Qdrant → BM25 → graph → fuse → CE first pass → CE second pass → logit/tie-break → meta-ranker → ranked results
- `SearchTimings` — per-stage timings

### Phase 4: Meta-Ranker ✅
- `lightgbm.rs` — LightGBM TXT parser + predictor (pure Rust, 200 деревьев)
- `features.rs` — 16 meta-ranker features: ce_score, ce_rank, base_fused, path_depth, file_name_tokens, dir_name_tokens, path_dir_overlap, path_token_overlap, is_test, is_source, fan_in_degree, role_score, extension_match, symbol_match, name_match

### CLI
- `main.rs` — 4 режима: single query, interactive, server (JSON stdin), benchmark
- `--catalog`, `--graph`, `--model`, `--embedding-url`, `--qdrant-url`, `--ce-url`, `--candidate-limit`

## Архитектура
- **No PyO3** — standalone binary, ноль Python
- **HTTP к внешним сервисам**: Qdrant, embedding, llama.cpp
- **LightGBM в чистом Rust** — парсинг TXT формата, предсказание без C++/Python
- **Данные загружаются один раз** при старте: каталог (150k items), BM25 индекс, граф, модель

## Ограничения
- LightGBM парсер — упрощённый (flat tree, без рекурсивных детей). Для полной точности нужен парсер nested TXT формата
- Feature extraction — портирован с Python, но fan-in degree — хэш (счётчик вхождений), не настоящий import analysis
- Document building — пока только путь, без реального content из файлов
- CE second pass — build_long_document пока урезан

## Файлы
```
native/code_diver_search_bin/
├── Cargo.toml
├── src/
│   ├── main.rs
│   ├── types.rs
│   ├── catalog.rs
│   ├── bm25.rs
│   ├── fusion.rs
│   ├── graph.rs
│   ├── embedding.rs
│   ├── features.rs
│   ├── lightgbm.rs
│   └── pipeline.rs
```

## Следующие шаги
1. Доработать LightGBM парсер для nested TXT формата (рекурсивные деревья)
2. Добавить real content из файлов в document building
3. Проверить parity на WHERE78 (сравнить hit@10 с Python champion)
4. Запустить benchmark n=20 для сравнения latency
5. Опционально: socket server mode для интеграции с Python