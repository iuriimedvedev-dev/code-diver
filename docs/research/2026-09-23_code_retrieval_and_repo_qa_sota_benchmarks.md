# Research: Code Retrieval & Repository Navigation Benchmarks (SotA 2024–2026)

**Date:** 2026-09-23  
**Focus:** Open datasets, established benchmarks, evaluation methodologies, and State of the Art (SotA) in repository-level code search and code navigation.

---

## 1. Landscape Overview

Code retrieval has evolved across three distinct generations:

1. **First Gen (Function Snippets / Token-level):**  
   - *CodeSearchNet* (GitHub docstrings $\leftrightarrow$ functions), *StaQC* (Stack Overflow), *CoSQA* (Bing web queries $\leftrightarrow$ Python functions).  
   - **Limitations:** Isolated snippets, 1-to-1 matching, heavily overfitted by modern embedding models, ignores repo hierarchy and dependency graphs.

2. **Second Gen (Multi-Choice & Holistic IR):**  
   - *CoIR* (Huawei Noah's Ark, 2024–2025): 10 datasets across 14 languages, 4 core IR tasks (Text-to-Code, Code-to-Code, Code-to-Text, Hybrid QA).  
   - *CoSQA+* (Sun Yat-sen Univ, 2024–2025): 412k test-driven agent-annotated pairs addressing multi-choice retrieval and NDCG@10.

3. **Third Gen (Full-Repository & Agentic Navigation):**  
   - *SWE-bench / SWE-bench Lite / Verified* (Princeton / OpenAI): End-to-end issue resolving where the primary failure point of agents is **localization / retrieval** across 100k+ LOC.  
   - *RepoQA / EvalPlus* (UIUC, ICML 2024): 50 real-world repositories across 5 languages (Python, Java, TypeScript, C++, Rust), testing needle retrieval from natural language intent with dependency ordering.  
   - *CrossCodeEval / RepoEval* (Microsoft / ByteDance): Multi-file context retrieval for code completion and cross-file API referencing.

---

## 2. Top Candidate Benchmarks for Testing `code-diver`

### Benchmark 1: RepoQA (Searching Needle Function - SNF)
* **Authors:** EvalPlus (UIUC, Zhang et al., 2024)
* **What it tests:** Given a natural language description of functionality (without leaking symbol/function names) and a full repository or sub-tree, locate the exact file and function definition.
* **Coverage:** 50 real GitHub repositories, 5 languages (Python, Java, TypeScript, C++, Rust), 500 ground-truth needle tasks.
* **Relevance to `code-diver`:** **Highest (9.8/10)**.
  - `code-diver` is built specifically for repository-level localization (`outline`, `symbols`, `read`).
  - RepoQA tests multi-language navigation where traditional BM25 fails due to paraphrased natural language queries.
* **How to benchmark:** Index the 10 Java / 10 Python repositories from RepoQA, run `code_diver_search_bin`, evaluate top-1 and top-5 function/file recall.

---

### Benchmark 2: SWE-bench Localization Split (SWE-bench / SWE-bench Verified)
* **Authors:** Princeton NLP & OpenAI (2024)
* **What it tests:** Given a real GitHub issue description (bug report, feature request), identify the exact set of modified files (`patch_files`) before generating code edits.
* **Why it matters:** In current LLM agent literature (Aider, Devin, OpenCode, SWE-agent), **over 40% of failures stem from retrieving the wrong files in large codebases**.
* **Relevance to `code-diver`:** **Extreme (9.5/10)**.
  - SWE-bench instances (Django, SymPy, Matplotlib, Sphinx, etc.) are standard battlegrounds.
  - Testing `code-diver` as the L1/L2 retrieval layer for SWE-bench agents against BM25, embeddings, and ctags will provide a definitive SotA comparison on file-level localization (Hit@1, Hit@3, Recall).

---

### Benchmark 3: CoIR (Code Information Retrieval Benchmark)
* **Authors:** Huawei Noah's Ark Lab (2024–2025)
* **What it tests:** Comprehensive benchmark following the BEIR / MTEB schema.
  - 10 curated datasets, 14 programming languages.
  - Tasks: Text-to-Code (`APPS`, `CoSQA`, `Synthetic Text2SQL`), Code-to-Code (`CodeSearchNet-CCR`), Hybrid QA (`StackOverflow QA`, `CodeFeedback`).
* **Current SotA:**
  - `Voyage-Code-002`: NDCG@10 = 56.26 (best proprietary)
  - `E5-Mistral-7B`: NDCG@10 = 55.18 (best open-source)
  - `BGE-M3 (567M)`: NDCG@10 = 39.31
  - `BM25`: NDCG@10 = 29.79
* **Relevance to `code-diver`:** **High for Zero-Shot Retrieval Evaluation (8.5/10)**.
  - Allows evaluating `code-diver`'s hybrid ranking engine on standardized MTEB-style tasks.

---

### Benchmark 4: CrossCodeEval / RepoEval
* **Authors:** Ding et al. (NeurIPS 2023) / Zhang et al. (ByteDance)
* **What it tests:** Cross-file context retrieval. Given a target file with missing code, retrieve other files in the project that define the required types, methods, or imports.
* **Relevance to `code-diver`:** **Direct for Graph Diffusion / Symbol Navigation (8.5/10)**.
  - `code-diver` already builds a project graph (`graph.json` with imports and symbol references). This benchmark tests whether our graph diffusion layer actually helps find dependent files.

---

## 3. What is State of the Art (SotA) in This Field?

| Domain | Leading Models / Approaches | Key Techniques |
| :--- | :--- | :--- |
| **Code Embeddings (Bi-encoders)** | `voyage-code-002`, `E5-Mistral-7B`, `Qwen3-Embedding-0.6B/8B`, `jina-embeddings-v3` | Task LoRAs, multi-stage contrastive pretraining, long context (8k-32k). |
| **Neural Cross-Encoders (Rerankers)** | `Qwen3-Reranker-0.6B/8B`, `bge-reranker-v2-m3`, `Cohere Rerank 3.5` | Token-level cross-attention over truncated headers + signatures. |
| **Hybrid Search Engines** | `code-diver Native (Rust)`, `jbcontext`, `Sourcegraph Cody`, `GitHub Blackbird` | Fast inverted index (BM25) + vector k-NN + AST graph propagation + cross-encoder re-scoring. |
| **Agentic / Long-Context Localization** | `RepoQA (EvalPlus)`, `SWE-bench Localization` | Tree-sitter outline traversal, file dependency topological ordering, test-driven self-verification. |

---

## 4. Recommended Next Steps for `code-diver`

1. **Integrate RepoQA (Python + Java):**
   - Download the 10 Java and 10 Python repositories from `evalplus/repoqa`.
   - Run `code-diver` indexer on each.
   - Run the 200 SNF queries through `code-diver` search and measure Needle-Hit@1 and Needle-Hit@3 against standard CodeSearchNet/BM25 baselines.

2. **Benchmark SWE-bench Lite Localization:**
   - Take the 300 instances of SWE-bench Lite.
   - Feed the issue description into `code-diver` and measure whether the files in `git diff` appear in top-1 / top-3 / top-5 retrieval results.
   - Compare `code-diver` against `ripgrep`, `bm25`, and dense embedding baselines.
