from __future__ import annotations

import json
import re
from typing import Any

from ..generation import GenerationProvider
from .explanation_case import ExplanationCase


class ExplanationJudge:
    def __init__(self, provider: GenerationProvider):
        self.provider = provider

    def judge(self, case: ExplanationCase, prediction: str) -> dict[str, Any]:
        prompt = self._prompt(case, prediction)
        result = self.provider.generate_json_result(prompt)
        payload = self._parse_json(result.text)
        scores = payload.get("scores") if isinstance(payload.get("scores"), dict) else {}
        normalized_scores = {
            "judge_correctness": self._bounded_score(scores.get("correctness")),
            "judge_completeness": self._bounded_score(scores.get("completeness")),
            "judge_specificity": self._bounded_score(scores.get("specificity")),
            "judge_groundedness": self._bounded_score(scores.get("groundedness")),
        }
        normalized_scores["judge_overall"] = sum(normalized_scores.values()) / max(len(normalized_scores), 1)
        return {
            "scores": normalized_scores,
            "rationale": str(payload.get("rationale") or ""),
            "model": result.model,
            "usage": {
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "total_tokens": result.total_tokens,
            },
        }

    def _prompt(self, case: ExplanationCase, prediction: str) -> str:
        return f"""You are judging a code explanation.

Score the candidate explanation against the source code. Use the reference docstring as supporting ground truth, but do not require identical wording.

Rubric, integer scores 1-5:
- correctness: factual accuracy about the code.
- completeness: covers purpose, inputs/outputs, and key behavior.
- specificity: names concrete concepts from the code rather than generic filler.
- groundedness: every important claim is supported by the shown code/reference.

Return JSON only:
{{
  "scores": {{
    "correctness": 1,
    "completeness": 1,
    "specificity": 1,
    "groundedness": 1
  }},
  "rationale": "short reason"
}}

Function metadata:
{json.dumps(case.metadata, ensure_ascii=False)}

Code:
```python
{case.code}
```

Reference docstring:
{case.reference}

Candidate explanation:
{prediction}
"""

    def _parse_json(self, text: str) -> dict[str, Any]:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if match:
                return json.loads(match.group(0))
            raise

    def _bounded_score(self, value: Any) -> float:
        try:
            score = float(value)
        except (TypeError, ValueError):
            return 0.0
        return min(max(score, 1.0), 5.0)
