# Plan: H-87 Hub Prior Implementation

## Phase 1: Small Fix (Part 1)
- **Goal**: Ensure `FileGraphCatalogStore` rebuilds if `fan_in` is missing.
- **Agent**: `Task(general-purpose)` with instructions for `ninja-coder`.
- **Steps**:
    1. Inspect `src/code_diver/strategies/file_graph_catalog.py`.
    2. Bump `SCHEMA_VERSION` or update `is_fresh_for`.
    3. Run `uv run --no-sync pytest -q tests/test_hub_prior.py` and other relevant tests.
    4. Verify runtime behavior with `intellij-h87c-hub-combo.yml`.
    5. Confirm `fan_in` is non-zero in the regenerated catalog.

## Phase 2: Sequential Experiments (Part 2)
- **Goal**: Run 5 evaluation arms.
- **Agent**: `Task(general-purpose)` / `qa-engineer`.
- **Arms**:
    1. champion_rebaseline (`intellij-h66b-champion.yml`)
    2. role-prior (`intellij-h87a-role-prior.yml`)
    3. hub-combo (`intellij-h87c-hub-combo.yml`)
    4. fanin-prior (`intellij-h87b-fanin-prior.yml`)
    5. band (`intellij-h87d-band.yml`)
- **Output**: `/tmp/h87/<name>.json`

## Phase 3: Analysis (Part 3)
- **Goal**: Aggregate metrics and per-query diff.
- **Agent**: `Task(general-purpose)`.
- **Metrics**: Recall@10, MRR@10, Hit@1, Hit@10, nDCG@10, Latency.
- **Comparison**: Gained/Lost vs champion.
- **Specifics**: 12-id rank table.

## Handoffs
- Agent 1 (Part 1) -> Success -> Agent 2 (Part 2) -> Agent 3 (Part 3).
