from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import AppConfig
from ..config.pi_repo_context_config import PiRepoContextConfig


@dataclass(frozen=True, slots=True)
class RepositoryContextResult:
    path: Path
    chars: int
    mode: str


class RepositoryContextBuilder:
    IGNORED_DIRS = {
        ".git",
        ".code-diver",
        ".idea",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "out",
        "target",
    }

    def build(self, config: AppConfig) -> RepositoryContextResult | None:
        context = config.pi.repo_context
        if not context.enabled:
            return None
        root = config.root.resolve()
        output = self._root_path(root, context.output)
        text = self._render(root, context)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
        return RepositoryContextResult(path=output, chars=len(text), mode=context.mode)

    def _render(self, root: Path, context: PiRepoContextConfig) -> str:
        sections = [
            "# Repository Context",
            "",
            "This context is a stable prefix for Code Diver chat sessions. Use it as orientation only;",
            "verify implementation claims with Code Diver tools before answering.",
            "",
            f"Repository root: `{root}`",
            "",
            "## Top-Level Layout",
            "",
            self._top_level_layout(root),
            "",
        ]
        readme = self._readme(root)
        if readme is not None:
            sections.extend(["## README", "", self._readme_text(readme, context.mode), ""])
        if context.include_docs:
            docs = self._docs(root, context.docs_limit)
            if docs:
                sections.extend(["## Markdown Documentation Map", ""])
                sections.extend(self._doc_summary(root, path) for path in docs)
        return self._truncate("\n".join(sections).strip() + "\n", context.max_chars)

    def _top_level_layout(self, root: Path) -> str:
        rows = []
        try:
            children = sorted(root.iterdir(), key=lambda path: (path.is_file(), path.name.lower()))
        except OSError:
            return "- unavailable"
        for path in children:
            if path.name in self.IGNORED_DIRS or path.name.startswith(".") and path.name != ".github":
                continue
            suffix = "/" if path.is_dir() else ""
            rows.append(f"- `{path.name}{suffix}`")
            if len(rows) >= 80:
                rows.append("- ...")
                break
        return "\n".join(rows) if rows else "- empty"

    def _readme(self, root: Path) -> Path | None:
        for name in ("README.md", "README", "readme.md", "Readme.md"):
            path = root / name
            if path.is_file():
                return path
        return None

    def _readme_text(self, path: Path, mode: str) -> str:
        text = self._read_text(path)
        if mode == "full_readme":
            return f"Source: `{path.name}`\n\n{text.strip()}"
        return f"Source: `{path.name}`\n\n{self._summarize_markdown(text)}"

    def _docs(self, root: Path, limit: int) -> list[Path]:
        docs: list[Path] = []
        for path in root.rglob("*.md"):
            if self._is_ignored(path.relative_to(root)):
                continue
            if path.name.lower().startswith("readme"):
                continue
            docs.append(path)
            if len(docs) >= limit:
                break
        return sorted(docs, key=lambda path: str(path.relative_to(root)))

    def _doc_summary(self, root: Path, path: Path) -> str:
        relative = path.relative_to(root)
        text = self._read_text(path)
        title = next((line.strip() for line in text.splitlines() if line.strip().startswith("#")), "")
        excerpt = self._summarize_markdown(text, max_lines=18)
        return f"### `{relative}`\n\n{title}\n\n{excerpt}\n"

    def _summarize_markdown(self, text: str, max_lines: int = 80) -> str:
        selected: list[str] = []
        in_code = False
        for raw in text.splitlines():
            line = raw.rstrip()
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("```"):
                in_code = not in_code
                if len(selected) < max_lines:
                    selected.append(stripped)
                continue
            if in_code:
                if self._looks_factful(stripped) and len(selected) < max_lines:
                    selected.append(stripped)
                continue
            if stripped.startswith(("#", "-", "*", "1.", "2.", "3.", "4.", "5.")) or self._looks_factful(stripped):
                selected.append(stripped)
            if len(selected) >= max_lines:
                break
        return "\n".join(selected) if selected else text[:2000].strip()

    def _looks_factful(self, line: str) -> bool:
        return any(token in line for token in ("`", ":", "http://", "https://", "uv ", "npm ", "python ", "docker "))

    def _read_text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8", errors="replace")

    def _is_ignored(self, relative: Path) -> bool:
        return any(part in self.IGNORED_DIRS for part in relative.parts)

    def _root_path(self, root: Path, path: Path) -> Path:
        return path if path.is_absolute() else root / path

    def _truncate(self, text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        marker = "\n\n[Repository context truncated by configured max_chars.]\n"
        return text[: max(0, max_chars - len(marker))].rstrip() + marker
