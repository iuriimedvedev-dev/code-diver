from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.config.cross_encoder_rerank_config import CrossEncoderRerankConfig
from code_diver.domain import CodeItem, SearchResult
from code_diver.reranking.cross_encoder_document_builder import build_cross_encoder_document

pytestmark = pytest.mark.unit


def _result(path: str, content: str = "indexed soup path:foo symbols:bar") -> SearchResult:
    return SearchResult(
        item=CodeItem(id=path, path=path, title=path, content=content),
        score=0.42,
    )


def test_flag_off_keeps_fused_locator_soup() -> None:
    result = _result("src/Foo.kt", "locator soup " * 20)
    text = build_cross_encoder_document(result, CrossEncoderRerankConfig(max_document_chars=40))
    assert text.startswith("path: src/Foo.kt")
    assert "locator soup" in text


def test_file_head_skips_boilerplate_uses_class_decl(tmp_path: Path) -> None:
    """H-55 now skips only copyright boilerplate, keeps package/import."""
    rel = "src/Plain.kt"
    source = tmp_path / rel
    source.parent.mkdir(parents=True)
    source.write_text(
        "// Copyright 2000-2026 JetBrains\npackage demo\nimport demo.Bar\n\nclass Plain {}\n"
        + ("x" * 2000),
        encoding="utf-8",
    )
    result = _result(rel)
    text = build_cross_encoder_document(
        result,
        CrossEncoderRerankConfig(max_document_chars=120, use_file_head_document=True),
        repository_root=tmp_path,
    )
    assert "path: src/Plain.kt" in text
    assert "class Plain" in text
    assert "Copyright" not in text
    assert "package demo" in text
    assert "import demo" in text
    assert "locator soup" not in text


def test_file_head_includes_kdoc_before_class(tmp_path: Path) -> None:
    rel = "src/Auth.kt"
    source = tmp_path / rel
    source.parent.mkdir(parents=True)
    source.write_text(
        "// Copyright 2000-2026\npackage demo\n\n/** Handles authorization tokens. */\nclass Auth {}\n",
        encoding="utf-8",
    )
    text = build_cross_encoder_document(
        _result(rel),
        CrossEncoderRerankConfig(max_document_chars=850, use_file_head_document=True),
        repository_root=tmp_path,
    )
    assert "Handles authorization tokens" in text
    assert "class Auth" in text
    assert "Copyright" not in text
    assert "package demo" in text


def test_missing_file_falls_back_to_fused_text(tmp_path: Path) -> None:
    result = _result("src/Missing.kt", "fused fallback body")
    text = build_cross_encoder_document(
        result,
        CrossEncoderRerankConfig(max_document_chars=850, use_file_head_document=True),
        repository_root=tmp_path,
    )
    assert "fused fallback body" in text
    assert text.startswith("path: src/Missing.kt")
