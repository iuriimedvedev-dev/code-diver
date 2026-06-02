from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.providers import EmbeddingProvider
from code_diver.services import CandidateFileScanner, CodebaseScanner, EphemeralDeepIndexService, IndexingOptions


pytestmark = pytest.mark.unit


class KeywordEmbeddingProvider(EmbeddingProvider):
    name = "test"
    model = "keyword"
    dimensions = 3

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, query: str) -> list[float]:
        return self._embed(query)

    def _embed(self, text: str) -> list[float]:
        lowered = text.lower()
        return [
            float("update" in lowered),
            float("delete" in lowered),
            float("user" in lowered),
        ]


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_ephemeral_deep_index_builds_breadcrumb_chunks_for_fixed_candidate_files(tmp_path: Path) -> None:
    write(
        tmp_path / "src" / "users.py",
        "class UserController:\n"
        "    def update_user(self, user_id):\n"
        "        return user_id\n"
        "    def delete_user(self, user_id):\n"
        "        return user_id\n",
    )
    write(tmp_path / "src" / "other.py", "def unrelated():\n    return None\n")
    service = EphemeralDeepIndexService(
        CandidateFileScanner(
            CodebaseScanner(
                include=["*.py", "**/*.py"],
                line_chunks=False,
                structural_chunks=True,
                symbol_chunks=True,
                symbol_body=True,
            )
        ),
        IndexingOptions(embedding_batch_size=4, embedding_workers=1, progress=False),
    )

    index = service.build(tmp_path, ["src/users.py"], KeywordEmbeddingProvider())
    search = service.search(index, KeywordEmbeddingProvider(), "update user", limit=1)

    assert index.temporary_vectors > 0
    assert index.build_ms >= 0.0
    assert index.cache_misses == index.temporary_vectors
    assert index.cache_hit_rate == 0.0
    assert search.query_ms >= 0.0
    assert search.results[0].item.path == "src/users.py"
    assert "[file: src/users.py]" in search.results[0].item.content
    assert "[function: update_user]" in search.results[0].item.content
    assert all(item.path == "src/users.py" for item in index.items)


def test_candidate_file_scanner_rejects_paths_outside_root(tmp_path: Path) -> None:
    service = EphemeralDeepIndexService(
        CandidateFileScanner(CodebaseScanner(include=["*.py"], line_chunks=True)),
        IndexingOptions(embedding_batch_size=4, embedding_workers=1, progress=False),
    )

    with pytest.raises(ValueError, match="escapes repository root"):
        service.build(tmp_path, ["../outside.py"], KeywordEmbeddingProvider())
