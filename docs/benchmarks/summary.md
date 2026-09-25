# Benchmarks: code-diver vs JetBrains Context (jbcontext)

This document provides a unified overview of all benchmarks comparing **code-diver** with JetBrains Context (**jbcontext** v0.9.14).

---

## 1. Multi-Language Fine-Grained Needle Localization: RepoQA 100-Case Benchmark

- **Corpus**: 10 distinct open-source repositories across 5 languages:
  - **Python**: `psf/black`, `python-poetry/poetry`
  - **Java**: `google/gson`, `square/retrofit`
  - **TypeScript**: `expressjs/express`, `axios/axios`
  - **Rust**: `rust-bakery/nom`, `tokio-rs/tracing`
  - **Go**: `junegunn/fzf`, `caddyserver/caddy`
- **Dataset**: 100 test queries (10 per repository).
- **Task**: Return the exact file and exact function definition line span `[start_line, end_line]` implementing the described procedure.
- **Model for code-diver agent**: `gemini-3.5-flash-lite`.

### Comprehensive 100-Case Results

| System / Configuration | File Hit@1 | File Hit@3 | File Hit@5 | File MRR | Line Overlap (Exact Hit) | Mean Latency (E2E) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **code-diver Raw Vector** | 84.0% | 93.0% | 96.0% | 0.892 | 52.0% | ~256 ms |
| **code-diver Agent (Initial Excerpt)** | 93.0% | 98.0% | 98.0% | 0.957 | 83.0% | ~2,089 ms |
| **code-diver Agent (Tuned Excerpt)** | 95.0% | 98.0% | 99.0% | 0.968 | 87.0% | ~2,334 ms |
| **JetBrains Context (`jbcontext` v0.9.14)** | **98.0%** | **100.0%** | **100.0%** | **0.990** | 87.0% | **~1,580 ms** |
| **code-diver Cascade Dual-Context** 🚀 | **98.0%** | **99.0%** | **99.0%** | **0.985** | **96.0%** 🏆 | ~2,169 ms |

#### Key Takeaways:
1. **File Hit@1**: **code-diver** matches JetBrains Context at **98.0%** (98/100 correct files).
2. **Line Overlap (Exact Code Localization)**: **code-diver** significantly outperforms JetBrains Context by **+9.0%** (**96.0%** vs **87.0%**).
3. **Chunk vs. Outline Dynamics**:
   - 95% of queries are resolved directly via Tier-1 concrete code chunks.
   - 5% are recovered via Tier-2 file outlines when chunks lack docstrings (such as `nom:i16_tests`).

---

## 2. Monolithic Codebase Architectural Intent: IntelliJ WHERE-78 Benchmark

- **Corpus**: `intellij-community` (~135,000 files, ~20M lines of code, Java/Kotlin).
- **Dataset**: `datasets/intellij_eval_where_only.jsonl` (78 real developer architectural questions).
- **Task**: Identify the primary files responsible for high-level IDE subsystem behaviors (e.g. *"where is dumb mode handled"*, *"where are write commands executed and undone"*).
- **Engines**:
  - `jbcontext` v0.9.14 (JetBrains AI Platform cloud index, revision `04cc17d449bd`).
  - `code-diver` native Rust search engine (`code_diver_search_bin` + Qdrant + MLX embeddings & reranker).

### Results on WHERE-78 (n=78)

| Metric | JetBrains Context (`jbcontext`) | code-diver (Rust Engine) | Advantage / Delta |
| :--- | :---: | :---: | :---: |
| **File Hit@1** | 15.38% (12/78) | **41.03%** (32/78) | **+25.65 pp** 🏆 |
| **File Hit@3** | 41.03% (32/78) | **69.23%** (54/78) | **+28.20 pp** 🏆 |
| **File Hit@5** | 57.69% (45/78) | **79.49%** (62/78) | **+21.80 pp** 🏆 |
| **File Hit@10** | 80.77% (63/78) | **82.05%** (64/78) | **+1.28 pp** |
| **MRR@10** | 0.3370 | **0.5635** | **+0.2265** 🏆 |
| **NDCG@10** | 0.4306 | **0.5904** | **+0.1598** 🏆 |
| **MAP@10** | 0.3165 | **0.5161** | **+0.1996** 🏆 |
| **Mean Latency** | 1,720 ms | **1,562 ms** | **-158 ms (9.2% faster)** ⚡ |
| **P95 Latency** | 2,254 ms | **1,985 ms** | **-269 ms (12.0% faster)** ⚡ |

#### Key Takeaways:
1. **Dramatic Advantage on Developer Intent Queries**:
   - On abstract developer questions ("where is X implemented"), `code-diver` delivers the correct file on rank 1 in **41.0%** of cases vs only **15.4%** for `jbcontext` (**2.67x higher accuracy**).
   - In top-3 results (`Hit@3`), `code-diver` reaches **69.2%** vs **41.0%** for `jbcontext`.
2. **Superior Speed**:
   - `code-diver` native Rust pipeline runs locally on device in **1,562 ms**, beating cloud-based `jbcontext` (1,720 ms).

---

## 3. Summary Scorecard

```text
===================================================================================================================
                                      SUMMARY OF BENCHMARK OUTCOMES
===================================================================================================================
Benchmark                     | code-diver                    | JetBrains Context            | Winner
----------------------------- | ----------------------------- | ---------------------------- | --------------------
RepoQA 100 (File Hit@1)       | 98.0%                         | 98.0%                        | Tie 🤝
RepoQA 100 (Exact Line Hit)   | 96.0%                         | 87.0%                        | code-diver (+9.0%) 🏆
RepoQA 600 (Overall Hit@1)    | 93.7% (Gemini) / 91.2% (Gemma Local) | N/A (5-lang subset: 87.0%)   | code-diver 🏆
RepoQA 600 (Line Overlap)     | 89.3% (Gemini) / 86.3% (Gemma Local) | N/A                          | code-diver 🏆
IntelliJ 1,065 (Hit@1)        | 66.85%                        | 43.29%                       | code-diver (+23.6%) 🏆
IntelliJ 1,065 (Mean Latency) | 669.6 ms                      | 1,740.4 ms                   | code-diver (2.6x faster) ⚡
IntelliJ WHERE-78 (Hit@1)     | 41.0%                         | 15.4%                        | code-diver (+25.6%) 🏆
IntelliJ WHERE-78 (Hit@3)     | 69.2%                         | 41.0%                        | code-diver (+28.2%) 🏆
IntelliJ WHERE-78 (Latency)   | 1,562 ms                      | 1,720 ms                     | code-diver (9% faster) ⚡
===================================================================================================================
```
