from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


class PiRuntimeManager:
    def __init__(self, package_root: Path | None = None) -> None:
        self.package_root = package_root or self._discover_package_root()

    def install(self) -> None:
        if shutil.which("npm") is None:
            raise RuntimeError("npm is required to install the Search agent runtime.")
        subprocess.run(["npm", "install"], cwd=self.package_root, check=True)

    def ensure_available(self) -> None:
        if not (self.package_root / "package.json").exists():
            raise RuntimeError(
                "Search agent package.json was not found. Run Code Diver from the project root or reinstall the package."
            )
        if not self.local_binary().exists():
            raise RuntimeError(
                "Search agent runtime is not installed. Run `uv run code-diver init` to install npm/Pi dependencies."
            )

    def local_binary(self) -> Path:
        suffix = ".cmd" if self._is_windows() else ""
        return self.package_root / "node_modules" / ".bin" / f"pi{suffix}"

    def cwd_for_command(self, command: list[str]) -> Path | None:
        if self._uses_local_npm_exec(command):
            return self.package_root
        return None

    def _discover_package_root(self) -> Path:
        for start in (Path.cwd(), Path(__file__).resolve().parent):
            for path in (start, *start.parents):
                package_json = path / "package.json"
                if package_json.exists() and ".pi" in {child.name for child in path.iterdir() if child.is_dir()}:
                    return path
        return Path.cwd()

    def _uses_local_npm_exec(self, command: list[str]) -> bool:
        return len(command) >= 4 and command[:3] == ["npm", "exec", "--"] and command[3] == "pi"

    def _is_windows(self) -> bool:
        return os.name == "nt"
