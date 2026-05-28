from __future__ import annotations

import os
import subprocess
from pathlib import Path

from ..config.ui_config import UiConfig
from ..domain import SearchResult
from ..settings import EnvironmentVariable


class EditorOpener:
    def __init__(self, root: Path, config: UiConfig):
        self.root = root
        self.config = config

    def open(self, result: SearchResult) -> list[str]:
        command = self.config.editor.command or os.environ.get(EnvironmentVariable.EDITOR.value)
        args_template = self.config.editor.args
        line = result.item.start_line or 1
        absolute_path = (self.root / result.item.path).resolve()
        args = [value.format(path=absolute_path, line=line, relative_path=result.item.path) for value in args_template]
        command_line = [command, *args]
        subprocess.Popen(command_line)
        return command_line
