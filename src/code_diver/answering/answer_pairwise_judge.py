"""Forced-choice comparison of two answers to the same question against one context.

Why this exists instead of scoring each answer on its own. The absolute rubric saturated:
with the (unusable, template-only) reference removed, a 12-case calibration of the local 12B
judge returned a flat 5.00/5 on 11 of 12 answers and zero critical issues, sd 0.05. An
instrument with 3.8% of its range in play cannot separate two pipeline arms. A forced choice
cannot collapse the same way -- the judge has to name a side and defend it.

The judge never learns which system produced which answer. Callers pass answers already
assigned to the `A`/`B` slots, and `AnswerPairwiseComparison` records the mapping so the
result can be read back in system terms. Position bias is real and is handled one level up,
in `answer_pairwise_report`, by alternating which system takes the `A` slot.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..generation import PAIRWISE_SCHEMA, GenerationProvider
from ..generation.jsonish_parser import JsonishParser
from ..generation.response_schemas import PAIRWISE_DIMENSION_NAMES, PAIRWISE_MARGINS, PAIRWISE_SIDES

TIE = "tie"


class AnswerPairwiseJudgeError(ValueError):
    """The judge returned a verdict that cannot be read as a comparison."""


@dataclass(frozen=True, slots=True)
class AnswerPairwiseComparison:
    """One verdict, already translated out of slot labels and into system labels.

    `winner` is a system name or `TIE`, never `"A"`/`"B"`. Keeping the raw slot verdict in
    `slot_winner` alongside it is what makes the position-bias diagnostic possible: without
    it there is no way to tell a judge that prefers better answers from one that prefers
    whichever answer it read first.
    """

    case_id: str
    winner: str
    slot_winner: str
    margin: str
    system_in_slot_a: str
    system_in_slot_b: str
    dimension_winners: dict[str, str]
    critical_errors: list[str]
    rationale: str
    model: str
    usage: dict[str, int]

    def as_json(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "winner": self.winner,
            "slot_winner": self.slot_winner,
            "margin": self.margin,
            "system_in_slot_a": self.system_in_slot_a,
            "system_in_slot_b": self.system_in_slot_b,
            "dimension_winners": dict(self.dimension_winners),
            "critical_errors": list(self.critical_errors),
            "rationale": self.rationale,
            "model": self.model,
            "usage": dict(self.usage),
        }


class AnswerPairwiseJudge:
    DEFAULT_PROMPT_PATH = Path("prompts/code-answer-pairwise.md")

    def __init__(
        self,
        provider: GenerationProvider,
        *,
        prompt_path: Path | None = None,
        parser: JsonishParser | None = None,
    ):
        self.provider = provider
        self.prompt_path = prompt_path or self.DEFAULT_PROMPT_PATH
        self.prompt_template = self._load_prompt_template(self.prompt_path)
        self.parser = parser or JsonishParser()

    def compare(
        self,
        *,
        case_id: str,
        question: str,
        context: str,
        answer_in_slot_a: str,
        answer_in_slot_b: str,
        system_in_slot_a: str,
        system_in_slot_b: str,
    ) -> AnswerPairwiseComparison:
        if system_in_slot_a == system_in_slot_b:
            raise AnswerPairwiseJudgeError(
                f"both slots hold the same system {system_in_slot_a!r}; a self-comparison "
                "measures judge noise, not arm quality, and is never what the caller meant"
            )
        result = self.provider.generate_json_result(
            self._prompt(question, context, answer_in_slot_a, answer_in_slot_b),
            schema=PAIRWISE_SCHEMA,
        )
        payload = self.parser.parse_object(result.text)
        slot_winner = self._side(payload.get("winner"), field="winner")
        margin = self._margin(payload.get("margin"))
        slots = {"A": system_in_slot_a, "B": system_in_slot_b}
        return AnswerPairwiseComparison(
            case_id=case_id,
            winner=slots.get(slot_winner, TIE),
            slot_winner=slot_winner,
            margin=margin,
            system_in_slot_a=system_in_slot_a,
            system_in_slot_b=system_in_slot_b,
            dimension_winners=self._dimension_winners(payload, slots),
            critical_errors=self._critical_errors(payload),
            rationale=str(payload.get("rationale") or "").strip(),
            model=result.model,
            usage={
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "total_tokens": result.total_tokens,
            },
        )

    def _dimension_winners(self, payload: dict[str, Any], slots: dict[str, str]) -> dict[str, str]:
        dimensions = payload.get("dimensions")
        if not isinstance(dimensions, dict):
            raise AnswerPairwiseJudgeError("judge returned no 'dimensions' object")
        winners: dict[str, str] = {}
        for name in PAIRWISE_DIMENSION_NAMES:
            entry = dimensions.get(name)
            if not isinstance(entry, dict):
                raise AnswerPairwiseJudgeError(f"judge returned no verdict for dimension {name!r}")
            side = self._side(entry.get("winner"), field=f"dimensions.{name}.winner")
            winners[name] = slots.get(side, TIE)
        return winners

    def _critical_errors(self, payload: dict[str, Any]) -> list[str]:
        errors = payload.get("critical_errors")
        if errors is None:
            return []
        if not isinstance(errors, list):
            raise AnswerPairwiseJudgeError("'critical_errors' must be a list")
        return [str(item).strip() for item in errors if str(item).strip()]

    def _side(self, value: Any, *, field: str) -> str:
        # Local models drift on case ("a") and on synonyms ("A wins", "answer_a"). Normalizing
        # here is safe because the vocabulary is three tokens wide; anything else is a real
        # protocol violation and must not be silently folded into a tie, which would quietly
        # bias every aggregate toward "no difference".
        text = str(value or "").strip().lower()
        if text in {"a", "answer a", "answer_a"}:
            return "A"
        if text in {"b", "answer b", "answer_b"}:
            return "B"
        if text in {TIE, "equal", "draw", "neither"}:
            return TIE
        raise AnswerPairwiseJudgeError(f"{field}: {value!r} is not one of {list(PAIRWISE_SIDES)}")

    def _margin(self, value: Any) -> str:
        text = str(value or "").strip().lower()
        if text in PAIRWISE_MARGINS:
            return text
        raise AnswerPairwiseJudgeError(f"margin: {value!r} is not one of {list(PAIRWISE_MARGINS)}")

    def _prompt(self, question: str, context: str, answer_a: str, answer_b: str) -> str:
        return (
            self.prompt_template.replace("{{question}}", question)
            .replace("{{context}}", context)
            .replace("{{answer_a}}", answer_a)
            .replace("{{answer_b}}", answer_b)
        )

    def _load_prompt_template(self, prompt_path: Path) -> str:
        if not prompt_path.exists():
            raise FileNotFoundError(f"Pairwise answer judge prompt not found: {prompt_path}")
        template = prompt_path.read_text(encoding="utf-8")
        missing = [
            placeholder
            for placeholder in ("{{question}}", "{{context}}", "{{answer_a}}", "{{answer_b}}")
            if placeholder not in template
        ]
        if missing:
            # A typo'd placeholder ships a prompt that silently omits the code or one of the
            # answers, and the judge answers anyway -- confidently, about nothing.
            raise ValueError(
                f"{prompt_path} is missing required placeholders: {', '.join(missing)}"
            )
        return template
