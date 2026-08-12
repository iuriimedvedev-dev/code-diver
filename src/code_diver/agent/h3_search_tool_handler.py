from __future__ import annotations

import re
from dataclasses import replace
from time import perf_counter
from typing import Any

from ..config import AppConfig
from ..domain import CodeItemIndexKindResolver
from ..graph import CodeGraphStore
from ..inspection import FileOutlineService, RgService, SymbolsService
from ..math_utils import normalize
from ..services import IdentifierAliasLocator
from ..strategies import RetrievalStrategyFactory


class H3SearchToolHandler:
    def __init__(
        self,
        config: AppConfig,
        provider: Any,
        vector_store: Any,
        *,
        exclude: list[str],
    ):
        self.config = config
        self.provider = provider
        self.vector_store = vector_store
        self.exclude = exclude
        self.kind_resolver = CodeItemIndexKindResolver()
        self.base_strategy = RetrievalStrategyFactory().create(config.search.strategy, config, provider, vector_store)
        self.outline = FileOutlineService(config.root, exclude, config.scanner.max_file_bytes)
        self.symbols = SymbolsService(config.root, exclude, config.scanner.max_file_bytes)
        self.rg = RgService(config.root, exclude, config.scanner.max_file_bytes)
        self.alias_locator: IdentifierAliasLocator | None = None
        self.alias_locator_loaded = False
        self.profile_strategies: dict[str, Any] = {}

    def search(self, query: str, limit: int, args: dict[str, Any]) -> dict[str, Any]:
        started = perf_counter()
        candidate_limit = self._bounded_int(args, "candidateLimit", "candidate_limit", default=max(limit, 30), maximum=120)
        union_profile_limit = self._bounded_int(
            args,
            "profileLimit",
            "profile_limit",
            default=max(candidate_limit, 80),
            maximum=200,
        )
        probe_files = self._bounded_int(args, "probeFiles", "probe_files", default=2, maximum=8)
        alias_limit = self._bounded_non_negative_int(args, "aliasLimit", "alias_limit", default=0, maximum=100)
        mode = str(args.get("mode") or "fast").strip().lower()
        if mode == "full":
            raw_union, profile_groups, profile_calls = self._full_profile_groups(query, union_profile_limit)
        else:
            raw_union, profile_groups, profile_calls = self._fast_profile_groups(query, union_profile_limit)
        union = self._balanced_candidate_mix(profile_groups, candidate_limit)
        probed, probe_metrics = self._probe_candidates(query, union[:probe_files])
        alias = self._alias_candidates(query, alias_limit)
        candidates = self._balanced_candidate_mix(
            [(union, 0.72), (alias, 0.18), (probed, 0.10)],
            candidate_limit,
        )
        elapsed_ms = (perf_counter() - started) * 1000
        return {
            "candidates": candidates[: max(limit, 1)],
            "metrics": {
                "candidateCount": len(candidates[: max(limit, 1)]),
                "rawUnionCandidateCount": len(self._dedupe_candidates(raw_union)),
                "unionProfileCalls": profile_calls,
                "aliasCalls": 1 if self.alias_locator is not None and alias_limit > 0 else 0,
                "aliasCandidateCount": len(alias),
                "outlineCalls": probe_metrics["outlineCalls"],
                "symbolCalls": probe_metrics["symbolCalls"],
                "rgCalls": probe_metrics["rgCalls"],
                "probeFailures": (
                    probe_metrics["outlineFailures"]
                    + probe_metrics["symbolFailures"]
                    + probe_metrics["rgFailures"]
                ),
                "source": f"h3_manifest_union:{mode}",
                "elapsedMs": elapsed_ms,
            },
        }

    def _fast_profile_groups(
        self,
        query: str,
        limit: int,
    ) -> tuple[list[dict[str, Any]], list[tuple[list[dict[str, Any]], float]], int]:
        query_vector = normalize(self.provider.embed_query(query))
        groups = [
            (self._vector_kind_candidates(query_vector, limit, "file_manifest", "h3:fast_manifest"), 0.62),
            (self._vector_kind_candidates(query_vector, limit, "file_summary", "h3:fast_summary"), 0.38),
        ]
        raw = [candidate for rows, _ in groups for candidate in rows]
        return raw, groups, len(groups)

    def _full_profile_groups(
        self,
        query: str,
        limit: int,
    ) -> tuple[list[dict[str, Any]], list[tuple[list[dict[str, Any]], float]], int]:
        raw_union: list[dict[str, Any]] = []
        profile_groups: list[tuple[list[dict[str, Any]], float]] = []
        profile_calls = 0
        for profile_name, profile_config in self._union_profiles(limit):
            strategy = self._profile_strategy(profile_name, profile_config)
            rows = self._locator_candidates(strategy, query, limit, source=f"h3:{profile_name}")
            profile_groups.append((rows, 1.0))
            raw_union.extend(rows)
            profile_calls += 1
        return raw_union, profile_groups, profile_calls

    def _vector_kind_candidates(
        self,
        query_vector: list[float],
        limit: int,
        index_kind: str,
        source: str,
    ) -> list[dict[str, Any]]:
        search_by_kind = getattr(self.vector_store, "search_by_index_kind", None)
        if callable(search_by_kind):
            results = search_by_kind(query_vector, limit, index_kind)
        else:
            results = [
                result
                for result in self.vector_store.search(query_vector, limit * 4)
                if self.kind_resolver.resolve(result.item) == index_kind
            ][:limit]
        return [
            {
                "id": result.item.id,
                "path": result.item.path,
                "title": result.item.title,
                "startLine": result.item.start_line,
                "endLine": result.item.end_line,
                "score": result.score,
                "indexKind": self.kind_resolver.resolve(result.item),
                "source": source,
                "preview": self._preview(result.item.content, 420),
            }
            for result in results
        ]

    def _alias_locator(self) -> IdentifierAliasLocator | None:
        if self.alias_locator_loaded:
            return self.alias_locator
        self.alias_locator_loaded = True
        if not self.config.graph.enabled:
            return None
        store = CodeGraphStore(self.config.graph.artifact)
        if not store.exists():
            return None
        try:
            self.alias_locator = IdentifierAliasLocator(store.load())
            return self.alias_locator
        except Exception:
            return None

    def _union_profiles(self, profile_limit: int) -> list[tuple[str, AppConfig]]:
        base = self.config.hybrid_search
        lexical_candidate_limit = max(base.lexical_candidate_limit, profile_limit * 4)
        return [
            ("balanced", self.config),
            (
                "lexical_heavy",
                replace(
                    self.config,
                    hybrid_search=replace(
                        base,
                        candidate_limit=profile_limit,
                        lexical_candidate_limit=lexical_candidate_limit,
                        vector_weight=0.24,
                        lexical_weight=0.46,
                        path_weight=0.20,
                        symbol_weight=0.08,
                        symbol_match_weight=0.16,
                        preserve_vector_top=False,
                    ),
                ),
            ),
            (
                "path_symbol",
                replace(
                    self.config,
                    hybrid_search=replace(
                        base,
                        candidate_limit=profile_limit,
                        lexical_candidate_limit=max(base.lexical_candidate_limit, profile_limit * 3),
                        vector_weight=0.20,
                        lexical_weight=0.24,
                        path_weight=0.30,
                        symbol_weight=0.12,
                        symbol_match_weight=0.24,
                        preserve_vector_top=False,
                    ),
                ),
            ),
            (
                "vector_wide",
                replace(
                    self.config,
                    hybrid_search=replace(
                        base,
                        candidate_limit=profile_limit,
                        vector_weight=0.64,
                        lexical_weight=0.16,
                        path_weight=0.10,
                        symbol_weight=0.06,
                        symbol_match_weight=0.08,
                        preserve_vector_top=True,
                    ),
                ),
            ),
        ]

    def _locator_candidates(self, strategy: Any, query: str, limit: int, source: str) -> list[dict[str, Any]]:
        return [
            {
                "id": result.item.id,
                "path": result.item.path,
                "title": result.item.title,
                "startLine": result.item.start_line,
                "endLine": result.item.end_line,
                "score": result.score,
                "indexKind": self.kind_resolver.resolve(result.item),
                "source": source,
                "preview": self._preview(result.item.content, 420),
            }
            for result in strategy.search(query, limit)
        ]

    def _probe_candidates(self, query: str, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
        # Probing is best-effort per file: one unreadable file must not abort the sweep.
        # Failures are counted rather than swallowed so a systemic fault (a missing `rg`
        # binary, an unreadable tree) shows up in the metrics instead of silently
        # degrading recall to zero probe candidates.
        candidates: list[dict[str, Any]] = []
        metrics = {
            "outlineCalls": 0,
            "symbolCalls": 0,
            "rgCalls": 0,
            "outlineFailures": 0,
            "symbolFailures": 0,
            "rgFailures": 0,
        }
        pattern = "|".join(re.escape(term) for term in self._terms(query)[:5])
        for candidate in rows:
            path = str(candidate.get("path") or "")
            if not path:
                continue
            try:
                outline_payload = self.outline.structured(path, symbol_limit=80, import_limit=30)
                metrics["outlineCalls"] += 1
                candidates.extend(self._outline_candidates(outline_payload))
            except Exception:  # best-effort probe; failure is counted, not swallowed
                metrics["outlineFailures"] += 1
            try:
                symbol_payload = self.symbols.structured(path=path, limit=40, query=query)
                metrics["symbolCalls"] += 1
                candidates.extend(self._tool_candidates(symbol_payload, "symbols"))
            except Exception:  # best-effort probe; failure is counted, not swallowed
                metrics["symbolFailures"] += 1
            if pattern:
                try:
                    rg_payload = self.rg.structured(pattern, path=path, limit=20, include_text=False)
                    metrics["rgCalls"] += 1
                    candidates.extend(self._tool_candidates(rg_payload, "rg"))
                except Exception:  # best-effort probe; failure is counted, not swallowed
                    metrics["rgFailures"] += 1
        return candidates, metrics

    def _alias_candidates(self, query: str, limit: int) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        alias_locator = self._alias_locator()
        if alias_locator is None:
            return []
        return [
            {
                "id": f"{candidate.path}:identifier_alias",
                "path": candidate.path,
                "title": candidate.title,
                "startLine": None,
                "endLine": None,
                "score": candidate.score,
                "indexKind": "identifier_alias",
                "source": "identifier_alias",
                "preview": candidate.preview,
                "matchedAliases": list(candidate.matched_aliases),
            }
            for candidate in alias_locator.search(query, limit)
        ]

    def _profile_strategy(self, profile_name: str, profile_config: AppConfig) -> Any:
        if profile_name == "balanced":
            return self.base_strategy
        strategy = self.profile_strategies.get(profile_name)
        if strategy is None:
            strategy = RetrievalStrategyFactory().create(
                profile_config.search.strategy,
                profile_config,
                self.provider,
                self.vector_store,
            )
            self.profile_strategies[profile_name] = strategy
        return strategy

    def _outline_candidates(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        rows = self._tool_candidates(payload, "outline")
        symbols = payload.get("symbols") if isinstance(payload.get("symbols"), list) else []
        preview = " ".join(
            str(symbol.get("signature") or symbol.get("name") or "")
            for symbol in symbols[:20]
            if isinstance(symbol, dict)
        )
        for row in rows:
            row["preview"] = self._preview(preview, 420)
        return rows

    def _tool_candidates(self, payload: dict[str, Any], source: str) -> list[dict[str, Any]]:
        rows = payload.get("candidates")
        if not isinstance(rows, list):
            return []
        candidates: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            path = str(row.get("path") or "").strip()
            if not path:
                continue
            clone = dict(row)
            clone.setdefault("id", f"{path}:{clone.get('startLine') or ''}:{source}")
            clone.setdefault("title", path)
            clone.setdefault("score", clone.get("confidence") or 0.0)
            clone.setdefault("source", source)
            clone.setdefault("preview", " ".join(str(value) for value in clone.get("symbols") or clone.get("evidenceLines") or []))
            candidates.append(clone)
        return candidates

    def _balanced_candidate_mix(
        self,
        groups: list[tuple[list[dict[str, Any]], float]],
        limit: int,
    ) -> list[dict[str, Any]]:
        positive_groups = [(self._dedupe_candidates(rows), max(float(weight), 0.0)) for rows, weight in groups if rows]
        if not positive_groups or limit <= 0:
            return []
        total_weight = sum(weight for _, weight in positive_groups) or float(len(positive_groups))
        quotas = [max(1, int(limit * weight / total_weight)) for _, weight in positive_groups]
        while sum(quotas) > limit:
            largest_index = max(range(len(quotas)), key=lambda index: quotas[index])
            quotas[largest_index] -= 1
        while sum(quotas) < limit:
            smallest_index = min(range(len(quotas)), key=lambda index: quotas[index])
            quotas[smallest_index] += 1
        selected: list[dict[str, Any]] = []
        seen: set[str] = set()
        for (rows, _), quota in zip(positive_groups, quotas, strict=False):
            self._append_candidates(selected, seen, rows, quota)
        if len(selected) < limit:
            for rows, _ in positive_groups:
                self._append_candidates(selected, seen, rows, limit - len(selected))
                if len(selected) >= limit:
                    break
        return selected[:limit]

    def _append_candidates(
        self,
        selected: list[dict[str, Any]],
        seen: set[str],
        rows: list[dict[str, Any]],
        quota: int,
    ) -> None:
        appended = 0
        for row in rows:
            key = self._candidate_key(row)
            if key in seen:
                continue
            seen.add(key)
            selected.append(row)
            appended += 1
            if appended >= quota:
                break

    def _dedupe_candidates(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        rows: list[dict[str, Any]] = []
        for candidate in candidates:
            path = str(candidate.get("path") or "").strip()
            if not path:
                continue
            key = self._candidate_key(candidate)
            if key in seen:
                continue
            seen.add(key)
            rows.append(candidate)
        return rows

    def _candidate_key(self, candidate: dict[str, Any]) -> str:
        return str(candidate.get("id") or f"{candidate.get('path')}:{candidate.get('startLine') or ''}")

    def _terms(self, query: str) -> list[str]:
        return [term.lower() for term in re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", query)][:8]

    def _preview(self, text: str, limit: int) -> str:
        compact = " ".join(str(text).split())
        if len(compact) <= limit:
            return compact
        return compact[:limit].rstrip() + "..."

    def _bounded_int(self, args: dict[str, Any], *keys: str, default: int, maximum: int) -> int:
        value: Any = None
        for key in keys:
            if key in args:
                value = args[key]
                break
        try:
            parsed = int(value if value is not None else default)
        except (TypeError, ValueError):
            parsed = default
        return max(1, min(parsed, maximum))

    def _bounded_non_negative_int(self, args: dict[str, Any], *keys: str, default: int, maximum: int) -> int:
        value: Any = None
        for key in keys:
            if key in args:
                value = args[key]
                break
        try:
            parsed = int(value if value is not None else default)
        except (TypeError, ValueError):
            parsed = default
        return max(0, min(parsed, maximum))
