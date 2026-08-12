from __future__ import annotations

import re
from pathlib import Path

DOC_SUFFIXES = {".md", ".mdx", ".rst", ".adoc", ".txt"}
HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$")
RST_HEADING_UNDERLINE_RE = re.compile(r"^\s*[=\-~^#*]{3,}\s*$")
LINK_RE = re.compile(r"\[([^\]]+)]\(([^)]+)\)")
CODE_FENCE_RE = re.compile(r"^\s*```([A-Za-z0-9_+.-]*)")
COMMAND_RE = re.compile(r"^\s*(?:[$>]?\s*)?(uv|python|pip|npm|pnpm|yarn|go|cargo|docker|kubectl|make|pytest|ruff)\b")

TRUNCATION_MARKER = " ...[truncated]"


class DocumentationMetadataExtractor:
    def __init__(
        self,
        *,
        max_headings: int = 48,
        max_links: int = 32,
        max_commands: int = 32,
        max_facts: int = 64,
        max_summary_chars: int = 3600,
        max_line_chars: int = 200,
    ):
        self.max_headings = max_headings
        self.max_links = max_links
        self.max_commands = max_commands
        self.max_facts = max_facts
        self.max_summary_chars = max_summary_chars
        self.max_line_chars = max_line_chars

    def is_documentation_path(self, rel_path: str) -> bool:
        path = Path(rel_path)
        normalized = rel_path.lower().replace("\\", "/")
        return (
            path.suffix.lower() in DOC_SUFFIXES
            or path.name.lower().startswith("readme")
            or "/docs/" in f"/{normalized}/"
        )

    def extract(self, rel_path: str, text: str) -> dict[str, object]:
        lines = text.splitlines()
        headings = self._headings(lines)
        return {
            "title": self._title(rel_path, headings),
            "role": self._role(rel_path),
            "headings": headings[: self.max_headings],
            "links": self._links(text)[: self.max_links],
            "code_languages": self._code_languages(lines),
            "commands": self._commands(lines)[: self.max_commands],
            "facts": self._facts(lines)[: self.max_facts],
            "summary": self._summary(lines, headings),
        }

    def _title(self, rel_path: str, headings: list[str]) -> str:
        if headings:
            return headings[0].lstrip("#").strip()
        return Path(rel_path).name

    def _role(self, rel_path: str) -> str:
        normalized = rel_path.lower().replace("\\", "/")
        name = Path(normalized).name
        if name.startswith("readme"):
            return "readme"
        if "/docs/" in f"/{normalized}/":
            return "docs"
        if name in {"changelog.md", "changes.md", "history.md"}:
            return "changelog"
        if "architecture" in normalized or "design" in normalized:
            return "architecture"
        return "documentation"

    def _headings(self, lines: list[str]) -> list[str]:
        headings: list[str] = []
        for index, line in enumerate(lines):
            match = HEADING_RE.match(line)
            if match:
                headings.append(match.group(2).strip(" #"))
                continue
            if index > 0 and RST_HEADING_UNDERLINE_RE.match(line):
                previous = lines[index - 1].strip()
                if previous:
                    headings.append(previous)
        return self._unique(headings)

    def _links(self, text: str) -> list[str]:
        rows = [f"{label.strip()} -> {target.strip()}" for label, target in LINK_RE.findall(text)]
        return self._unique(rows)

    def _code_languages(self, lines: list[str]) -> list[str]:
        languages = []
        for line in lines:
            match = CODE_FENCE_RE.match(line)
            if not match:
                continue
            language = match.group(1).strip() or "plain"
            languages.append(language.lower())
        return self._unique(languages)

    def _commands(self, lines: list[str]) -> list[str]:
        commands = []
        in_code = False
        for line in lines:
            if CODE_FENCE_RE.match(line):
                in_code = not in_code
                continue
            stripped = line.strip().lstrip("$>").strip()
            if (in_code and COMMAND_RE.match(stripped)) or COMMAND_RE.match(stripped):
                commands.append(stripped)
        return self._unique(commands)

    def _facts(self, lines: list[str]) -> list[str]:
        facts = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("```"):
                continue
            bullet = stripped.lstrip("-*0123456789. ").strip()
            if not bullet:
                continue
            if stripped.startswith(("#", "-", "*")) or ":" in bullet or "`" in bullet:
                facts.append(bullet)
        return self._unique(facts)

    def _summary(self, lines: list[str], headings: list[str]) -> str:
        rows: list[str] = []
        if headings:
            rows.append("Headings: " + " | ".join(headings[:12]))
        rows.extend(self._facts(lines)[:24])
        if not rows:
            rows = [line.strip() for line in lines if line.strip()][:24]
        summary = "\n".join(f"- {row}" for row in rows)
        if len(summary) <= self.max_summary_chars:
            return summary
        return summary[: self.max_summary_chars].rstrip() + "..."

    def _unique(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        rows: list[str] = []
        for value in values:
            row = " ".join(value.split())
            if not row:
                continue
            row = self._cap_line(row)
            key = row.lower()
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
        return rows

    def _cap_line(self, row: str) -> str:
        if len(row) <= self.max_line_chars:
            return row
        return row[: self.max_line_chars] + TRUNCATION_MARKER
