# M1 catalog builder plan

Scope: native/code_diver_search_bin code/tests/Cargo files, STATUS/DECISIONS and
this plan/session note only. External Python sources/prototype/Pier are read-only.

1. Read SPEC and Python scanner/builders/extractor/router/dump contracts; inspect
   the prototype rather than assume its compact-only implementation is sufficient.
2. Reuse reviewed generic helpers; implement ID/tokenizer separation and existing
   CatalogItem JSONL integration. Add catalog-only and comparison CLI commands.
3. Reproduce hidden include and noncompact defects, then implement fixes and
   configuration switches. Keep dedicated strategies explicitly deferred to M2.
4. Add synthetic reference-template goldens, scanner edge cases, caps and isolated
   CLI tests with PATH empty. Never generate references with Python.
5. Measure kb/ and whole-root parity against the existing Pier catalog. Explain
   SPEC/Python hidden divergence and separately measure Python enumeration replay.
6. Run fmt, strict all-targets Clippy and full tests; fix baseline style defects.
7. Record measured counts/limitations and commit only scoped changes. Parent joins
   worker, then requests independent QA; worker tests are not independent QA.

Completed through local validation. Acceptance gaps: full YAML grammar, frozen
Python-generated synthetic oracle and owner approval of hidden-file divergence.