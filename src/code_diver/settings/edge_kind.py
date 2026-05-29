from __future__ import annotations

from enum import StrEnum


class EdgeKind(StrEnum):
    CALLS = "calls"
    CONTAINS = "contains"
    IMPORTS = "imports"
    REFERENCES = "references"
    SAME_FILE_NEXT = "same_file_next"
