from __future__ import annotations

import argparse
import json
import re
import time
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from code_diver.cli import (
    config_for_search_hypothesis,
    direct_search_eval_result,
    direct_search_file_path,
    direct_search_matches_any,
    direct_search_metrics,
    eval_result_to_json,
    inspection_exclude_patterns,
    make_embedding_provider,
    make_ephemeral_search_tool_handler,
    make_retrieval_strategy,
    make_rerank_tool_handler,
    search_tool_hypotheses,
)
from code_diver.config import ConfigLoader
from code_diver.domain import CodeItemIndexKindResolver
from code_diver.generation import create_generation_provider
from code_diver.graph import CodeGraphStore
from code_diver.inspection import FileOutlineService, RgService, SymbolsService
from code_diver.orchestration.json_response import JsonResponse
from code_diver.services import DatasetLoader, IdentifierAliasLocator
from code_diver.store import create_vector_store
from code_diver.agent.model_cost_estimator import ModelCostEstimator


@dataclass(slots=True)
class DeterministicRun:
    hypothesis: str
    scenario: str
    metrics: dict[str, Any]
    orchestrator_usage: dict[str, Any]
    results: list[dict[str, Any]]
    errors: list[str]
    tool_metrics: dict[str, Any]
    diagnostics: list[dict[str, Any]]


class DeterministicPostrankH2:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.config = ConfigLoader().load(args.config)
        if args.trace_artifact is not None:
            self.config = replace(self.config, trace=replace(self.config.trace, artifact=args.trace_artifact))
        if args.disable_trace:
            self.config = replace(self.config, trace=replace(self.config.trace, enabled=False))
        self.limit = int(args.limit)
        self.locator_limit = int(args.locator_limit)
        self.run_id = args.run_id or uuid.uuid4().hex[:12]

    def run(self) -> dict[str, Any]:
        cases = DatasetLoader().load(self.args.dataset)
        if self.args.cases > 0:
            cases = cases[: self.args.cases]
        rows = []
        for hypothesis in search_tool_hypotheses(self.config, self.args.hypothesis):
            scenario = self._scenario(hypothesis.name)
            if scenario not in {"branch_a", "branch_b", "branch_c", "branch_d"}:
                continue
            rows.append(self._run_hypothesis(hypothesis, scenario, cases))
        result = {
            "run_id": self.run_id,
            "benchmark": {
                "config": str(self.args.config),
                "dataset": str(self.args.dataset),
                "cases": len(cases),
                "limit": self.limit,
                "locator_limit": self.locator_limit,
                "mode": "deterministic_postrank_h2",
            },
            "results": [self._run_to_json(row) for row in rows],
        }
        self.args.output.parent.mkdir(parents=True, exist_ok=True)
        self.args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        if self.args.report is not None:
            self._build_report()
        return result

    def _run_hypothesis(self, hypothesis: Any, scenario: str, cases: list[Any]) -> DeterministicRun:
        config = config_for_search_hypothesis(self.config, hypothesis)
        vector_store = create_vector_store(config)
        started = time.perf_counter()
        errors: list[str] = []
        degraded_case_ids: set[str] = set()
        durations_ms: list[float] = []
        eval_results = []
        diagnostics: list[dict[str, Any]] = []
        usage = self._empty_usage()
        tool_metrics = {
            "locator_calls": 0,
            "outline_calls": 0,
            "symbol_calls": 0,
            "rg_calls": 0,
            "ephemeral_calls": 0,
            "union_profile_calls": 0,
            "union_candidate_count_total": 0,
            "planner_calls": 0,
            "planner_errors": 0,
            "query_variant_total": 0,
            "alias_calls": 0,
            "alias_candidate_count_total": 0,
            "rerank_calls": 0,
            "rerank_errors": 0,
            "rerank_error_attempts": 0,
            "rerank_error_cases": 0,
            "candidate_count_total": 0,
            "candidate_count_mean": 0.0,
            "ephemeral_build_ms_total": 0.0,
            "ephemeral_query_ms_total": 0.0,
            "temporary_vectors_total": 0,
            "protected_base_files": int(self.args.protected_base_files),
        }
        try:
            retrieval_config = self._retrieval_config(config)
            provider = make_embedding_provider(retrieval_config, vector_store.metadata())
            strategy = make_retrieval_strategy(retrieval_config, provider, vector_store)
            generation_provider = create_generation_provider(config)
            rerank = make_rerank_tool_handler(config, generation_provider)
            ephemeral = make_ephemeral_search_tool_handler(config)
            alias_locator = self._alias_locator(config)
            outline = FileOutlineService(config.root, inspection_exclude_patterns(config), config.scanner.max_file_bytes)
            symbols = SymbolsService(config.root, inspection_exclude_patterns(config), config.scanner.max_file_bytes)
            rg = RgService(config.root, inspection_exclude_patterns(config), config.scanner.max_file_bytes)
            total_cases = len(cases)
            for case_index, case in enumerate(cases, start=1):
                if self._should_print_progress(case_index, total_cases):
                    print(
                        f"{hypothesis.name}: case {case_index}/{total_cases} "
                        f"(scenario={scenario}, degraded_cases={len(degraded_case_ids)})",
                        flush=True,
                    )
                case_started = time.perf_counter()
                query_variants: list[str] = []
                try:
                    locator = self._locator_candidates(strategy, case.query, self.locator_limit)
                    tool_metrics["locator_calls"] += 1
                    if scenario == "branch_a":
                        candidates = self._branch_a_candidates(case.query, locator, outline, symbols, rg, tool_metrics)
                    elif scenario == "branch_b":
                        candidates = self._branch_b_candidates(case.query, locator, ephemeral, tool_metrics)
                    else:
                        if scenario == "branch_c":
                            candidates = self._branch_c_candidates(
                                case.query,
                                retrieval_config,
                                provider,
                                vector_store,
                                strategy,
                                outline,
                                symbols,
                                rg,
                                alias_locator,
                                tool_metrics,
                            )
                        else:
                            query_variants, planner_metrics = self._query_variants(generation_provider, case.query, tool_metrics)
                            self._merge_usage(usage, planner_metrics)
                            candidates = self._branch_d_candidates(
                                case.query,
                                query_variants,
                                retrieval_config,
                                provider,
                                vector_store,
                                strategy,
                                outline,
                                symbols,
                                rg,
                                alias_locator,
                                tool_metrics,
                            )
                    tool_metrics["candidate_count_total"] += len(candidates)
                    reranked, rerank_metrics, rerank_degraded = self._rerank(rerank, case.query, candidates, tool_metrics)
                    if rerank_degraded:
                        degraded_case_ids.add(str(case.id))
                    self._merge_usage(usage, rerank_metrics)
                    retrieved = [str(candidate.get("path") or "") for candidate in reranked if candidate.get("path")]
                    eval_results.append(direct_search_eval_result(case, retrieved, self.limit))
                    diagnostics.append(
                        self._case_diagnostic(
                            case,
                            locator=locator,
                            candidates=candidates,
                            reranked=reranked,
                            degraded=rerank_degraded,
                            query_variants=query_variants,
                        )
                    )
                except Exception as exc:
                    degraded_case_ids.add(str(case.id))
                    errors.append(f"{case.id}: {type(exc).__name__}: {exc}")
                    eval_results.append(direct_search_eval_result(case, [], self.limit))
                    diagnostics.append(
                        {
                            "case_id": str(case.id),
                            "query": case.query,
                            "expected": list(case.expected),
                            "error": f"{type(exc).__name__}: {exc}",
                            "locator_rank": None,
                            "candidate_rank": None,
                            "rerank_rank": None,
                            "query_variants": query_variants,
                        }
                    )
                durations_ms.append((time.perf_counter() - case_started) * 1000)
                if self._should_print_progress(case_index, total_cases):
                    tool_metrics["candidate_count_mean"] = tool_metrics["candidate_count_total"] / max(case_index, 1)
                    self._write_partial(
                        hypothesis.name,
                        scenario,
                        case_index,
                        total_cases,
                        eval_results,
                        durations_ms,
                        usage,
                        tool_metrics,
                        errors,
                        degraded_case_ids,
                        diagnostics,
                    )
        finally:
            close = getattr(vector_store, "close", None)
            if callable(close):
                close()
        if cases:
            tool_metrics["candidate_count_mean"] = tool_metrics["candidate_count_total"] / len(cases)
        metrics = direct_search_metrics(eval_results, durations_ms, self.limit)
        metrics["duration_ms"] = (time.perf_counter() - started) * 1000
        tool_metrics["rerank_error_cases"] = len(degraded_case_ids)
        metrics["degraded"] = bool(degraded_case_ids)
        metrics["degraded_cases"] = len(degraded_case_ids)
        return DeterministicRun(
            hypothesis=hypothesis.name,
            scenario=scenario,
            metrics=metrics,
            orchestrator_usage=usage,
            results=[eval_result_to_json(result) for result in eval_results],
            errors=errors[:20],
            tool_metrics=tool_metrics,
            diagnostics=diagnostics,
        )

    def _locator_candidates(self, strategy: Any, query: str, limit: int, source: str = "locator") -> list[dict[str, Any]]:
        resolver = CodeItemIndexKindResolver()
        return [
            {
                "id": result.item.id,
                "path": result.item.path,
                "title": result.item.title,
                "startLine": result.item.start_line,
                "endLine": result.item.end_line,
                "score": result.score,
                "indexKind": resolver.resolve(result.item),
                "source": source,
                "preview": self._preview(result.item.content, 420),
            }
            for result in strategy.search(query, limit)
        ]

    def _branch_a_candidates(
        self,
        query: str,
        locator: list[dict[str, Any]],
        outline: FileOutlineService,
        symbols: SymbolsService,
        rg: RgService,
        metrics: dict[str, Any],
    ) -> list[dict[str, Any]]:
        outline_candidates: list[dict[str, Any]] = []
        symbol_candidates: list[dict[str, Any]] = []
        rg_candidates: list[dict[str, Any]] = []
        terms = self._terms(query)
        pattern = "|".join(re.escape(term) for term in terms[:5])
        for candidate in locator[: self.args.probe_files]:
            path = str(candidate.get("path") or "")
            if not path:
                continue
            try:
                payload = outline.structured(path, symbol_limit=80, import_limit=30)
                metrics["outline_calls"] += 1
                outline_candidates.extend(self._outline_candidates(payload))
            except Exception:
                pass
            try:
                payload = symbols.structured(path=path, limit=40, query=query)
                metrics["symbol_calls"] += 1
                symbol_candidates.extend(self._tool_candidates(payload, "symbols"))
            except Exception:
                pass
            if pattern:
                try:
                    payload = rg.structured(pattern, path=path, limit=20, include_text=False)
                    metrics["rg_calls"] += 1
                    rg_candidates.extend(self._tool_candidates(payload, "rg"))
                except Exception:
                    pass
        return self._balanced_candidate_mix(
            [
                (locator, 0.58),
                (outline_candidates, 0.14),
                (symbol_candidates, 0.14),
                (rg_candidates, 0.14),
            ],
            self.args.rerank_candidate_limit,
        )

    def _branch_b_candidates(
        self,
        query: str,
        locator: list[dict[str, Any]],
        ephemeral: Any,
        metrics: dict[str, Any],
    ) -> list[dict[str, Any]]:
        files = [str(candidate.get("path") or "") for candidate in locator if candidate.get("path")]
        payload = ephemeral(query, files[: self.locator_limit], self.args.ephemeral_limit, {"fileLimit": self.locator_limit})
        metrics["ephemeral_calls"] += 1
        deep_metrics = payload.get("metrics") or {}
        metrics["ephemeral_build_ms_total"] += float(deep_metrics.get("ephemeral_build_ms") or 0.0)
        metrics["ephemeral_query_ms_total"] += float(deep_metrics.get("ephemeral_query_ms") or 0.0)
        metrics["temporary_vectors_total"] += int(deep_metrics.get("temporary_vectors") or 0)
        deep = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []
        for candidate in deep:
            if isinstance(candidate, dict):
                candidate["source"] = "ephemeral"
        return self._balanced_candidate_mix([(locator, 0.55), (deep, 0.45)], self.args.rerank_candidate_limit)

    def _branch_c_candidates(
        self,
        query: str,
        config: Any,
        provider: Any,
        vector_store: Any,
        base_strategy: Any,
        outline: FileOutlineService,
        symbols: SymbolsService,
        rg: RgService,
        alias_locator: IdentifierAliasLocator | None,
        metrics: dict[str, Any],
    ) -> list[dict[str, Any]]:
        profile_groups: list[tuple[list[dict[str, Any]], float]] = []
        raw_union: list[dict[str, Any]] = []
        for profile_name, profile_config in self._union_profiles(config):
            strategy = base_strategy if profile_name == "balanced" else make_retrieval_strategy(profile_config, provider, vector_store)
            limit = max(self.locator_limit, int(self.args.union_profile_limit))
            profile_candidates = self._locator_candidates(strategy, query, limit, source=f"union:{profile_name}")
            profile_groups.append((profile_candidates, 1.0))
            raw_union.extend(profile_candidates)
            metrics["union_profile_calls"] += 1
        metrics["union_candidate_count_total"] += len(self._dedupe_candidates(raw_union))
        union = self._balanced_candidate_mix(profile_groups, self.args.rerank_candidate_limit)
        probed = self._branch_a_candidates(query, union[: self.args.union_probe_files], outline, symbols, rg, metrics)
        alias = self._alias_candidates(alias_locator, query, metrics, limit=self._alias_limit())
        return self._balanced_candidate_mix(
            [(union, 0.72), (alias, 0.18), (probed, 0.10)],
            self.args.rerank_candidate_limit,
        )

    def _branch_d_candidates(
        self,
        query: str,
        query_variants: list[str],
        config: Any,
        provider: Any,
        vector_store: Any,
        base_strategy: Any,
        outline: FileOutlineService,
        symbols: SymbolsService,
        rg: RgService,
        alias_locator: IdentifierAliasLocator | None,
        metrics: dict[str, Any],
    ) -> list[dict[str, Any]]:
        search_groups: list[tuple[list[dict[str, Any]], float]] = []
        raw_union: list[dict[str, Any]] = []
        searches = [query, *query_variants]
        for search_query in searches[: max(int(self.args.query_variant_limit), 1)]:
            search_candidates = self._union_locator_candidates(
                search_query,
                config,
                provider,
                vector_store,
                base_strategy,
                metrics,
                source_prefix="multiquery",
            )
            search_groups.append((search_candidates, 1.0))
            raw_union.extend(search_candidates)
        metrics["union_candidate_count_total"] += len(self._dedupe_candidates(raw_union))
        union = self._priority_query_candidate_mix(search_groups, self.args.rerank_candidate_limit)
        probed = self._branch_a_candidates(query, union[: self.args.union_probe_files], outline, symbols, rg, metrics)
        alias_rows: list[dict[str, Any]] = []
        for search_query in searches[: max(int(self.args.query_variant_limit), 1)]:
            alias_rows.extend(self._alias_candidates(alias_locator, search_query, metrics, limit=self._alias_limit()))
        alias = self._dedupe_candidates(alias_rows)
        return self._balanced_candidate_mix(
            [(union, 0.70), (alias, 0.20), (probed, 0.10)],
            self.args.rerank_candidate_limit,
        )

    def _alias_locator(self, config: Any) -> IdentifierAliasLocator | None:
        artifact = self.args.alias_graph or config.graph.artifact
        store = CodeGraphStore(artifact)
        if not store.exists():
            return None
        try:
            return IdentifierAliasLocator(store.load())
        except Exception:
            return None

    def _retrieval_config(self, config: Any) -> Any:
        if not self.args.disable_graph_retrieval:
            return config
        disabled_artifact = self.args.partial_dir / f"disabled-graph-{self.run_id}.json"
        return replace(config, graph=replace(config.graph, artifact=disabled_artifact))

    def _alias_candidates(
        self,
        alias_locator: IdentifierAliasLocator | None,
        query: str,
        metrics: dict[str, Any],
        limit: int,
    ) -> list[dict[str, Any]]:
        if alias_locator is None:
            return []
        metrics["alias_calls"] += 1
        rows = []
        for candidate in alias_locator.search(query, limit):
            rows.append(
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
            )
        metrics["alias_candidate_count_total"] += len(rows)
        return rows

    def _alias_limit(self) -> int:
        return max(int(self.args.alias_limit), 0)

    def _union_locator_candidates(
        self,
        query: str,
        config: Any,
        provider: Any,
        vector_store: Any,
        base_strategy: Any,
        metrics: dict[str, Any],
        source_prefix: str,
    ) -> list[dict[str, Any]]:
        profile_groups: list[tuple[list[dict[str, Any]], float]] = []
        for profile_name, profile_config in self._union_profiles(config):
            strategy = base_strategy if profile_name == "balanced" else make_retrieval_strategy(profile_config, provider, vector_store)
            limit = max(self.locator_limit, int(self.args.union_profile_limit))
            profile_groups.append(
                (
                    self._locator_candidates(strategy, query, limit, source=f"{source_prefix}:{profile_name}"),
                    1.0,
                )
            )
            metrics["union_profile_calls"] += 1
        return self._balanced_candidate_mix(profile_groups, max(self.locator_limit, int(self.args.union_profile_limit)))

    def _union_profiles(self, config: Any) -> list[tuple[str, Any]]:
        base = config.hybrid_search
        profile_limit = max(int(self.args.union_profile_limit), self.locator_limit)
        return [
            ("balanced", config),
            (
                "lexical_heavy",
                replace(
                    config,
                    hybrid_search=replace(
                        base,
                        candidate_limit=profile_limit,
                        lexical_candidate_limit=max(base.lexical_candidate_limit, profile_limit * 4),
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
                    config,
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
                    config,
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

    def _query_variants(self, generation_provider: Any, query: str, metrics: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
        metrics["planner_calls"] += 1
        heuristic_queries = self._heuristic_query_variants(query)
        prompt = f"""
You are a query-planning tool for repository-agnostic code search.

Given one informal code-navigation query, produce alternate search queries that improve file recall.

Generate:
- exact symbol-like variants in camelCase/PascalCase when likely;
- implementation-owner terms such as manager, service, handler, command, strategy, provider, factory, parser, resolver;
- class-name hypotheses by combining the main nouns with common suffixes: Manager, Service, Handler, Command, Strategy, Provider, Factory, Parser, Resolver, Util, Impl;
- method-name hypotheses from verbs, for example "open project" -> "openProject";
- short lexical variants that grep/BM25 can match;
- domain synonyms from the query.

Rules:
- Prefer likely symbol/class names over broad English paraphrases.
- Do not name files unless the class or path is strongly implied by the query.
- Do not include explanations.
- Return 5 unique query strings.
- Keep each query under 12 words.

Return JSON only:
{{"queries":["..."]}}

Input query: {query}
""".strip()
        try:
            started = time.perf_counter()
            response = generation_provider.generate_json_result(prompt)
            parsed = JsonResponse().parse_object(response.text)
            duration_ms = (time.perf_counter() - started) * 1000
            queries = self._merge_query_variants(query, heuristic_queries, parsed.get("queries"))
            metrics["query_variant_total"] += len(queries)
            cost = ModelCostEstimator().estimate(response.model, response.input_tokens, response.output_tokens)
            return queries, {
                "modelCalls": 1,
                "inputTokens": response.input_tokens,
                "outputTokens": response.output_tokens,
                "totalTokens": response.total_tokens,
                "estimatedCost": cost,
                "models": [response.model],
                "durationMs": duration_ms,
            }
        except Exception:
            metrics["planner_errors"] += 1
            queries = self._merge_query_variants(query, heuristic_queries)
            metrics["query_variant_total"] += len(queries)
            return queries, {"errors": 1, "degraded": True}

    def _merge_query_variants(self, original: str, *groups: Any) -> list[str]:
        seen = {original.strip().lower()}
        queries: list[str] = []
        for values in groups:
            if not isinstance(values, list):
                continue
            for value in values:
                query = " ".join(str(value).split())
                if not query:
                    continue
                key = query.lower()
                if key in seen:
                    continue
                seen.add(key)
                queries.append(query[:160])
                if len(queries) >= max(int(self.args.query_variant_limit) - 1, 0):
                    return queries
        return queries

    def _heuristic_query_variants(self, query: str) -> list[str]:
        terms = [term for term in self._terms(query) if term not in self._query_stopwords()]
        normalized_terms = [self._normalize_query_term(term) for term in terms]
        nouns = [term for term in normalized_terms if len(term) >= 4][:4]
        variants: list[str] = []
        if nouns:
            owner = self._pascal_case(nouns[0])
            variants.extend([f"{owner}Manager", f"{owner}ManagerImpl"])
        for first, second in zip(nouns, nouns[1:], strict=False):
            pair = self._pascal_case(first + " " + second)
            variants.extend(
                [
                    pair,
                    f"{pair}Impl",
                    f"{pair}Manager",
                    f"{pair}ManagerImpl",
                    f"{pair}Processor",
                    f"{pair}ProcessorImpl",
                    f"{pair}Handler",
                ]
            )
        for action in [term for term in normalized_terms if term in self._action_terms()]:
            action_pascal = self._pascal_case(action)
            variants.extend([f"{action_pascal}Manager", f"{action_pascal}ManagerImpl", f"{action_pascal}Processor"])
        for noun in nouns[:3]:
            pascal = self._pascal_case(noun)
            variants.extend(
                [
                    f"{pascal}Manager",
                    f"{pascal}ManagerImpl",
                    f"{pascal}Service",
                    f"{pascal}Handler",
                    f"{pascal}Provider",
                    f"{pascal}Processor",
                    f"{pascal}ProcessorImpl",
                ]
            )
        action_pairs = self._action_noun_pairs(normalized_terms)
        for action, noun in action_pairs:
            action_pascal = self._pascal_case(action)
            noun_pascal = self._pascal_case(noun)
            variants.extend(
                [
                    action + noun_pascal,
                    f"{action_pascal}{noun_pascal}Command",
                    f"{action_pascal}{noun_pascal}Handler",
                    f"{noun_pascal}{action_pascal}Processor",
                    f"{noun_pascal}{action_pascal}Manager",
                ]
            )
        return variants

    def _query_stopwords(self) -> set[str]:
        return {
            "where",
            "what",
            "which",
            "show",
            "does",
            "are",
            "is",
            "implemented",
            "implementation",
            "codebase",
            "code",
            "ide",
            "here",
            "there",
            "used",
            "created",
            "handled",
            "orchestrated",
            "coordinated",
            "executed",
            "undone",
            "managed",
            "happen",
        }

    def _normalize_query_term(self, term: str) -> str:
        aliases = {
            "opening": "open",
            "opened": "open",
            "opens": "open",
            "authorization": "auth",
            "authentication": "auth",
            "configuration": "config",
            "configurations": "config",
            "commands": "command",
            "usages": "usages",
        }
        if term in aliases:
            return aliases[term]
        if term.endswith("ies") and len(term) > 4:
            return term[:-3] + "y"
        if term.endswith("s") and len(term) > 5:
            return term[:-1]
        return term

    def _action_noun_pairs(self, terms: list[str]) -> list[tuple[str, str]]:
        actions = self._action_terms()
        pairs: list[tuple[str, str]] = []
        for index, term in enumerate(terms):
            if term not in actions:
                continue
            for candidate in terms[max(0, index - 2) : index] + terms[index + 1 : index + 3]:
                if candidate != term and len(candidate) >= 4:
                    pairs.append((term, candidate))
        return pairs[:4]

    def _action_terms(self) -> set[str]:
        return {"open", "create", "update", "edit", "delete", "remove", "load", "save", "parse", "resolve", "run", "execute", "find", "rename", "write", "import"}

    def _pascal_case(self, text: str) -> str:
        return "".join(part[:1].upper() + part[1:] for part in re.split(r"[^A-Za-z0-9]+", text) if part)

    def _rerank(
        self,
        rerank: Any,
        query: str,
        candidates: list[dict[str, Any]],
        metrics: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
        cumulative = {
            "modelCalls": 0,
            "inputTokens": 0,
            "outputTokens": 0,
            "totalTokens": 0,
            "estimatedCost": 0.0,
            "models": [],
            "errors": 0,
            "attempts": 0,
        }
        last_ranked: list[dict[str, Any]] = candidates[: self.limit]
        degraded = False
        return_limit = max(self.limit, int(self.args.rerank_return_limit or self.limit))
        for attempt in range(1, max(int(self.args.rerank_attempts), 1) + 1):
            metrics["rerank_calls"] += 1
            cumulative["attempts"] = attempt
            try:
                result = rerank(
                    query,
                    candidates,
                    self.limit,
                    {
                        "mode": self.args.rerank_mode if attempt == 1 else "compact",
                        "candidateLimit": self.args.rerank_candidate_limit,
                    },
                )
                rerank_metrics = result.get("metrics") or {}
            except Exception as exc:
                rerank_metrics = {"errors": 1, "degraded": True, "error": str(exc)}
                result = {"candidates": []}
            self._merge_rerank_metrics(cumulative, rerank_metrics)
            ranked = result.get("candidates")
            if isinstance(ranked, list) and ranked:
                ranked = self._dedupe_final_files([*ranked, *candidates], return_limit)
                last_ranked = self._preserve_base_files(
                    ranked,
                    candidates,
                    self.args.protected_base_files,
                    self.limit,
                    self.args.protected_base_mode,
                    self.args.llm_prefix_files,
                )
            if not rerank_metrics.get("errors") and not rerank_metrics.get("degraded"):
                return last_ranked, cumulative, degraded
            degraded = True
            metrics["rerank_errors"] += 1
            metrics["rerank_error_attempts"] += 1
        return last_ranked, cumulative, degraded

    def _dedupe_final_files(self, ranked: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        if not self.args.dedupe_final_files:
            return ranked[:limit]
        rows: list[dict[str, Any]] = []
        seen_files: set[str] = set()
        for candidate in ranked:
            path = str(candidate.get("path") or "").strip()
            if not path:
                continue
            file_path = direct_search_file_path(path)
            if file_path in seen_files:
                continue
            seen_files.add(file_path)
            clone = dict(candidate)
            clone["rerankRank"] = len(rows) + 1
            rows.append(clone)
            if len(rows) >= limit:
                break
        return rows

    def _preserve_base_files(
        self,
        ranked: list[dict[str, Any]],
        candidates: list[dict[str, Any]],
        preserve_count: int,
        limit: int,
        mode: str = "prefix",
        llm_prefix_files: int = 0,
    ) -> list[dict[str, Any]]:
        preserve_count = max(int(preserve_count), 0)
        if preserve_count <= 0 or limit <= 0:
            return ranked[:limit]

        protected: list[dict[str, Any]] = []
        protected_files: set[str] = set()
        for candidate in candidates:
            path = str(candidate.get("path") or "").strip()
            if not path:
                continue
            file_path = direct_search_file_path(path)
            if file_path in protected_files:
                continue
            protected_files.add(file_path)
            clone = dict(candidate)
            clone.setdefault("source", str(candidate.get("source") or "base_protected"))
            clone["protectedBaseRank"] = len(protected) + 1
            protected.append(clone)
            if len(protected) >= preserve_count:
                break

        ordered = [*protected, *ranked]
        if mode == "rescue":
            prefix_count = max(min(int(llm_prefix_files), limit), 0)
            ordered = [*ranked[:prefix_count], *protected, *ranked[prefix_count:]]

        merged: list[dict[str, Any]] = []
        seen_files: set[str] = set()
        for candidate in ordered:
            path = str(candidate.get("path") or "").strip()
            if not path:
                continue
            file_path = direct_search_file_path(path)
            if file_path in seen_files:
                continue
            seen_files.add(file_path)
            clone = dict(candidate)
            clone["rerankRank"] = len(merged) + 1
            merged.append(clone)
            if len(merged) >= limit:
                break
        return merged

    def _merge_rerank_metrics(self, target: dict[str, Any], source: dict[str, Any]) -> None:
        target["modelCalls"] += int(source.get("modelCalls") or source.get("model_calls") or 0)
        target["inputTokens"] += int(source.get("inputTokens") or source.get("input_tokens") or 0)
        target["outputTokens"] += int(source.get("outputTokens") or source.get("output_tokens") or 0)
        target["totalTokens"] += int(source.get("totalTokens") or source.get("total_tokens") or 0)
        target["estimatedCost"] += float(source.get("estimatedCost") or source.get("estimated_cost") or 0.0)
        target["errors"] += int(source.get("errors") or 0)
        target["degraded"] = bool(target["errors"])
        for model in source.get("models") or [source.get("model")]:
            if model and model not in target["models"]:
                target["models"].append(str(model))

    def _outline_candidates(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        rows = self._tool_candidates(payload, "outline")
        symbols = payload.get("symbols") if isinstance(payload.get("symbols"), list) else []
        preview = " ".join(str(symbol.get("signature") or symbol.get("name") or "") for symbol in symbols[:20] if isinstance(symbol, dict))
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

    def _dedupe_candidates(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        rows: list[dict[str, Any]] = []
        for candidate in candidates:
            path = str(candidate.get("path") or "").strip()
            if not path:
                continue
            key = str(candidate.get("id") or f"{path}:{candidate.get('startLine') or ''}")
            if key in seen:
                continue
            seen.add(key)
            rows.append(candidate)
        return rows

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

    def _priority_query_candidate_mix(
        self,
        groups: list[tuple[list[dict[str, Any]], float]],
        limit: int,
    ) -> list[dict[str, Any]]:
        if not groups or limit <= 0:
            return []
        deduped_groups = [(self._dedupe_candidates(rows), weight) for rows, weight in groups if rows]
        selected: list[dict[str, Any]] = []
        seen: set[str] = set()
        if not deduped_groups:
            return selected

        base_quota = min(max(int(limit * 0.50), self.locator_limit), limit)
        self._append_candidates(selected, seen, deduped_groups[0][0], base_quota)

        priority_variant_quota = max(10, int(limit * 0.16))
        for rows, _ in deduped_groups[1:3]:
            self._append_candidates(selected, seen, rows, min(priority_variant_quota, limit - len(selected)))
            if len(selected) >= limit:
                return selected[:limit]

        remaining = limit - len(selected)
        if remaining > 0:
            for candidate in self._balanced_candidate_mix(deduped_groups[3:], remaining):
                key = self._candidate_key(candidate)
                if key in seen:
                    continue
                seen.add(key)
                selected.append(candidate)
        if len(selected) < limit:
            for rows, _ in deduped_groups:
                self._append_candidates(selected, seen, rows, limit - len(selected))
                if len(selected) >= limit:
                    break
        return selected[:limit]

    def _append_candidates(
        self,
        selected: list[dict[str, Any]],
        seen: set[str],
        candidates: list[dict[str, Any]],
        limit: int,
    ) -> None:
        if limit <= 0:
            return
        added = 0
        for candidate in candidates:
            path = str(candidate.get("path") or "").strip()
            if not path:
                continue
            key = str(candidate.get("id") or f"{path}:{candidate.get('startLine') or ''}")
            if key in seen:
                continue
            seen.add(key)
            selected.append(candidate)
            added += 1
            if added >= limit:
                return

    def _candidate_key(self, candidate: dict[str, Any]) -> str:
        path = str(candidate.get("path") or "").strip()
        return str(candidate.get("id") or f"{path}:{candidate.get('startLine') or ''}")

    def _terms(self, query: str) -> list[str]:
        return [term for term in re.split(r"[^A-Za-z0-9_]+", query.lower()) if len(term) >= 3]

    def _case_diagnostic(
        self,
        case: Any,
        locator: list[dict[str, Any]],
        candidates: list[dict[str, Any]],
        reranked: list[dict[str, Any]],
        degraded: bool,
        query_variants: list[str] | None = None,
    ) -> dict[str, Any]:
        locator_paths = [str(candidate.get("path") or "") for candidate in locator if candidate.get("path")]
        candidate_paths = [str(candidate.get("path") or "") for candidate in candidates if candidate.get("path")]
        reranked_paths = [str(candidate.get("path") or "") for candidate in reranked if candidate.get("path")]
        return {
            "case_id": str(case.id),
            "query": case.query,
            "expected": list(case.expected),
            "locator_rank": self._first_matching_rank(locator_paths, case.expected),
            "candidate_rank": self._first_matching_rank(candidate_paths, case.expected),
            "rerank_rank": self._first_matching_rank(reranked_paths, case.expected),
            "locator_count": len(locator_paths),
            "candidate_count": len(candidate_paths),
            "rerank_count": len(reranked_paths),
            "expected_sources": self._expected_sources(candidates, case.expected),
            "query_variants": query_variants or [],
            "degraded": degraded,
            "top_locator_files": self._top_files(locator_paths, 5),
            "top_candidate_files": self._top_files(candidate_paths, 5),
            "top_reranked_files": self._top_files(reranked_paths, self.limit),
        }

    def _first_matching_rank(self, paths: list[str], expected: list[str]) -> int | None:
        for rank, path in enumerate(paths, start=1):
            if direct_search_matches_any(path, expected):
                return rank
        return None

    def _expected_sources(self, candidates: list[dict[str, Any]], expected: list[str]) -> list[str]:
        sources: list[str] = []
        for candidate in candidates:
            path = str(candidate.get("path") or "")
            if direct_search_matches_any(path, expected):
                source = str(candidate.get("source") or "unknown")
                if source not in sources:
                    sources.append(source)
        return sources

    def _top_files(self, paths: list[str], limit: int) -> list[str]:
        rows: list[str] = []
        seen: set[str] = set()
        for path in paths:
            file_path = direct_search_file_path(path)
            if file_path in seen:
                continue
            seen.add(file_path)
            rows.append(file_path)
            if len(rows) >= limit:
                break
        return rows

    def _preview(self, text: str, limit: int) -> str:
        compact = " ".join(text.split())
        if len(compact) <= limit:
            return compact
        return compact[:limit].rstrip() + "..."

    def _scenario(self, name: str) -> str:
        lowered = name.lower()
        if "multiquery" in lowered or "query_plan" in lowered:
            return "branch_d"
        if "union" in lowered:
            return "branch_c"
        if "ephemeral" in lowered:
            return "branch_b"
        if "grep" in lowered or "read" in lowered:
            return "branch_a"
        return "unknown"

    def _should_print_progress(self, case_index: int, total_cases: int) -> bool:
        progress_every = int(self.args.progress_every)
        return case_index == 1 or case_index == total_cases or (progress_every > 0 and case_index % progress_every == 0)

    def _write_partial(
        self,
        hypothesis: str,
        scenario: str,
        case_index: int,
        total_cases: int,
        eval_results: list[Any],
        durations_ms: list[float],
        usage: dict[str, Any],
        tool_metrics: dict[str, Any],
        errors: list[str],
        degraded_case_ids: set[str],
        diagnostics: list[dict[str, Any]],
    ) -> None:
        if self.args.partial_dir is None:
            return
        metrics = direct_search_metrics(eval_results, durations_ms, self.limit)
        metrics["degraded"] = bool(degraded_case_ids)
        metrics["degraded_cases"] = len(degraded_case_ids)
        payload = {
            "run_id": self.run_id,
            "hypothesis": hypothesis,
            "scenario": scenario,
            "completed_cases": case_index,
            "total_cases": total_cases,
            "metrics": metrics,
            "orchestrator_usage": usage,
            "tool_metrics": tool_metrics,
            "errors": errors[:20],
            "diagnostics": diagnostics,
        }
        self.args.partial_dir.mkdir(parents=True, exist_ok=True)
        path = self.args.partial_dir / f"{hypothesis}.partial.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _empty_usage(self) -> dict[str, Any]:
        return {"model_calls": 0, "tool_calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "total_cost": 0.0, "models": []}

    def _merge_usage(self, target: dict[str, Any], metrics: dict[str, Any]) -> None:
        target["model_calls"] += int(metrics.get("modelCalls") or metrics.get("model_calls") or 0)
        target["tool_calls"] += 1
        target["input_tokens"] += int(metrics.get("inputTokens") or metrics.get("input_tokens") or 0)
        target["output_tokens"] += int(metrics.get("outputTokens") or metrics.get("output_tokens") or 0)
        target["total_tokens"] += int(metrics.get("totalTokens") or metrics.get("total_tokens") or 0)
        target["total_cost"] += float(metrics.get("estimatedCost") or metrics.get("estimated_cost") or 0.0)
        for model in metrics.get("models") or [metrics.get("model")]:
            if model and model not in target["models"]:
                target["models"].append(str(model))

    def _run_to_json(self, row: DeterministicRun) -> dict[str, Any]:
        return {
            "hypothesis": row.hypothesis,
            "scenario": row.scenario,
            "orchestrator": "deterministic_postrank_h2",
            "metrics": row.metrics,
            "orchestrator_usage": row.orchestrator_usage,
            "tool_metrics": row.tool_metrics,
            "errors": row.errors,
            "error_count": len(row.errors),
            "results": row.results if self.args.details else [],
            "diagnostics": row.diagnostics,
        }

    def _build_report(self) -> None:
        import subprocess

        subprocess.run(
            [".venv/bin/python", "scripts/build_eval_report.py", str(self.args.output), "--output", str(self.args.report)],
            check=True,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic IntelliJ H2 post-ranking benchmark.")
    parser.add_argument("--config", type=Path, default=Path("configs/intellij-postrank-h2.yml"))
    parser.add_argument("--dataset", type=Path, default=Path("datasets/intellij_eval_1000.jsonl"))
    parser.add_argument("--cases", type=int, default=100)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--locator-limit", type=int, default=30)
    parser.add_argument("--probe-files", type=int, default=5)
    parser.add_argument("--union-profile-limit", type=int, default=100)
    parser.add_argument("--union-probe-files", type=int, default=10)
    parser.add_argument("--query-variant-limit", type=int, default=8)
    parser.add_argument("--ephemeral-limit", type=int, default=30)
    parser.add_argument("--rerank-candidate-limit", type=int, default=30)
    parser.add_argument("--rerank-return-limit", type=int, default=0)
    parser.add_argument("--rerank-attempts", type=int, default=2)
    parser.add_argument("--rerank-mode", default="file_first")
    parser.add_argument("--dedupe-final-files", action="store_true")
    parser.add_argument("--protected-base-files", type=int, default=0)
    parser.add_argument("--protected-base-mode", choices=["prefix", "rescue"], default="prefix")
    parser.add_argument("--llm-prefix-files", type=int, default=0)
    parser.add_argument("--alias-limit", type=int, default=50)
    parser.add_argument("--alias-graph", type=Path, default=None)
    parser.add_argument("--disable-graph-retrieval", action="store_true")
    parser.add_argument("--progress-every", type=int, default=25)
    parser.add_argument("--partial-dir", type=Path, default=Path(".code-diver/reports/partials"))
    parser.add_argument("--hypothesis", action="append", default=[])
    parser.add_argument("--details", action="store_true")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--trace-artifact", type=Path, default=None)
    parser.add_argument("--disable-trace", action="store_true")
    parser.add_argument("--output", type=Path, default=Path(".code-diver/reports/intellij-postrank-h2-deterministic-100.json"))
    parser.add_argument("--report", type=Path, default=Path(".code-diver/reports/intellij-postrank-h2-deterministic-100.html"))
    args = parser.parse_args()
    result = DeterministicPostrankH2(args).run()
    print(json.dumps({"run_id": result["run_id"], "output": str(args.output), "report": str(args.report)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
