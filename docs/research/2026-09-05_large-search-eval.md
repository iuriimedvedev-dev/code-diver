# R2 N192 paired H91a evaluation — 2026-09-05

**Execution complete; JOIN for parent review before independent QA/final acceptance. R2 loses; no promotion or label-driven algorithm changes. R1 deferred.**

## Design and fidelity

- Single-query search, actual H91a control A versus B replacing only first-pass indexed content with query-aware source fragments. The path/title/base-score envelope is unchanged; content ceiling850 (not a total rendered-document ceiling).
- Both inherit production second pass (floor0.3, cap24, content2400), adjustments, LightGBM meta-ranking and final preservation. No custom postprocessing or reconstructed champion approximation. Actual retries may differ under the identical policy.
- One real ordered34 pool per pair, snapshotted with full candidate content/metadata/scores. Each arm gets independent deserialized candidates, copied configuration and fan-in data, provider, feature extractor/cache and LightGBM Booster. No class-cached Booster is used by research arms. Sequential worker, 96AB/96BA; joint WHERE/novel strata balanced to within one.
- Frozen source selection: tokenize query and every line-start850-character source window, maximize distinct token overlap, earliest offset on ties; the historical stop-list is fixed. No labels enter extraction. Missing/unsafe/unreadable sources fall back to the exact baseline document, recording why.
- Four initial pytest setup errors came from a missing parent for the explicitly scoped temporary directory; corrected by creating that directory. Final expanded suite: **14 passed in2.06s**, covering invalid scores, unsafe paths, ceilings, pool/model/cache isolation, retry-zero/failure, deadline propagation, config rejection, deterministic selection and production parity.
- Live parity smoke: one real34 pool and two live production CE calls, then recorded-score replay through isolated unmodified A. First/retry requests, complete output objects and model-input features matched. This is not two independent live searches or a quality experiment.

## Frozen population, provenance and timing

Manifest frozen after tests/parity, before R2: **78WHERE +95 reconstructed novel −15 overlap +34 unique added mechanical guards =192**. Guard quotas use seeded proportional extension/top-level-family strata with largest-remainder allocation. Non-WHERE mechanical guards total40; selected mechanical total118/229. All original IDs and labels are retained.

The `where-editor-caret` answer set has three labels in WHERE versus four in full/mechanical; each slice is scored with its own labels. Overlapping slice counts are **not added**. Novel95 is **NOT an independent holdout of the historical model**. The full1065 exploratory regression was not run.

All192/192 pairs completed; failures0, not-started0, every pool34. Total campaign wall **2428.84s (40.48min)**, including the foreground segment boundary. Fixed deadline4200s; ETA at12 pairs3499s, at96 pairs2641s. Two foreground96-pair commands shared the original absolute deadline; no processes survive. Preflight tests/parity and offline reporting are outside campaign time. Initial interpreter imports/hash validation precede creation of the campaign checkpoint and are not included in that wall measurement.

Executor integrity checks passed: frozen code/config/data/model hashes, source hashes, pool hashes, exact A documents and both arms' production retry documents/policy. All6528 B first documents differed from A, with6528 readable source records and zero source fallback. Alias mappings remained identical across both segments and postflight; collection point count136578 before/after. The initial offline alias comparison included Qdrant's variable response-time field; corrected to compare actual mapping payloads, not request duration. No inference was repeated.

## Quality (exact-file hit@10 / MRR@10 / macro recall@10)

| Slice (overlapping) | N | Pool gold present | A hit | B hit | A MRR | B MRR | A recall | B recall |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Selected, full labels |192|168|0.8750|0.8646|0.7922|0.7210|0.8503|0.8338|
| WHERE labels |78|68|0.8718|0.8462|0.7066|0.5270|0.8186|0.7818|
| Novel, not independent |95|85|0.8947|0.8842|0.7984|0.8056|0.8886|0.8763|
| Non-WHERE mechanical guards |40|33|0.8250|0.8250|0.8125|0.7708|0.8167|0.8067|
| Selected mechanical labels |118|101|0.8559|0.8390|0.7425|0.6096|0.8158|0.7888|

Selected192 paired B−A deltas, bootstrap10000 replicates, seed42, percentile95CI:

- Hit: **−0.01042 [−0.02604,0]**; wins0/losses2/ties190. Lost hits: `where-git-rebase`, `where-attach-to-local-process`.
- MRR: **−0.07122 [−0.10658,−0.03713]**; wins8/losses34/ties150.
- Macro recall: **−0.01658 [−0.03333,−0.00382]**; wins0/losses8/ties184.
- WHERE MRR delta−0.17958 [−0.24686,−0.11553]; guards MRR−0.04167 [−0.09167,0], recall−0.01000 [−0.025,0]. Guard hit ties do not establish non-inferiority: seven guards have no exact gold in their pools, and the sample is small.
- Novel MRR improves slightly (+0.00726 [−0.02246,+0.03801]) but its hit/recall decrease; do not select this overlapping slice to reverse the overall conclusion.

Per-slice CIs/wins/losses, micro recall, pool-present diagnostic hit, missing-pair bounds,191 normalized-query and190 no-glob sensitivities are in `summary.json`. No missing pairs need imputation. Descriptive cluster bootstrap preserves the negative result:191 normalized-query clusters;179 shared-exact-answer/query connected components (largest2), full MRR CI[−0.10687,−0.03834]. This is not an independent-case significance claim.

## Latency and realized budgets

| Measurement, seconds (linear percentile; N192) | A p50 | A p95 | B p50 | B p95 |
|---|---:|---:|---:|---:|
| Rerank, including document construction and postprocessing |2.697|5.511|2.877|6.208|
| Reconstructed E2E: shared retrieval + arm rerank |8.167|14.213|8.569|14.593|
| First CE provider call |2.108|4.117|2.150|4.687|

Mean paired rerank delta **+0.171s** (A3.156s, B3.327s; +5.4%). Rerank p95 worsens12.7%. No favorable latency tradeoff offsets the quality loss.

- First-pass documents:6528/arm, content mean808.22A versus780.07B, maximum850. Total rendered first+retry characters9,270,176A versus8,793,773B (envelopes included).
- Retry documents1061A versus967B; counts differ in105/192 pairs. Mean5.526A versus5.036B. Retry buckets0/1–8/9–16/17–24: A71/70/26/25; B70/79/18/25. Actual token counts unavailable; equal ceilings are not equal realized tokens/cost.
- Shared retrieval is counted once per reconstructed E2E arm, once in campaign wall time. This is not independently measured standalone E2E. Per-arm setup/model construction is excluded from rerank and recorded separately (mean0.0047A/0.0052B seconds).
- Feature and model-prediction times, warm-excluding-first and AB/BA strata are retained. Source read/extraction and finalization are included but not separately timed. The services were not restarted; no service-cold claim. External exclusive-service ownership was not independently instrumented, so contention/cache/order effects remain possible.

## Commands and retained evidence

From project root, prefix all Python commands with `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python`:

1. `-m pytest -q -p no:cacheprovider --basetemp=artifacts/research/2026-09-05/large-search-eval/test-tmp tests/test_research_large_search_eval.py` —14 passed.
2. `scripts/research_large_search_eval.py smoke` —PASS; terminal timeout330s.
3. `scripts/research_large_search_eval.py prepare` —manifest frozen.
4. `scripts/research_large_search_eval.py run --max-pairs 96` —executed twice; terminal timeouts3600s and2800s, common campaign deadline4200s.
5. `scripts/research_large_search_eval.py summarize` —192 complete.
6. `artifacts/research/2026-09-05/large-search-eval/analyze_retained.py` —offline executor integrity/sensitivity PASS, no service inference. Frozen experiment runner/tests were not changed after the manifest.

Artifacts: `artifacts/research/2026-09-05/large-search-eval/` (~172MiB before archive), with manifest, parity smoke, per-call durable journal,192 atomic pair files, checkpoint, summary, offline analysis source/log and integrity/sensitivity JSON. Full candidate objects, rendered documents, scores, model input features/predictions, source offsets/hashes and timings are retained. No automatic deletion/resume or further inference is authorized.

Retention bundle created: `artifacts/research/2026-09-05/large-search-eval/evidence.tar.gz` (~29MiB), SHA256 `5914a00564fe444f2592740e50aa2768287e9b83008e1487cbdfdcd0d2f8320a`. Includes frozen runner/tests and raw/derived evidence, excluding disposable test files; report/session/plan remain separately in the project. Verified202 files (179,017,289 uncompressed bytes) byte-for-byte. Initial verification encountered macOS AppleDouble metadata; rebuilt with `COPYFILE_DISABLE=1`, then passed without excluded members. Git scope-delta check detected interface-generated `.output.txt` from truncated tool output, not an intentional project edit; left untouched. No other out-of-scope status delta from the frozen manifest.

| Artifact | SHA256 |
|---|---|
| Frozen runner |`f8d8f88b97b4fec241f3ab7ea73aa2ee85f55cf3b81cca8b9243870ed5992cda`|
| Tests |`3fe771ddb51741bbd213d66864a6c950dee568a00eda2b548867a3943deeb51a`|
| H91a config |`4052a6528a4643c615453aec8f8b7ba518a4b336ffdd059a23a6652cb3db24f9`|
| Manifest |`a579c628a5f1e96157dc6df8adc2c4713627d5582c550009a8496ed5d9738a13`|
| Checkpoint |`a924f9dcf606629e2abb979230af232f76e100e4a29d6221454b753e8667cdad`|
| Summary |`c97ee8ad4c1fd71c519ddb1893c9b618faf5c7507e6b25802f3c82b434fab4db`|
| Integrity/sensitivity |`50ad7bacb1019273e99d0e6cf7ae95db7a1ab8ef582d42991a0d457b48aed522`|

Manifest contains all dataset, source-code, graph, local GGUF, meta-model/manifest and lock hashes, resolved configuration, package versions and pre-existing git dirty state. Endpoint metadata and local GGUF hash do not certify the bytes actually loaded by the service or the entire indexed corpus. No immutable Qdrant snapshot was created.

**Retention/action:** artifacts are gitignored; parent must copy the evidence bundle to approved durable storage before worktree cleanup. Exclusive writable scope prevented an unapproved external copy. Production/champion/older scripts/tests were not modified; no installations, service restarts, paid APIs, training, R1 or promotion. Parent gate requires paired gain without critical guard regression: this run shows no overall paired gain. Join this executor handoff before independent QA and final architectural acceptance.

### Independent delegated QA — 2026-09-05

- Executed `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_research_large_search_eval.py tests/test_research_ce_evidence.py tests/test_research_candidate_budget.py tests/test_research_latency_independence.py`: **35 passed in 3.44s** (14 new +21 prior). `git diff --check`: exit0. Initial `uv run pytest -q tests/test_research_large_search_eval.py tests/test_research_ce_evidence.py tests/test_research_candidate_budget.py tests/test_research_latency_independence.py` failed before collection on HTTP404 for the pinned `vllm-metal` wheel; existing interpreter succeeded without dependency synchronization. No `uv.lock`/`pyproject.toml` diff.
- Read-only offline Python heredocs, invoked with `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -`, recomputed retained integrity/sensitivity and the complete summary in memory. For `analyze_retained.py`, the final artifact write was replaced in memory by an equality assertion; for `summarize()`, `atomic` was redirected to an in-memory comparison. No CE/bench, service requests, artifact replacement or inference occurred. Integrity/sensitivity matched exactly. The first raw-dictionary summary comparison failed because integer pool-size keys serialize as JSON strings; comparing JSON-normalized structures then matched exactly, including all metrics, CIs, latency distributions and denominators. This was a QA comparator issue, not a result discrepancy.
- Confirmed 192 unique manifest/checkpoint IDs, 192 complete/0 failures/0 errors/0 not-started, 96AB/96BA, and all192 individual pair files equal checkpoint entries. Report tables/CIs agree with recomputation at displayed precision: full hit0.87500→0.86458, MRR0.79225→0.72103, MRR CI[−0.10658,−0.03713], rerank p95 5.51050→6.20772s. Bundle SHA256 matches the value above.
- Denominator audit: planned192 remains fixed under partial completion; hit/MRR use all planned slice cases, macro recall uses cases with exact gold; missing-pair bounds are retained. Pool-present hit is conditional on observed retrieval pools, not an unconditional192-case estimate. Full checkpoint has no missing pairs. Slice overlap is explicit:78+95−15+34=192;40 non-WHERE mechanical includes six already selected novel cases;118 mechanical is not an additional cohort.191 deduplicated-query and190 no-glob sensitivities reproduce.
- **Selection caveat:** absence of all label-driven selection cannot be certified: `select()` lines87–89 uses the first sorted exact expected path to stratify guards by extension/top-level family, and novel membership derives from answer-overlap audit. This is frozen label-informed sampling, not label-blind sampling. No labels enter query-aware fragment scoring or either arm; no outcome-driven tuning appears in the frozen runner. Historical absence of tuning outside retained evidence cannot be proved.
- Production parity is bounded to the retained one-pool live-production/recorded-score replay (passed, runner hash matches), plus the passing fixture test; not independent live equivalence for every query. Offline validation confirmed frozen provenance, pool/source hashes, exact A documents and production retry documents for both arms. Independent deserialized candidates, copied config/fan-in, per-arm provider/extractor/Booster prevent mutable arm-state sharing. Actual external services/source filesystem remain shared; source hashes validate retained bytes, not an immutable corpus or cache isolation.
- No critical numerical/integrity discrepancy found. Remaining risks: label-informed/non-independent overlapping sample, uncontrolled service caches/contention, reconstructed rather than standalone E2E, missing tokenizer measurements, and gitignored evidence requiring durable retention. QA changed only this report and the designated session note; production/champion and results were not altered. **QA handoff ready for parent JOIN; final verdict belongs to parent.**