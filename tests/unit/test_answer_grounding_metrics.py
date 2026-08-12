from __future__ import annotations

import pytest

from code_diver.answering.answer_grounding_metrics import AnswerGroundingMetrics

pytestmark = pytest.mark.unit

CONTEXT = ["src/app/cli.ts", "src/app/router.ts", "docs/setup.md"]
EXPECTED = ["src/app/cli.ts"]


def test_a_grounded_answer_passes_the_gate() -> None:
    metrics = AnswerGroundingMetrics().score(
        "The CLI entry point is in cli.ts.",
        [{"path": "src/app/cli.ts", "lines": "10-20"}],
        CONTEXT,
        EXPECTED,
    )

    assert metrics["answer_grounded"] == 1.0
    assert metrics["citation_expected_hit"] == 1.0
    assert metrics["citation_expected_recall"] == 1.0
    assert metrics["citation_fabricated_count"] == 0.0


def test_citing_a_plausible_neighbour_from_the_bundle_fails_the_gate() -> None:
    """The `where-angular-cli` failure: retrieval put the right file in the bundle, the model
    cited a neighbour instead. `citation_path_valid_rate` scores this 1.0 because the cited
    path really is in the context -- which is why it cannot be the promotion signal."""
    metrics = AnswerGroundingMetrics().score(
        "Routing is handled in router.ts.",
        [{"path": "src/app/router.ts", "lines": "1-40"}],
        CONTEXT,
        EXPECTED,
    )

    assert metrics["citation_resolved_rate"] == 1.0
    assert metrics["citation_expected_hit"] == 0.0
    assert metrics["answer_grounded"] == 0.0


def test_a_citation_naming_a_file_absent_from_the_context_counts_as_fabricated() -> None:
    """The model cannot have read a file it was not shown, so the reference is invented --
    even when the path happens to exist in the repository."""
    metrics = AnswerGroundingMetrics().score(
        "See the bootstrap module.",
        [{"path": "src/app/cli.ts"}, {"path": "src/app/bootstrap.ts"}],
        CONTEXT,
        EXPECTED,
    )

    assert metrics["citation_fabricated_count"] == 1.0
    assert metrics["citation_fabricated_rate"] == 0.5
    assert metrics["citation_expected_hit"] == 1.0
    # One real citation does not redeem an invented one.
    assert metrics["answer_grounded"] == 0.0


def test_an_answer_with_no_citations_fails_the_gate() -> None:
    metrics = AnswerGroundingMetrics().score("It is handled by the CLI.", [], CONTEXT, EXPECTED)

    assert metrics["answer_nonempty"] == 1.0
    assert metrics["answer_grounded"] == 0.0
    assert metrics["citation_fabricated_rate"] == 0.0


def test_an_empty_answer_fails_the_gate_even_with_valid_citations() -> None:
    """Thinking mode left enabled produced empty answers ~10% of the time; token-overlap
    metrics scored those as merely weak rather than as no answer at all."""
    metrics = AnswerGroundingMetrics().score("   ", [{"path": "src/app/cli.ts"}], CONTEXT, EXPECTED)

    assert metrics["answer_nonempty"] == 0.0
    assert metrics["answer_grounded"] == 0.0


def test_partial_coverage_of_a_multi_file_answer_is_reported_as_recall() -> None:
    metrics = AnswerGroundingMetrics().score(
        "Both the CLI and the router are involved.",
        [{"path": "src/app/cli.ts"}],
        CONTEXT,
        ["src/app/cli.ts", "src/app/router.ts"],
    )

    assert metrics["citation_expected_recall"] == 0.5
    assert metrics["citation_expected_precision"] == 1.0
    # Citing one of two expected files is still grounded: the answer may legitimately
    # reference the file that carries the answer without enumerating every expected path.
    assert metrics["answer_grounded"] == 1.0


def test_duplicate_citations_of_the_same_path_are_counted_once() -> None:
    metrics = AnswerGroundingMetrics().score(
        "The CLI parses the flags and then dispatches.",
        [{"path": "src/app/cli.ts", "lines": "1-10"}, {"path": "./src/app/cli.ts", "lines": "40-50"}],
        CONTEXT,
        EXPECTED,
    )

    assert metrics["citation_expected_precision"] == 1.0
    assert metrics["answer_grounded"] == 1.0


def test_bare_string_citations_are_accepted() -> None:
    """Citations arrive straight from model output, where the schema is a request rather
    than a guarantee on backends that cannot constrain decoding."""
    metrics = AnswerGroundingMetrics().score("In cli.ts.", ["src/app/cli.ts"], CONTEXT, EXPECTED)

    assert metrics["answer_grounded"] == 1.0


def test_malformed_citation_entries_do_not_raise() -> None:
    metrics = AnswerGroundingMetrics().score(
        "In cli.ts.",
        [None, 42, {}, {"path": ""}, {"path": "src/app/cli.ts"}],
        CONTEXT,
        EXPECTED,
    )

    assert metrics["answer_grounded"] == 1.0


def test_expected_ratios_are_omitted_when_a_case_declares_no_expected_paths() -> None:
    """Reporting 0.0 would drag a sweep's mean down with cases that never had a target."""
    metrics = AnswerGroundingMetrics().score("Anything.", [{"path": "src/app/cli.ts"}], CONTEXT, [])

    assert "citation_expected_recall" not in metrics
    assert "citation_expected_precision" not in metrics
    assert metrics["answer_grounded"] == 0.0
