from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .ltr_feature_row import LtrFeatureRow


class LtrFeatureSinkAttacher:
    """Finds the stage that owns the fused per-file features and attaches an export sink.

    Strategies are composed as a chain of wrappers (rerankers around the graph-file
    fusion), and only the innermost stage that computes `FileScore` can emit features.
    Walking `base_strategy` keeps the export working for every wrapped strategy id
    without the reranker layers needing to know the export exists.
    """

    def attach(self, strategy: Any, sink: Callable[[str, list[LtrFeatureRow]], None]) -> bool:
        current = strategy
        while current is not None:
            if hasattr(current, "feature_sink") and hasattr(current, "feature_extractor"):
                current.feature_sink = sink
                return True
            current = getattr(current, "base_strategy", None)
        return False
