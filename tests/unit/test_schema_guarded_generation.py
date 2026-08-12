from __future__ import annotations

import json

import pytest

from code_diver.generation.generation_result import GenerationResult
from code_diver.generation.json_schema_validator import JsonSchemaValidator
from code_diver.generation.openai_compatible_generation_provider import (
    OpenAICompatibleGenerationProvider,
)
from code_diver.generation.response_schemas import (
    ANSWER_SCHEMA,
    JUDGE_CRITERIA_NAMES,
    JUDGE_SCHEMA,
    QUERY_PLAN_SCHEMA,
    QUERY_VARIANTS_SCHEMA,
    RERANK_SCHEMA,
)
from code_diver.generation.schema_guarded_generation_provider import (
    SchemaGuardedGenerationProvider,
    SchemaViolationError,
)
from code_diver.generation.served_model_identity import ServedModelIdentity

pytestmark = pytest.mark.unit


class ScriptedProvider:
    """Returns a fixed sequence of responses and records the prompts it was given."""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.prompts: list[str] = []
        self.schemas: list[dict | None] = []
        self.name = "scripted"
        self.model = "scripted-model"

    def generate_json(self, prompt: str, *, schema: dict | None = None) -> str:
        return self.generate_json_result(prompt, schema=schema).text

    def generate_json_result(self, prompt: str, *, schema: dict | None = None) -> GenerationResult:
        self.prompts.append(prompt)
        self.schemas.append(schema)
        text = self.responses.pop(0)
        return GenerationResult(text=text, model=self.model, input_tokens=10, output_tokens=5, total_tokens=15)


def test_validator_accepts_a_conforming_payload() -> None:
    payload = {"results": [{"index": 1, "confidence": 0.5}, {"index": 2, "confidence": 0.1, "reason": "ok"}]}
    assert JsonSchemaValidator().violations(payload, RERANK_SCHEMA) == []


def test_validator_rejects_the_empty_object_that_the_old_vacuous_schema_allowed() -> None:
    """`{"type": "object"}` was the schema the provider used to send; `{}` satisfies it."""
    violations = JsonSchemaValidator().violations({}, ANSWER_SCHEMA)
    assert any("missing required property 'answer'" in violation for violation in violations)


def test_validator_treats_an_empty_required_string_as_a_violation() -> None:
    """Plain JSON Schema accepts `{"answer": ""}`; a model that answers with nothing is
    exactly the failure this catches, so `required` here means present *and* non-empty."""
    violations = JsonSchemaValidator().violations({"answer": "", "citations": []}, ANSWER_SCHEMA)
    assert any(violation == "$.answer: required property is empty" for violation in violations)
    assert any(violation == "$.citations: required property is empty" for violation in violations)


def test_validator_reports_type_mismatches_with_the_json_type_name() -> None:
    violations = JsonSchemaValidator().violations({"queries": "auth flow"}, QUERY_VARIANTS_SCHEMA)
    assert violations == ["$.queries: expected array, got string"]


def test_validator_checks_nested_array_items() -> None:
    violations = JsonSchemaValidator().violations({"queries": [{"purpose": "why"}]}, QUERY_PLAN_SCHEMA)
    assert violations == ["$.queries[0]: missing required property 'query'"]


def test_validator_rejects_unexpected_properties_when_additional_properties_are_disallowed() -> None:
    payload = {"queries": ["a"], "thinking": "let me consider"}
    violations = JsonSchemaValidator().violations(payload, QUERY_VARIANTS_SCHEMA)
    assert violations == ["$: unexpected property 'thinking'"]


def test_validator_enforces_the_judge_answer_enum() -> None:
    passing = {"score": 4, "answer": "yes", "evidence": "src/a.py"}
    criteria = {name: passing for name in JUDGE_CRITERIA_NAMES}
    criteria["hallucination_control"] = {"score": 4, "answer": "definitely", "evidence": "src/a.py"}
    payload = {
        "criteria": criteria,
        "answer_type": "substantive",
        "critical_issues": ["none"],
        "rationale": "fine",
    }

    violations = JsonSchemaValidator().violations(payload, JUDGE_SCHEMA)

    assert violations == [
        "$.criteria.hallucination_control.answer: 'definitely' is not one of "
        "['yes', 'mostly', 'partially', 'no']"
    ]


def test_validator_does_not_accept_a_boolean_where_a_number_is_required() -> None:
    payload = {"results": [{"index": 1, "confidence": True}]}
    violations = JsonSchemaValidator().violations(payload, RERANK_SCHEMA)
    assert violations == ["$.results[0].confidence: expected number, got boolean"]


def test_guard_passes_through_untouched_when_no_schema_is_requested() -> None:
    provider = ScriptedProvider(["not json at all"])
    guarded = SchemaGuardedGenerationProvider(provider)

    assert guarded.generate_json("plan") == "not json at all"
    assert provider.schemas == [None]


def test_guard_returns_the_first_conforming_response_without_repairing() -> None:
    provider = ScriptedProvider(['{"queries": ["auth"]}'])
    guarded = SchemaGuardedGenerationProvider(provider)

    result = guarded.generate_json_result("plan", schema=QUERY_VARIANTS_SCHEMA)

    assert json.loads(result.text) == {"queries": ["auth"]}
    assert len(provider.prompts) == 1
    assert result.total_tokens == 15


def test_guard_repairs_by_reprompting_with_the_concrete_violations() -> None:
    provider = ScriptedProvider(['{"answer": ""}', '{"answer": "It routes via Router.", "citations": [{"path": "a.py"}]}'])
    guarded = SchemaGuardedGenerationProvider(provider)

    result = guarded.generate_json_result("question", schema=ANSWER_SCHEMA)

    assert json.loads(result.text)["answer"] == "It routes via Router."
    assert len(provider.prompts) == 2
    repair_prompt = provider.prompts[1]
    assert "$.answer: required property is empty" in repair_prompt
    assert "missing required property 'citations'" in repair_prompt
    assert repair_prompt.startswith("question")


def test_guard_sums_token_usage_across_repair_attempts() -> None:
    """Charging only the successful attempt would understate the cost of a backend that
    cannot constrain decoding -- and that cost is part of what the sweeps measure."""
    provider = ScriptedProvider(['{}', '{"queries": ["auth"]}'])
    guarded = SchemaGuardedGenerationProvider(provider)

    result = guarded.generate_json_result("plan", schema=QUERY_VARIANTS_SCHEMA)

    assert result.total_tokens == 30
    assert result.input_tokens == 20
    assert result.output_tokens == 10


def test_guard_raises_after_exhausting_the_repair_budget() -> None:
    """Raising keeps model quality separable from infrastructure failure in the results:
    a silent empty answer is indistinguishable from a model that could not answer."""
    provider = ScriptedProvider(['{}', '{}', '{}'])
    guarded = SchemaGuardedGenerationProvider(provider, repair_attempts=2)

    with pytest.raises(SchemaViolationError) as excinfo:
        guarded.generate_json_result("plan", schema=QUERY_VARIANTS_SCHEMA)

    assert len(provider.prompts) == 3
    assert "missing required property 'queries'" in str(excinfo.value)
    assert excinfo.value.model == "scripted-model"


def test_guard_reports_unparseable_output_as_a_violation_rather_than_crashing() -> None:
    provider = ScriptedProvider(["I think the answer is in auth.py", '{"queries": ["auth"]}'])
    guarded = SchemaGuardedGenerationProvider(provider)

    result = guarded.generate_json_result("plan", schema=QUERY_VARIANTS_SCHEMA)

    assert json.loads(result.text) == {"queries": ["auth"]}
    assert "is not a JSON object" in provider.prompts[1]


def test_guard_forwards_the_schema_so_capable_backends_can_constrain_decoding() -> None:
    provider = ScriptedProvider(['{"results": [{"index": 1, "confidence": 0.9}]}'])
    guarded = SchemaGuardedGenerationProvider(provider)

    guarded.generate_json_result("rank", schema=RERANK_SCHEMA)

    assert provider.schemas == [RERANK_SCHEMA]


def test_guard_names_the_wrapped_backend() -> None:
    guarded = SchemaGuardedGenerationProvider(ScriptedProvider([]))

    assert guarded.name == "schema_guarded:scripted"
    assert guarded.model == "scripted-model"


def test_guard_rejects_a_negative_repair_budget() -> None:
    with pytest.raises(ValueError, match="repair_attempts"):
        SchemaGuardedGenerationProvider(ScriptedProvider([]), repair_attempts=-1)


def test_served_model_identity_matches_the_same_weights_across_backend_naming() -> None:
    """mlx_lm advertises the HF repo id; llama.cpp advertises the GGUF file name."""
    identity = ServedModelIdentity()

    assert identity.same_model("mlx-community/gemma-4-e2b-it-4bit", "gemma-4-E2B-it-qat-UD-Q4_K_XL")
    assert identity.same_model("mlx-community/gemma-4-e4b-it-OptiQ-4bit", "mlx-community/gemma-4-e4b-it-4bit")
    assert identity.same_model(".code-diver/models/mlx-community-gemma-4-12B-it-4bit", "gemma-4-12B-it-qat-UD-Q4_K_XL")


@pytest.mark.parametrize(
    ("configured", "served"),
    [
        ("mlx-community/gemma-4-e4b-it-4bit", "mlx-community/gemma-4-e2b-it-4bit"),
        ("mlx-community/Qwen3.5-4B-OptiQ-4bit", "mlx-community/gemma-4-e2b-it-4bit"),
        ("mlx-community/Qwen3.5-9B-MLX-4bit", "mlx-community/Qwen3.5-4B-MLX-4bit"),
        ("gemma-4-12B-it-qat-UD-Q4_K_XL", "gemma-4-26B-A4B-it-qat-UD-Q4_K_XL"),
        ("Qwen3-Reranker-0.6B", "Qwen3-Reranker-4B"),
    ],
)
def test_served_model_identity_separates_sizes_and_families(configured: str, served: str) -> None:
    """Every pair here shares a local port in the shipped configs, so a stale server would
    otherwise be evaluated and filed under the requested model's name."""
    assert not ServedModelIdentity().same_model(configured, served)


def test_provider_raises_when_the_port_is_held_by_a_different_model(monkeypatch) -> None:
    provider = OpenAICompatibleGenerationProvider(
        model="mlx-community/Qwen3.5-4B-MLX-4bit",
        api_key="local",
        url="http://127.0.0.1:8012/v1/chat/completions",
    )

    def fake_post(payload):
        return {
            "model": "mlx-community/gemma-4-e2b-it-4bit",
            "choices": [{"message": {"content": '{"queries":["auth"]}'}}],
        }

    monkeypatch.setattr(provider, "_post", fake_post)

    with pytest.raises(RuntimeError, match="is serving"):
        provider.generate_json("plan")


def test_provider_accepts_a_matching_served_model_and_checks_only_once(monkeypatch) -> None:
    provider = OpenAICompatibleGenerationProvider(
        model="mlx-community/gemma-4-e2b-it-4bit",
        api_key="local",
    )
    served = ["gemma-4-E2B-it-qat-UD-Q4_K_XL"]

    def fake_post(payload):
        return {"model": served[0], "choices": [{"message": {"content": '{"queries":["auth"]}'}}]}

    monkeypatch.setattr(provider, "_post", fake_post)

    assert provider.generate_json("plan") == '{"queries":["auth"]}'
    assert provider._served_model_verified is True


def _judge_payload(**overrides: object) -> dict[str, object]:
    passing = {"score": 4, "answer": "yes", "evidence": "src/a.py"}
    payload: dict[str, object] = {
        "criteria": {name: passing for name in JUDGE_CRITERIA_NAMES},
        "answer_type": "substantive",
        "critical_issues": ["one issue"],
        "rationale": "fine",
    }
    payload.update(overrides)
    return payload


def test_a_flawless_judgement_may_leave_critical_issues_empty() -> None:
    """The strict prompt tells the judge to leave this empty when every criterion is 4/4.
    Rejecting that threw away a complete judgement and scored the row as an error."""
    assert JsonSchemaValidator().violations(_judge_payload(critical_issues=[]), JUDGE_SCHEMA) == []


def test_allow_empty_does_not_excuse_dropping_the_key_entirely() -> None:
    payload = _judge_payload()
    del payload["critical_issues"]

    violations = JsonSchemaValidator().violations(payload, JUDGE_SCHEMA)

    assert violations == ["$: missing required property 'critical_issues'"]


def test_allow_empty_is_per_property_and_does_not_leak_to_its_siblings() -> None:
    violations = JsonSchemaValidator().violations(_judge_payload(rationale=""), JUDGE_SCHEMA)

    assert violations == ["$.rationale: required property is empty"]


def test_the_local_only_keyword_is_stripped_before_the_schema_goes_on_the_wire() -> None:
    """`allowEmpty` is this repo's, not JSON Schema's. llama.cpp compiles the schema into a
    grammar and Vertex validates it, so an unknown keyword is a server's problem, not ours."""
    provider = OpenAICompatibleGenerationProvider(model="m", url="http://127.0.0.1:1/v1/chat/completions")

    sent = provider._response_format_payload("json_schema", JUDGE_SCHEMA)

    assert "allowEmpty" not in json.dumps(sent)
    # Stripping is a copy, not a mutation: the validator still needs the keyword locally.
    assert JUDGE_SCHEMA["properties"]["critical_issues"]["allowEmpty"] is True
    assert sent["json_schema"]["schema"]["required"] == JUDGE_SCHEMA["required"]
