# Local & Cloud LLM Tournament: Closed-Loop Answering & Citation Benchmark

**Date:** 2026-09-23  
**Environment:** Apple Silicon (macOS Darwin, 64 GB Unified Memory)  
**Dataset:** 100 standardized representative contexts from `intellij_eval_1000.answer_sets.jsonl` (cached in `artifacts/research/precomputed_agent_contexts_100.json`)  
**Repositories:** `intellij-community` (60,000+ files)

---

## 1. Executive Summary

This study benchmarks end-to-end closed-loop question answering and grounded code citation in `code-diver`. We compare:
1. **Local Apple Silicon LLMs:** MLX 4-bit and llama.cpp Metal backends spanning 2B to 35B parameter scales (MoE, dense, QAT quantized).
2. **Cloud Models via LiteLLM:** `gemini-3.5-flash-lite` and `gpt-5.6-luna`.
3. **End-to-End Pipeline Performance:** Comparing `jbcontext 0.9.14` vs. `code-diver Local (Best)` vs. `code-diver Cloud LiteLLM`.

---

## 2. Grand Tournament Leaderboard (100 Precomputed Cases)

Every candidate received identical context assembled by `code-diver`'s native search and AST outline service.

| Model | Size / Arch | Backend | Speed (t/s) | Gen Mean (ms) | Gen p95 (ms) | Total Closed-Loop (s)* | JSON Valid | Path Valid | Line Valid | Grounded Cites |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **gemini-3.5-flash-lite** | Cloud API | LiteLLM | **128.2** | **1,779** | **2,847** | **~2.45 s** | **100.0%** | **100.0%** | **100.0%** | **100.0%** |
| **gemma-4-e2b-it-4bit** | 2B Dense | MLX | **74.2** | **3,243** | **5,730** | **~3.92 s** | 94.0% | 96.6% | 95.3% | 96.6% |
| **gemma-4-e2b-it-qat** | 2B QAT | llama.cpp | 65.4 | 4,569 | 6,973 | ~5.24 s | 94.0% | 98.9% | 98.9% | 98.9% |
| **gemma-4-e4b-it-4bit** | 4B Dense | MLX | **43.2** | **6,089** | **9,842** | **~6.76 s** | 95.0% | 99.3% | 98.7% | 99.3% |
| **gpt-5.6-luna** | Cloud API | LiteLLM | **80.1** | **6,360** | **10,536** | **~7.03 s** | **100.0%** | **100.0%** | 99.7% | **100.0%** |
| **gemma-4-e4b-it-qat** | 4B QAT | llama.cpp | 36.4 | 7,313 | 10,881 | ~7.99 s | **98.0%** | **100.0%** | 99.4% | **100.0%** |
| **Qwen3-Coder-30B-A3B** | 30.5B MoE (3.3B act) | MLX | **34.3** | **7,577** | **12,028** | **~8.25 s** | 95.0% | 95.5% | 94.5% | 95.5% |
| **Qwen3.5-4B-4bit** | 4B Dense | MLX | 44.1 | 7,819 | 11,850 | ~8.49 s | 90.0% | **100.0%** | **100.0%** | **100.0%** |
| **Qwen3.6-35B-A3B** | 35B MoE (3.0B act) | MLX | **36.1** | 10,066 | 18,981 | ~10.74 s | 92.0% | **100.0%** | **100.0%** | **100.0%** |
| **Qwen3.5-9B-4bit** | 9B Dense | MLX | 25.2 | 10,416 | 16,039 | ~11.09 s | 96.0% | 99.4% | 98.8% | 99.4% |
| **gemma-4-12B-it-4bit** | 12B Dense | MLX | 11.5 | 18,612 | 27,259 | ~19.29 s | **100.0%** | **100.0%** | **100.0%** | **100.0%** |
| **Qwen3.8-27B-4bit** | 27B Dense | MLX | 8.8 | 39,324 | 56,839 | ~40.00 s | 93.0% | **100.0%** | **100.0%** | **100.0%** |

*\*Total Closed-Loop includes 670 ms search latency (native selective-strict engine) + 5.5 ms AST inspection + generation latency + 1.3 ms verification latency.*

---

## 3. Architecture Comparison: `jbcontext` vs `code-diver`

`jbcontext` functions exclusively as an AST slicing tool to provide raw candidate chunks. In contrast, `code-diver` provides an autonomous closed-loop engine that retrieves, slices, answers, and verifies source lines.

| Metric | `jbcontext 0.9.14` | `code-diver Local (Best)` (`gemma-4-e2b` / `Qwen3-Coder`) | `code-diver Cloud LiteLLM` (`gemini-3.5-flash-lite`) |
| :--- | :---: | :---: | :---: |
| **Execution Environment** | Local | **100% Local (Apple Silicon Metal)** | Cloud Proxy (LiteLLM) |
| **Search Hit@1** | 37.9% | **66.9%** (+29.0 pp) | **66.9%** (+29.0 pp) |
| **Search Hit@10** | 63.7% | **76.8%** (+13.1 pp) | **76.8%** (+13.1 pp) |
| **MRR@10** | 0.467 | **0.710** (+52%) | **0.710** (+52%) |
| **Search Latency (mean)** | 1,308 ms | **670 ms** (2.0x faster) | **670 ms** (2.0x faster) |
| **Search Latency (p95)** | 1,448 ms | **778 ms** (1.9x faster) | **778 ms** (1.9x faster) |
| **AST Inspection & Excerpt** | Slicing only | **5.5 ms** (Tree-sitter outline + read) | **5.5 ms** (Tree-sitter outline + read) |
| **Answer Generation Time** | *None* | **3.24 s** (`e2b`) / **7.58 s** (`Coder-30B`) | **1.78 s** |
| **Citation AST Verification** | *None* | **1.3 ms** | **1.3 ms** |
| **End-to-End Latency** | *Incomplete (chunks only)* | **~3.9 s** (Ultra) / **~8.2 s** (Coder MoE) | **~2.45 s** |
| **Citation Precision (Path/Line)** | *N/A* | **95.5% – 100.0%** | **100.0%** |
| **JSON Schema Adherence** | *N/A* | 94.0% – 98.0% | **100.0%** |

---

## 4. In-Depth Insights

### 4.1 MLX vs llama.cpp (Metal Runtime)
On identical quantized weights (`gemma-4-e2b` and `gemma-4-e4b`):
- **MLX delivers 14% to 19% higher generation throughput:**
  - `gemma-e2b`: 74.2 tok/s (MLX) vs. 65.4 tok/s (llama.cpp)
  - `gemma-e4b`: 43.2 tok/s (MLX) vs. 36.4 tok/s (llama.cpp)
- **MLX achieves significantly lower prefill latency:** The unified memory layout in MLX enables prompt processing times under 150 ms for ~1.5k token contexts.

### 4.2 MoE vs Dense Architecture on Apple Silicon
- **Dense 27B (`Qwen3.8-27B`):** Memory bandwidth limits generation to **8.8 tok/s**, yielding a 39.3s wait time.
- **MoE 30.5B / 3.3B active (`Qwen3-Coder-30B-A3B`):** Achieves **34.3 tok/s** with an average response time of **7.58s** (a **5.2x speedup** over dense 27B) while retaining large-model reasoning depth.
- **MoE 35B / 3.0B active (`Qwen3.6-35B-A3B`):** Delivered **100% path and line citation precision** with zero hallucinations across 223 extracted references.

### 4.3 Lightweight Edge Champions
- **`gemma-4-e2b-it-4bit` (MLX):** Sub-4-second full closed loop (**3.92s** total time), generating at **74.2 tok/s** with 96.6% citation accuracy. Perfect for real-time interactive CLI workflows.
- **`gemma-4-e4b-it-qat` (llama.cpp):** Exceptional precision (**98% schema valid, 100% grounded citations**) at a manageable ~8s turnaround.

### 4.4 Cloud Benchmarking
- **`gemini-3.5-flash-lite`:** Ultra-fast turnaround (**1.78s generation**, 128 tok/s) and flawless 100% schema and citation grounding.
- **`gpt-5.6-luna`:** Delivers comprehensive, detailed answers (**6.36s generation**, 80 tok/s) with 99.7% citation accuracy.

---

## 5. Artifacts and Reproduction
- Precomputed Contexts: `artifacts/research/precomputed_agent_contexts_100.json`
- Local MLX Tournament Data: `artifacts/research/local_llm_tournament_report.json`
- Local Extended Tournament Data: `artifacts/research/local_llm_tournament_extended_report.json`
- LiteLLM Cloud Report: `artifacts/research/litellm_cloud_benchmark_report.json`
- Runner Scripts:
  - `scripts/cache_agent_benchmark_contexts.py`
  - `scripts/run_local_llm_tournament.py`
  - `scripts/run_local_llm_tournament_extended.py`
  - `scripts/run_litellm_cloud_benchmark.py`
