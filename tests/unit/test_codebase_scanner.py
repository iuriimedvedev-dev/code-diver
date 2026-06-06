from __future__ import annotations

import shutil
import warnings
from pathlib import Path

import pytest

from code_diver.services import CodebaseScanner


pytestmark = pytest.mark.unit


def test_scanner_chunks_text_files_and_preserves_line_ranges(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text("line1\nline2\nline3\nline4\nline5\n", encoding="utf-8")

    items = CodebaseScanner(include=["*.py"], chunk_lines=2).scan(tmp_path)

    assert [item.start_line for item in items] == [1, 3, 5]
    assert [item.end_line for item in items] == [2, 4, 5]
    assert all(item.path == "sample.py" for item in items)


def test_scanner_can_disable_line_chunks(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        """
class UserService:
    def create_user(self):
        return "created"
""".strip(),
        encoding="utf-8",
    )

    items = CodebaseScanner(include=["*.py"], line_chunks=False, file_summary_chunks=True).scan(tmp_path)

    assert [item.metadata["index_kind"] for item in items] == ["file_summary"]
    assert items[0].path == "app.py"


def test_scanner_skips_binary_and_excluded_paths(tmp_path: Path) -> None:
    (tmp_path / "keep.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "skip.py").write_text("print('skip')\n", encoding="utf-8")
    (tmp_path / "binary.py").write_bytes(b"abc\x00def")
    nested = tmp_path / "generated" / "nested.py"
    nested.parent.mkdir()
    nested.write_text("print('generated')\n", encoding="utf-8")

    items = CodebaseScanner(include=["*.py"], exclude=["skip.py", "generated/**"]).scan(tmp_path)

    assert [item.path for item in items] == ["keep.py"]


def test_scanner_respects_gitignore_when_ripgrep_is_available(tmp_path: Path) -> None:
    if shutil.which("rg") is None:
        pytest.skip("ripgrep is required for gitignore-aware scanner enumeration")
    (tmp_path / ".gitignore").write_text("ignored.py\ngenerated/\n", encoding="utf-8")
    (tmp_path / "keep.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "ignored.py").write_text("print('ignored')\n", encoding="utf-8")
    generated = tmp_path / "generated" / "nested.py"
    generated.parent.mkdir()
    generated.write_text("print('generated')\n", encoding="utf-8")

    scanner = CodebaseScanner(include=["*.py"])
    items = scanner.scan(tmp_path)

    assert scanner.count_candidate_files(tmp_path) == 1
    assert [item.path for item in items] == ["keep.py"]


def test_scanner_can_chunk_python_symbols(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        """
class UserService:
    def create_user(self):
        return "created"

def build_app():
    return UserService()
""".strip(),
        encoding="utf-8",
    )

    items = CodebaseScanner(include=["*.py"], symbol_chunks=True).scan(tmp_path)

    titles = {item.title for item in items}
    assert "app.py" in titles
    assert "app.py::UserService" in titles
    assert "app.py::UserService.create_user" in titles
    assert "app.py::build_app" in titles
    assert all(item.metadata["source"] == "scanner" for item in items)


def test_scanner_can_index_symbol_signatures_without_bodies(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        """
class UserService:
    def create_user(self):
        secret = "body should stay out"
        return secret
""".strip(),
        encoding="utf-8",
    )

    items = CodebaseScanner(include=["*.py"], line_chunks=False, symbol_chunks=True, symbol_body=False).scan(tmp_path)

    symbol_items = [item for item in items if item.metadata["index_kind"] == "symbol"]
    assert symbol_items
    assert all("lines:" in item.content for item in symbol_items)
    assert all("body should stay out" not in item.content for item in symbol_items)


def test_scanner_can_use_structural_chunks(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        """
import os


class UserService:
    def create_user(self):
        return os.getenv("USER")


def build_app():
    return UserService()
""".strip(),
        encoding="utf-8",
    )

    items = CodebaseScanner(include=["*.py"], chunk_lines=20, structural_chunks=True).scan(tmp_path)

    structural = [item for item in items if item.metadata["index_kind"] == "structural_chunk"]
    assert [item.title for item in structural] == [
        "app.py::module preamble",
        "app.py::UserService",
        "app.py::build_app",
    ]
    assert [(item.start_line, item.end_line) for item in structural] == [(1, 3), (4, 6), (9, 10)]


def test_scanner_suppresses_python_invalid_escape_warnings(tmp_path: Path) -> None:
    (tmp_path / "regexes.py").write_text(
        'PATTERN = "\\("\n\n'
        "def parse_regex():\n"
        "    return PATTERN\n",
        encoding="utf-8",
    )

    scanner = CodebaseScanner(include=["*.py"], structural_chunks=True, symbol_chunks=True)

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        items = scanner.scan(tmp_path)

    assert items
    assert not [warning for warning in captured if issubclass(warning.category, SyntaxWarning)]


def test_scanner_can_add_file_summary_items(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        """
from services.auth import authorize

class UserService:
    def create_user(self):
        return authorize()
""".strip(),
        encoding="utf-8",
    )

    items = CodebaseScanner(include=["*.py"], symbol_chunks=True, file_summary_chunks=True).scan(tmp_path)

    summaries = [item for item in items if item.metadata["index_kind"] == "file_summary"]
    assert len(summaries) == 1
    assert summaries[0].path == "app.py"
    assert "imports:" in summaries[0].content
    assert "symbols:" in summaries[0].content
    assert "UserService.create_user" in summaries[0].content


def test_scanner_can_add_file_manifest_items(tmp_path: Path) -> None:
    source = tmp_path / "src" / "main" / "kotlin" / "com" / "example" / "UserService.kt"
    source.parent.mkdir(parents=True)
    source.write_text(
        """
package com.example

import com.example.auth.Authorizer

class UserService {
    fun updateUser() = Authorizer.authorize()
}
""".strip(),
        encoding="utf-8",
    )

    items = CodebaseScanner(
        include=["**/*.kt"],
        line_chunks=False,
        file_manifest_chunks=True,
    ).scan(tmp_path)

    manifests = [item for item in items if item.metadata["index_kind"] == "file_manifest"]
    assert len(manifests) == 1
    assert manifests[0].path == "src/main/kotlin/com/example/UserService.kt"
    assert "path_tokens:" in manifests[0].content
    assert "package: com.example" in manifests[0].content
    assert "UserService" in manifests[0].content
    assert "updateUser" in manifests[0].content
    assert "com.example.auth.Authorizer" in manifests[0].content


def test_file_manifest_extracts_config_keys(tmp_path: Path) -> None:
    config = tmp_path / "META-INF" / "plugin.xml"
    config.parent.mkdir()
    config.write_text(
        """
<idea-plugin>
  <extensions defaultExtensionNs="com.intellij">
    <toolWindow id="User Tool"/>
  </extensions>
</idea-plugin>
""".strip(),
        encoding="utf-8",
    )

    items = CodebaseScanner(
        include=["**/*.xml"],
        line_chunks=False,
        file_manifest_chunks=True,
    ).scan(tmp_path)

    manifest = next(item for item in items if item.metadata["index_kind"] == "file_manifest")
    assert "config_keys:" in manifest.content
    assert "idea-plugin" in manifest.content
    assert "extensions" in manifest.content
    assert "toolWindow" in manifest.content


def test_scanner_can_add_file_api_manifest_items(tmp_path: Path) -> None:
    (tmp_path / "users.py").write_text(
        '''
class UserService:
    """Manage user lifecycle."""

    def update_user(self, user_id: str):
        """Update a user profile and authorization state."""
        client = requests.Session()
        client.post("https://api.example.com/users/update", json={"user_id": user_id})
        return user_id
'''.strip(),
        encoding="utf-8",
    )

    items = CodebaseScanner(
        include=["*.py"],
        line_chunks=False,
        file_api_manifest_chunks=True,
    ).scan(tmp_path)

    manifests = [item for item in items if item.metadata["index_kind"] == "file_api_manifest"]
    assert len(manifests) == 1
    assert manifests[0].path == "users.py"
    assert "api_symbols:" in manifests[0].content
    assert "UserService.update_user" in manifests[0].content
    assert "identifier_terms:" in manifests[0].content
    assert "call_terms:" in manifests[0].content
    assert "session" in manifests[0].content.lower()
    assert "post" in manifests[0].content.lower()
    assert "resource_terms:" in manifests[0].content
    assert "example" in manifests[0].content.lower()
    assert "effect_tags:" in manifests[0].content
    assert "auth" in manifests[0].content
    assert "network" in manifests[0].content
    assert "update a user profile" in manifests[0].content.lower()


def test_scanner_can_limit_symbols_per_file(tmp_path: Path) -> None:
    (tmp_path / "app.kt").write_text(
        """
class UserService
fun createUser() = Unit
fun deleteUser() = Unit
""".strip(),
        encoding="utf-8",
    )

    items = CodebaseScanner(include=["*.kt"], symbol_chunks=True, max_symbols_per_file=2).scan(tmp_path)

    symbol_items = [item for item in items if item.metadata["index_kind"] == "symbol"]
    assert [item.metadata["symbol"] for item in symbol_items] == ["UserService", "createUser"]
