from __future__ import annotations

from dataclasses import dataclass, field

from ..settings import Defaults
from .editor_config import EditorConfig


@dataclass(slots=True)
class UiConfig:
    color: bool = Defaults.UI_COLOR
    pager: str = Defaults.UI_PAGER
    links: bool = Defaults.UI_LINKS
    editor: EditorConfig = field(default_factory=EditorConfig)
