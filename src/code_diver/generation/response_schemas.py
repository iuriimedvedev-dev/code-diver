"""Real JSON schemas for every generation task that expects structured output.

Until these existed the OpenAI-compatible provider sent `{"type": "object"}` as its
`json_schema`, which every JSON object satisfies — including `{}`. Local servers were
therefore free to return an empty object, a raw thinking trace, or prose, and the
failure only surfaced downstream as a missing key or an empty prediction.

The schemas are deliberately conservative so that llama.cpp can compile each one to a
GBNF grammar: object/array/string/number/boolean/integer, `required`, `enum`, and
`additionalProperties: false`. No `$ref`, `oneOf`, `patternProperties`, or format
assertions, none of which survive the grammar conversion intact.

Shapes are derived from the code that consumes them, not from the prompt text:
- query plan -> `answering/answer_query_planner.py`
- rerank     -> `strategies/llm_rerank_response_parser.py`
- answer     -> `answering/answer_evaluator.py`
- judge      -> `answering/answer_judge_rubric.py` + `prompts/code-answer-judge-strict.md`
"""

from __future__ import annotations

from typing import Any, Final

JsonSchema = dict[str, Any]

QUERY_PLAN_SCHEMA: Final[JsonSchema] = {
    "type": "object",
    "properties": {
        "queries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "purpose": {"type": "string"},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        "rationale": {"type": "string"},
    },
    "required": ["queries"],
    "additionalProperties": False,
}

# Distinct from QUERY_PLAN_SCHEMA on purpose: `orchestration/query_plan_orchestrator.py`
# reads `queries` as a list of plain strings, while the answering planner reads a list of
# `{query, purpose}` objects. One schema for both would let each side accept the other's
# malformed output.
QUERY_VARIANTS_SCHEMA: Final[JsonSchema] = {
    "type": "object",
    "properties": {"queries": {"type": "array", "items": {"type": "string"}}},
    "required": ["queries"],
    "additionalProperties": False,
}

RERANK_SCHEMA: Final[JsonSchema] = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "confidence": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["index", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}

ANSWER_SCHEMA: Final[JsonSchema] = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "lines": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
        "confidence": {"type": "number"},
    },
    "required": ["answer", "citations"],
    "additionalProperties": False,
}

_JUDGE_CRITERION: Final[JsonSchema] = {
    "type": "object",
    "properties": {
        "score": {"type": "integer"},
        "answer": {"type": "string", "enum": ["yes", "mostly", "partially", "no"]},
        "evidence": {"type": "string"},
    },
    "required": ["score", "answer", "evidence"],
    "additionalProperties": False,
}

JUDGE_CRITERIA_NAMES: Final[tuple[str, ...]] = (
    "answer_correctness",
    "evidence_grounding",
    "coverage",
    "citation_quality",
    "specificity",
    "hallucination_control",
)

# `substantive` — the prediction asserts something about the codebase.
# `abstention` — the prediction explicitly declines to answer (insufficient context,
#   could not find the relevant code) without asserting anything substantive.
# `empty` — the prediction is blank/whitespace or contains no assertion at all.
JUDGE_ANSWER_TYPES: Final[tuple[str, ...]] = ("substantive", "abstention", "empty")

JUDGE_SCHEMA: Final[JsonSchema] = {
    "type": "object",
    "properties": {
        "criteria": {
            "type": "object",
            "properties": dict.fromkeys(JUDGE_CRITERIA_NAMES, _JUDGE_CRITERION),
            "required": list(JUDGE_CRITERIA_NAMES),
            "additionalProperties": False,
        },
        # Not required: the local 4B judge model frequently omits it, and re-prompting
        # on a missing-but-non-essential field burned every repair attempt and lost
        # the whole judgement (see `answer_judge_payload_validator.DEFAULT_ANSWER_TYPE`
        # and `AnswerJudgeRubric.score()`'s `judge_answer_type_missing` flag). Kept as a
        # property so constrained decoding still steers the model toward emitting it.
        "answer_type": {"type": "string", "enum": list(JUDGE_ANSWER_TYPES)},
        # Required so a judge that silently drops the key is still caught, but allowed to be
        # empty: the strict prompt tells the judge to leave this list empty when every
        # criterion scores 4/4, and rejecting that discarded an otherwise complete judgement.
        "critical_issues": {"type": "array", "items": {"type": "string"}, "allowEmpty": True},
        "rationale": {"type": "string"},
    },
    "required": ["criteria", "critical_issues", "rationale"],
    "additionalProperties": False,
}

PAIRWISE_SIDES: Final[tuple[str, ...]] = ("A", "B", "tie")
PAIRWISE_MARGINS: Final[tuple[str, ...]] = ("decisive", "clear", "slight")
PAIRWISE_DIMENSION_NAMES: Final[tuple[str, ...]] = (
    "correctness",
    "grounding",
    "coverage",
    "specificity",
)

_PAIRWISE_DIMENSION: Final[JsonSchema] = {
    "type": "object",
    "properties": {
        "winner": {"type": "string", "enum": list(PAIRWISE_SIDES)},
        "evidence": {"type": "string"},
    },
    "required": ["winner", "evidence"],
    "additionalProperties": False,
}

# Pairwise exists because the absolute rubric saturated: on a 12-case calibration the local
# 12B judge scored 11 answers a flat 5.00/5 once the (unusable) reference was removed, so
# `judge_overall` could not separate two arms. A forced choice between two answers cannot
# saturate the same way -- the judge has to name a side.
PAIRWISE_SCHEMA: Final[JsonSchema] = {
    "type": "object",
    "properties": {
        "winner": {"type": "string", "enum": list(PAIRWISE_SIDES)},
        "margin": {"type": "string", "enum": list(PAIRWISE_MARGINS)},
        "dimensions": {
            "type": "object",
            "properties": dict.fromkeys(PAIRWISE_DIMENSION_NAMES, _PAIRWISE_DIMENSION),
            "required": list(PAIRWISE_DIMENSION_NAMES),
            "additionalProperties": False,
        },
        # Empty is the correct answer when neither side made a false claim, and the
        # validator would otherwise discard a complete verdict. See `allowEmpty` in
        # `json_schema_validator`.
        "critical_errors": {"type": "array", "items": {"type": "string"}, "allowEmpty": True},
        "rationale": {"type": "string"},
    },
    "required": ["winner", "margin", "dimensions", "critical_errors", "rationale"],
    "additionalProperties": False,
}

EXPLANATION_JUDGE_CRITERIA_NAMES: Final[tuple[str, ...]] = (
    "purpose_accuracy",
    "behavior_accuracy",
    "api_contract",
    "groundedness",
    "specificity",
    "completeness",
    "clarity",
)

EXPLANATION_JUDGE_SCHEMA: Final[JsonSchema] = {
    "type": "object",
    "properties": {
        "criteria": {
            "type": "object",
            "properties": dict.fromkeys(EXPLANATION_JUDGE_CRITERIA_NAMES, _JUDGE_CRITERION),
            "required": list(EXPLANATION_JUDGE_CRITERIA_NAMES),
            "additionalProperties": False,
        },
        "critical_issues": {"type": "array", "items": {"type": "string"}},
        "rationale": {"type": "string"},
    },
    "required": ["criteria"],
    "additionalProperties": False,
}

EXPLANATION_SCHEMA: Final[JsonSchema] = {
    "type": "object",
    "properties": {"explanation": {"type": "string"}},
    "required": ["explanation"],
    "additionalProperties": False,
}

SUMMARY_SCHEMA: Final[JsonSchema] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "topics": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary"],
    "additionalProperties": False,
}
