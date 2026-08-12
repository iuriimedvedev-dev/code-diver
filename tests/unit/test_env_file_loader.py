from __future__ import annotations

import os
from pathlib import Path

import pytest

from code_diver.env import EnvFileLoader

pytestmark = pytest.mark.unit


def test_env_file_loader_reads_dotenv_without_overriding_existing_values(tmp_path: Path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("GEMINI_API_KEY=from-file\nOPENAI_API_KEY='quoted'\n", encoding="utf-8")
    monkeypatch.setenv("GEMINI_API_KEY", "existing")
    # Must be absent for the second assertion to mean anything. An earlier test in the same
    # process can have run a CLI path that loaded the developer's real .env into os.environ,
    # in which case the loader correctly declines to override it and this test fails for a
    # reason that has nothing to do with the loader.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    EnvFileLoader().load(env_path)

    assert os.environ["GEMINI_API_KEY"] == "existing"
    assert os.environ["OPENAI_API_KEY"] == "quoted"
