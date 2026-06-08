from __future__ import annotations

from collections import defaultdict

from ..domain import CodeItem, CodeItemIndexKind, CodeItemIndexKindResolver
from ..graph import CodeGraph, GraphEdge
from .graph_expansion_profile import GraphExpansionProfile


class FileGraphCandidateExpander:
    def __init__(self, graph: CodeGraph):
        self.graph = graph
        self.kind_resolver = CodeItemIndexKindResolver()
        self.items_by_path = self._items_by_path(graph.items.values())
        self.adjacency = self._adjacency(graph.edges)

    def expand(
        self, seed_scores: dict[str, float], profile: GraphExpansionProfile
    ) -> dict[str, float]:
        if profile.depth <= 0 or not seed_scores:
            return {}
        seed_file_scores = self._seed_file_scores(seed_scores)
        if not seed_file_scores:
            return {}
        file_scores = self._expand_files(seed_file_scores, profile)
        return self._representative_item_scores(file_scores)

    def _seed_file_scores(self, seed_scores: dict[str, float]) -> dict[str, float]:
        scores: dict[str, float] = {}
        for item_id, score in seed_scores.items():
            item = self.graph.items.get(item_id)
            if item is None:
                continue
            scores[item.path] = max(scores.get(item.path, 0.0), score)
        return scores

    def _expand_files(
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
                        next_frontier[neighbor_path] = max(
                            next_frontier.get(neighbor_path, 0.0), score
                        )
            if not next_frontier:
                break
            frontier = dict(
                sorted(next_frontier.items(), key=lambda item: item[1], reverse=True)[
                    : profile.neighbor_limit
                ]
            )
        return dict(accumulated)

    def _representative_item_scores(
        self, file_scores: dict[str, float]
    ) -> dict[str, float]:
        scores: dict[str, float] = {}
        for path, score in file_scores.items():
            representatives = self._representatives(path)
            for item in representatives:
                scores[item.id] = max(scores.get(item.id, 0.0), score)
        return scores

    def _representatives(self, path: str) -> list[CodeItem]:
        items = self.items_by_path.get(path, [])
        file_items = [
            item
            for item in items
            if self.kind_resolver.resolve(item)
            in {
                CodeItemIndexKind.FILE_SUMMARY,
                CodeItemIndexKind.FILE_MANIFEST,
                CodeItemIndexKind.FILE_API_MANIFEST,
            }
        ]
        return file_items or items

    def _items_by_path(self, items: list[CodeItem]) -> dict[str, list[CodeItem]]:
        by_path: dict[str, list[CodeItem]] = defaultdict(list)
        for item in items:
            by_path[item.path].append(item)
        return dict(by_path)

    def _adjacency(self, edges: list[GraphEdge]) -> dict[str, list[tuple[str, float]]]:
        adjacency: dict[str, dict[str, float]] = defaultdict(dict)
        for edge in edges:
            source = self.graph.items.get(edge.source)
            target = self.graph.items.get(edge.target)
            if source is None or target is None or source.path == target.path:
                continue
            adjacency[source.path][target.path] = max(
                adjacency[source.path].get(target.path, 0.0), edge.weight
            )
            adjacency[target.path][source.path] = max(
                adjacency[target.path].get(source.path, 0.0), edge.weight * 0.7
            )
        return {
            path: sorted(neighbors.items(), key=lambda item: item[1], reverse=True)
            for path, neighbors in adjacency.items()
        }
