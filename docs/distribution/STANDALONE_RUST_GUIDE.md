# Code Diver — Pure Rust Standalone Engine

Высокопроизводительный поисковый движок по кодовой базе, написанный на **Rust**. Работает автономно без рантайма Python, сочетает гибридный поиск (BM25 + Dense Vectors + Graph Adjacency), кросс-энкодерное переранжирование (Cross-Encoder) и финальный LightGBM Meta-Ranker.

---

## ⚡ Быстрый старт (Quickstart)

### 1. Архитектура и сервисы
Движок `code-diver` работает как легковесный нативный клиент к трем локальным сервисам:
```text
                      ┌─────────────────────────────────────────┐
                      │          code-diver (Rust)              │
                      │  - BM25 Inverted Index                  │
                      │  - Graph Fan-in / Adjacency             │
                      │  - Hybrid Fusion (0.42/0.26/0.12/0.10)  │
                      │  - LightGBM Meta-Ranker (16 features)   │
                      └────┬──────────────┬───────────────┬─────┘
                           │              │               │
        Dense Search       │              │ Vector Embed  │ CE Rerank
        :6333              │              │ :8001         │ :18081
       ┌───────────────────▼┐      ┌──────▼──────┐ ┌──────▼────────┐
       │   Qdrant Vector    │      │ vLLM-Metal  │ │  llama-server │
       │       Store        │      │ Qwen3-0.6B  │ │  Qwen3-0.6B   │
       │                    │      │  Embedding  │ │   Reranker    │
       └────────────────────┘      └─────────────┘ └───────────────┘
```

1. **Qdrant** (`http://127.0.0.1:6333`): база векторных индексов (коллекция `intellij_h66b_budget_qwen`).
2. **Embedding Model** (`http://127.0.0.1:8001`): `mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ` (vLLM-metal pooling).
3. **Cross-Encoder Reranker** (`http://127.0.0.1:18081`): `Qwen3-Reranker-0.6B-Q4_K_M.gguf` (llama-server с `--pooling rank --reranking`).

---

### 2. Самопроверка готовности окружения (Doctor)
Для проверки доступности всех портов, моделей и файлов артефактов запустите встроенный режим проверки:

```bash
./bin/code-diver --doctor
```

Вывод при штатной работе:
```text
=== code-diver doctor ===
Checking Qdrant (http://localhost:6333)... OK (status 200 OK)
Checking Embedding Service (http://localhost:8001/v1/models)... OK (status 200 OK)
Checking CE Rerank Service (http://localhost:18081/health)... OK (status 200 OK)

Checking local artifacts:
  Catalog: Some("artifacts/rust_catalog.jsonl")
  Graph:   Some("artifacts/rust_graph.jsonl")
  Model:   Some("artifacts/ce_meta_ranker/ce_meta_ranker.lgb.txt")
=========================
```

---

### 3. Запуск поиска

#### Одиночный запрос через CLI
```bash
./bin/code-diver \
  --catalog artifacts/rust_catalog.jsonl \
  --graph artifacts/rust_graph.jsonl \
  --model models/ce_meta_ranker.lgb.txt \
  --query "where is project structure dialog" \
  --limit 10
```

#### Интерактивный режим (REPL)
```bash
./bin/code-diver \
  --catalog artifacts/rust_catalog.jsonl \
  --graph artifacts/rust_graph.jsonl \
  --model models/ce_meta_ranker.lgb.txt
```
Вводите запросы построчно, для выхода нажмите `Ctrl+D`.

#### Серверный режим (JSON Lines через stdin/stdout)
Предназначен для интеграции в плагины IDE, демоны и бенчмарки без накладных расходов на инициализацию:
```bash
./bin/code-diver --server
```
Формат входного запроса (одна строка JSON):
```json
{"query": "where is project structure dialog", "limit": 10}
```
Формат ответа:
```json
{
  "query": "where is project structure dialog",
  "num_results": 10,
  "results": [
    {
      "item_id": "0fc81165-b246-5d8e-b4db-49a6e38cdd84",
      "path": "platform/lang-impl/src/com/intellij/conversion/impl/ui/ConvertProjectDialog.java",
      "score": 0.99396,
      "ce_score": 0.99396,
      "meta_score": -0.08342
    }
  ],
  "timings": {
    "total_ms": 1420.5,
    "embed_ms": 12.4,
    "vector_search_ms": 78.1,
    "bm25_ms": 160.2,
    "ce_first_pass_ms": 1150.3
  }
}
```

---

### 4. Инкрементальное обновление индекса (Incremental Index Update)
Rust-движок включает полностью нативный инкрементальный апдейтер векторной базы Qdrant. Он вычисляет разницу (diff) между файлами свежего репозитория и текущей коллекцией Qdrant, после чего эмбеддит и перезаписывает **только измененные файлы**, а удаленные вычищает:

```bash
# Сухой прогон (показывает количество added / changed / deleted)
./bin/code-diver --index-update --catalog artifacts/rust_catalog.jsonl

# Применение изменений
./bin/code-diver --index-update --apply --catalog artifacts/rust_catalog.jsonl
```

---

## 📊 Сравнение качества: Code-Diver против JetBrains Context (jbcontext)

Тестирование на реальном монорепозитории `intellij-community` (135 404 файла, коммит `c6143439a2a4`):

| Метрика | **`code-diver` (Rust Meta-Ranker)** | **`jbcontext 0.9.14`** | Преимущество |
| :--- | :---: | :---: | :---: |
| **`file_hit_rate@1`** | **0.346** | 0.179 | **+16.7 pp (в 1.93 раза выше!)** 🚀 |
| **`file_hit_rate@3`** | **0.692** | 0.410 | **+28.2 pp (в 1.69 раза выше!)** 🚀 |
| **`file_hit_rate@5`** | **0.782** | 0.564 | **+21.8 pp** 🚀 |
| **`file_hit_rate@10`** | **0.833** | 0.782 | **+5.1 pp** 🚀 |
| **`file_mrr@10`** | **0.523** | 0.347 | **+17.6 pp** 🚀 |
| **`map@10`** | **0.484** | 0.327 | **+15.7 pp** 🚀 |
| **`ndcg@10`** | **0.567** | 0.434 | **+13.3 pp** 🚀 |

---

## 🛠 Запуск фоновых бэкендов на Apple Silicon (Metal)

### 1. Qdrant (Docker)
```bash
docker run -d --name qdrant -p 6333:6333 -v ~/.qdrant_storage:/qdrant/storage qdrant/qdrant
```

### 2. Embedding модель (vLLM-Metal)
```bash
vllm serve mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ \
  --runner pooling \
  --host 127.0.0.1 \
  --port 8001 \
  --max-model-len 512
```

### 3. Cross-Encoder Reranker (llama-server)
```bash
llama-server \
  -m Qwen3-Reranker-0.6B-Q4_K_M.gguf \
  --host 127.0.0.1 \
  --port 18081 \
  --ctx-size 40960 \
  --batch-size 2048 \
  --ubatch-size 2048 \
  --pooling rank \
  --reranking
```
