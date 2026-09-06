# Comprehensive Research Protocol: Code Retrieval & Agentic Search Optimization

**Date**: 2026-09-02  
**System**: `code-diver` vs `jbcontext` (IntelliJ Community Repository)  
**Lead Architect Protocol**: Architectural Decisions, Experimental Log, Falsified Hypotheses, and Current State  

---

### 1. Executive Summary

This protocol synthesizes the full experimental cycle conducted on repository-scale semantic and lexical code search, evaluating `code-diver` against `jbcontext` on the IntelliJ Community codebase. 

Key high-level conclusions:
1. **The Retrieval Bottleneck is Intermediate Rank Consolidation, Not Index Capacity**: Diagnostic tracing demonstrated that **98.7% (78/79)** of relevant targets are captured in the initial retrieval union (`vector ∪ BM25`). The pool ceiling at depth 200 is **0.923**. Losses occurred during cross-lane score fusion and cross-encoder truncation.
2. **Signal Density Wins Over Document Volume**: Expanding context windows (`H-70` 500 chars -> 1800 chars / 512 tokens; `H-78` cross-encoder 850 -> 1600 chars; `H-64` AST chunks) consistently degraded retrieval performance by diluting dense vector space and inflating convincing distractors.
3. **Validated Production Gains**:
   - `H-66b`: Structure-first manifest payload + stop-word stripping (+0.06 recall).
   - `H-77`: Seed score parity in graph-file fusion (+0.036 recall, +3 hits).
   - `H-83`: Conditional two-pass Cross-Encoder for sub-floor truncation victims (+0.022 recall, +2 hits).
4. **Current Champion State**: `intellij-h66b-champion.yml` achieves **0.6444 recall@10** and **0.3753 MRR@10** on the cleaned `WHERE-78` benchmark, outperforming `jbcontext` on ranking precision (MRR `0.3753` vs `0.3499`, Hit@1 `0.2308` vs `0.1923`).
5. **Search vs. Agent Distinction**: Evaluations against `jbcontext` were strictly **search-tool vs search-tool CLI**, not agent-in-loop. Testing agent orchestrators revealed that multi-round agentic verification (`H-74` tool loop with read/grep) suffered severe degradation (`0.3598` recall), while parallel multi-query fan-out with LLM tail re-ranking (`H-75`) reached **0.6904 recall@10 (59/78)**, closing the gap with `jbcontext` live (`0.7370 / 61/78`).

---

### 2. Systematic Value Funnel Diagnostic (WHERE-79 Benchmark)

To isolate failure modes, full candidate tracing was instrumented across all pipeline stages:

| Stage | Candidates Retained | Target Losses | Primary Loss Mechanism |
|---|---:|---:|---|
| **Vector `file_summary`** (top 170) | 72 / 79 | — | Dense semantic match |
| **Vector `file_manifest`** (top 170) | 73 / 79 | — | Structural symbol/path match |
| **Vector Union** | 77 / 79 | 2 | Semantic/structural coverage |
| **BM25 Lexical** (top 1000) | 74 / 79 | 5 | Exact term matching |
| **Retrieval Union (`Vector ∪ BM25`)** | **78 / 79 (98.7%)** | **1** | Only 1 target was unindexed (excluded by scan filter) |
| **Hybrid Fusion (140 pool)** | 74 / 79 | 4 | Fused trim & kind-cap interactions |
| **Graph-File Candidate Scorer** | **60 / 79** | **14** | **Critical Defect**: Structural zeroing of lexical/path/symbol for vector-only candidates |
| **Cross-Encoder Input -> Top-10** | **51 / 79** | **9** | Document truncation (850 chars) + score saturation ties |

**Dataset Hygiene Finding**: Analysis revealed 2 invalid benchmark targets: 1 deleted file (`EditorCaretMoveProcessor.kt`) and 1 generated file excluded by design (`gen/JsonParser.java`). Cleaning the dataset established the clean `WHERE-78` ground truth.

---

### 3. Chronological Experimental Waves & Results

#### Wave A: Index Representation & Volume (H-52 to H-70)
- **`H-59` File Purpose Vector**: Generating an explicit LLM purpose vector per file -> **Flat (0.000 Δ)**.
- **`H-62` Raw File Content in CE**: Feeding raw source code instead of summaries to Cross-Encoder -> **Degraded (-0.02 to -0.07)**.
- **`H-64` Chunk-Level Index**: Indexing class and method chunks (+70% index footprint) -> **Statistically insignificant (+0.006)**.
- **`H-66b` Information Density Structuring**: Restructuring manifests to put purpose and terms first, truncating path noise, and stripping boilerplate -> **Promoted (+0.06 recall)**.
- **`H-70` Extended Token Window**: Raising embedding character cutoff from 500 to 1800 chars (512 tokens) -> **Degraded (WHERE-79 recall 0.6120 -> 0.5508, p95 +1.8s)**. Proved that compact 500-char text acts as a high-precision filter; verbosity causes vector drift toward corpus centroids.

#### Wave B: Lane Scoring Parity & Learning to Rank (H-77 to H-80)
- **`H-77` Seed Score Parity**: Scored lexical, path, and symbol features on cached profiles for vector candidates instead of injecting zeros -> **Promoted (+0.036 recall, hit@10 51 -> 54/79)**.
- **`H-78` Global CE Expansion**: Increasing Cross-Encoder window globally to 1600 chars / 80 candidates -> **Degraded (hit@10 54 -> 50/79)** due to distractor inflation.
- **`H-80` Learned-to-Rank (LTR LambdaRank)**: Training LightGBM GBDT ranker on 13 retrieval features -> **Degraded (WHERE recall 0.6120 -> 0.5808, MRR 0.3679 -> 0.2868)**. The model overfitted to rank-derived features (`fused_score_gap_to_top`), adding variance to decisions already resolved by cross-encoding.

#### Wave C: Fusion Surgery & Cross-Encoder Precision (H-81 to H-85)
- **`H-81` Fusion Width & Kind Cap Fix**: Enabling 360-candidate hybrid pool + preserving per-kind vector tops -> **Flat (0.6199 vs 0.6220)**. Targets died before the CE input cut.
- **`H-82` CE Logit Inversion & Fused Tie-Break**: Logit ranking and graph-score tie-breaking -> **Flat (0.6220)**.
- **`H-83` Conditional Two-Pass CE**: Re-scoring only candidates below floor 0.3 with a 2400-char window using `max(first, second)` -> **Promoted (WHERE-78 recall 0.6220 -> 0.6444, hit@10 54 -> 56/78, MRR 0.3753)**. Successfully rescued truncation victims without inflating distractors.
- **`H-84` Multi-Query RRF v1**: Full retrieval+CE pipeline across 4 query variants with post-CE RRF -> **Killed (recall 0.6327, MRR 0.3266, 2.7x latency)**.
- **`H-85` Combination Arm**: H-81 + H-82 + H-83 -> **Redundant (0.6423, no improvement over H-83 alone)**.

#### Wave D: Pre-CE Fusion & Agent Orchestration (H-84v2 & H-86)
- **`H-84v2` Pre-CE Multi-Query RRF**: Fan out query variants, union candidates via RRF into a 34-candidate pool, then execute a single Cross-Encoder pass -> **Killed (recall 0.6188, hit@10 54/78, 10.95s)**. Inferior to single-query champion.
- **`H-86` Agent Evaluation on Champion Retrieval Stack**:
  - `h74_agentic_h3_gpt4omini` (5-round loop with grep/read tools): **Collapsed to 0.3598 recall@10 / 33/78 hit@10**.
  - `h76_union_ce_q4` (4 query fan-out with CE union): **0.6081 recall@10 / 53/78 hit@10**.
  - `h75_fanout_champion_llmrerank_monotonic` (LLM fan-out + parallel champion search + LLM tail re-ranking): **0.6904 recall@10 / 59/78 hit@10 / 0.3770 MRR**.

---

### 4. Empirical Performance Matrix (WHERE-78 Benchmark)

All models evaluated under consistent conditions on the cleaned 78-query dataset:

| Architecture / Arm | Modality | Recall@10 | MRR@10 | Hit@1 | Hit@10 | Mean Latency | Status |
|---|---|---:|---:|---:|---:|---:|---|
| **H-66b + H-77 Baseline** | Search CLI | 0.6220 | 0.3726 | 0.2308 | 54 / 78 | 4.8s | Superseded |
| **H-81 Fusion Width** | Search CLI | 0.6199 | 0.3689 | 0.2308 | 54 / 78 | 4.8s | Rejected |
| **H-82 CE Logits** | Search CLI | 0.6220 | 0.3726 | 0.2308 | 54 / 78 | 5.1s | Rejected |
| **H-83 Two-Pass CE (Champion)** | Search CLI | **0.6444** | **0.3753** | **0.2308** | **56 / 78** | 5.8s | **Production Champion** |
| **H-84 Multi-Query RRF v1** | Search CLI | 0.6327 | 0.3266 | 0.1923 | 54 / 78 | 13.2s | Rejected |
| **H-84v2 Pre-CE Multi-Query** | Search CLI | 0.6188 | 0.3690 | 0.2436 | 54 / 78 | 10.9s | Rejected |
| **H-86: h74 Agentic Loop (5 rounds)** | Agent (Read) | 0.3598 | 0.2098 | 0.1410 | 33 / 78 | 15.7s | Rejected |
| **H-86: h76 Union CE (4 queries)** | Agent Fan-Out| 0.6081 | 0.3662 | 0.2436 | 53 / 78 | 37.1s | Rejected |
| **H-86: h75 Fan-Out + LLM Rerank**| Agent Fan-Out| **0.6904** | **0.3770** | **0.2308** | **59 / 78** | 42.8s | **Best Agentic Arm** |
| *jbcontext FAST (Historical Recomputed)* | Search CLI | 0.6831 | 0.3445 | 0.2179 | 57 / 78 | ~1.5s | Reference |
| *jbcontext 0.9.11 (Live Run)* | Search CLI | **0.7370** | 0.3499 | 0.1923 | **61 / 78** | 1.89s | External Target |

---

### 5. Architectural Findings & Strategic Takeaways

1. **Precision Dominance vs. Recall Lag**:
   - `code-diver` consistently dominates `jbcontext` on rank quality: **MRR 0.3753 vs 0.3499**; **Hit@1 0.2308 vs 0.1923**. When `code-diver` finds a target, it places it higher than `jbcontext`.
   - `jbcontext` maintains a recall advantage on single-pass CLI retrieval (61 vs 56 hits out of 78).
2. **The Verification Loop Trap**:
   - Allowing an LLM agent to inspect files via `read` / `grep` (`h74`) resulted in severe catastrophic degradation (33/78 hits). The LLM repeatedly hallucinated refutations or over-focused on peripheral references, discarding true target entry points.
   - Verification loops in open code search must be tightly constrained by deterministic bounds rather than open LLM reasoning turns.
3. **Fan-Out + Listwise Re-ranking Closes the Recall Gap**:
   - Fan-out with LLM re-ranking (`h75`) achieves **59/78 hits (0.6904 recall@10)**, closing within 2 hits of live `jbcontext` while preserving superior MRR (`0.3770`).
   - The trade-off is latency (~42s vs ~1.9s), making it suitable for asynchronous deep search modes rather than interactive IDE completions.
