from __future__ import annotations

import pytest

from code_diver.services.documentation_metadata_extractor import (
    TRUNCATION_MARKER,
    DocumentationMetadataExtractor,
)

pytestmark = pytest.mark.unit


def test_extremely_long_fact_line_is_truncated() -> None:
    huge_bullet = "- " + "x" * 10_000 + ": details"
    text = f"# Title\n\n{huge_bullet}\n"

    metadata = DocumentationMetadataExtractor(max_line_chars=200).extract(
        "README.md", text
    )

    facts = metadata["facts"]
    assert isinstance(facts, list)
    assert facts
    assert all(len(fact) <= 200 + len(TRUNCATION_MARKER) for fact in facts)
    assert any(TRUNCATION_MARKER in fact for fact in facts)


def test_short_headings_and_facts_are_unchanged() -> None:
    text = "# Setup\n\n- Run `uv run code-diver index`.\n- Authentication lives in src/auth.\n"

    metadata = DocumentationMetadataExtractor().extract("README.md", text)

    assert metadata["headings"] == ["Setup"]
    assert "Run `uv run code-diver index`." in metadata["facts"]
    assert all(TRUNCATION_MARKER not in fact for fact in metadata["facts"])
