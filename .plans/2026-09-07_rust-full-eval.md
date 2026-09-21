# Full Rust/Python diagnostic evaluation

- Freeze exact H91a config with endpoint/graph overrides, binary/model/source/data hashes and Qdrant metadata.
- Use production Python factories and native JSON-lines server (request limit honored); exclude initialization from both request clocks and save startup separately.
- Seed 42 shuffled cases and paired arm order; full1065 plus exact nonoverlapping WHERE78/mech150 cases. Score using DatasetLoader/ExpectedPathMatcher.
- Test metrics, scheduling, failure denominator and checkpoint replay; separate smoke and full evidence.
- Append/fsync every attempt and result; immutable per-chunk snapshots. Interrupted attempts remain failures, not omitted or retried.
- Run finite 3000-second chunks, continuing until all pairs finish. No application edits, builds, installs, service starts, training or git mutations.
- Report quality and latency with cache/workload caveats; known95 tuned and training856/test209 overlap preclude independent acceptance.