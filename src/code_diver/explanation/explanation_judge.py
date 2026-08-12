from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..generation import EXPLANATION_JUDGE_SCHEMA, GenerationProvider
from ..generation.jsonish_parser import JsonishParser
from .explanation_case import ExplanationCase
from .explanation_judge_rubric import ExplanationJudgeRubric


class ExplanationJudge:
    DEFAULT_PROMPT_PATH = Path("prompts/code-explanation-judge.md")

    def __init__(
        self,
        provider: GenerationProvider,
        *,
        prompt_path: Path | None = None,
        rubric: ExplanationJudgeRubric | None = None,
        parser: JsonishParser | None = None,
    ):
        self.provider = provider
        self.prompt_path = prompt_path or self.DEFAULT_PROMPT_PATH
        self.prompt_template = self._load_prompt_template(self.prompt_path)
        self.rubric = rubric or ExplanationJudgeRubric()
        self.parser = parser or JsonishParser()

    def judge(self, case: ExplanationCase, prediction: str) -> dict[str, Any]:
        prompt = self._prompt(case, prediction)
        result = self.provider.generate_json_result(prompt, schema=EXPLANATION_JUDGE_SCHEMA)
        payload = self._parse_json(result.text)
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

    def _prompt(self, case: ExplanationCase, prediction: str) -> str:
        return (
            self.prompt_template.replace("{{metadata_json}}", json.dumps(case.metadata, ensure_ascii=False, indent=2))
            .replace("{{code}}", case.code)
            .replace("{{reference}}", case.reference)
            .replace("{{prediction}}", prediction)
            .replace("{{user_prompt}}", case.prompt)
        )

    def _parse_json(self, text: str) -> dict[str, Any]:
        return self.parser.parse_object(text)

    def _load_prompt_template(self, prompt_path: Path) -> str:
        if not prompt_path.exists():
            raise FileNotFoundError(f"Explanation judge prompt not found: {prompt_path}")
        return prompt_path.read_text(encoding="utf-8")
