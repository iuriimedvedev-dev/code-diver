# Plan: WHERE-79 Dataset Hygiene

## Objective
Fix two hygiene defects in the WHERE-79 evaluation dataset: stale gold file `EditorCaretMoveProcessor.kt` and unindexable gold file `JsonParser.java`.

## Steps
1. **Exploration Phase** (Delegated to `Explore` subagent):
    - Find the dataset file(s) in `datasets/` matching "where".
    - Extract the IntelliJ checkout path from `configs/intellij/intellij-h66b-champion.yml`.
    - Verify the existence of the dataset file and its format.

2. **Investigation Phase** (Delegated to `Explore` subagent):
    - Search the IntelliJ checkout for `EditorCaretMoveProcessor.kt` successors (class name search).
    - Search the IntelliJ checkout for `JsonParser.java` occurrences outside of `**/gen/**`.

3. **Execution Phase** (Delegated to `Task` agent):
    - Update or remove the query for `EditorCaretMoveProcessor.kt`.
    - Update or remove the query for `JsonParser.java`.
    - Ensure format is byte-identical for other entries.

4. **Verification Phase** (Delegated to `qa-engineer` or `Task` agent):
    - Grep `scripts/` for "79".
    - Verify final query count.

5. **Documentation Phase** (Lead Architect):
    - Update `.session/2026-09-01_where79-hygiene.md`.
