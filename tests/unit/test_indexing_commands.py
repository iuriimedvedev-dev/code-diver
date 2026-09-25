from __future__ import annotations

import argparse
import io
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from code_diver.commands.indexing import (
    cmd_index,
    cmd_index_clear,
    cmd_index_selected,
    config_for_indexing_hypothesis,
    current_repo_collection_prefix,
    format_index_composition,
    graph_activity_message,
    graph_label,
    index_content_label,
    index_profile_label,
    index_write_mode_label,
    is_index_maintenance_command,
    prepare_index_collection,
    store_label,
    suffixed_artifact_path,
)
from code_diver.config import AppConfig
from code_diver.config.embedding_config import EmbeddingConfig
from code_diver.config.graph_config import GraphConfig
from code_diver.config.qdrant_config import QdrantConfig
from code_diver.config.scanner_config import ScannerConfig
from code_diver.config.storage_config import StorageConfig
from code_diver.domain.code_item import CodeItem


def test_is_index_maintenance_command() -> None:
    assert is_index_maintenance_command("clear") is True
    assert is_index_maintenance_command("prune") is True
    assert is_index_maintenance_command("reset") is True
    assert is_index_maintenance_command("search") is False
    assert is_index_maintenance_command(None) is False


def test_current_repo_collection_prefix() -> None:
    config = AppConfig(
        storage=StorageConfig(
            qdrant=QdrantConfig(collection="code_diver__repo_demo__emb_qwen")
        )
    )
    assert current_repo_collection_prefix(config) == "code_diver__repo_demo"

    fallback = AppConfig(
        storage=StorageConfig(qdrant=QdrantConfig(collection="plain_collection"))
    )
    assert current_repo_collection_prefix(fallback) == "plain_collection"


def test_store_label() -> None:
    qdrant_cfg = AppConfig(
        storage=StorageConfig(
            provider="qdrant",
            qdrant=QdrantConfig(collection="my_col"),
        )
    )
    assert store_label(qdrant_cfg) == "qdrant:my_col"

    json_cfg = AppConfig(
        storage=StorageConfig(provider="json"),
        artifact=Path("/tmp/index.json"),
    )
    assert store_label(json_cfg) == "/tmp/index.json"


def test_suffixed_artifact_path(tmp_path: Path) -> None:
    path = tmp_path / "index.json"
    assert (
        suffixed_artifact_path(path, "hypo", "run1")
        == tmp_path / "index_hypo_run1.json"
    )
    assert suffixed_artifact_path(path, "hypo") == tmp_path / "index_hypo.json"


def test_config_for_indexing_hypothesis(tmp_path: Path) -> None:
    config = AppConfig(
        artifact=tmp_path / "index.json",
        storage=StorageConfig(qdrant=QdrantConfig(collection="base_col")),
        graph=GraphConfig(artifact=tmp_path / "graph.json"),
    )
    isolated = config_for_indexing_hypothesis(config, "h1", "run1")
    assert isolated.storage.qdrant.collection == "base_col_h1_run1"
    assert isolated.artifact == tmp_path / "index_h1_run1.json"
    assert isolated.graph.artifact == tmp_path / "graph_h1_run1.json"

    # With hypothesis object
    @dataclass
    class Hyp:
        name: str

    isolated2 = config_for_indexing_hypothesis(config, Hyp(name="h2"))
    assert isolated2.storage.qdrant.collection == "base_col_h2"
    assert isolated2.artifact == tmp_path / "index_h2.json"
    assert isolated2.graph.artifact == tmp_path / "graph_h2.json"


def test_prepare_index_collection_handles_both_param_orders(tmp_path: Path) -> None:
    config = AppConfig(
        root=tmp_path,
        storage=StorageConfig(
            provider="qdrant",
            qdrant=QdrantConfig(collection="code_diver__repo__emb_x"),
        ),
    )
    args = argparse.Namespace(
        update_index=True, override_repo=False, reindex=False
    )

    mock_store = MagicMock()
    mock_store.exists.return_value = True

    with patch(
        "code_diver.commands.indexing.make_vector_store", return_value=mock_store
    ):
        # Order 1: prepare_index_collection(config, args)
        prepare_index_collection(config, args, progress=False)
        assert mock_store.close.called

        mock_store.reset_mock()
        # Order 2: prepare_index_collection(args, config)
        prepare_index_collection(args, config, progress=False)
        assert mock_store.close.called


def test_prepare_index_collection_rejects_existing_collection_without_flag(
    tmp_path: Path,
) -> None:
    config = AppConfig(
        root=tmp_path,
        storage=StorageConfig(
            provider="qdrant",
            qdrant=QdrantConfig(collection="code_diver__repo__emb_x"),
        ),
    )
    args = argparse.Namespace(
        update_index=False, override_repo=False, reindex=False
    )

    mock_store = MagicMock()
    mock_store.exists.return_value = True

    with patch(
        "code_diver.commands.indexing.make_vector_store", return_value=mock_store
    ):
        with pytest.raises(RuntimeError, match="--update-index"):
            prepare_index_collection(config, args, progress=False)


def test_labels_and_formatting() -> None:
    cfg = AppConfig(graph=GraphConfig(enabled=False))
    assert graph_label(cfg) == "disabled"
    assert index_write_mode_label(argparse.Namespace(override_repo=True)) == "override repo collections"
    assert index_write_mode_label(argparse.Namespace(update_index=True)) == "update current collection"
    assert index_write_mode_label(argparse.Namespace()) == "create new collection"

    item = CodeItem(
        id="item-1",
        path="foo.py",
        title="foo",
        start_line=1,
        end_line=10,
        content="print('foo')",
    )
    composition_str = format_index_composition([item])
    assert "unique_paths=1" in composition_str


def test_cmd_index_clear_rejects_non_qdrant() -> None:
    config = AppConfig(storage=StorageConfig(provider="json"))
    args = argparse.Namespace()
    with pytest.raises(ValueError, match="only supported for Qdrant storage"):
        cmd_index_clear(args, config)


def test_cmd_index_clear_rejects_flags() -> None:
    config = AppConfig(storage=StorageConfig(provider="qdrant"))
    args = argparse.Namespace(update_index=True)
    with pytest.raises(ValueError, match="cannot be combined"):
        cmd_index_clear(args, config)


def test_cmd_index_clear_deletes_prefix() -> None:
    config = AppConfig(
        storage=StorageConfig(
            provider="qdrant",
            qdrant=QdrantConfig(collection="code_diver__repo__emb_x"),
        )
    )
    args = argparse.Namespace(
        update_index=False,
        override_repo=False,
        all=False,
        no_progress=True,
        quiet=True,
    )
    mock_store = MagicMock()
    mock_store.delete_collections_with_prefix.return_value = ["col1"]

    with patch(
        "code_diver.commands.indexing.ensure_storage_runtime"
    ), patch(
        "code_diver.commands.indexing.make_vector_store", return_value=mock_store
    ):
        exit_code = cmd_index_clear(args, config)
        assert exit_code == 0
        mock_store.delete_collections_with_prefix.assert_called_with(
            "code_diver__repo"
        )
        assert mock_store.close.called


def test_cmd_index_selected_empty_stdin(capsys: pytest.CaptureFixture) -> None:
    config = AppConfig()
    args = argparse.Namespace(json=True)
    with patch("sys.stdin", io.StringIO('{"items": []}')):
        code = cmd_index_selected(args, config)
        assert code == 0
        captured = capsys.readouterr().out
        assert '"indexed": 0' in captured
