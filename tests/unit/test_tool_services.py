from __future__ import annotations

import re
from pathlib import Path

import pytest

from code_diver.inspection.grep_service import GrepService
from code_diver.inspection.file_outline_service import FileOutlineService
from code_diver.inspection.path_guard import PathGuard
from code_diver.inspection.read_excerpt_service import ReadExcerptService
from code_diver.inspection.rg_service import RgService
from code_diver.inspection.symbols_service import SymbolsService
from code_diver.inspection.tree_service import TreeService


pytestmark = pytest.mark.unit


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_path_guard_accepts_relative_and_absolute_paths_inside_root(tmp_path: Path) -> None:
    source = tmp_path / "src" / "service.py"
    write(source, "print('ok')\n")

    guard = PathGuard(tmp_path)

    assert guard.resolve("src/service.py") == source.resolve()
    assert guard.resolve(str(source)) == source.resolve()


def test_path_guard_rejects_parent_traversal_and_absolute_escape(tmp_path: Path) -> None:
    guard = PathGuard(tmp_path)

    with pytest.raises(ValueError, match="escapes repository root"):
        guard.resolve("../outside.txt")

    with pytest.raises(ValueError, match="escapes repository root"):
        guard.resolve("/etc/passwd")


def test_tree_service_respects_gitignore_extra_excludes_depth_and_limit(tmp_path: Path) -> None:
    write(tmp_path / ".gitignore", "ignored-dir/\n*.secret\n")
    write(tmp_path / "src" / "visible.py", "x = 1\n")
    write(tmp_path / "src" / "nested" / "deep.py", "x = 2\n")
    write(tmp_path / "ignored-dir" / "hidden.py", "x = 3\n")
    write(tmp_path / "src" / "hidden.secret", "x = 4\n")
    write(tmp_path / "vendor" / "dep.py", "x = 5\n")

    payload = TreeService(tmp_path, exclude=["vendor/**"]).list_entries(max_depth=1, limit=2)

    paths = {entry["path"] for entry in payload["entries"]}
    assert "src" in paths
    assert "ignored-dir" not in paths
    assert "vendor" not in paths
    assert all(entry["depth"] == 1 for entry in payload["entries"])
    assert payload["metrics"]["entryCount"] == 2
    assert payload["metrics"]["truncated"] is True


def test_tree_service_file_path_returns_empty_structured_tree(tmp_path: Path) -> None:
    write(tmp_path / "src" / "visible.py", "x = 1\n")

    payload = TreeService(tmp_path).list_entries(path="src/visible.py", max_depth=3, limit=20)

    assert payload["root"] == "src/visible.py"
    assert payload["entries"] == []
    assert payload["metrics"]["entryCount"] == 0
    assert payload["metrics"]["truncated"] is False


def test_grep_service_python_backend_returns_structured_matches_without_text_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("code_diver.inspection.grep_service.shutil.which", lambda _: None)
    write(tmp_path / ".gitignore", "build/\n")
    write(tmp_path / "src" / "auth.py", "class AuthService:\n    token = 'AUTH'\n")
    write(tmp_path / "src" / "billing.py", "class BillingService:\n    pass\n")
    write(tmp_path / "build" / "generated.py", "AuthService\n")
    (tmp_path / "src" / "binary.bin").write_bytes(b"AuthService\x00hidden")
    write(tmp_path / "src" / "large.py", "AuthService\n" * 20)

    payload = GrepService(tmp_path, max_file_bytes=60).structured("AuthService", path="src", limit=10)

    assert payload["query"] == {"pattern": "AuthService", "path": "src", "regex": False, "includeText": False}
    assert payload["metrics"]["backend"] == "python"
    assert payload["metrics"]["matchCount"] == 1
    assert payload["matches"] == [{"path": "src/auth.py", "line": 1}]
    assert payload["candidates"][0]["path"] == "src/auth.py"
    assert payload["candidates"][0]["confidence"] > 0


def test_grep_service_python_backend_supports_regex_and_include_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("code_diver.inspection.grep_service.shutil.which", lambda _: None)
    write(tmp_path / "src" / "auth.py", "def login_user():\n    return issue_token()\n")

    payload = GrepService(tmp_path).structured(r"login_\w+|issue_token", path="src", limit=5, regex=True, include_text=True)

    assert payload["metrics"]["matchCount"] == 2
    assert payload["matches"][0] == {"path": "src/auth.py", "line": 1, "text": "def login_user():"}
    assert payload["candidates"][0]["evidenceLines"] == [1, 2]


def test_grep_service_invalid_regex_fails_fast_in_python_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("code_diver.inspection.grep_service.shutil.which", lambda _: None)
    write(tmp_path / "src" / "auth.py", "def login():\n    pass\n")

    with pytest.raises(re.error):
        GrepService(tmp_path).structured("[", path="src", regex=True)


def test_rg_service_python_fallback_returns_regex_metadata_and_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("code_diver.inspection.rg_service.shutil.which", lambda _: None)
    write(tmp_path / "src" / "auth.py", "login\nlogout\nlogin again\n")

    payload = RgService(tmp_path).structured("login", path="src", limit=1, include_text=True)

    assert payload["query"]["regex"] is True
    assert payload["metrics"]["backend"] == "python"
    assert payload["metrics"]["matchCount"] == 1
    assert payload["metrics"]["truncated"] is True
    assert payload["matches"] == [{"path": "src/auth.py", "line": 1, "text": "login"}]


def test_read_excerpt_service_bounds_lines_and_reports_truncation(tmp_path: Path) -> None:
    write(tmp_path / "src" / "auth.py", "\n".join(f"line {index}" for index in range(1, 6)) + "\n")

    payload = ReadExcerptService(tmp_path).structured("src/auth.py", start_line=-10, lines=999)

    assert payload["path"] == "src/auth.py"
    assert payload["startLine"] == 1
    assert payload["endLine"] == 5
    assert payload["lineCount"] == 5
    assert payload["lines"][0] == {"line": 1, "text": "line 1"}
    assert payload["metrics"]["requestedLines"] == 999
    assert payload["metrics"]["truncated"] is True


def test_read_excerpt_service_rejects_ignored_missing_directory_and_large_files(tmp_path: Path) -> None:
    write(tmp_path / ".gitignore", "ignored.py\n")
    write(tmp_path / "ignored.py", "secret\n")
    write(tmp_path / "src" / "large.py", "abcdef\n")

    service = ReadExcerptService(tmp_path, max_file_bytes=3)

    with pytest.raises(ValueError, match="Path is ignored"):
        service.structured("ignored.py")
    with pytest.raises(ValueError, match="Path is not a file"):
        service.structured("src")
    with pytest.raises(ValueError, match="Path exceeds max file size"):
        service.structured("src/large.py")


def test_file_outline_service_returns_imports_symbols_and_candidates(tmp_path: Path) -> None:
    write(
        tmp_path / "src" / "users.py",
        "from db import Session\n\n"
        "class UserController:\n"
        "    def update_user(self, db: Session, user_id: str):\n"
        "        return user_id\n",
    )

    payload = FileOutlineService(tmp_path).structured("src/users.py")

    assert payload["path"] == "src/users.py"
    assert payload["imports"] == [{"line": 1, "text": "from db import Session"}]
    assert [symbol["name"] for symbol in payload["symbols"]] == ["UserController", "UserController.update_user"]
    assert payload["candidates"][0]["path"] == "src/users.py"
    assert payload["metrics"]["symbolCount"] == 2


def test_symbols_service_supports_fuzzy_symbol_definition_query(tmp_path: Path) -> None:
    write(
        tmp_path / "src" / "users.py",
        "class UserController:\n"
        "    def update_user(self, db,\n"
        "                    user_id):\n"
        "        return user_id\n"
        "    def delete_user(self, user_id):\n"
        "        return user_id\n",
    )

    payload = SymbolsService(tmp_path).structured("src/users.py", query="update user")

    assert [symbol["name"] for symbol in payload["symbols"]] == ["UserController.update_user"]
    assert payload["query"] == {"path": "src/users.py", "query": "update user"}
