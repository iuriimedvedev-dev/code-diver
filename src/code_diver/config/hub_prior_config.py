from __future__ import annotations

from dataclasses import dataclass, field

from ..settings import Defaults


@dataclass(slots=True)
class HubPriorConfig:
    """H-87: filename-role vocabulary for the hub prior.

    Only the *vocabulary* lives here so every stage that applies the prior (cross-encoder
    ordering, graph-file seed scoring) classifies files identically. Each stage keeps its own
    weights, so this block alone never changes any ranking.
    """

    hub_tokens: list[str] = field(default_factory=lambda: list(Defaults.HUB_PRIOR_HUB_TOKENS))
    peripheral_tokens: list[str] = field(default_factory=lambda: list(Defaults.HUB_PRIOR_PERIPHERAL_TOKENS))
    test_path_segments: list[str] = field(default_factory=lambda: list(Defaults.HUB_PRIOR_TEST_PATH_SEGMENTS))
    non_source_extensions: list[str] = field(
        default_factory=lambda: list(Defaults.HUB_PRIOR_NON_SOURCE_EXTENSIONS)
    )
