from __future__ import annotations

from pathlib import Path
import os

import pytest

from code_diver.env import EnvFileLoader


pytestmark = pytest.mark.unit


def test_env_file_loader_reads_dotenv_without_overriding_existing_values(tmp_path: Path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("GEMINI_API_KEY=from-file\nOPENAI_API_KEY='quoted'\n", encoding="utf-8")
    monkeypatch.setenv("GEMINI_API_KEY", "existing")

    EnvFileLoader().load(env_path)

    assert os.environ["GEMINI_API_KEY"] == "existing"
    assert os.environ["OPENAI_API_KEY"] == "quoted"
