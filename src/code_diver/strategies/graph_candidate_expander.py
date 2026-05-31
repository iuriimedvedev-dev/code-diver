from __future__ import annotations

from collections import defaultdict

from .graph_expansion_profile import GraphExpansionProfile
from .graph_neighbor_index import GraphNeighborIndex


class GraphCandidateExpander:
    def __init__(self, neighbor_index: GraphNeighborIndex):
        self.neighbor_index = neighbor_index

    def expand(self, seed_scores: dict[str, float], profile: GraphExpansionProfile) -> dict[str, float]:
        if profile.depth <= 0 or not seed_scores:
            return {}
        accumulated: dict[str, float] = defaultdict(float)
        frontier = dict(seed_scores)
        best_seen = dict(seed_scores)
        for depth in range(profile.depth):
            next_frontier: dict[str, float] = {}
            decay = profile.decay**depth
            for item_id, seed_score in frontier.items():
                for neighbor in self.neighbor_index.neighbors(item_id, profile):
                    score = seed_score * neighbor.weight * decay
                    if score <= profile.min_score:
                        continue
                    accumulated[neighbor.item_id] = max(accumulated[neighbor.item_id], score)
                    previous = best_seen.get(neighbor.item_id, 0.0)
                    if score > previous:
                        best_seen[neighbor.item_id] = score
                        next_frontier[neighbor.item_id] = max(next_frontier.get(neighbor.item_id, 0.0), score)
            if not next_frontier:
                break
            frontier = dict(
                sorted(next_frontier.items(), key=lambda item: item[1], reverse=True)[: profile.neighbor_limit]
            )
        return dict(accumulated)
