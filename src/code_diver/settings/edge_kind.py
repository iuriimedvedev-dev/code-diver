from __future__ import annotations

from enum import StrEnum


class EdgeKind(StrEnum):
    IMPORTS = "imports"
    SAME_FILE_NEXT = "same_file_next"
