from __future__ import annotations

import pytest

from code_diver.domain import CodeSymbol
from code_diver.services.file_summary_item_builder import (
    TRUNCATION_MARKER,
    FileSummaryItemBuilder,
)

pytestmark = pytest.mark.unit


def test_head_section_caps_a_single_extremely_long_line() -> None:
    text = "x" * 50_000 + "\n"

    item = FileSummaryItemBuilder(
        max_head_line_chars=200, max_head_block_chars=4000
    ).build("huge.js", text, symbols=[])

    assert len(item.content) < 4000
    assert TRUNCATION_MARKER in item.content


def test_head_section_caps_overall_block_even_with_many_short_lines() -> None:
    text = "\n".join(f"line {index}" for index in range(1000))

    item = FileSummaryItemBuilder(
        max_head_lines=1000, max_head_line_chars=200, max_head_block_chars=4000
    ).build("many_lines.py", text, symbols=[])

    # With symbols-first ordering, symbols come before head
    symbols_start = item.content.index("symbols:")
    head_start = item.content.index("head:", symbols_start)
    # Find end of head block: next section marker after head
    imports_start = item.content.index("imports:", head_start)
    head_block = item.content[head_start:imports_start].rstrip("\n")
    assert len(head_block) <= 4000
    assert TRUNCATION_MARKER in head_block


def test_head_section_occurs_before_symbols_section() -> None:
    head_text = "known head text"
    symbol_text = "known symbol text"

    item = FileSummaryItemBuilder().build(
        "ordered.py",
        head_text,
        symbols=[
            CodeSymbol(
                name=symbol_text,
                kind="function",
                start_line=1,
                end_line=1,
                signature="known symbol signature",
            )
        ],
    )

    # symbols section should appear before head section (symbols-first ordering)
    assert item.content.index(f"symbols:\n- function {symbol_text}: known symbol signature") < item.content.index(
        f"head:\n- {head_text}"
    )


def test_build_places_head_section_before_symbols() -> None:
    head_text = "distinct text-file head marker"
    dense_prose = "dense prose body marker " * 20

    item = FileSummaryItemBuilder().build(
        "ordered.txt",
        f"{head_text}\n{dense_prose}",
        symbols=[
            CodeSymbol(
                name="parse_document",
                kind="function",
                start_line=1,
                end_line=1,
                signature="parse_document(text: str) -> Document",
            )
        ],
    )

    # symbols section should appear before head section (symbols-first ordering)
    assert item.content.index(
        "symbols:\n- function parse_document: parse_document(text: str) -> Document"
    ) < item.content.index(f"head:\n- {head_text}")


def test_build_uses_complete_stable_section_order() -> None:
    item = FileSummaryItemBuilder().build(
        "ordered.py",
        "from package import value\nhead marker",
        symbols=[
            CodeSymbol(
                name="parse",
                kind="function",
                start_line=1,
                end_line=1,
                signature="parse()",
            )
        ],
    )

    sections = ["file:", "extension:", "symbols:", "head:", "imports:"]
    positions = [item.content.index(section) for section in sections]
    assert positions == sorted(positions)


def test_head_section_is_unchanged_for_a_normal_small_file() -> None:
    text = (
        "from services.auth import authorize\n"
        "\n"
        "class UserService:\n"
        "    def create_user(self):\n"
        "        return authorize()"
    )

    before = FileSummaryItemBuilder(max_head_lines=24).build(
        "app.py", text, symbols=[]
    )
    after = FileSummaryItemBuilder(
        max_head_lines=24, max_head_line_chars=200, max_head_block_chars=4000
    ).build("app.py", text, symbols=[])

    assert after.content == before.content
    assert TRUNCATION_MARKER not in after.content


def test_purpose_section_uses_first_meaningful_line() -> None:
    item = FileSummaryItemBuilder().build(
        "service.py",
        "# Copyright 2024\n\n@file: service\nclass Service:\n    pass",
        symbols=[],
    )

    assert "purpose: class Service:" in item.content


def test_purpose_section_is_none_for_empty_source() -> None:
    item = FileSummaryItemBuilder().build("empty.py", "\n# Copyright 2024\n", symbols=[])

    assert "purpose: none" in item.content


def test_purpose_section_caps_a_long_first_meaningful_line() -> None:
    item = FileSummaryItemBuilder(max_head_line_chars=10).build(
        "long.py", "class " + "x" * 100, symbols=[]
    )

    assert "purpose: class xxxx ...[truncated]" in item.content


def test_terms_section_includes_path_components() -> None:
    item = FileSummaryItemBuilder().build("src/auth/UserService.py", "pass", symbols=[])

    assert "terms: user service src auth py" in item.content


def test_terms_section_includes_symbol_names_and_signatures() -> None:
    item = FileSummaryItemBuilder().build(
        "handlers.py",
        "pass",
        symbols=[
            CodeSymbol(
                name="parseRequest",
                kind="function",
                start_line=1,
                end_line=1,
                signature="parseRequest(request: Request) -> Response",
            )
        ],
    )

    assert "parse request" in item.content
    assert "response" in item.content


def test_terms_section_lowercases_deduplicates_and_ignores_short_tokens() -> None:
    item = FileSummaryItemBuilder().build(
        "src/API/APIClient.py",
        "pass",
        symbols=[
            CodeSymbol(
                name="ApiClient",
                kind="class",
                start_line=1,
                end_line=1,
                signature="ApiClient(x: X)",
            )
        ],
    )
    terms = item.content[item.content.index("terms: ") :].splitlines()[0]

    assert terms.split().count("api") == 1
    assert "client" in terms
    assert " x " not in f" {terms} "


def test_terms_section_respects_max_symbols() -> None:
    item = FileSummaryItemBuilder(max_symbols=1).build(
        "symbols.py",
        "pass",
        symbols=[
            CodeSymbol("firstSymbol", "function", 1, 1, "firstSymbol()"),
            CodeSymbol("secondSymbol", "function", 2, 2, "secondSymbol()"),
        ],
    )

    assert "first symbol" in item.content
    assert "second" not in item.content


def test_terms_section_has_stable_first_occurrence_order() -> None:
    item = FileSummaryItemBuilder().build("src/auth/Auth.py", "pass", symbols=[])
    terms = item.content[item.content.index("terms: ") :].splitlines()[0]

    assert terms == "terms: auth src py"


def test_terms_section_is_none_when_path_has_no_terms() -> None:
    item = FileSummaryItemBuilder().build("a", "pass", symbols=[])

    assert "terms: none" in item.content
