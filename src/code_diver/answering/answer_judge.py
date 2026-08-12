from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..generation import JUDGE_SCHEMA, GenerationProvider
from ..generation.jsonish_parser import JsonishParser
from .answer_case import AnswerCase
from .answer_judge_payload_validator import validate_judge_payload
from .answer_judge_rubric import AnswerJudgeRubric


class AnswerJudge:
    DEFAULT_PROMPT_PATH = Path("prompts/code-answer-judge.md")

    def __init__(
        self,
        provider: GenerationProvider,
        *,
        prompt_path: Path | None = None,
        rubric: AnswerJudgeRubric | None = None,
        parser: JsonishParser | None = None,
    ):
        self.provider = provider
        self.prompt_path = prompt_path or self.DEFAULT_PROMPT_PATH
        self.prompt_template = self._load_prompt_template(self.prompt_path)
        self.rubric = rubric or AnswerJudgeRubric()
        self.parser = parser or JsonishParser()

    def judge(self, case: AnswerCase, prediction: str, context: str) -> dict[str, Any]:
        result = self.provider.generate_json_result(
            self._prompt(case, prediction, context), schema=JUDGE_SCHEMA
        )
        payload = self.parser.parse_object(result.text)
        validate_judge_payload(payload)
        scored = self.rubric.score(payload)
        return {
            "scores": scored["scores"],
            "questionnaire": scored["questionnaire"],
            "rationale": scored["rationale"],
            "critical_issues": scored["critical_issues"],
            "prompt_path": str(self.prompt_path),
            "model": result.model,
            "usage": {
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "total_tokens": result.total_tokens,
            },
        }

    def _prompt(self, case: AnswerCase, prediction: str, context: str) -> str:
        return (
            self.prompt_template.replace("{{metadata_json}}", json.dumps(case.metadata, ensure_ascii=False, indent=2))
            .replace("{{question}}", case.question)
            .replace("{{reference}}", case.reference)
            .replace("{{prediction}}", prediction)
            .replace("{{context}}", context)
        )

    def _load_prompt_template(self, prompt_path: Path) -> str:
        if not prompt_path.exists():
            raise FileNotFoundError(f"Answer judge prompt not found: {prompt_path}")
        return prompt_path.read_text(encoding="utf-8")
