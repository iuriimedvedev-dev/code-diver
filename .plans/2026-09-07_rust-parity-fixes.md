# Rust parity fixes — status

## Implemented

- Shared ranking/feature preparation and shared export paths.
- Final ranking uses merged second-pass scores with deterministic tie behavior.
- Retrieval limit `360` and CE candidate limit `34` are independently configurable.
- Exact-path representative deduplication before CE truncation.
- Release binary validated with `35` native tests passing, including `7` new tests. Earlier ordering regressions (`2` failures) were fixed before release.
- Release SHA-256: `7c54b8750d4c327a19b8045577837eac09e784d61658d76bf0033ed1efcf9724`.

## Diagnostic status

- Paired diagnostic completed `12/12` arms with zero failures over three known cases, two repeats, and deterministic seed `42` pair ordering.
- Python MRR was `1.000000`; Rust MRR was `0.833333`. Both arms had Hit@10 `1.000000`.
- The result is not parity evidence: it is not an independent holdout and contains three cases repeated twice, not six independent cases. Timing is asymmetric because Python initialization is excluded from per-search wall time while native process startup and context loading are included in native wall time.
- Full measured rows, commands, hashes, top-10 lists, and the computed `43` unique reported paths are recorded in `docs/research/2026-09-07_rust-parity-diagnostic.md`.

## Outstanding

- Independent lexical/path/symbol admission.
- Python file aggregation and voting equivalence.
- Graph fan-in and graph-enabled behavior equivalence.
- Sealed independent holdout evaluation.
- Comparable persistent-workload latency measurement.

No parity, precision@10, production speedup, or warm `p95` acceptance claim is authorized from the current diagnostic.