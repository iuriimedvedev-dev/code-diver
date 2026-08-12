from __future__ import annotations

import pytest

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

    head_block = item.content[item.content.index("head:") :]
    assert len(head_block) <= 4000
    assert TRUNCATION_MARKER in head_block


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
