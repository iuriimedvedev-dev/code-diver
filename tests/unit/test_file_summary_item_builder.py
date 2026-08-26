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

    head_start = item.content.index("head:")
    symbols_start = item.content.index("symbols:", head_start)
    head_block = item.content[head_start:symbols_start].rstrip("\n")
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

    assert item.content.index(f"head:\n- {head_text}") < item.content.index(
        f"symbols:\n- function {symbol_text}: known symbol signature"
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

    assert item.content.index(f"head:\n- {head_text}") < item.content.index(
        "symbols:\n- function parse_document: parse_document(text: str) -> Document"
    )


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

    sections = ["file:", "extension:", "head:", "symbols:", "imports:"]
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
