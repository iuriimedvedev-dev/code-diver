from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from ..graph import CodeGraph, GraphEdge
from .graph_expansion_profile import GraphExpansionProfile


class FileGraphAdjacencyIndex:
    def __init__(self, adjacency: dict[str, list[tuple[str, float]]]):
        self.adjacency = adjacency

    @classmethod
    def from_graph(cls, graph: CodeGraph) -> FileGraphAdjacencyIndex:
        return cls.from_item_paths_and_edges(
            {item_id: item.path for item_id, item in graph.items.items()},
            graph.edges,
        )

    @classmethod
    def from_item_paths_and_edges(
        cls,
        item_paths: dict[str, str],
        edges: Iterable[GraphEdge],
    ) -> FileGraphAdjacencyIndex:
        adjacency: dict[str, dict[str, float]] = defaultdict(dict)
        for edge in edges:
            source_path = item_paths.get(edge.source)
            target_path = item_paths.get(edge.target)
            if source_path is None or target_path is None or source_path == target_path:
                continue
            adjacency[source_path][target_path] = max(
                adjacency[source_path].get(target_path, 0.0), edge.weight
            )
            adjacency[target_path][source_path] = max(
                adjacency[target_path].get(source_path, 0.0), edge.weight * 0.7
            )
        return cls(
            {
                path: sorted(neighbors.items(), key=lambda item: item[1], reverse=True)
                for path, neighbors in adjacency.items()
            }
        )

    def expand(
        self,
        seed_file_scores: dict[str, float],
        profile: GraphExpansionProfile,
    ) -> dict[str, float]:
        accumulated: dict[str, float] = defaultdict(float)
        frontier = dict(seed_file_scores)
        best_seen = dict(seed_file_scores)
        for depth in range(profile.depth):
            next_frontier: dict[str, float] = {}
            decay = profile.decay**depth
            for path, seed_score in frontier.items():
                for neighbor_path, weight in self.adjacency.get(path, []):
                    score = seed_score * weight * decay
                    if score <= profile.min_score:
                        continue
                    accumulated[neighbor_path] = max(accumulated[neighbor_path], score)
                    previous = best_seen.get(neighbor_path, 0.0)
                    if score > previous:
                        best_seen[neighbor_path] = score
                        next_frontier[neighbor_path] = max(next_frontier.get(neighbor_path, 0.0), score)
            if not next_frontier:
                break
            frontier = dict(
                sorted(next_frontier.items(), key=lambda item: item[1], reverse=True)[
                    : profile.neighbor_limit
                ]
            )
        return dict(accumulated)

    def to_json(self) -> dict[str, Any]:
        return {
            "adjacency": {
                path: [[neighbor_path, weight] for neighbor_path, weight in neighbors]
                for path, neighbors in self.adjacency.items()
            }
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> FileGraphAdjacencyIndex:
        return cls(
            {
                path: [
                    (str(neighbor_path), float(weight))
                    for neighbor_path, weight in neighbors
                ]
                for path, neighbors in dict(data.get("adjacency") or {}).items()
            }
        )
