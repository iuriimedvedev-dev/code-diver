from __future__ import annotations

import json
from pathlib import Path

import pytest

from code_diver.cli import main
from code_diver.config import AppConfig
from code_diver.config.storage_config import StorageConfig
from code_diver.inspection.info_service import InfoService


def test_info_service_with_json_store(tmp_path: Path) -> None:
    json_artifact = tmp_path / "index.json"
    json_artifact.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "provider": "openai_compatible",
                "model": "test-model",
                "dimensions": 768,
                "items": [
                    {
                        "item": {
                            "id": "item1",
                            "path": "foo.py",
                            "content": "print('hello')",
                        },
                        "vector": [0.1] * 768,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    config = AppConfig(
        root=tmp_path,
        artifact=json_artifact,
        storage=StorageConfig(
            provider="json",
        ),
    )

    service = InfoService(config)
    info = service.get_info()

    assert info.root == str(tmp_path.resolve())
    assert info.store.provider == "json"
    assert info.store.items_count == 1
    assert info.store.location == str(json_artifact)
    assert info.store.disk_size_bytes is not None and info.store.disk_size_bytes > 0
    assert info.store.metadata["model"] == "test-model"
    assert info.graph.enabled is True
    assert info.graph.exists is False

    d = info.to_dict()
    assert d["root"] == str(tmp_path.resolve())
    assert d["store"]["items_count"] == 1


def test_cli_info_command(tmp_path: Path, capsys) -> None:
    cfg_file = tmp_path / "config.yml"
    json_artifact = tmp_path / "index.json"
    json_artifact.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "provider": "openai_compatible",
                "model": "test-model",
                "dimensions": 768,
                "items": [],
            }
        ),
        encoding="utf-8",
    )
    cfg_file.write_text(
        f"""
root: {tmp_path}
artifact: {json_artifact}
storage:
  provider: json
""",
        encoding="utf-8",
    )

    exit_code = main(["--config", str(cfg_file), "info"])
    assert exit_code == 0
    captured = capsys.readouterr().out
    assert "Code Diver Index & Storage Overview" in captured
    assert "Vector Store" in captured

    exit_code_json = main(["--config", str(cfg_file), "info", "-j"])
    assert exit_code_json == 0
    captured_json = capsys.readouterr().out
    parsed = json.loads(captured_json)
    assert parsed["store"]["provider"] == "json"
    assert parsed["root"] == str(tmp_path.resolve())
