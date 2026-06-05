from __future__ import annotations

from pathlib import Path

from ..domain import SearchResult
from ..inspection import ReadExcerptService
from .answer_context import AnswerContext


class AnswerContextBuilder:
    def __init__(
        self,
        root: Path,
        *,
        max_files: int = 8,
        lines_per_file: int = 160,
        exclude: list[str] | None = None,
        max_file_bytes: int = 1_000_000,
    ):
        self.root = root
        self.max_files = max(1, int(max_files or 1))
        self.lines_per_file = max(20, int(lines_per_file or 160))
        self.reader = ReadExcerptService(root, exclude=exclude, max_file_bytes=max_file_bytes)

    def build(self, results: list[SearchResult]) -> AnswerContext:
        files: list[str] = []
        file_ranges: dict[str, tuple[int, int]] = {}
        errors: list[str] = []
        blocks: list[str] = []
        seen: set[str] = set()
        for rank, result in enumerate(results, start=1):
            path = result.item.path
            if path in seen:
                continue
            seen.add(path)
            if len(files) >= self.max_files:
                break
            start_line = max(int(result.item.start_line or 1) - 20, 1)
            try:
                excerpt = self.reader.structured(path, start_line=start_line, lines=self.lines_per_file)
            except Exception as exc:
                errors.append(f"{path}: {exc}")
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
        return AnswerContext(text="\n\n".join(blocks), files=files, file_ranges=file_ranges, errors=errors)
