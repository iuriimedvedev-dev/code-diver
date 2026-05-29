from __future__ import annotations

import ast
import re
from pathlib import Path

from ..domain import CodeItem
from ..settings import EdgeKind
from .code_graph import CodeGraph
from .graph_containment_builder import GraphContainmentBuilder
from .graph_edge import GraphEdge
from .python_ast_call_graph_builder import PythonAstCallGraphBuilder

TS_IMPORT_RE = re.compile(r"""from\s+['"]([^'"]+)['"]|import\s*\([^)]*['"]([^'"]+)['"][^)]*\)""")
IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class CodeGraphBuilder:
    def __init__(self, ast_enabled: bool = True):
        self.ast_enabled = ast_enabled

    def build(self, root: Path, items: list[CodeItem]) -> CodeGraph:
        by_id = {item.id: item for item in items}
        by_path: dict[str, list[CodeItem]] = {}
        for item in items:
            by_path.setdefault(item.path, []).append(item)

        edges: list[GraphEdge] = []
        edges.extend(self._same_file_edges(by_path))
        edges.extend(self._import_edges(root, by_path))
        edges.extend(self._reference_edges(items))
        if self.ast_enabled:
            edges.extend(GraphContainmentBuilder().build(by_path))
            edges.extend(PythonAstCallGraphBuilder().build(root, by_path))
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
            target_items = [self._path_representative(by_path[target_path]) for target_path in target_paths]
            for source in chunks:
                for target in target_items:
                    edges.append(GraphEdge(source=source.id, target=target.id, kind=EdgeKind.IMPORTS.value, weight=0.8))
        return edges

    def _path_representative(self, items: list[CodeItem]) -> CodeItem:
        sorted_items = sorted(items, key=lambda item: (self._symbol_name(item) != "", item.start_line or 0, item.id))
        return sorted_items[0]

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

    def _reference_edges(self, items: list[CodeItem]) -> list[GraphEdge]:
        by_name: dict[str, list[CodeItem]] = {}
        for item in items:
            name = self._symbol_name(item)
            if name and len(name) >= 3:
                by_name.setdefault(name, []).append(item)
        edges: list[GraphEdge] = []
        for source in items:
            tokens = set(IDENTIFIER_RE.findall(f"{source.title}\n{source.content}"))
            for name in tokens.intersection(by_name):
                for target in by_name[name]:
                    if source.id == target.id:
                        continue
                    edges.append(
                        GraphEdge(source=source.id, target=target.id, kind=EdgeKind.REFERENCES.value, weight=0.7)
                    )
                    break
                if len(edges) > len(items) * 20:
                    break
        return edges

    def _symbol_name(self, item: CodeItem) -> str:
        metadata_symbol = item.metadata.get("symbol") if isinstance(item.metadata, dict) else None
        if metadata_symbol:
            return str(metadata_symbol).split(".")[-1]
        if "::" in item.title:
            return item.title.rsplit("::", 1)[-1].split(".")[-1]
        return ""

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
