# Full 1065 paired E2E selective second pass

Execution outcome: parent-approved metadata contract implemented; 16 tests and smoke4/parity passed. Attempt-03 froze1065 and genuinely ran34 pairs,33 complete before critical champion second-pass HTTP500. Stopped fail-closed without retry, promotion or deadline extension. ETA32 was6.62h. Parent/independent QA handoff required; see current report/session. Attempt-02 and original blocked evidence retained.

Parent authorization (continuation): ignore only integer data[*].created and, for embedding only, string data[*].permission[*].id and integer .created values. Preserve keys, types, list lengths and all other fields strictly; retain raw differences. This does not prove loaded weights equivalence. Retain original evidence unchanged; use attempt-02. Build two production retrieval stacks and isolated meta boosters once per foreground segment, instrument without replacing A behavior, and bind only S's second-pass override. Four balanced smoke pairs precede the main deadline and are never counted as main observations. Stop on any critical error or other drift.

1. Establish frozen H91a baseline provenance before implementation or measurement. Hash actual dependencies, configuration, models and datasets; stop if the frozen baseline cannot be verified or differs. Never describe the dirty checkout as a clean champion.
2. Add core and negative tests, then implement a separate research runner. Independent warm production search lifecycles per arm; shared external services/index only. A uses production behavior; S overrides only the frozen evidence-filtered second pass (0.3, cap 24, 850 to 2400, no refill), without access to labels.
3. Freeze all 1065 IDs and deterministic AB/BA ordering (533/532). Preserve exact scoring and overlapping WHERE78/mech229 slices. Record setup separately from full wall search, rerank timing, retries, errors and missing bounds.
4. Validate unit tests and four balanced full smoke pairs outside the measured population. Start the main run with a 32-pair ETA gate, bounded foreground chunks and fail-closed resume/checkpoints after every pair. Enforce one shared seven-hour deadline without extensions.
5. Report fixed-denominator and paired-complete quality, latency and seeded 10000-resample uncertainty. Archive hashed evidence, explicitly identify gitignored files, avoid promotion and hand off for independent QA. Stop on baseline drift or critical errors without quality-driven tuning.

## HTTP500 observability repair and fresh runtime handoff

Offline repair only: no inference, service management, production edits or shared-runner edits. A local RecordedProvider subclass records UTC request start/end, a local correlation UUID (not sent to the server), allowlisted response headers including server request IDs when available, HTTP status, at most 4096 body bytes, truncation and traceback. Production urllib HTTPError reads at most 4097 bytes; httpx diagnostics use already-buffered content and never force an unread stream. Authorization/cookies are excluded from headers; body/traceback evidence is diagnostic data, not guaranteed secret-free. The original exception is re-raised; swallowed production rerank failures still make the pair incomplete. No retry was added.

Reproduction: the initial diagnostic test failed before implementation; the real production urllib provider path was then reproduced offline and failed with missing status before urllib support. Final targeted suite: **24 passed**. Coverage includes original exception identity, body bounds, safe headers, unread-body diagnostic failure, wrapped/non-HTTP errors, swallowed errors failing closed, fresh attempt overwrite rejection, and smoke-only / bounded main checkpoints. Offline verification confirmed the same 357 production/model/data hashes, unchanged policy and resolved configuration against the historical manifest. Repair freeze: `artifacts/research/2026-09-05/full-e2e1065-selective-second-pass/diagnostics-repair-01/freeze.json`. This is not a runtime manifest or server-readiness claim.

### Required ordering / QA gates

1. Independent QA reviews the repaired runner/tests and freeze. Parent MUST join the separate server-fix agent before any smoke or evaluation, confirm the fix and runtime provenance, and authorize execution. No server config is in this executor's scope. Loaded-weight equivalence remains unproven.
2. Keep attempt-03 and its 33 completed pairs immutable and separate. Never resume or import its evidence into the new runtime. `--attempt attempt-04` creates a new directory exclusively; an existing directory is an error, not an overwrite. Use a higher unused attempt number if necessary, consistently in all commands. `--resume` requires an existing manifest/checkpoint and only accepts an intentional segment boundary with unchanged hashes and pair evidence. Failed attempts are terminal.
3. Freeze new runner/tests in the fresh attempt manifest while retaining exactly the previous 357 hashes and policy. Every invocation retains dependency/version/config/cache/model-metadata gates. Fresh service metadata is checked against the approved attempt-02 metadata contract; do not rerun/overwrite its preflight file or loosen gates for the server fix.
4. Run smoke4 with exact production replay parity, outside the 1065 population. Smoke-only leaves `started_at` unset. Inspect all four complete smoke records before authorizing main measurement. The next invocation performs the existing per-segment warmup.
5. Run the first 32 main pairs with the ETA gate, then successive foreground chunks of at most 128 pairs. Segment alarm: 3300 seconds; reserve: 240 seconds; one seven-hour wall deadline from main `started_at`, including subsequent setup, warmup and pauses, never reset on resume. Initial smoke is excluded as previously authorized. Dependency freeze/checks happen before the segment alarm; leave external command timeout headroom. Checkpoint after every pair; only `segment_boundary` may continue. Stop on blocked/error, ETA overflow, hard cap or completed. No background process, daemon, automatic retry or automatic loop.
6. Final QA checks service-fix provenance, freeze hashes, no old/new pair mixing, smoke/parity, 1065 fixed denominator, WHERE78/mech229 overlap, A/S balance, complete/missing bounds, runtime/ETA/error evidence and independent uncertainty. No promotion or equivalence claim from an incomplete run.

### Exact foreground commands (project root)

Target runner: `/Users/iurii.medvedev/Work/code-diver/scripts/research_full_e2e1065_selective_second_pass.py`.

Offline unit verification (already executed):

```sh
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_research_full_e2e1065_selective_second_pass.py
```

After QA AND server-fix join only, fresh smoke4/parity (do not pre-create attempt-04):

```sh
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python scripts/research_full_e2e1065_selective_second_pass.py smoke --attempt attempt-04 --rerank-url http://localhost:18081/v1/rerank
```

After four complete smoke records and approval, first 32 of fresh1065:

```sh
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python scripts/research_full_e2e1065_selective_second_pass.py run --attempt attempt-04 --resume --max-pairs 32 --rerank-url http://localhost:18081/v1/rerank
```

Each next bounded foreground chunk, only after inspecting checkpoint/summary status `segment_boundary` and ETA:

```sh
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python scripts/research_full_e2e1065_selective_second_pass.py run --attempt attempt-04 --resume --max-pairs 128 --rerank-url http://localhost:18081/v1/rerank
```

Current readiness: offline repair ready for independent QA; smoke and full1065 intentionally NOT run. Server-fix join and runtime verification remain blockers. The 7h budget belongs only to the fresh main runtime; never pool its results with attempt-03.

## Explicit same-model endpoint exception (2026-09-06)

One research-only patch, then standard execution only. The frozen CE URL is `http://127.0.0.1:8081/v1/rerank`; the sole permitted override is the same path on localhost port 18081 (literal localhost or 127.0.0.1). No shared runner, champion/config, production, model or dataset changes. `runtime_config` deep-copies the baseline; both independently built arms and smoke/parity/main receive this effective config. The manifest retains original `resolved_config` and records `effective_resolved_config` plus `effective_runtime_delta`. Required common A/S server parameters are batch=2048, ubatch=2048, ctx=8192; these are requirements, NOT a claim of verified live process flags. Parent coordinates runtime verification separately before smoke.

Live service collection derives CE health/models origins from the actual effective URL, without shared-global monkeypatching. Comparison only remaps the two historical CE service keys; existing strict model, health, Qdrant, package, config, cache and 357 dependency hash gates remain. Attempt-02 passed preflight remains historical production provenance and is never rewritten because attempt-04 is fresh. The retained preflight command rejects an override. Resume rejects missing/changed override, effective config or runtime delta; all old/new pair separation and seven-hour deadline rules remain.

Fail-first endpoint/config/metadata/resume tests: 9 failed, 41 deselected before implementation. Final full six-suite command (the prior 110 tests plus 11 new cases):

```sh
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_research_full_e2e1065_selective_second_pass.py tests/test_research_candidate_budget.py tests/test_research_ce_evidence.py tests/test_research_large_search_eval.py tests/test_research_latency_independence.py tests/test_research_selective_second_pass.py && git diff --check
```

Result: 121 passed in 7.71s, exit 0. CLI help verified with the exact smoke arguments plus `--help`, no inference. New immutable diagnostic revision: `artifacts/research/2026-09-05/full-e2e1065-selective-second-pass/diagnostics-endpoint-01/freeze.json`; previous evidence retained. Commands above supersede earlier no-override commands. No smoke, main evaluation, service management or historical evidence edits performed by this patch. Remaining handoff gate: parent runtime verification/QA, then standard smoke4/parity and bounded foreground main chunks only.