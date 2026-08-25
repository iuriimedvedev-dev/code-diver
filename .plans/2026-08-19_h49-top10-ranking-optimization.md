# H49 — Top-10 Candidate Ranking Optimization and Loss Recovery

Date: 2026-08-19
Status: Pre-registered
Baseline / Champion: `configs/intellij/intellij-h46-preserve-top.yml` & `configs/context-awareness/protogen-h29-xenc-strict-cite.yml`
Target Corpora: IntelliJ Community (74 906 files, 1000 cases), Protogen (1911 files, 247 cases), CodeSearchNet Python (1000 cases)

## 1. Problem Statement & Motivation

The findings from H48 (pool depth sweep on IntelliJ Community 1000) established a clear decomposition of retrieval losses:
- **Pool Ceiling**: `recall@200 = 0.9665` (only 25/1000 cases fail to include the target file in the top-200 candidate pool).
- **Decomposition**: Candidate generation is *not* the primary bottleneck. The shortfall in `recall@10` (0.8958 – 0.9018) is **74.4% attributed to ranking / truncation loss** within the candidate pool, and only **25.6% to pool absence**.
- **First-relevant scattering**: In missed cases, the first relevant item is dispersed across bands (29% in positions 11–20, ~20% in each subsequent 20-candidate band up to 100).
- **The Cross-Encoder Dilemma (H38 vs H43 vs H46)**:
  - Raw cross-encoder reranking introduces distractor confusion, improving recall (+0.024) at the expense of top-1 ordering (MRR −0.052, nDCG −0.039).
  - H46's positional protection (`preserve_top_candidate: true`) recovers head ordering (MRR +0.0704, nDCG +0.0593), demonstrating that the first stage holds critical high-confidence signals that the cross-encoder occasionally overrides.
  - However, positions 2–10 remain vulnerable to distractor promotions when candidate pools are widened.

H49 systematically investigates methods to convert the available 0.9665 pool recall into top-10 precision and recall without sacrificing MRR or latency.

## 2. Experimental Arms & Hypothesis Design

H49 consists of three experimental arms designed to isolate candidate pool pressure, score calibration, and feature blending:

### Arm A: Rerank Pool Depth Sweep (candidate_limit ∈ [20, 30, 34, 40, 50])
- **Hypothesis**: The optimal cross-encoder candidate depth on large repositories lies in the 20–40 range. Deeper pools (>40) introduce noise and distractor competition that lower top-10 conversion, while shallower pools (<25) bottleneck recall supply.
- **Configurations**:
  - `candidate_limit: 20` (tight high-precision window)
  - `candidate_limit: 30` (lean default)
  - `candidate_limit: 34` (current reference)
  - `candidate_limit: 40` (extended candidate pool)
  - `candidate_limit: 50` (upper bound under latency limits)

### Arm B: Pre-Rerank Feature Fusion & Score Blending
- **Hypothesis**: The cross-encoder makes isolated pairwise judgements without repository context or multi-modal signal awareness (dense + BM25 + symbol match + path boost). Linearly blending normalized base hybrid scores with cross-encoder logit scores prevents catastrophic displacement of strong lexical/symbol matches by subtle semantic distractors.
- **Formulation**:
  `final_score = (1 - α) * normalized_cross_encoder_score + α * base_hybrid_score`
  where `α ∈ [0.0, 0.10, 0.20, 0.30]`.
- **Implementation Mechanism**:
  - Feature weighting inside `CrossEncoderRerankRetrievalStrategy._reranked`.
  - Margin-based skip / preservation triggers (`preserve_top_score_margin: 0.1`).

### Arm C: Multi-Tier Top-K Preservation
- **Hypothesis**: Extending top-candidate preservation from top-1 to top-k (or applying margin-based preservation where top candidate margin exceeds threshold `Δ >= 0.10`) stabilizes the head without penalizing bottom-window exploratory retrieval.
- **Evaluation Variants**:
  - `preserve_top_score_margin`: sweep across `[0.0, 0.05, 0.10, 0.15, 0.20]`.
  - `skip_when_top_margin_at_least`: evaluate early-exit when stage-1 margin is unambiguous (`Δ >= 0.25`).

## 3. Metrics & Pre-Registered Criteria

### Primary Metrics
- **`file_recall@10`**: Target ≥ 0.9150 on IntelliJ Community 1000 (recovering +0.015 of the 74% ranking loss).
- **`file_reciprocal_rank` (MRR@10)**: Target ≥ 0.8300 on IntelliJ Community 1000.
- **`ndcg@10`**: Target ≥ 0.8250 on IntelliJ Community 1000.

### Secondary & Guardrail Metrics
- **Anti-gaming / Distractor Guardrail**: `hit@1` must not drop below baseline H46 (0.750).
- **Latency Budget**: Mean search latency must remain ≤ 2.5 s/case on search-axis benchmark runs. Depth candidates causing > 20% latency increase without statistically significant recall gain (p < 0.05) will be rejected.
- **Protogen Answer Axis Guardrail**: `citation_expected_recall` ≥ 0.8171, `citation_fabricated_rate` ≤ 0.035.

### Refutation Conditions
- If no depth in [20, 50] achieves `recall@10 > 0.9050` or all depths > 34 degrade MRR by > 0.02, pure depth scaling is declared ineffective for large-repo retrieval.
- If feature fusion (Arm B) fails to outperform pure cross-encoder ranking at p < 0.05, score blending is rejected in favor of pure positional guards.

## 4. Validation Protocol & Execution Steps

1. **Step 1: Offline Replay Simulation**:
   - Replay reranker score distributions over cached H48 top-200 pools (`scripts/replay_rerank_depth.py` extended for score blending and margin thresholds).
   - Evaluate `recall@10`, `MRR@10`, `nDCG@10` over IntelliJ 1000 and Protogen 247 without incurring live model inference overhead.
2. **Step 2: Live Matched-Pair Search Runs**:
   - Execute live search evaluations on `datasets/intellij_eval_1000.answer_sets.jsonl` with fixed background machine state (idle generator, cold caches isolated).
   - Compute paired McNemar / Wilcoxon signed-rank tests against H46 baseline.
3. **Step 3: Multi-Corpus External Generalization**:
   - Test winning configuration on CodeSearchNet Python 1000 and Protogen 247 to verify cross-domain robustness.
4. **Step 4: Promotion Decision & Documentation**:
   - Update repository configuration defaults and record full campaign metrics in `.session/` log.
