from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable
from enum import StrEnum
from pathlib import PurePosixPath

from ..config.hub_prior_config import HubPriorConfig

# H-87 role-prior levels. Hubs get the full positive unit; peripherals a half-unit penalty so a
# hub next to a peripheral separates by 1.5 units while two neutral files stay untouched.
# Test sources and non-source files (xml/md/properties/json) are stronger negatives because a
# WHERE-style query is never answered by them, yet they crowd the saturated CE top-10.
HUB_ROLE_PRIOR = 1.0
NEUTRAL_ROLE_PRIOR = 0.0
PERIPHERAL_ROLE_PRIOR = -0.5
TEST_PATH_ROLE_PRIOR = -0.75
NON_SOURCE_ROLE_PRIOR = -1.0

# Returns the directed in-degree of the file node, or None when no graph is available.
FanInLookup = Callable[[str], int | None]

_TOKEN_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|[_\-.\s]+")


class HubPriorMode(StrEnum):
    ADDITIVE = "additive"
    BAND = "band"


class HubPriorScorer:
    """H-87: query-independent "hubness" of a file, from its name/path and its graph fan-in.

    Pure and side-effect free: the only external input is an optional fan-in lookup, so the
    scorer is unit-testable without a graph artifact. `role_prior` is in [-1, 1],
    `fanin_prior` in [0, 1]; `priors` combines them with the caller's weights over one
    candidate set (fan-in is normalised against the busiest candidate of that set).
    """

    def __init__(self, vocabulary: HubPriorConfig | None = None, fan_in: FanInLookup | None = None):
        vocabulary = vocabulary or HubPriorConfig()
        self._hub_entries = [self._tokens(entry) for entry in vocabulary.hub_tokens]
        self._peripheral_entries = [self._tokens(entry) for entry in vocabulary.peripheral_tokens]
        self._test_path_segments = {segment.lower() for segment in vocabulary.test_path_segments}
        self._non_source_extensions = {extension.lower() for extension in vocabulary.non_source_extensions}
        self._fan_in = fan_in

    def role_prior(self, path: str) -> float:
        posix = PurePosixPath(path.replace("\\", "/"))
        if posix.suffix.lower() in self._non_source_extensions:
            return NON_SOURCE_ROLE_PRIOR
        if any(segment.lower() in self._test_path_segments for segment in posix.parts[:-1]):
            return TEST_PATH_ROLE_PRIOR
        tokens = self._tokens(posix.stem)
        if not tokens:
            return NEUTRAL_ROLE_PRIOR
        # The suffix names the role (RenameProcessor, RenameHandler); it wins over any earlier
        # token. Only when the suffix is unclassified does an inner token decide, and then a
        # peripheral marker (Handler, Test, Util) outweighs a hub marker.
        if self._ends_with_any(tokens, self._hub_entries):
            return HUB_ROLE_PRIOR
        if self._ends_with_any(tokens, self._peripheral_entries):
            return PERIPHERAL_ROLE_PRIOR
        if self._contains_any(tokens, self._peripheral_entries):
            return PERIPHERAL_ROLE_PRIOR
        if self._contains_any(tokens, self._hub_entries):
            return HUB_ROLE_PRIOR
        return NEUTRAL_ROLE_PRIOR

    def fan_in_degree(self, path: str) -> int | None:
        if self._fan_in is None:
            return None
        return self._fan_in(path)

    def max_in_degree(self, paths: Iterable[str]) -> int:
        return max((self.fan_in_degree(path) or 0 for path in paths), default=0)

    def fanin_prior(self, path: str, max_in_degree: int) -> float:
        if max_in_degree <= 0:
            return 0.0
        degree = self.fan_in_degree(path)
        if degree is None or degree <= 0:
            return 0.0
        return math.log1p(degree) / math.log1p(max_in_degree)

    def priors(self, paths: Iterable[str], *, role_weight: float, fanin_weight: float) -> dict[str, float]:
        """Combined prior per path for one candidate set: role_weight*role + fanin_weight*fanin.

        H-90: skip role_prior when role_weight == 0.0, cache fan_in_degree to avoid
        double lookups (max_in_degree + fanin_prior each call the fan-in source).
        """
        unique_paths = list(dict.fromkeys(paths))
        result: dict[str, float] = {}
        if role_weight != 0.0:
            for path in unique_paths:
                result[path] = role_weight * self.role_prior(path)
        if fanin_weight != 0.0:
            cached = {path: self.fan_in_degree(path) for path in unique_paths}
            max_deg = max((d or 0 for d in cached.values()), default=0)
            if max_deg > 0:
                for path in unique_paths:
                    degree = cached.get(path) or 0
                    result[path] = result.get(path, 0.0) + fanin_weight * (math.log1p(degree) / math.log1p(max_deg))
        return result

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return [token.lower() for token in _TOKEN_BOUNDARY.split(text) if token]

    @staticmethod
    def _ends_with_any(tokens: list[str], entries: list[list[str]]) -> bool:
        return any(entry and tokens[-len(entry) :] == entry for entry in entries)

    @staticmethod
    def _contains_any(tokens: list[str], entries: list[list[str]]) -> bool:
        for entry in entries:
            if not entry or len(entry) > len(tokens):
                continue
            if any(tokens[start : start + len(entry)] == entry for start in range(len(tokens) - len(entry) + 1)):
                return True
        return False
