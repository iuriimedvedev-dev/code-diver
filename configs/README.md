# Configuration Layout

Tracked configs are grouped by purpose:

- `benchmarks/`: benchmark corpus profiles, currently CodeSearchNet/MTEB.
- `intellij/`: IntelliJ Community index, search, and post-rank profiles.
- `local-models/`: local/API model sweep and reranker experiment suites.
- `protogen-legacy/`: historical Protogen sibling-repo profiles.
- `runtimes/`: container/runtime deployment profiles.
- `smoke-experiments/`: small smoke and one-off experiment profiles.

The flat `configs/*.yml` paths are compatibility aliases for existing commands,
scripts, and older docs. Prefer the grouped paths for new documentation and new
configs.

Explainer judge configs should live under an explanation/judge grouping once the
active judge work stabilizes. Existing untracked judge configs are intentionally
left in place to avoid conflicting with in-progress work.
