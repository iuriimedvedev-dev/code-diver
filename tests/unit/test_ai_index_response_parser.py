from __future__ import annotations

import pytest

from code_diver.ai_indexing.ai_index_response_parser import AiIndexResponseParser

pytestmark = pytest.mark.unit


def test_ai_index_response_parser_accepts_json_with_trailing_text() -> None:
    response = """
{"items":[{"path":"main.py","title":"Main","summary":"Entrypoint.","kind":"entrypoint"}]}

extra notes that should be ignored
""".strip()

    items = AiIndexResponseParser().parse(response, max_items=10)

    assert items[0].path == "main.py"
    assert items[0].metadata["kind"] == "entrypoint"
