# Session: WHERE-79 Hygiene Fixes (2026-09-01)

## Changes
1. `where-editor-caret`: removed stale gold path `platform/platform-impl/src/com/intellij/openapi/editor/impl/EditorCaretMoveProcessor.kt` (file does not exist at the pinned IntelliJ revision; no clear renamed successor found). The other 3 gold paths were kept.
2. `where-json-file-parsing`: query removed entirely. Its only gold `json/gen/com/intellij/json/JsonParser.java` lies under `**/gen/**`, which the indexer excludes (see `configs/intellij/intellij-h66b-champion.yml` scanner.exclude), so it can structurally never be retrieved. No non-generated copy exists in the checkout.

## Entries Verbatim (Before Fix)
{"id": "where-editor-caret", "query": "where are editor caret movements handled", "expected": ["platform/platform-impl/src/com/intellij/openapi/editor/impl/CaretModelImpl.java", "platform/platform-impl/src/com/intellij/openapi/editor/actions/MoveCaretUpOrDownHandler.java", "platform/platform-impl/src/com/intellij/openapi/editor/actions/MoveCaretLeftOrRightHandler.java", "platform/platform-impl/src/com/intellij/openapi/editor/impl/EditorCaretMoveProcessor.kt"]}
{"id": "where-json-file-parsing", "query": "where is json file parsing implemented", "expected": ["json/gen/com/intellij/json/JsonParser.java"]}

## Entry After Fix (edited query)
{"id": "where-editor-caret", "query": "where are editor caret movements handled", "expected": ["platform/platform-impl/src/com/intellij/openapi/editor/impl/CaretModelImpl.java", "platform/platform-impl/src/com/intellij/openapi/editor/actions/MoveCaretUpOrDownHandler.java", "platform/platform-impl/src/com/intellij/openapi/editor/actions/MoveCaretLeftOrRightHandler.java"]}

## Statistics
- File: datasets/intellij_eval_where_only.jsonl
- Before: 79 queries
- After: 78 queries
- No renumbering/reordering; all other lines byte-identical.

## Scripts hardcoding the old "79" count (NOT edited, report only)
- scripts/dump_h53_where79.py
- scripts/dump_h52v2_where79.py
- scripts/dump_h46_where79.py
