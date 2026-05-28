from __future__ import annotations


class AiIndexToolManifest:
    def render(self) -> str:
        return "\n".join(
            [
                "tree(path, depth, limit): gitignore-aware repository structure.",
                "rg(pattern, path, limit): gitignore-aware regex search for language symbols and project conventions.",
                "grep(pattern, path, limit): gitignore-aware literal search for exact identifiers.",
                "read_excerpt(path, start_line, line_count): read-only bounded source excerpt.",
            ]
        )
