from __future__ import annotations

import os
import subprocess
from pathlib import Path

from ..domain import SearchResult


class EditorOpener:
    def __init__(self, root: Path, config: dict):
        self.root = root
        self.config = config

    def open(self, result: SearchResult) -> list[str]:
        editor = dict(self.config.get("editor") or {})
        command = str(editor.get("command") or os.environ.get("EDITOR") or "code")
        args_template = [str(value) for value in editor.get("args") or ["{path}:{line}"]]
        line = result.item.start_line or 1
        absolute_path = (self.root / result.item.path).resolve()
        args = [value.format(path=absolute_path, line=line, relative_path=result.item.path) for value in args_template]
        command_line = [command, *args]
        subprocess.Popen(command_line)
        return command_line
