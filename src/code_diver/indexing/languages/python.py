from __future__ import annotations

import ast
import contextlib
import warnings
from pathlib import Path

from ...domain import CodeSymbol
from .base import LanguageEvidence, StructuralSpan, with_preamble_span


class PythonStrategy:
    name: str = "python"
    supported_extensions: frozenset[str] = frozenset({".py", ".pyi"})

    def extract_symbols(self, rel_path: str, text: str) -> list[CodeSymbol]:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                tree = ast.parse(text)
        except SyntaxError:
            return []

        lines = text.splitlines()
        parent_by_id = {id(child): parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        symbols: list[CodeSymbol] = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                continue

            node_lineno = int(getattr(node, "lineno", 0) or 0)
            if node_lineno <= 0:
                continue

            decorator_lines = [
                int(getattr(d, "lineno", node_lineno))
                for d in getattr(node, "decorator_list", [])
                if getattr(d, "lineno", None)
            ]
            start_line = min([node_lineno, *decorator_lines])
            end_line = int(getattr(node, "end_lineno", node_lineno) or node_lineno)

            parent = parent_by_id.get(id(node))
            in_class = isinstance(parent, ast.ClassDef)
            name = f"{parent.name}.{node.name}" if in_class and parent else node.name
            kind = "class" if isinstance(node, ast.ClassDef) else "method" if in_class else "function"

            # Construct signature including decorators if present
            decorator_strs = []
            for d in getattr(node, "decorator_list", []):
                with contextlib.suppress(Exception):
                    decorator_strs.append(f"@{ast.unparse(d)}")

            def_line = lines[node_lineno - 1].strip() if 1 <= node_lineno <= len(lines) else node.name
            signature = f"{' '.join(decorator_strs)} {def_line}"[:240] if decorator_strs else def_line[:240]

            symbols.append(
                CodeSymbol(
                    name=name,
                    kind=kind,
                    start_line=start_line,
                    end_line=max(start_line, end_line),
                    signature=signature,
                )
            )

        symbols.sort(key=lambda s: (s.start_line, s.name))
        return symbols

    def extract_spans(self, rel_path: str, text: str, line_count: int) -> list[StructuralSpan]:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                tree = ast.parse(text)
        except SyntaxError:
            return []

        spans: list[StructuralSpan] = []
        top_level_nodes = [
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
            and getattr(node, "lineno", 0)
        ]

        for node in top_level_nodes:
            node_lineno = int(getattr(node, "lineno", 0))
            decorator_lines = [
                int(getattr(d, "lineno", node_lineno))
                for d in getattr(node, "decorator_list", [])
                if getattr(d, "lineno", None)
            ]
            start_line = min([node_lineno, *decorator_lines])
            end_line = int(getattr(node, "end_lineno", node_lineno) or node_lineno)
            kind = "class" if isinstance(node, ast.ClassDef) else "function"

            spans.append(
                StructuralSpan(
                    title=str(node.name),
                    kind=kind,
                    start_line=start_line,
                    end_line=min(end_line, line_count),
                )
            )

        return with_preamble_span(spans, line_count, title="module preamble")

    def extract_evidence(self, rel_path: str, text: str) -> LanguageEvidence:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                tree = ast.parse(text)
        except SyntaxError:
            return LanguageEvidence()

        path_obj = Path(rel_path)
        parts = [p for p in path_obj.parent.parts if p and p != "."]
        package = ".".join(parts) if parts else None

        imports: list[str] = []
        declarations: list[str] = []
        explicit_all: list[str] | None = None
        doc_hints: list[str] = []

        mod_doc = ast.get_docstring(tree)
        if mod_doc:
            first_line = mod_doc.strip().splitlines()[0].strip()
            if first_line:
                doc_hints.append(first_line)

        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                for alias in node.names:
                    imports.append(f"{mod}.{alias.name}" if mod else alias.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if (
                        isinstance(target, ast.Name)
                        and target.id == "__all__"
                        and isinstance(node.value, ast.List | ast.Tuple)
                    ):
                        explicit_all = [
                            elt.value
                            for elt in node.value.elts
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                        ]

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                declarations.append(f"class {node.name}")
                doc = ast.get_docstring(node)
                if doc:
                    first = doc.strip().splitlines()[0].strip()
                    if first:
                        doc_hints.append(f"{node.name}: {first}")
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
                declarations.append(f"{prefix} {node.name}")

        if explicit_all is not None:
            exports = explicit_all
        else:
            exports = [
                node.name
                for node in tree.body
                if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
                and not node.name.startswith("_")
            ]

        companion_path = self._resolve_companion(rel_path)

        return LanguageEvidence(
            package=package,
            imports=imports,
            exports=exports,
            declarations=declarations,
            doc_hints=doc_hints,
            companion_path=companion_path,
        )

    def _resolve_companion(self, rel_path: str) -> str | None:
        p = Path(rel_path)
        if p.suffix == ".pyi":
            py_cand = p.with_suffix(".py")
            return str(py_cand)
        if p.suffix == ".py":
            pyi_cand = p.with_suffix(".pyi")
            if pyi_cand.exists():
                return str(pyi_cand)
            name = p.name
            if name.startswith("test_"):
                # Test file -> find source
                target_name = name[5:]
                candidates = [
                    p.parent / target_name,
                    Path("src") / target_name,
                ]
                for cand in candidates:
                    if cand.exists():
                        return str(cand)
                return str(p.parent / target_name)
            else:
                # Source file -> find test
                test_name = f"test_{name}"
                candidates = [
                    p.parent / test_name,
                    Path("tests") / test_name,
                    Path("tests") / "unit" / test_name,
                ]
                for cand in candidates:
                    if cand.exists():
                        return str(cand)
                return str(Path("tests") / test_name)
        return None
