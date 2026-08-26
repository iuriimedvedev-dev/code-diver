# WHERE eval holdout dataset (2026-08-26)

## Purpose

Upgrade realistic “where is X implemented” evaluation **as a HOLDOUT**. Do **not** mix these cases into the original 79 (`datasets/intellij_eval_where_only.jsonl` / `where-*` rows in `datasets/intellij_eval_1000.answer_sets.jsonl`) and do **not** use them for champion claims or hill-climbing against `configs/intellij/intellij-h46-preserve-top.yml`.

## Schema

Same JSONL object as `intellij_eval_where_only.jsonl`:

- `id` (string) — holdout ids are prefixed `where-holdout-…`
- `query` (string) — hand-written developer question
- `expected` (string[]) — repo-relative gold paths

Holdout file: `datasets/intellij_eval_where_holdout.jsonl`  
**n = 36** (within 20–40). Original `where_only` is unchanged.

## How gold was verified

Checkout: `/Users/iurii.medvedev/Work/intellij-community` (sibling of this repo).

Fail-fast: every `expected` path was checked with `Path.is_file()` on that tree before write. Zero skips. No gold path overlaps the original 79 expected set. Queries are not copies of the original 79.

Coverage (diverse vs original platform/lang/java-refactor/git/maven/gradle cluster): line markers, scratch files, file-based/stub/directory indexes, inlay hints, TODO, bookmarks, annotate/blame, three-way merge, goto file/class, recent projects, welcome frame, JavaDoc generator, ClsFile PSI, postfix templates, FUS event log, trusted projects, native file watcher, run toolwindow layout, Python run config, Kotlin facet, JPS workspace sync, external-system project data, settings sync, properties/XML PSI, language injection, WolfTheProblemSolver, problems view, PSI–document sync, editor gutter, UAST language plugins, library tables, SM test runner console.

## Original 79 vs 1000-set

`intellij_eval_where_only.jsonl` is the 79 hand-written `where-*` cases. The same objects also appear **interleaved** in `intellij_eval_1000.answer_sets.jsonl` among mechanical `symbol-*` / `config-*` / `path-*` rows (name-echo of the target file). Session notes (`.session/2026-08-25_jbcontext-comparison-report.md`): ~8.4% of the **full** 1065-set has at least one missing gold path; mechanical categories vs realistic WHERE; sibling-family ranking failures.

## H52 top-10 misses (`/tmp/h52_where79.json`)

32/79 cases had **no gold file in top-10** (`file_hit` false). None of those 32 had a missing gold file on the current tree.

Categorization (non-exclusive):

- **missing file in repo**: 0 of the 32 misses (gold still on disk).
- **name-echo** (query tokens overlap gold filename): intention-actions, structural-search, extract-method, introduce-variable, project-view, find-in-path, code-style-settings, code-completion-service.
- **multi-gold**: quick-documentation-popup, structural-search-and-replace, regular-expression-language-support.
- **vague query** (short “where is … implemented/managed/handled”): most of the 32 (rename refactoring, keymap, live templates, folding, yaml/json parsing, github PR, debugger eval, spellchecking, notifications, progress, VFS refresh, dumb mode, extension points, plugin loading, terminal, settings persistence, etc.).

Dominant failure shape matches the 2026-08-25 report: ranking/intent, not stale paths.

## Stale hygiene (optional)

`datasets/intellij_eval_where_stale.jsonl` — original cases whose **at least one** gold path is missing from the current tree. **Do not delete originals.**

- **stale count = 1**
- `where-editor-caret` missing `platform/platform-impl/src/com/intellij/openapi/editor/impl/EditorCaretMoveProcessor.kt` (other golds for that case still exist).

## Do-not-mix warning

- Holdout is **not** a replacement for `intellij_eval_where_only.jsonl`.
- Do **not** append holdout rows into `intellij_eval_1000.answer_sets.jsonl`.
- Do **not** cite holdout metrics as champion/H46 evidence.
- Use holdout only for unseen WHERE-quality checks after a candidate is frozen.

## Files written

- `datasets/intellij_eval_where_holdout.jsonl` (n=36)
- `datasets/intellij_eval_where_stale.jsonl` (n=1)
- `.session/2026-08-26_where-dataset-holdout.md`
