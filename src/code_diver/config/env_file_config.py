from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..settings import Defaults


@dataclass(slots=True)
class EnvFileConfig:
    path: Path = Defaults.ENV_FILE
    override: bool = False
