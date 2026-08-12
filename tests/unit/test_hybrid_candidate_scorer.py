from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

import pytest

from code_diver.domain import CodeItem
from code_diver.strategies.hybrid_candidate_scorer import HybridCandidateScorer
from code_diver.strategies.hybrid_item_profiler import HybridItemProfiler
from code_diver.strategies.hybrid_query import HybridQuery

pytestmark = pytest.mark.unit


class SlowCountingProfiler(HybridItemProfiler):
    def __init__(self) -> None:
        self.calls = 0
        self._lock = Lock()

    def profile(self, item: CodeItem):
        with self._lock:
            self.calls += 1
        time.sleep(0.01)
        return super().profile(item)


def test_hybrid_candidate_scorer_locks_shared_profile_cache() -> None:
    item = CodeItem(
        id="src/users.py#update_user",
        path="src/users.py",
        title="update_user",
        content="def update_user(user_id): return user_id",
        metadata={},
    )
    profiler = SlowCountingProfiler()
    profiles = {}
    profile_lock = Lock()
    scorer = HybridCandidateScorer(
        HybridQuery(text="update user", terms=("update", "user")),
        profiler=profiler,
        profiles=profiles,
        profile_lock=profile_lock,
    )

    with ThreadPoolExecutor(max_workers=8) as executor:
        scores = list(executor.map(lambda _: scorer.score(item), range(16)))

    assert profiler.calls == 1
    assert list(profiles) == [item.id]
    assert all(score.item.id == item.id for score in scores)
    assert all(score.lexical_score > 0 for score in scores)
