# Large-Scale Benchmarks: RepoQA (600 Needles) & IntelliJ (1,065 Cases)

This document provides a comprehensive evaluation of **code-diver** across two massive, realistic benchmark suites:
1. **RepoQA Full Suite (600 Cases)**: 60 repositories across 6 languages (Python, Java, TypeScript, Rust, Go, C++).
2. **IntelliJ Full Suite (1,065 Cases)**: Monolithic multi-million LOC repository (`intellij-community`).

---

## 1. RepoQA Full Benchmark: 600 Needles Across 60 Repositories

### Benchmark Setup
- **Scope**: 60 open-source repositories, 10 repositories per language across 6 programming languages.
- **Languages**: Python, C++, Java, TypeScript, Rust, Go.
- **Granularity**: Needle-in-a-haystack localization of exact function definitions (`[start_line, end_line]`).
- **Engine**: `code-diver` Dual-Context Cascade with `gemini-3.5-flash-lite` (10 concurrent worker threads).
- **Duration**: 276.8 seconds (~4.6 minutes wall-clock time).

### Overall Metrics (600 Needles)

| Metric | All 6 Languages (600 Cases) | Primary 5 Languages (500 Cases) |
| :--- | :---: | :---: |
| **File Hit@1** | **93.7%** (562/600) 🏆 | **95.2%** (476/500) 🏆 |
| **File Hit@3** | **97.0%** (582/600) | **97.2%** (486/500) |
| **File Hit@5** | **97.5%** (585/600) | **97.8%** (489/500) |
| **File MRR** | **0.953** | **0.960** |
| **Line Overlap (Exact Span)** | **89.3%** (536/600) 🏆 | **91.6%** (458/500) 🏆 |
| **Average Agent Latency** | 1,936 ms | 1,945 ms |
| **Average E2E Latency** | 2,127 ms | 2,126 ms |

*\*Note: With the new `LanguageIndexingRouter` (`CppStrategy`), C++ indexing coverage was dramatically increased, boosting C++ Hit@1 from 57% to 86% and bringing overall 600-case Hit@1 to 93.7%.*

---

### Language Breakdown (100 Needles / 10 Repositories Each)

```text
========================================================================================================================
                                     REPOQA-600 PER-LANGUAGE METRICS TABLE
========================================================================================================================
Language        | Repos | Needles | File Hit@1 | File Hit@3 | File Hit@5 | File MRR | Line Overlap | Agent Latency
----------------|-------|---------|------------|------------|------------|----------|--------------|----------------
Rust            | 10    | 100     | 97.0%      | 98.0%      | 98.0%      | 0.973    | 93.0%        | 1,885 ms
Go              | 10    | 100     | 96.0%      | 97.0%      | 98.0%      | 0.965    | 92.0%        | 1,762 ms
TypeScript      | 10    | 100     | 95.0%      | 96.0%      | 97.0%      | 0.956    | 93.0%        | 1,888 ms
Python          | 10    | 100     | 94.0%      | 99.0%      | 99.0%      | 0.957    | 89.0%        | 2,047 ms
Java            | 10    | 100     | 94.0%      | 96.0%      | 97.0%      | 0.951    | 91.0%        | 2,143 ms
C++             | 10    | 100     | 86.0%      | 96.0%      | 97.0%      | 0.914    | 78.0%        | 1,891 ms
----------------|-------|---------|------------|------------|------------|----------|--------------|----------------
Total / Average | 60    | 600     | 93.7%      | 97.0%      | 97.5%      | 0.953    | 89.3%        | 1,936 ms
========================================================================================================================
```

---

## 2. IntelliJ Benchmark: 1,065 Cases on `intellij-community`

### Benchmark Setup
- **Corpus**: `intellij-community` (135,000 files, ~20,000,000 LOC, Java & Kotlin).
- **Dataset**: `datasets/intellij_eval_1000.answer_sets.jsonl` (1,065 test cases).
- **Competitors**:
  - **`jbcontext` v0.9.14**: JetBrains Context official cloud backend with Grazie neural embeddings and listwise reranker.
  - **`code-diver`**: Native Rust search engine (`code_diver_search_bin`) + local Qdrant + local MLX neural embeddings & reranker.

### Head-to-Head Comparison (1,065 Cases)

```text
===================================================================================================================
                               INTELLIJ 1,065-CASE BENCHMARK (code-diver vs jbcontext)
===================================================================================================================
Metric                        | jbcontext (0.9.14)         | code-diver (Rust Engine)   | Advantage / Delta
----------------------------- | -------------------------- | -------------------------- | -------------------------
Hit@1                         | 43.29%                     | **66.85%**                 | **+23.56 pp** (+54.4%) 🏆
Hit@3                         | 59.72%                     | **74.74%**                 | **+15.02 pp** (+25.2%) 🏆
Hit@5                         | 64.79%                     | **76.06%**                 | **+11.27 pp** (+17.4%) 🏆
Hit@10                        | 68.54%                     | **76.81%**                 | **+8.27 pp** (+12.1%) 🏆
MRR@10                        | 0.5223                     | **0.7102**                 | **+0.1879** (+36.0%) 🏆
NDCG@10                       | 0.5531                     | **0.7135**                 | **+0.1604** (+29.0%) 🏆
MAP@10                        | 0.5106                     | **0.6951**                 | **+0.1845** (+36.1%) 🏆
Mean Latency                  | 1,740.4 ms                 | **669.6 ms**               | **2.60x faster** ⚡
P95 Latency                   | 3,063.2 ms                 | **777.6 ms**               | **3.94x faster** ⚡
===================================================================================================================
```

---

## 3. High-Level Summary & Conclusions

1. **Multi-Repo Breadth (RepoQA 600)**:
   - On modern languages with AST symbols (Rust, Go, TypeScript, Python, Java), `code-diver` averages **95.2% Hit@1** and **91.6% Exact Line Localization** across 500 independent queries.
   - C++ (57.0% Hit@1) is currently the main area for future improvement (adding AST-based macro and header/cpp symbol resolution).

2. **Monolithic Scale (IntelliJ 1,065)**:
   - Against JetBrains' proprietary code search (`jbcontext`), `code-diver` delivers **+23.56 percentage points higher Hit@1** (66.9% vs 43.3%) on an industrial 20M-line codebase.
   - Operates entirely locally with a native Rust pipeline that is **2.6x to 3.9x faster** than cloud-based `jbcontext`.
