"""Decorator that makes a response schema mean something on every backend.

Passing `schema` to a provider is a *request* for constrained decoding, and only some
servers honour it (llama.cpp does, `mlx_lm` 0.31.3 ignores `response_format` entirely).
This decorator closes the gap: it parses what came back, validates it against the same
schema, and re-prompts with the concrete violations when it does not conform.

When the repair budget runs out it raises. That is intentional -- a silent fallback to an
unusable payload is what made local small models look far worse than they are: an empty
`{"answer": ""}` scores as a wrong answer and is indistinguishable from a model that
genuinely could not answer. A raised error is recorded as an error by the evaluation
harness, keeping model quality and infrastructure failure separable in the results.
"""

from __future__ import annotations

import json
from typing import Any

from .generation_result import GenerationResult
from .json_schema_validator import JsonSchemaValidator
from .jsonish_parser import JsonishParser


class SchemaViolationError(RuntimeError):
    """Model output did not conform to the requested schema after every repair attempt."""

    def __init__(self, model: str, violations: list[str], text: str):
        self.model = model
        self.violations = violations
        self.text = text
        preview = text.strip().replace("\n", " ")[:300] or "<empty>"
        super().__init__(
            f"{model} output does not match the requested schema after repair attempts. "
            f"Violations: {'; '.join(violations)}. Output was: {preview}"
        )


class SchemaGuardedGenerationProvider:
    DEFAULT_REPAIR_ATTEMPTS = 2

    def __init__(
        self,
        provider: Any,
        *,
        repair_attempts: int = DEFAULT_REPAIR_ATTEMPTS,
        parser: JsonishParser | None = None,
        validator: JsonSchemaValidator | None = None,
    ):
        if repair_attempts < 0:
            raise ValueError("repair_attempts must not be negative")
        self.provider = provider
        self.repair_attempts = repair_attempts
        self.parser = parser or JsonishParser()
        self.validator = validator or JsonSchemaValidator()

    @property
    def name(self) -> str:
        return f"schema_guarded:{self.provider.name}"

    @property
    def model(self) -> str:
        return str(self.provider.model)

    def generate_json(self, prompt: str, *, schema: dict[str, Any] | None = None) -> str:
        return self.generate_json_result(prompt, schema=schema).text

    def generate_json_result(self, prompt: str, *, schema: dict[str, Any] | None = None) -> GenerationResult:
        if schema is None:
            return self.provider.generate_json_result(prompt)
        attempt_prompt = prompt
        violations: list[str] = []
        result: GenerationResult | None = None
        spent = _TokenTally()
        for _ in range(self.repair_attempts + 1):
            result = self.provider.generate_json_result(attempt_prompt, schema=schema)
            spent.add(result)
            violations = self._violations(result.text, schema)
            if not violations:
                return spent.applied_to(result)
            attempt_prompt = self._repair_prompt(prompt, schema, result.text, violations)
        if result is None:  # unreachable: the loop body always runs at least once
            raise RuntimeError("Schema-guarded generation produced no result.")
        raise SchemaViolationError(result.model, violations, result.text)

    def _violations(self, text: str, schema: dict[str, Any]) -> list[str]:
        try:
            payload = self.parser.parse_object(text)
        except (json.JSONDecodeError, ValueError) as exc:
            return [f"$: output is not a JSON object ({exc})"]
        return self.validator.violations(payload, schema)

    def _repair_prompt(self, prompt: str, schema: dict[str, Any], text: str, violations: list[str]) -> str:
        listed = "\n".join(f"- {violation}" for violation in violations)
        return (
            f"{prompt}\n\n"
            "## Previous attempt rejected\n"
            "Your previous response did not match the required JSON schema.\n\n"
            f"Previous response:\n{text.strip()[:2000]}\n\n"
            f"Schema violations:\n{listed}\n\n"
            f"Required JSON schema:\n{json.dumps(schema, ensure_ascii=False)}\n\n"
            "Return only the corrected JSON object. No markdown fence, no commentary, "
            "no reasoning. Every required field must be present and non-empty."
        )


class _TokenTally:
    """Sums usage across repair attempts.

    Reporting only the successful attempt's usage would understate the cost of a backend
    that cannot constrain decoding -- and that cost is one of the things being measured.
    """

    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0

    def add(self, result: GenerationResult) -> None:
        self.input_tokens += result.input_tokens
        self.output_tokens += result.output_tokens
        self.total_tokens += result.total_tokens

    def applied_to(self, result: GenerationResult) -> GenerationResult:
        return GenerationResult(
            text=result.text,
            model=result.model,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            total_tokens=self.total_tokens,
        )
