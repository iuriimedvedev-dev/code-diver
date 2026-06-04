from __future__ import annotations

import ast
import warnings
from pathlib import Path

from ..domain import CodeItem
from ..settings import EdgeKind
from .graph_edge import GraphEdge


class PythonAstCallGraphBuilder:
    def build(self, root: Path, by_path: dict[str, list[CodeItem]]) -> list[GraphEdge]:
        symbol_items = self._symbol_items(by_path)
        by_basename = self._by_basename(symbol_items)
        edges: list[GraphEdge] = []
        for rel_path, items in by_path.items():
            if not rel_path.endswith(".py"):
                continue
            tree = self._parse(root / rel_path)
            if tree is None:
                continue
            source_by_symbol = {self._symbol(item): item for item in items if self._symbol(item)}
            imports = self._imports_for_file(rel_path, tree)
            for node, symbol in self._symbol_nodes(tree):
                source = source_by_symbol.get(symbol)
                if source is None:
                    continue
                for target in self._targets_for_calls(node, source, by_basename, imports):
                    edges.append(GraphEdge(source=source.id, target=target.id, kind=EdgeKind.CALLS.value, weight=0.9))
        return edges

    def _parse(self, path: Path) -> ast.AST | None:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                return ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            return None

    def _symbol_items(self, by_path: dict[str, list[CodeItem]]) -> list[CodeItem]:
        return [item for items in by_path.values() for item in items if self._symbol(item)]

    def _by_basename(self, items: list[CodeItem]) -> dict[str, list[CodeItem]]:
        result: dict[str, list[CodeItem]] = {}
        for item in items:
            symbol = self._symbol(item)
            if symbol:
                result.setdefault(symbol.rsplit(".", 1)[-1], []).append(item)
        return result

    def _symbol_nodes(self, tree: ast.AST):
        parent_by_id = {id(child): parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            parent = parent_by_id.get(id(node))
            in_class = isinstance(parent, ast.ClassDef)
            if isinstance(node, ast.ClassDef):
                yield node, node.name
            else:
                yield node, f"{parent.name}.{node.name}" if in_class else node.name

    def _targets_for_calls(
        self,
        node: ast.AST,
        source: CodeItem,
        by_basename: dict[str, list[CodeItem]],
        imports: set[str],
    ) -> list[CodeItem]:
        targets: list[CodeItem] = []
        seen: set[str] = set()
        for call_name in self._call_names(node):
            candidates = self._rank_candidates(source, by_basename.get(call_name, []), imports)
            for candidate in candidates[:2]:
                if candidate.id == source.id or candidate.id in seen:
                    continue
                seen.add(candidate.id)
                targets.append(candidate)
                break
            if len(targets) >= 20:
                break
        return targets

    def _call_names(self, node: ast.AST) -> list[str]:
        names: list[str] = []
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            name = self._call_name(child.func)
            if name:
                names.append(name)
        return names

    def _call_name(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return ""

    def _rank_candidates(self, source: CodeItem, candidates: list[CodeItem], imports: set[str]) -> list[CodeItem]:
        return sorted(
            candidates,
            key=lambda item: (
                item.path != source.path,
                item.path not in imports,
                item.path,
                item.start_line or 0,
            ),
        )

    def _imports_for_file(self, rel_path: str, tree: ast.AST) -> set[str]:
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

    def _symbol(self, item: CodeItem) -> str:
        if not isinstance(item.metadata, dict):
            return ""
        return str(item.metadata.get("symbol") or "")
