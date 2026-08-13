from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from ..domain import SearchResult
from ..generation import ANSWER_SCHEMA, GenerationProvider
from ..generation.jsonish_parser import JsonishParser
from ..strategies import RetrievalStrategy
from .answer_candidate_reranker import AnswerCandidateReranker
from .answer_case import AnswerCase
from .answer_context import AnswerContext
from .answer_context_builder import AnswerContextBuilder
from .answer_outcome import AnswerOutcome
from .answer_pipeline import AnswerPipeline
from .answer_query_merge import merge_query_results
from .answer_query_planner import AnswerQueryPlanner

PRODUCT_CASE_ID = "query"


@dataclass(slots=True)
class AnswerService:
    """The one place a question becomes a grounded answer.

    Retrieval, context assembly, prompt, generation, parse. No metrics, no judge, no dataset:
    those belong to whoever is measuring, not to answering. AnswerEvaluator wraps this and
    scores the outcome; `code-diver answer`, `ask` and the pi tool call it directly. That is
    the entire point — the measured pipeline and the shipped pipeline are the same object.
    """

    retrieval_strategy: RetrievalStrategy
    answer_provider: GenerationProvider
    context_builder: AnswerContextBuilder
    query_planner: AnswerQueryPlanner | None = None
    query_retrieval_strategy: RetrievalStrategy | None = None
    query_result_reranker: AnswerCandidateReranker | None = None
    repository_context: str = ""
    limit: int = 10
    query_workers: int = 4
    restrict_citations_to_context: bool = False
    parser: JsonishParser = field(default_factory=JsonishParser)

    @classmethod
    def from_pipeline(
        cls, pipeline: AnswerPipeline, restrict_citations_to_context: bool = False
    ) -> AnswerService:
        return cls(
            retrieval_strategy=pipeline.retrieval_strategy,
            answer_provider=pipeline.answer_provider,
            context_builder=pipeline.context_builder,
            query_planner=pipeline.query_planner,
            query_retrieval_strategy=pipeline.query_retrieval_strategy,
            query_result_reranker=pipeline.query_result_reranker,
            repository_context=pipeline.repository_context,
            limit=pipeline.limit,
            query_workers=pipeline.query_workers,
            restrict_citations_to_context=restrict_citations_to_context,
        )

    def answer(
        self, question: str, metadata: dict[str, Any] | None = None
    ) -> AnswerOutcome:
        """Answer a bare question. The product entry point."""
        return self.answer_case(
            AnswerCase(
                id=PRODUCT_CASE_ID,
                question=question,
                reference="",
                expected_paths=[],
                metadata=dict(metadata or {}),
            )
        )

    def answer_case(self, case: AnswerCase) -> AnswerOutcome:
        """Answer a dataset case. The query planner reads case metadata, so it needs the case."""
        retrieval_started = perf_counter()
        (
            search_results,
            plan_payload,
            planning_usage,
            planning_model,
            rerank_usage,
            rerank_model,
        ) = self.retrieve(case)
        retrieval_duration_ms = (perf_counter() - retrieval_started) * 1000
        context_started = perf_counter()
        context = self.context_builder.build(search_results)
        context_duration_ms = (perf_counter() - context_started) * 1000
        retrieved_files = [
            search_result.item.path for search_result in search_results
        ]
        generation_started = perf_counter()
        result = self.answer_provider.generate_json_result(
            self.answer_prompt(case, context), schema=ANSWER_SCHEMA
        )
        generation_duration_ms = (perf_counter() - generation_started) * 1000
        outcome = AnswerOutcome(
            question=case.question,
            answer="",
            search_results=search_results,
            retrieved_files=retrieved_files,
            context=context,
            query_plan=plan_payload,
            raw_prediction=result.text,
            generation_model=result.model,
            usage={
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "total_tokens": result.total_tokens,
            },
            planning_usage=planning_usage,
            planning_model=planning_model,
            rerank_usage=rerank_usage,
            rerank_model=rerank_model,
            retrieval_duration_ms=retrieval_duration_ms,
            context_duration_ms=context_duration_ms,
            generation_duration_ms=generation_duration_ms,
        )
        try:
            payload = self.parser.parse_object(result.text)
        except Exception as exc:
            # Not raised: an unparseable reply is a first-class outcome. The evaluator scores
            # it as a parse failure and a product surface can still show the raw text.
            outcome.parse_error = str(exc)
            return outcome
        outcome.answer = str(payload.get("answer") or "").strip()
        citations = payload.get("citations")
        outcome.citations = citations if isinstance(citations, list) else []
        confidence = payload.get("confidence")
        if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
            outcome.confidence = float(confidence)
        return outcome

    def retrieve(
        self,
        case: AnswerCase,
    ) -> tuple[
        list[SearchResult],
        dict[str, Any],
        dict[str, int] | None,
        str | None,
        dict[str, int] | None,
        str | None,
    ]:
        if self.query_planner is None:
            return (
                self.retrieval_strategy.search(case.question, self.limit),
                {
                    "mode": "single_query",
                    "queries": [case.question],
                    "duration_ms": 0.0,
                },
                None,
                None,
                None,
                None,
            )
        started = perf_counter()
        plan, result = self.query_planner.plan_result(case)
        plan_payload = {
            "mode": "llm_multi_query",
            "queries": plan.queries,
            "rationale": plan.rationale,
            "duration_ms": (perf_counter() - started) * 1000,
        }
        usage = {
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "total_tokens": result.total_tokens,
        }
        rerank_candidate_limit = (
            self.query_result_reranker.candidate_limit
            if self.query_result_reranker
            else self.limit
        )
        query_limit = max(self.limit, rerank_candidate_limit, 1)
        worker_count = max(1, min(int(self.query_workers or 1), len(plan.queries)))
        probe_strategy = self.query_retrieval_strategy or self.retrieval_strategy
        if worker_count == 1:
            result_sets = [
                probe_strategy.search(query, query_limit) for query in plan.queries
            ]
        else:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = [
                    executor.submit(probe_strategy.search, query, query_limit)
                    for query in plan.queries
                ]
                result_sets = [future.result() for future in futures]
        merged = merge_query_results(result_sets, query_limit)
        candidate_pool = self._build_candidate_pool(merged[:rerank_candidate_limit])
        if self.query_result_reranker is None:
            plan_payload["final_rerank"] = self._disabled_rerank_payload(candidate_pool)
            return merged[: self.limit], plan_payload, usage, result.model, None, None
        reranked, rerank_payload = self.query_result_reranker.rerank(
            case.question, merged, self.limit
        )
        rerank_payload["candidate_pool"] = candidate_pool
        plan_payload["final_rerank"] = rerank_payload
        rerank_usage = {
            "input_tokens": int(rerank_payload.get("input_tokens") or 0),
            "output_tokens": int(rerank_payload.get("output_tokens") or 0),
            "total_tokens": int(rerank_payload.get("total_tokens") or 0),
        }
        rerank_model = str(rerank_payload.get("model") or "")
        return reranked, plan_payload, usage, result.model, rerank_usage, rerank_model

    def _build_candidate_pool(
        self, candidates: list[SearchResult]
    ) -> list[dict[str, Any]]:
        pool: list[dict[str, Any]] = []
        for rank, candidate in enumerate(candidates, start=1):
            entry: dict[str, Any] = {"rank": rank, "path": candidate.item.path}
            candidate_id = getattr(candidate.item, "id", None)
            if candidate_id is not None:
                entry["id"] = candidate_id
            entry["score"] = float(candidate.score)
            pool.append(entry)
        return pool

    def _disabled_rerank_payload(
        self, candidate_pool: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return {
            "enabled": False,
            "candidate_count": len(candidate_pool),
            "selected_indices": [],
            "selected_candidates": [],
            "candidate_pool": candidate_pool,
        }

    def answer_prompt(self, case: AnswerCase, context: AnswerContext) -> str:
        repository_context = self.repository_context.strip()
        context_section = ""
        if repository_context:
            context_section = f"""
Repository orientation:
{repository_context}

"""
        return f"""Answer the developer's repository question using only the provided retrieval context.

Requirements:
- Explain the code behavior, not only where it is.
- Treat Repository orientation and Documentation context as navigation help only.
- Ground behavioral claims in Code context whenever code context is available.
- Prefer citations to implementation files over documentation files for code behavior, ownership, inputs, outputs, side effects, and control flow.
- Use documentation citations only for setup, terminology, public commands, or architecture claims that are not visible in code excerpts.
- Cite relative file paths and line numbers from the context for important claims.
- Citation line values must be compact numeric ranges like "61-71"; never put code text in citation lines.
- If the context is insufficient, say what is missing instead of inventing behavior.
- Return JSON only: {{"answer":"...","citations":[{{"path":"...","lines":"...","reason":"..."}}],"confidence":0.0}}
{self._citation_allowlist_section(context.files)}
{context_section}
Question:
{case.question}

Case metadata:
{json.dumps(case.metadata, ensure_ascii=False)}

Retrieved context:
{context.text}
"""

    def _citation_allowlist_section(self, context_files: list[str]) -> str:
        """Close the citation set to the files actually shown, when the arm asks for it.

        The bare "from the context" line above states the rule but never says what the context
        is, so the model has to infer the boundary from the excerpts. h28's fabrications were
        real repo paths -- `src/app.py`, `src/api/routes/sessions.py`, README files -- that a
        model with any sense of the repository will produce whether or not it was shown them.
        Enumerating the allowed set turns an inference into a lookup.
        """
        if not self.restrict_citations_to_context or not context_files:
            return ""
        allowed = "\n".join(f"  - {path}" for path in context_files)
        return f"""
Citable files -- every citation path must be copied exactly from this list:
{allowed}
Citing any other path is an error, even one you believe exists in this repository. If the
answer needs a file that is not listed, say so in the answer instead of citing it.
"""
