# Code-Diver: complete Rust rewrite (single binary) - specification

Status: ready to implement. Owner: Iurii Medvedev. This document is the contract for the remaining work. The Python implementation under `src/code_diver` is a deprecated prototype: it is the behavioural reference, not a dependency. When this spec and the Python behaviour disagree, this spec wins; where this spec is silent, match Python.

## 1. Goal

One self-contained executable, `code-diver`, written in Rust, with no Python (and no other runtime) needed to index a repository, search it, or serve it to AI agents over MCP. A colleague installs one file and points it at a Qdrant, an OpenAI-compatible embeddings endpoint and a rerank endpoint.

Non-goals for v1 (document them as "removed" in `docs/DEPRECATION.md`): the LLM-driven `search` agent, `answer`, `evaluate`, `provider`, the async task API (`code_diver_submit_agent_search`, `code_diver_task_*`), gRPC/HTTP/ACP transports, `init` wizard. They may return later; none blocks removing Python.

## 2. Current state (verified on 2026-10-07)

- `native/code_diver_search_bin` (crate, ~5.5k lines): subcommands `search`, `info`, `doctor`, `mcp` (stdio MCP with two tools: `code_diver_search`, `code_diver_read`), plus `--index-update` (diff a catalog JSONL against a Qdrant collection, embed and upsert only changed items; dry run unless `--apply`). Modules: main, mcp, pipeline, catalog, bm25, embedding, fusion, graph, features, lightgbm, index_update, info, types.
- It cannot build a catalog or graph. `rust_catalog.jsonl` / `rust_graph.jsonl` come from `scripts/dump_rust_catalog.py` running the Python scanner. That is the main blocker.
- Known defects to fix (from testing): `doctor` always exits 0 and checks little; `info` has no collection flag; `search`/`mcp` previously ignored `--qdrant-collection` (fixed in the baseline commit of this branch; keep a test); no `--version`; MCP `serverInfo.version` says 0.1.0 while Cargo says 0.4.5; `code_diver_read` has no sandbox (absolute paths and `../..` work) and no output cap; tool arguments are not validated (an empty query runs the whole pipeline); `limit` is silently capped at 34; results are ordered by `meta_score` but `score` is the CE score so it looks non-monotonic; tool errors are JSON-RPC -32603 instead of MCP `isError` results; `ping` is "method not found"; requests are served serially so a trivial read waits behind a 20 s search; a 10,000-char query fails in the embedder (512-token limit) without truncation; reranker failure on the first pass aborts the search while on the second pass it degrades silently.
- Reference prototypes (local, unpushed, may be read or cherry-picked, no obligation): worktree `../code-diver-wt-catalog` branch `feat/rust-catalog-builder` (scanner, generic-lane `file_summary`/`file_manifest` builder, `compare` tool; 100% parity on Pier `kb/`, 71% on the whole Pier root because Go/TS/Python/JS strategies are not ported) and `../code-diver-wt-rust` branch `feat/rust-shared-index-auth` (Qdrant api-key/bearer, TLS and CA options, `--config` TOML, `doctor` improvements, `rerank_applied` in JSON output).

## 3. Product surface

Binary name `code-diver` (crate name may stay; set `[[bin]] name = "code-diver"` and keep `code_diver_search_bin` as an alias only if existing MCP configs need it; document the change in CHANGELOG). `code-diver --version` prints the Cargo version; MCP `serverInfo.version` uses it.

Subcommands (all accept `--config`, global flags below):

| Command | Behaviour |
|---|---|
| `index` | Scan the repo, build catalog (+graph), embed, upsert to Qdrant. Full or incremental. See section 5. |
| `search "<query>"` | The existing pipeline. `--json` default output for non-TTY. See section 6. |
| `read <file>` | Bounded excerpt with line numbers (same semantics as the MCP tool). |
| `grep <pattern>` | Literal or regex search over the repo, gitignore-aware. |
| `tree [path]` | Gitignore-aware directory tree. |
| `symbols [path]` | Symbols per file from the same extractor the indexer uses. |
| `info` | Index, graph and vector-store overview for the configured collection. |
| `doctor` | Dependency and configuration checks; exit code 1 on any failure; `fix:` hint per problem. |
| `mcp` | MCP server on stdio. See section 7. |

Global flags (precedence: flag > env `CODE_DIVER_<FLAG>` > config file > default): `--config`, `--root` (repo root; default = current dir), `--qdrant-url`, `--qdrant-collection`, `--qdrant-api-key` (env `QDRANT_API_KEY`), `--qdrant-bearer`, `--embedding-url`, `--embedding-model`, `--embedding-dimensions`, `--embedding-api-key`, `--embedding-query-prefix`, `--embedding-document-prefix`, `--ce-url`, `--second-ce-url`, `--ce-model`, `--ce-api-key`, `--ce-route`, `--ce-timeout-ms`, `--ca-bundle` (also `SSL_CERT_FILE`), `--insecure-skip-verify` (loud warning; TLS is verified by default), `--require-rerank`, `--catalog`, `--graph`, `--model` (LightGBM meta-ranker). Secrets must never appear in logs, `--help` defaults, debug output, or error messages; each secret goes only to its own service; redirects only within the same origin.

Config file: read the existing `code-diver.yml` format (sections `storage.qdrant`, `embedding`, `scanner`, `indexing`, `search`, `hybrid_search`, `cross_encoder_rerank`, `graph`, `graph_file_search`; see `code-diver.yml` and `.code-diver/code-diver-pier.yml` in the Pier repo for real examples) so that existing configs keep working, and also accept a TOML equivalent. Unknown keys: warn, do not fail. Relative paths resolve against the config file's directory; `~/` is expanded.

## 4. Quality bar and non-functional requirements

- Single binary, no Python, no Node, no system `rg` required (use the `ignore`, `regex`, `walkdir` crates). Build targets: macOS arm64 and x86_64, Linux x86_64 and aarch64 (CI cross builds), release assets with a `.sha256` per file.
- Cold start of `mcp` (catalog of 16k items) under 0.5 s; `search` end-to-end dominated by the reranker, never by us. Memory: the 135k-item IntelliJ catalog currently needs about 4 GB per process: find out why (BM25 index? duplicated strings?) and reduce at least by half, or document the cause.
- MCP concurrency: `read`, `grep`, `tree`, `symbols`, `info` must not wait behind a running `search`.
- Errors: clear, actionable, with a hint; no panics on bad input; never block forever (all network calls have timeouts).
- `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings`, `cargo test` all clean. Tests never touch the network (use a local mock HTTP server) and never need Qdrant or models; integration tests that do are `#[ignore]` and documented.
- No file larger than 1 MB, no secrets, no real internal repo content committed (fixtures are synthetic).

## 5. `index` (the missing piece)

Reference: Python `services/codebase_scanner.py`, `services/*item_builder*.py`, `code_symbol_extractor.py`, `graph/code_graph_builder.py`, `scripts/dump_rust_catalog.py`, and the Rust `index_update.rs`. A frozen set of golden catalogs produced by the Python implementation is the acceptance oracle (see section 9).

5.1 Scanner. Candidates sorted by path; honour `.gitignore`, `.ignore`, global gitignore and `scanner.include/exclude` globs (`"X/**"` means directory X at any depth; hidden directories are skipped like `rg --files` does unless explicitly included); skip files larger than `max_file_bytes` (default 1,000,000), files containing NUL bytes, files empty after strip; decode UTF-8 lossily. Deterministic across machines (no dependency on an installed `rg`).

5.2 Items. Only two item kinds are required: `file_summary` and `file_manifest` (all other Python kinds are off in every production config; implement behind flags later). Item id: `<path>::<kind>#<sha1(path + ":" + kind-with-dash)[:12]>` exactly as Python (`file-summary`, `file-manifest`); `name = "<path>::<kind>"`; content templates, section order, caps and the compact budget are those of `FileSummaryItemBuilder` and `FileManifestItemBuilder` with `file_summary_compact_budget` honoured (24 imports, 80 symbols, 24 head lines, 40 terms in 220 chars; manifest 20 imports, 80 symbols, 80 config keys; `file_summary_head_line_max_chars` 200, `file_summary_head_block_max_chars` 4000, `max_symbols_per_file` 96 with the `max(cap, lines/4)` rule).

5.3 Symbols. Regex-based extractors per language exactly as Python (no tree-sitter anywhere in Python, none required here): generic lane first (Markdown, YAML, JSON, TOML, Dockerfile, Terraform, shell, HTML, config files; already 100% matching in the prototype), then Go, TypeScript/JavaScript/MJS, Rust, Python (the Python extractor uses `ast`; port with a small hand-written parser or a Rust Python parser crate, document the choice), JVM (Java/Kotlin/Scala), C/C++. Keep the Python quirks that affect output (generic regex starting with `\s*`, `package` only on the first line, import cap letting the list exceed 24 before truncation).

5.4 Tokenized fields: `tokenized_name/path/dir/content` = ASCII alphanumeric runs, camelCase split, length >= 2, lowercased. Decision pending from the owner for `tokenized_content`: full content (as `dump_rust_catalog.py`) or first 1000 chars (as the knotgate catalog). Implement a config switch `tokenize_content_chars` (default 0 = full) and keep both reproducible.

5.5 Graph. v1: write an empty graph file or `imports`-edge adjacency (weight 0.8, reverse 0.56) as Python does for Pier; the search pipeline needs the file to exist when `graph_weight > 0`; document that production configs use weight 0.0. Make the graph optional in the CLI (no file required when weight is 0).

5.6 Qdrant upsert. Reuse and harden `index_update.rs`: collection auto-create with vector size taken from the first embedding response (Cosine), point id = UUIDv5(NAMESPACE_URL, item.id), payload exactly as Python (`item{...}, root, provider, model, dimensions`), embed text built like Python's `CodeItem.to_embedding_text` with `max_input_chars` (default 2000, character budget; Python additionally truncates by tokens when a tokenizer is available: document the difference), `document_prefix` applied (the Pier config sets `Represent this code file metadata for retrieval: `; verify what Python actually sends before relying on it, and add a test with a recorded Python request body), batching, bounded concurrency, retries with backoff, progress on stderr, `--dry-run` (default) vs `--apply`, `--collection` required explicit (never default to an IntelliJ collection), deletion of points whose items disappeared (e.g. a `vendor/` directory now excluded; report counts before deleting; require `--apply --prune`), and a lock so two indexers do not run at once. Re-running on an unchanged repo reports `added=0 changed=0 deleted=0` and writes nothing.

5.7 Outputs of `index`: catalog and graph files in `<root>/.code-diver/` (configurable) in the same JSONL schemas as today (so `search` can run from them) and the Qdrant collection. A single command `code-diver index` must be enough to get a searchable index of a new repository.

## 6. `search`

Keep the current pipeline (neural + BM25 + fusion + graph + CE rerank + LightGBM meta-ranker); do not change ranking behaviour while porting. Changes required: authoritative collection flag; JSON output adds `rerank_applied`, `rerank_second_pass_failed`, `rerank_error`; with `--require-rerank` any reranker failure is an error (exit 1); results sorted consistently with the `score` field exposed (expose both `score` = final ordering score and `ce_score`); validate `query` (non-empty, length limit with truncation notice); `limit` max configurable, not silently capped without telling; optional `preview_chars` (default 0) adds a content preview per result for agents that want snippets; `--model` optional (if absent run without the meta-ranker and say so in the output, never silently).

## 7. MCP server (stdio)

Implement the MCP protocol correctly: `initialize` (protocol version negotiation), `notifications/initialized`, `ping`, `tools/list`, `tools/call`, `resources`/`prompts` empty or absent, tool failures returned as results with `isError: true` and a text explanation (JSON-RPC errors only for protocol-level problems), cancellation notifications honoured where cheap, log to stderr only, async handling so slow tools do not block fast ones.

Tools (names and argument names are a public contract; agents already use the first two):

| Tool | Arguments | Result |
|---|---|---|
| `code_diver_search` | `query` (string, required), `limit` (int, default 10), `preview_chars` (int, default 0) | JSON array of `{path, score, ce_score, title, start_line, end_line, preview?}` plus a text warning item when rerank was degraded |
| `code_diver_read` | `file` (relative path, required), `start_line` (default 1), `lines` (default 100, max 400) | numbered lines; sandboxed to `--root`; refuses absolute paths and any path escaping the root after symlink resolution; refuses binary and non-UTF-8 with a clear message; output capped (default 40,000 chars) with a truncation notice |
| `code_diver_grep` | `pattern`, `path?`, `limit` (default 50), `regex` (default false) | JSON array of `{path, line, text}`; gitignore-aware; line text capped |
| `code_diver_symbols` | `path?`, `limit` (default 100) | JSON array of symbols from the indexer's extractor |
| `code_diver_tree` | `path?`, `depth` (default 3), `limit` (default 100) | text tree, gitignore-aware |
| `code_diver_info` | none | JSON overview of the configured collection, catalog, graph |

Do NOT add a `find_files` tool (it never existed in Python; hosts have glob).

## 8. Packaging, release, removal of Python

- GitHub Actions workflow `release.yml`: build matrix (see section 4), strip, tar.gz per target, sha256, upload to the release; `ci.yml`: fmt, clippy, test on Linux and macOS.
- README top section rewritten for the Rust binary (install, config example, `index`, `search`, `mcp`, `doctor`); `docs/DEPRECATION.md` updated; Python package marked removed in CHANGELOG once the acceptance criteria hold.
- Final milestone: delete `src/code_diver` (Python), `scripts/dump_rust_catalog.py` and Python-only tests/deps from `pyproject.toml`, only after section 9 passes; keep one frozen golden dataset produced by the Python code in `tests/goldens/` (gzipped JSONL, synthetic or public repos only) so parity stays testable.

## 9. Acceptance criteria (every milestone adds its own tests)

1. Catalog parity: for pinned snapshots (the Pier repo at a recorded commit, the knotgate repo, a small public JVM repo, a small public Python repo, plus a synthetic edge-case fixture with CRLF, BOM, non-UTF-8, empty, huge and unicode-path files) the Rust-built catalog has 100% id equality and 100% content equality per ported language lane against the Python-built golden, with a documented allow-list of known quirks. Tool: a `catalog-compare` subcommand or test harness (the prototype branch has one).
2. Incremental index: `index` on an unchanged repo reports 0/0/0; touching one file changes exactly that file's items; deleting a file removes its points (with `--prune`); results verified against a scratch Qdrant collection (names `zz_*` only).
3. Retrieval parity: on the 80-query set in `/Users/iurii.medvedev/Work/sre-support-pier/tmp/rust-pier/queries80.json` (fields `query`, `expected_files`; code and hard questions in Russian and English) the new binary reaches Hit@1/5/10 within 3 points of the current Rust search on the Python-built catalog (reference: Hit@1 61.2, Hit@5 86.2, Hit@10 92.5 at candidate limit 34).
4. MCP: scripted stdio tests for every tool (valid, invalid, hostile arguments: `../..`, absolute path, symlink escape, huge `lines`, binary file, empty query, 10,000-char query), concurrency test (a read returns while a search runs), `ping`, error shape, `serverInfo.version`.
5. `doctor` exits non-zero on: unreachable Qdrant, missing collection, wrong vector size vs embedder, rerank failure on a short or a ~1000-token pair, missing catalog/graph/model files; every failure prints a `fix:` line.
6. No Python process or `python` invocation anywhere in the binary's runtime paths (test by running with `PATH` stripped of any python).
7. Security: no secret in any output path; `--insecure-skip-verify` warns; TLS verification on by default; a test with a self-signed server proves both behaviours.

## 10. Milestones (each ends with a commit and a green `cargo test`)

- M1 Catalog builder: scanner, item builders (summary and manifest), generic symbol lane, tokenizers, `catalog-compare`, goldens harness. Output files equal to Python for generic-lane files; command `code-diver index --catalog-only`.
- M2 Language lanes in this order: Go, TypeScript/JavaScript/MJS, Rust, Python, JVM, C/C++. Each lane lands with golden tests and its parity percentage in `docs/rust-rewrite/PARITY.md`.
- M3 `index` end to end: embeddings, Qdrant create/upsert/delete/prune, incremental logic, config loading, secrets handling, `index --dry-run`.
- M4 Server surface: `read` sandbox and caps, `grep`, `tree`, `symbols`, `info`, argument validation, MCP protocol fixes and concurrency, `isError` results, `--version`.
- M5 `search` and `doctor` hardening: authoritative collection, `rerank_applied` fields, `--require-rerank`, doctor exit codes and checks, memory use of the catalog.
- M6 Packaging: CI, release workflow, cross builds, checksums, README, CHANGELOG, DEPRECATION updates.
- M7 Python removal gated on section 9.

## 11. Working rules for the implementer

- Work only in this worktree (`/Users/iurii.medvedev/Work/code-diver-wt-rust-full`, branch `feat/rust-full`). Never touch `/Users/iurii.medvedev/Work/code-diver` (the owner's main working tree with the running binary and uncommitted files) or any other repository. Do not push; do not publish releases.
- Do not edit or run the Python code, except reading it as the reference and, in M7, deleting it. Python may be run only to regenerate goldens and only through `scripts/dump_rust_catalog.py`, never to serve anything.
- Services for manual tests (read-only unless told otherwise): Qdrant `http://localhost:6333` (do NOT write to the real collections `code_diver_pier`, `code_diver_knotgate`, `intellij_*`; use `zz_<name>` scratch collections and delete them afterwards), embedder `http://127.0.0.1:8001/v1/embeddings` (model `mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ`, 1024 dims), reranker `http://127.0.0.1:18081/v1/rerank`. Do not stop or restart services.
- Commit style: one summary line plus wrapped `-` bullets; no trailers; one logical change per commit; never commit artifacts, large files, secrets or real internal repo content.
- After every milestone, update `docs/rust-rewrite/STATUS.md` (done, parity numbers, open questions) so the owner can follow progress.
- When this spec is ambiguous, pick the behaviour of the Python implementation, write the decision into `docs/rust-rewrite/DECISIONS.md` with the reason, and continue.
