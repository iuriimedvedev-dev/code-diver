# Plan: Hub Prior Protect Top (Protected Head)

## Objective
Gain recall by applying hub prior to tail candidates without destroying Hit@1/MRR by reordering confident CE heads.

## Architecture
- Setting `hub_prior_protect_top: int` pins the first N candidates in CE order.
- Hub prior (additive or band) reorders ONLY positions N+1..end.

## Steps
1. **Config Update**:
   - `src/code_diver/settings/defaults.py`: Add `CROSS_ENCODER_RERANK_HUB_PRIOR_PROTECT_TOP = 0`.
   - `src/code_diver/config/cross_encoder_rerank_config.py`: Add `hub_prior_protect_top` field.
   - `src/code_diver/config/config_loader.py`: Update `_cross_encoder_rerank` to parse the setting.
2. **Strategy Update**:
   - `src/code_diver/strategies/cross_encoder_rerank_retrieval_strategy.py`: Update `_hub_prior_adjusted`.
   - Split `scores` into `head` and `tail` based on `config.hub_prior_protect_top`.
   - Apply hub prior only to `tail`.
   - Recombine `head + adjusted_tail`.
   - Update `cross_encoder_hub_prior` trace event to include `protect_top`.
3. **Verification**:
   - Add unit tests in `tests/test_hub_prior.py`.
   - Run existing tests to ensure no regressions.
4. **Experimental Configs**:
   - `configs/intellij/intellij-h89a-fanin-protect3.yml`
   - `configs/intellij/intellij-h89b-fanin-protect1.yml`
   - `configs/intellij/intellij-h89c-fanin-protect3-w08.yml`
5. **Evaluation**:
   - Run `evaluate` for h89a, h89c, h89b.
   - Compare with `champion_rebaseline.json`.
