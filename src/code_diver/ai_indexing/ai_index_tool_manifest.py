from __future__ import annotations


class AiIndexToolManifest:
    def render(self) -> str:
        return "tree(path, depth, limit): gitignore-aware repository structure.\nrg(pattern, path, limit): gitignore-aware regex search for language symbols and project conventions.\ngrep(pattern, path, limit): gitignore-aware literal search for exact identifiers.\nread_excerpt(path, start_line, line_count): read-only bounded source excerpt."
