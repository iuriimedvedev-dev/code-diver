# Champion approach synthesis — reproduction aid for the jbcontext head-to-head

Date: 2026-08-25. Scope: what is our validated best config per corpus, what the numbers are,
where they came from, and how to re-run them. Primary source: `.session/2026-08-19_protocol-august.md`
+ `.plans/2026-08-12_h36-*` (Findings 63–70) + `.plans/2026-08-19_h49-*`. Every metric below was
re-read from the raw `metrics` object in `.code-diver/reports/*.json`, not copied from prose.

> **READ THIS FIRST — reproduction hazard.** Commit `b36ecb4` (2026-08-25 11:33) promoted
> `preserve_top_candidate: true` + `preserve_top_score_margin: 0.1` into **every** reference
> config. All published numbers below predate that commit. Consequence:
> * `intellij-h46-preserve-top.yml` scored 0.9018 with `preserve_top_score_margin` **absent**,
>   i.e. the code default `0.0` (`settings/defaults.py:231`) — an *unconditional* top-1 guard.
>   The file on disk today says `0.1` (conditional). **Re-running the file as-is is not
>   guaranteed to reproduce 0.9018.** To reproduce exactly, set the margin to `0.0`.
> * `protogen-h29-xenc-strict-cite.yml` (0.8171) and
>   `codesearchnet-h37-champion-xenc-1000.yml` (0.9730) were both measured with
>   `preserve_top_candidate: false`. The current files say `true`/`0.1`. **The promoted configs
>   have never been measured on protogen or CSN.**
> * There is also an uncommitted edit to `src/code_diver/strategies/graph_file_retrieval_strategy.py`
>   (the Finding 71 profile-sharing fix). It is argued to be behaviour-identical but has not
>   been shown byte-identical on an eval report.

---

## 1. Current champion, per corpus

Shared across all three: embedder **`mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ`** on
`:8001` (vllm, `--runner pooling --max-model-len 512`); cross-encoder
**`Qwen3-Reranker-0.6B-Q4_K_M.gguf`** via llama.cpp on `:8081` (`-b/-ub 768` — mandatory, see §3);
generator **`mlx-community/Qwen3.5-4B-OptiQ-4bit`** on `:8012` (answer axis only; search axis
does not touch it). Retrieval strategy id is `graph_file_cross_encoder` everywhere.
Common hyperparameters: `hybrid_search.candidate_limit: 360`, `lexical_candidate_limit: 1000`,
weights `vector 0.42 / lexical 0.26 / path 0.12 / symbol 0.10 / symbol_match 0.10 /
file_vote 0.06`, `hybrid_search.graph_weight: 0.0`, `fusion: weighted`, `lexical_scoring: bm25`,
`preserve_vector_top: true` with `vector_top_score_margin: 0.03`,
`graph_file_search` seeds `140/280`, `depth 2`, `neighbor_limit 40`, `decay 0.65`,
`cross_encoder_rerank.candidate_limit: 34`, `max_document_chars: 850`, `search.limit: 10`,
`evaluation.workers: 1`.

**Chain in plain English:** embed query → dense vector search over per-file
`file_summary` + `file_manifest` items (kind-capped 170/170, manifest multiplier 1.08) →
BM25 lexical scan over the whole catalog + path/symbol boosts → weighted fusion with the base
vector top-1 pinned if its margin ≥ 0.03 → **graph file-level propagation** (depth 2, import
adjacency; ON for protogen/CSN, OFF for IntelliJ) → cut to 34 candidates →
**Qwen3 cross-encoder rerank** with optional base-top-1 preservation → top 10 files.
Answer axis then appends: read 10 files × 160 lines → Qwen3.5-4B grounded answer with
`restrict_citations_to_context: true`.

### 1a. protogen (~1911 files) — the dev corpus

| axis | config | metric | value | source |
|---|---|---|---|---|
| answer (primary) | `configs/context-awareness/protogen-h29-xenc-strict-cite.yml` | `citation_expected_recall` | **0.8171** | `protogen-h29-xenc-strict-cite-247-cf10-cl160.json` |
| | | `citation_expected_precision` | 0.3675 | same |
| | | `citation_fabricated_rate` | 0.0268 (bound 0.035) | same |
| | | `file_recall` (shown @10) | 0.8354 | same |
| | | `answer_duration_ms_mean` | 45 280 ms/case | same |
| search | `configs/context-awareness/protogen-h45-search-graph-on.yml` (H45a) | `file_recall@10` | **0.8246** | `protogen-h45-search-graph-on-247.json` (2026-08-19) |
| | | `mrr@10` | 0.6492 | same |
| | | `ndcg@10` | 0.6661 | same |
| | | `hit_rate@1` | 0.5344 | same |
| | | `hit_rate@10` | 0.8907 | same |
| | | `search_duration_ms_mean` | 2 214 ms | same |

Differentiator vs IntelliJ: **`graph_file_search.graph_weight: 0.45`** (graph ON). Also carries
`doc_summary/doc_manifest/doc_chunk` kinds (limits 36/24/48, multipliers 0.72/0.58/0.64) that
the other two corpora do not have. Qdrant collection `code_diver_h17_ctrl`, graph artifact
`.code-diver/protogen-h17-ctrl.json`, embedding prefixes are corpus-specific
(`"Represent this code and repository documentation search query: "` /
`"...file-level code or documentation metadata for retrieval: "`), `max_input_chars: 400`.

H45a (graph ON) beats H45b (graph off + xenc, 0.7598) by +6.48 pp recall and H45c (graph off,
no xenc, 0.7861) by +3.85 pp — all three verified from the report files. Note H45a ran
2026-08-19; H45b/H45c ran 2026-08-14 — all three predate `b36ecb4`, so they are a fair
matched set at `preserve_top_candidate: false`.

### 1b. IntelliJ Community (74 906 files, 1000 cases) — the large-repo champion

Config: `configs/intellij/intellij-h46-preserve-top.yml` (supersedes h37 and h38).

| metric | value | source |
|---|---|---|
| `file_recall@10` | **0.9018** | `intellij-h46-preserve-top-1000.json` (2026-08-14 13:28) |
| `recall@10` (any-expected) | 0.9109 | same |
| `mrr@10` | **0.8200** | same |
| `ndcg@10` | **0.8318** | same |
| `hit_rate@1` | 0.742 | same |
| `hit_rate@10` | 0.931 | same |
| `file_precision@R` | 0.7512 | same |
| `file_recall@200` (pool ceiling) | **0.9665** | `intellij-h48-pool-depth-1000.json` (H48, `search.limit: 200`) |
| `search_duration_ms_mean` | 8 278 ms — **treat as void**, see §3 | same |

Differentiators: **`graph_file_search.graph_weight: 0.0`** (graph OFF — H38, worth +5.6 pp
recall, p=7.3e-10), **`cross_encoder_rerank.preserve_top_candidate: true`** (H46), Qdrant
collection `intellij_community_file_manifest_local_qwen`, graph artifact
`.code-diver/intellij-h37-jvm-graph.json` (JVM-aware rebuild, 1 157 273 edges / 1 081 652
cross-file), **no embedding prefixes**, `max_input_chars: 500`, `embedding.workers: 4`,
no `doc_*` kinds. Dataset `datasets/intellij_eval_1000.answer_sets.jsonl`.

Reference arms on the same 1000 cases (all verified from reports): H37 champion port 0.8397 /
MRR 0.7320 / nDCG 0.7457; H38 graph-off 0.8958 / 0.7496 / 0.7725 at 10 939 ms;
H43 graph-off no-xenc 0.8716 / **0.8020** / **0.8110** at **1 994 ms**.
A historical June `deterministic_postrank_h2` run scored `file_recall@10` **0.9025** —
higher than H46's 0.9018 — but on a different harness/strategy, so it is not a matched pair
and is not the champion. **Flag: H46 has not been shown to beat that June number.**

**If jbcontext is compared on latency-sensitive interactive use, H43 is arguably the better
arm to show**: 4.2× faster than H46 with only −0.030 recall, and it wins hit@1-adjacent
ranking on nDCG/MRR nearly as well. Task #37 (recall-first vs precision-first default) is
still open precisely because of this.

### 1c. CodeSearchNet Python (1000 cases)

Config: `configs/benchmarks/codesearchnet-h37-champion-xenc-1000.yml`.

| metric | value | source |
|---|---|---|
| `file_recall@10` = `hit_rate@10` | **0.9730** | `codesearchnet-h37-champion-xenc-1000-postfix.json` |
| `mrr@10` | 0.8952 | same |
| `ndcg@10` | 0.9148 | same |
| `hit_rate@1` | 0.840 | same |
| `search_duration_ms_mean` | 3 563 ms | same |

`-postfix` = after the 512-token reranker fix (Finding 66). **Do not cite the pre-fix
`codesearchnet-h37-champion-xenc-1000.json` (0.9700) — 22% of its cases were silently never
reranked.** Store is JSON (not Qdrant): index
`.code-diver/benchmarks/mteb-codesearchnet-python/index-h10-graph-file-qwen3-0_6b-quality.json`.
`max_input_chars: 900`, prefixes as in base `code-diver.yml`. `graph_weight: 0.45` is set but
**structurally inert** (1000 standalone files, zero cross-file edges) — it is an additive
constant, so CSN measures the seed mixture + cross-encoder only.

**Contradiction to flag:** this is *not* our best CSN result. `.session/2026-07-29_research-results-audit.md`
records, on the same 1000-case slice: H9 body-evidence bounded (embeddinggemma-300m)
FH@10 **0.986** / nDCG **0.930** at **1 601 ms**, and H7 + Gemini-Lite rerank FH@1 **0.911** /
FH@10 **0.989** / nDCG **0.956**. Finding 64 states plainly that the champion is *off the CSN
Pareto frontier*. For a fair external comparison, show both the champion and the actual best
CSN config, or pick CSN's own best.

---

## 2. Confirmed / refuted / open

| H | Verdict | One line |
|---|---|---|
| H15 | Mechanism CONFIRMED, primary null | Context budget 4→10 moved bundle-completeness, not `answer_grounded`. |
| H16-C | **REFUTED** | Rerank ablation loses 0.145 recall. Rerank stays. |
| H17 | **REFUTED** (as stated) | The lean-rebuild gain was vendor removal, not embedding truncation caps. |
| H28/H29 | **PROMOTED** | Cross-encoder replaces LLM rerank; citation allowlist fixes the fabrication guardrail. Protogen champion. |
| H32-A | **REFUTED** at 247 cases | Cut 14 → +0.0162, CI covers zero. Cut stays 10. |
| H33 | **REFUTED** | Directory-cluster diversity. |
| H34 | CLOSED | Fusion/weights axis at its optimum. |
| H36 | **REFUTED** | Deeper rerank pool (34→100) *loses* recall; conversion falls 91.5%→82.3%. Don't retry depth on protogen. |
| H37 | **REFUTED** (generality) | Protogen champion does not transfer: IntelliJ 0.8397 vs 0.9025 at 1.56× latency; CSN off-Pareto. |
| H38 | **CONFIRMED / PROMOTED** | Graph OFF on JVM repos: +0.0561 recall (p=7.3e-10). |
| H39 | **REFUTED** | Lexical seed scan is not the latency villain (732 ms) and is load-bearing (−0.19 recall without it). |
| H40 | **REFUTED** twice | 34-candidate pool is not too narrow. |
| H41 | CONFIRMED-inverted | Cross-encoder mostly repairs the graph's own damage. |
| H42 | CONFIRMED (direction) | On CSN the reranker is 67–85% of runtime. |
| H43 | **CONFIRMED** | Cross-encoder buys recall (−0.024 without it) and *costs* head order (nDCG +0.039, MRR +0.052 without it). Genuine split. |
| H44 | CONFIRMED (recall half) | CSN xenc-off: recall −0.008 n.s. for 85% of the runtime. Ranking degrades though (unpredicted). |
| H45a | **VOID → RESOLVED, CONFIRMED** | Original run was a defect (240/247 empty). Fixed + re-run 2026-08-19: graph ON wins on protogen, 0.8246. |
| H45b/H45c | Measured, n.s. between them | 0.7598 / 0.7861, p=0.405. |
| H46 | **CONFIRMED / PROMOTED** | Preserve base top-1 through the xenc: recall +0.006 (0 worse), MRR +0.0704, nDCG +0.0593. IntelliJ champion. |
| H47 | **OPEN** | Raw `score={:.6f}` printed into the answer prompt ⇒ exact answer-axis replay impossible. |
| H48 | **PASS** | `file_recall@200 = 0.9665`; the recall@10 shortfall is 74.4% ranking, 25.6% pool-absence. |
| H49 | **PENDING / pre-registered only** | Three arms (depth sweep 20–50, score blending α, multi-tier margin sweep). Not executed. |
| Finding 63 | Defect fixed | `graph_weight` had never had a graph on any JVM repo. |
| Finding 66 | Defect fixed | Reranker 512-token silent-failure ceiling; needs `-b/-ub 768`. |
| Finding 68 | Self-**REFUTED** twice | Neither `ubatch 4096` nor 36 GB swap explains H38's wall clock. All H38/H46 latency figures void. |
| Finding 69 | CONFIRMED | Search-axis replay is deterministic on IntelliJ (999/1000 byte-identical). |
| Finding 71 | CONFIRMED + fixed | Per-process cold-start tokenization tax; 209.3 s → 140.1 s. |

Also note H49's own pre-registered nDCG target (≥ 0.8250) is **below** the H46 baseline it is
supposed to beat (0.8318), and its stated H46 hit@1 baseline (0.750) does not match the report
(0.742). The plan's numeric targets need re-derivation before execution.

---

## 3. Known ceilings and weaknesses a fair comparison must account for

1. **Ranking, not retrieval, is the IntelliJ ceiling (H48).** Pool@200 holds the answer 96.65%
   of the time; only 25/1000 cases are unreachable. 74.4% of the recall@10 gap is ordering
   loss. The first-relevant file is *scattered* (29% at rank 11–20, ~20% per band out to 200),
   so no window widening recovers it. Realistic near-term ceiling at top-10 is ~0.93–0.95.
2. **Cold-start tax (Finding 71) — the single biggest fairness issue for an interactive
   comparison.** Every fresh CLI process pays a one-time, in-memory-only, per-process
   tokenization/BM25-build cost before the *first* result: **140.1 s at IntelliJ scale**
   (149 614 catalog items; was 209.3 s before the fix) and roughly **~5 s on protogen**. All
   published numbers are *batch* (1000 cases/process) where this amortizes to ~0.14–0.2 s/case
   and is invisible. A live single-query `code-diver search`/`answer` on IntelliJ is therefore
   ~140 s slower than the reported 8.3 s/case. Disk-persisting the BM25/profile build (the
   obvious fix, mirroring `FileGraphCatalogStore`) is **not implemented**.
3. **All champion latency numbers are void or suspect.** Finding 68 voided H38's wall clock
   twice (swap, then QoS throttling), and by extension H46's 8 278 ms/case carries the same
   caveat: it was measured in a sequential campaign on a shared machine. Standing rule: latency
   and quality never share an arm; latency needs an idle machine and ~150 cases. The only
   trustworthy relative latency signal is H43's ~2.0 s/case vs H46's ~8.3 s/case ordering.
4. **The promoted configs are unmeasured** (see the banner). If the comparison runs the files
   as they sit on disk today, none of protogen/CSN's headline numbers are the expected output.
5. **Corpus-native tuning beats porting.** Finding 64: the champion's *absolute level* transfers
   (0.8354 protogen ↔ 0.8397 IntelliJ) but its *advantage* does not. Any single "our config"
   claim across three corpora is unsupported — the graph must be ON for protogen and OFF for
   IntelliJ.
6. **Reranker fragility.** With `-ub 512` the reranker silently returns base order for the whole
   request on any query+doc pair over 512 tokens (was 22% of CSN cases). Confirm `-b/-ub 768`
   and zero rerank-failure warnings before trusting any run.
7. **Answer axis has no external validation.** Task #45 is open: 0.8171 exists only on protogen.
   There is no IntelliJ answer-axis number to compare against jbcontext.
8. **Answer-axis replay is not deterministic** (H47, Finding 50a). Search axis is (Finding 69).
9. **Corpus caveats.** CSN has 1 expected file/case, so recall@10 ≡ hit@10 and moves in 1/1000
   steps. protogen 247 has `multi_expected_rate` 0.38 (mean 1.39 expected files); IntelliJ 1000
   has 0.071 (mean 1.28) — recall@10 is not comparable across corpora.

---

## 4. Reproduction recipe

**Servers** (start from repo root; each script guards its port and refuses to double-bind):

```bash
scripts/serve_embedder.sh    # :8001  vllm, Qwen3-Embedding-0.6B-4bit-DWQ, --max-model-len 512
scripts/serve_reranker.sh    # :8081  llama-server, Qwen3-Reranker-0.6B-Q4_K_M, -b/-ub 768
scripts/serve_generator.sh   # :8012  mlx_lm, Qwen3.5-4B-OptiQ-4bit  (ANSWER AXIS ONLY)
scripts/serve_judge.sh       # :8030  gemma-4-12B  (only if --judge)
# plus Qdrant on :6333 for protogen + IntelliJ (CSN uses a local JSON store)
```
Search-axis runs must have `:8012` and `:8030` **stopped** (Finding 37/68). Log `vm.swapusage`
before and after each arm; a latency claim without machine state is not evidence.

**Search axis** (writes the same JSON shape as every report cited above):

```bash
# IntelliJ champion — target file_recall@10 0.9018, MRR 0.8200, nDCG 0.8318, hit@1 0.742
# NOTE: set cross_encoder_rerank.preserve_top_score_margin: 0.0 to match the 2026-08-14 run.
code-diver --config configs/intellij/intellij-h46-preserve-top.yml evaluate \
  --dataset datasets/intellij_eval_1000.answer_sets.jsonl --limit 10 --json \
  > .code-diver/reports/intellij-h46-preserve-top-1000-repro.json

# IntelliJ pool ceiling — target file_recall@200 0.9665  (config: intellij-h48-pool-depth.yml)
code-diver --config configs/intellij/intellij-h48-pool-depth.yml evaluate \
  --dataset datasets/intellij_eval_1000.answer_sets.jsonl --limit 200 --json > .../h48-repro.json

# protogen search axis — target file_recall@10 0.8246 (set preserve_top_candidate: false to match)
code-diver --config configs/context-awareness/protogen-h45-search-graph-on.yml evaluate \
  --dataset datasets/protogen_eval_247.jsonl --limit 10 --json > .../h45a-repro.json

# CodeSearchNet — target file_recall@10 0.9730 (set preserve_top_candidate: false to match)
code-diver --config configs/benchmarks/codesearchnet-h37-champion-xenc-1000.yml evaluate \
  --dataset .code-diver/benchmarks/mteb-codesearchnet-python/codesearchnet_python_1000.jsonl \
  --limit 10 --json > .../csn-repro.json
```

**Answer axis** (protogen only; needs `:8012`). Report suffix `cf10-cl160` encodes the flags:

```bash
code-diver --config configs/context-awareness/protogen-h29-xenc-strict-cite.yml evaluate-answers \
  --dataset datasets/protogen_eval_247.jsonl --context-files 10 --context-lines 160 \
  --output .code-diver/reports/protogen-h29-xenc-strict-cite-247-cf10-cl160-repro.json
# targets: citation_expected_recall 0.8171, citation_expected_precision 0.3675,
#          citation_fabricated_rate 0.0268, file_recall 0.8354, ~45.3 s/case
```

**Interactive single query** (this is what a live jbcontext comparison should time, and where the
Finding 71 tax shows up):
```bash
code-diver --config <champion.yml> search "<question>" --json --limit 10
code-diver --config configs/context-awareness/protogen-h29-xenc-strict-cite.yml answer "<question>" --json
```

**Pairing / analysis:** `scripts/compare_arm_runs.py` for paired sign tests on `case_id`;
`scripts/clobber_guard.py` before writing any report (and guard the `.partial` sibling too);
`scripts/audit_index_staleness.py` before trusting a collection you did not just build;
`scripts/replay_rerank_depth.py` for offline depth/blending screens (treat replay recall as
**comparative only** — it sits ~0.027 below live).
