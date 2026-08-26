# Continue jbcontext research — 2026-08-26

User: assess status quo, fix obvious search bugs, compete with jbcontext; parallel Rust search-core rewrite for latency.

## Decisions
- Workstream: bugs first, then where-quality vs jbcontext.
- Rust scope: **search core** (hybrid + graph + rerank glue), CLI/eval stay Python.
- Champion `configs/intellij/intellij-h46-preserve-top.yml` remains frozen.

## Status quo (from report + pipeline audit)
- Mechanical categories: code-diver wins; **where** (n=79): jbcontext recall@10 0.685 vs 0.503.
- Root cause (Opus): name-echo + path-heavy embeddings, not sibling-family.
- H-A/H-B/H50/H50b/H-2: null or blocked. H-5 mixed, not promoted.
- SWE-bench: recall@10 0.174 untuned; **48s/query** (#60) — Python scoring over large postings + JSON store.
- No in-repo Rust today.

## This session
1. Obvious fixes: token-aware embed truncate (#64); test-path exclusion (H-7).
2. Do not promote H-5 without full 1065.
3. Parallel: Rust search-core design + first PyO3 crate (BM25/fusion hot path as landing zone).
4. Quality later: H-1 incremental prose, H-3 listwise, eval expansion #65.

## Agent handoffs
- py-developer: #64 + scanner testSrc/testSources/platform-tests.
- rust-core: architecture + scaffold, no full rewrite in one pass.
