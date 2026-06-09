from __future__ import annotations

from pathlib import Path

from ..domain import CodeItemIndexKindResolver, SearchResult
from ..inspection import ReadExcerptService
from .answer_context import AnswerContext


class AnswerContextBuilder:
    def __init__(
        self,
        root: Path,
        *,
        max_files: int = 8,
        lines_per_file: int = 160,
        max_docs: int = 3,
        doc_lines_per_file: int = 120,
        exclude: list[str] | None = None,
        max_file_bytes: int = 1_000_000,
    ):
        self.root = root
        self.max_files = max(1, int(max_files or 1))
        self.lines_per_file = max(20, int(lines_per_file or 160))
        self.max_docs = max(0, int(max_docs or 0))
        self.doc_lines_per_file = max(20, int(doc_lines_per_file or 120))
        self.reader = ReadExcerptService(root, exclude=exclude, max_file_bytes=max_file_bytes)
        self.kind_resolver = CodeItemIndexKindResolver()

    def build(self, results: list[SearchResult]) -> AnswerContext:
        files: list[str] = []
        file_ranges: dict[str, tuple[int, int]] = {}
        errors: list[str] = []
        blocks: list[str] = []
        doc_blocks: list[str] = []
        seen: set[str] = set()
        for rank, result in enumerate(results, start=1):
            path = result.item.path
            if path in seen:
                continue
            seen.add(path)
            if self._is_documentation_result(result):
                if len(doc_blocks) >= self.max_docs:
                    continue
                block = self._documentation_block(rank, result, file_ranges, errors)
                if block:
                    doc_blocks.append(block)
                continue
            if len(files) >= self.max_files:
                break
            excerpt = self._read_excerpt(path, result, self.lines_per_file, errors)
            if excerpt is None:
                continue
            files.append(path)
            file_ranges[path] = (int(excerpt["startLine"]), int(excerpt["endLine"]))
            index_summary = result.item.content.strip()
            if len(index_summary) > 1400:
                index_summary = f"{index_summary[:1400].rstrip()}..."
            code = "\n".join(f"{line['line']:>5} | {line['text']}" for line in excerpt["lines"])
            blocks.append(
                "\n".join(
                    [
                        f"### Candidate {len(files)} rank={rank} score={result.score:.6f}",
                        f"Path: {path}",
                        f"Indexed summary: {index_summary}",
                        f"Excerpt: {path}:{excerpt['startLine']}-{excerpt['endLine']}",
                        "```",
                        code,
                        "```",
                    ]
                )
            )
        sections = []
        if doc_blocks:
            sections.append("## Documentation context\n\n" + "\n\n".join(doc_blocks))
        if blocks:
            sections.append("## Code context\n\n" + "\n\n".join(blocks))
        return AnswerContext(text="\n\n".join(sections), files=files, file_ranges=file_ranges, errors=errors)

    def _documentation_block(
        self,
        rank: int,
        result: SearchResult,
        file_ranges: dict[str, tuple[int, int]],
        errors: list[str],
    ) -> str:
        path = result.item.path
        excerpt = self._read_excerpt(path, result, self.doc_lines_per_file, errors)
        if excerpt is None:
            return ""
        file_ranges[path] = (int(excerpt["startLine"]), int(excerpt["endLine"]))
        index_summary = result.item.content.strip()
        if len(index_summary) > 1800:
            index_summary = f"{index_summary[:1800].rstrip()}..."
        text = "\n".join(f"{line['line']:>5} | {line['text']}" for line in excerpt["lines"])
        return "\n".join(
            [
                f"### Documentation candidate {rank} score={result.score:.6f}",
                f"Path: {path}",
                f"Indexed documentation metadata: {index_summary}",
                f"Excerpt: {path}:{excerpt['startLine']}-{excerpt['endLine']}",
                "```",
                text,
                "```",
            ]
        )

    def _read_excerpt(
        self,
        path: str,
        result: SearchResult,
        lines: int,
        errors: list[str],
    ) -> dict | None:
        start_line = max(int(result.item.start_line or 1) - 20, 1)
        try:
            return self.reader.structured(path, start_line=start_line, lines=lines)
        except Exception as exc:
            errors.append(f"{path}: {exc}")
            return None

    def _is_documentation_result(self, result: SearchResult) -> bool:
        kind = self.kind_resolver.resolve(result.item)
        if kind.startswith("doc_"):
            return True
        normalized = result.item.path.lower().replace("\\", "/")
        name = Path(normalized).name
        suffix = Path(name).suffix
        return suffix in {".md", ".mdx", ".rst", ".txt", ".adoc"} or name.startswith("readme")
