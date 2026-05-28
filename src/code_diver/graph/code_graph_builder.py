from __future__ import annotations

import ast
import re
from pathlib import Path

from ..domain import CodeItem
from ..settings import EdgeKind
from .code_graph import CodeGraph
from .graph_edge import GraphEdge

TS_IMPORT_RE = re.compile(r"""from\s+['"]([^'"]+)['"]|import\s*\([^)]*['"]([^'"]+)['"][^)]*\)""")


class CodeGraphBuilder:
    def build(self, root: Path, items: list[CodeItem]) -> CodeGraph:
        by_id = {item.id: item for item in items}
        by_path: dict[str, list[CodeItem]] = {}
        for item in items:
            by_path.setdefault(item.path, []).append(item)

        edges: list[GraphEdge] = []
        edges.extend(self._same_file_edges(by_path))
        edges.extend(self._import_edges(root, by_path))
        return CodeGraph(items=by_id, edges=self._dedupe_edges(edges))

    def _same_file_edges(self, by_path: dict[str, list[CodeItem]]) -> list[GraphEdge]:
        edges: list[GraphEdge] = []
        for chunks in by_path.values():
            sorted_chunks = sorted(chunks, key=lambda item: item.start_line or 0)
            for left, right in zip(sorted_chunks, sorted_chunks[1:]):
                edges.append(GraphEdge(source=left.id, target=right.id, kind=EdgeKind.SAME_FILE_NEXT.value, weight=0.6))
        return edges

    def _import_edges(self, root: Path, by_path: dict[str, list[CodeItem]]) -> list[GraphEdge]:
        edges: list[GraphEdge] = []
        known_paths = set(by_path)
        for path, chunks in by_path.items():
            imports = self._imports_for_file(root, path)
            target_paths = [target for target in imports if target in known_paths]
            for source in chunks:
                for target_path in target_paths:
                    for target in by_path[target_path]:
                        edges.append(GraphEdge(source=source.id, target=target.id, kind=EdgeKind.IMPORTS.value, weight=0.8))
        return edges

    def _imports_for_file(self, root: Path, rel_path: str) -> set[str]:
        path = root / rel_path
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return set()
        suffix = path.suffix.lower()
        if suffix == ".py":
            return self._python_imports(rel_path, text)
        if suffix in {".ts", ".tsx", ".js", ".jsx"}:
            return self._ts_imports(rel_path, text)
        return set()

    def _python_imports(self, rel_path: str, text: str) -> set[str]:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return set()
        imports: set[str] = set()
        package_dir = Path(rel_path).parent
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.update(self._python_module_to_paths(alias.name))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level:
                    base = package_dir
                    for _ in range(max(node.level - 1, 0)):
                        base = base.parent
                    module_path = base / module.replace(".", "/")
                    imports.add(f"{module_path}.py")
                    imports.add(f"{module_path}/__init__.py")
                else:
                    imports.update(self._python_module_to_paths(module))
        return imports

    def _python_module_to_paths(self, module: str) -> set[str]:
        module_path = module.replace(".", "/")
        return {f"{module_path}.py", f"{module_path}/__init__.py"}

    def _ts_imports(self, rel_path: str, text: str) -> set[str]:
        imports: set[str] = set()
        base_dir = Path(rel_path).parent
        for match in TS_IMPORT_RE.findall(text):
            raw = next((part for part in match if part), "")
            if not raw.startswith("."):
                continue
            candidate = (base_dir / raw).as_posix()
            for suffix in (".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.tsx", "/index.js", "/index.jsx"):
                imports.add(f"{candidate}{suffix}")
        return imports

    def _dedupe_edges(self, edges: list[GraphEdge]) -> list[GraphEdge]:
        seen: set[tuple[str, str, str]] = set()
        deduped: list[GraphEdge] = []
        for edge in edges:
            key = (edge.source, edge.target, edge.kind)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(edge)
        return deduped
