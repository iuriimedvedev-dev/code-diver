"""Backend-independent validation of model output against a response schema.

This exists because schema *enforcement* is not portable. llama.cpp compiles
`response_format.json_schema` into a GBNF grammar and genuinely constrains decoding;
`mlx_lm`'s server (0.31.3) does not read `response_format` at all and silently drops it,
so an MLX-served model is completely unconstrained no matter what the payload says.
Validating the parsed object after the fact is the only check that holds on every
backend, so it runs on every backend.

Only the keyword subset the response schemas actually use is implemented: `type`,
`properties`, `required`, `items`, `enum`, and `additionalProperties`. An unsupported
keyword is ignored rather than guessed at.

One deliberate strictness beyond JSON Schema: a `required` property whose value is an
empty string, empty list, or `None` counts as a violation. Plain JSON Schema accepts
`{"answer": ""}` against `required: ["answer"]`, and that is precisely the failure this
module was written to catch -- a model that "answers" with nothing.

That strictness needs an opt-out, because for some fields empty is the answer. A judge
asked to list critical issues in a flawless answer must return `[]`, and rejecting that
throws away a complete, correct judgement. Mark such a property `"allowEmpty": true` in
the schema: it stays required -- the model must still emit the key, so a silently dropped
field is still caught -- but an empty value is accepted as meaningful.
"""

from __future__ import annotations

from typing import Any

_TYPE_CHECKS: dict[str, tuple[type, ...]] = {
    "object": (dict,),
    "array": (list,),
    "string": (str,),
    "number": (int, float),
    "integer": (int,),
    "boolean": (bool,),
}


class JsonSchemaValidator:
    def __init__(self, *, max_violations: int = 8):
        if max_violations < 1:
            raise ValueError("max_violations must be at least 1")
        self.max_violations = max_violations

    def violations(self, payload: Any, schema: dict[str, Any]) -> list[str]:
        found: list[str] = []
        self._check(payload, schema, "$", found)
        return found[: self.max_violations]

    def _check(self, value: Any, schema: dict[str, Any], path: str, found: list[str]) -> None:
        if len(found) >= self.max_violations:
            return
        expected_type = schema.get("type")
        if isinstance(expected_type, str) and not self._matches_type(value, expected_type):
            found.append(f"{path}: expected {expected_type}, got {self._type_name(value)}")
            return
        allowed = schema.get("enum")
        if isinstance(allowed, list) and value not in allowed:
            found.append(f"{path}: {value!r} is not one of {allowed}")
            return
        if expected_type == "object" and isinstance(value, dict):
            self._check_object(value, schema, path, found)
        elif expected_type == "array" and isinstance(value, list):
            item_schema = schema.get("items")
            if isinstance(item_schema, dict):
                for index, item in enumerate(value):
                    self._check(item, item_schema, f"{path}[{index}]", found)

    def _check_object(self, value: dict[str, Any], schema: dict[str, Any], path: str, found: list[str]) -> None:
        properties = schema.get("properties")
        properties = properties if isinstance(properties, dict) else {}
        for name in schema.get("required", []):
            if name not in value:
                found.append(f"{path}: missing required property {name!r}")
            elif self._is_blank(value[name]) and not self._allows_empty(properties.get(name)):
                found.append(f"{path}.{name}: required property is empty")
        if schema.get("additionalProperties") is False:
            for name in value:
                if name not in properties:
                    found.append(f"{path}: unexpected property {name!r}")
        for name, child_schema in properties.items():
            if name in value and isinstance(child_schema, dict):
                self._check(value[name], child_schema, f"{path}.{name}", found)

    def _matches_type(self, value: Any, expected: str) -> bool:
        types = _TYPE_CHECKS.get(expected)
        if types is None:
            return True
        # JSON has no bool/number distinction problem; Python does -- True is an int.
        if expected in {"number", "integer"} and isinstance(value, bool):
            return False
        return isinstance(value, types)

    def _allows_empty(self, property_schema: Any) -> bool:
        return isinstance(property_schema, dict) and property_schema.get("allowEmpty") is True

    def _is_blank(self, value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, (str, list, dict)):
            return len(value) == 0
        return False

    def _type_name(self, value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, dict):
            return "object"
        if isinstance(value, list):
            return "array"
        if isinstance(value, str):
            return "string"
        if isinstance(value, int):
            return "integer"
        if isinstance(value, float):
            return "number"
        return type(value).__name__
