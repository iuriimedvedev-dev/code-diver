# External embedding evaluation

`embedding.runtime_mode: external` is a supported client-only configuration option.
It skips embedding runtime config access and manager construction (hence no runtime
install/start/stop) while retaining model, dimensions, prefixes and index metadata
validation. The default is `managed`, retaining existing profile-based management
and missing-runtime errors. Invalid modes are rejected on load/construction and
again at provider use. This option does not change explicit runtime-management commands.

The evaluator accepts `--embedding-runtime-mode {managed,external}` and explicit
`--embedding-url`, `--qdrant-url`, `--python-ce-url`, `--rust-ce-url` options.
Defaults retain historical localhost routes. URLs must be HTTP(S), with a hostname,
valid port, and no credentials, whitespace, query or fragment. Pair/time bounds
must be positive; run names cannot escape the output directory. Managed recognized
embedding profiles are still refused before any endpoint probes. The existing
Qdrant no-start guard remains intact; external mode is not a general safety bypass.

## QA commands

Run from `/Users/iurii.medvedev/Work/code-diver`, after independently preparing and
checking services. These commands do not install dependencies or launch services;
the evaluator launches only its existing persistent native search subprocess.
Runtime preparation evidence remains in `2026-09-09_mlx-search-recovery.md`.

Smoke (two distinct scheduled pairs, plus existing one-query-per-arm warmup):

```bash
.venv/bin/python scripts/research_rust_full_eval.py \
  --run 2026-09-09_external-smoke2 --max-pairs 2 --seconds 3000 \
  --embedding-runtime-mode external \
  --embedding-url http://127.0.0.1:8001/v1/embeddings \
  --qdrant-url http://127.0.0.1:6333 \
  --python-ce-url http://127.0.0.1:18081/v1/rerank \
  --rust-ce-url http://127.0.0.1:18083/v1/rerank
```

Separate 30-pair run (includes the same first two scheduled pairs):

```bash
.venv/bin/python scripts/research_rust_full_eval.py \
  --run 2026-09-09_external-run30 --max-pairs 30 --seconds 3000 \
  --embedding-runtime-mode external \
  --embedding-url http://127.0.0.1:8001/v1/embeddings \
  --qdrant-url http://127.0.0.1:6333 \
  --python-ce-url http://127.0.0.1:18081/v1/rerank \
  --rust-ce-url http://127.0.0.1:18083/v1/rerank
```

Budgets remain retrieval 360, CE candidates 34, results 10. Time is a soft
between-pair bound, not a guarantee of completing the requested pair count.

## Frozen evidence and resume

The effective Python config includes embedding mode, embedding/Qdrant/Python CE
routes and unchanged model/prefix/dimensions. The frozen native command contains
the actual embedding/Qdrant/Rust CE routes and budgets, and is passed directly to
the subprocess. Per-segment endpoint evidence probes the effective routes,
including both CE model endpoints separately, recording probe URLs and identity
errors. Model probes do not certify server immutability or equivalent CE models.

Reusing a run directory requires exact frozen identity equality, including source
hashes, effective config, native command, datasets and schedule. Changed endpoints
or runtime mode reject resume before journal mutation or live queries. Historical
manifests also reject after this source/config change: use new run names. Summary
mode requires the same explicit endpoint/mode arguments and matching identity.

Journal behavior is unchanged: completed failures remain attempts, interrupted
begins become failed results with unknown latency, and attempts are not retried.
`--max-pairs` caps additional pairs per invocation, not the run's cumulative total;
re-running either command resumes and can add more pairs. Warmup is separately
journaled and repeated each segment. Parent QA owns acceptance and service readiness.