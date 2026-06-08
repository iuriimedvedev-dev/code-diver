from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.config import AppConfig
from code_diver.config.pi_config import PiConfig
from code_diver.config.pi_repo_context_config import PiRepoContextConfig
from code_diver.pi import RepositoryContextBuilder


pytestmark = pytest.mark.unit


def test_repository_context_builder_writes_readme_summary(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text(
        "# Demo\n\n"
        "Intro paragraph.\n\n"
        "Run: `uv run code-diver index .`\n\n"
        "Hidden prose that should not dominate the summary.\n",
        encoding="utf-8",
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "architecture.md").write_text("# Architecture\n\n- Service layer\n", encoding="utf-8")
    config = AppConfig(
        root=tmp_path,
        pi=PiConfig(
            repo_context=PiRepoContextConfig(
                enabled=True,
                mode="readme_summary",
                output=Path(".code-diver/context/repository-context.md"),
                include_docs=True,
                max_chars=4000,
                docs_limit=4,
            )
        ),
    )

    result = RepositoryContextBuilder().build(config)

    assert result is not None
    text = result.path.read_text(encoding="utf-8")
    assert "Repository Context" in text
    assert "Run: `uv run code-diver index .`" in text
    assert "Architecture" in text
    assert result.mode == "readme_summary"


def test_repository_context_builder_can_include_full_readme(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Demo\n\nFull prose is kept.\n", encoding="utf-8")
    config = AppConfig(
        root=tmp_path,
        pi=PiConfig(
            repo_context=PiRepoContextConfig(
                enabled=True,
                mode="full_readme",
                output=Path(".code-diver/context/repository-context.md"),
                include_docs=False,
                max_chars=4000,
                docs_limit=0,
            )
        ),
    )

    result = RepositoryContextBuilder().build(config)

    assert result is not None
    assert "Full prose is kept." in result.path.read_text(encoding="utf-8")
