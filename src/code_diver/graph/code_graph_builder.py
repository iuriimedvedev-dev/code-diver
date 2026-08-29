from __future__ import annotations

import ast
import itertools
import re
import warnings
from pathlib import Path

from ..domain import CodeItem, CodeItemIndexKind, CodeItemIndexKindResolver
from ..settings import EdgeKind
from .code_graph import CodeGraph
from .graph_containment_builder import GraphContainmentBuilder
from .graph_edge import GraphEdge
from .python_ast_call_graph_builder import PythonAstCallGraphBuilder

TS_IMPORT_RE = re.compile(r"""from\s+['"]([^'"]+)['"]|import\s*\([^)]*['"]([^'"]+)['"][^)]*\)""")
JVM_IMPORT_RE = re.compile(r"^\s*import\s+(?:static\s+)?([A-Za-z_][\w.]*)", re.MULTILINE)
JVM_SUFFIXES = (".java", ".kt", ".kts")
# A no-op on every corpus measured so far (protogen's most import-heavy file resolves 31
# in-repo targets) and a bound on the monorepo tail: without it a 75k-file Java repository
# produces millions of edges and an artifact that cannot be loaded.
IMPORT_TARGETS_PER_FILE = 64
IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+]\(([^)#]+)(?:#[^)]+)?\)")
BACKTICK_PATH_RE = re.compile(r"`([^`\n]+\.[A-Za-z0-9]{1,8})`")
ARROW_PATH_RE = re.compile(r"->\s*([^\s)]+)")
REFERENCE_EDGE_FACTOR = 5
REFERENCE_EDGES_PER_SOURCE = 3
REFERENCE_TOKEN_LIMIT = 256
NON_SYMBOL_INDEX_KINDS = {
    CodeItemIndexKind.FILE_SUMMARY,
    CodeItemIndexKind.FILE_MANIFEST,
    CodeItemIndexKind.FILE_PURPOSE,
    CodeItemIndexKind.DOC_SUMMARY,
    CodeItemIndexKind.DOC_MANIFEST,
    CodeItemIndexKind.DOC_CHUNK,
}
DOCUMENTATION_INDEX_KINDS = {
    CodeItemIndexKind.DOC_SUMMARY,
    CodeItemIndexKind.DOC_MANIFEST,
    CodeItemIndexKind.DOC_CHUNK,
}


class CodeGraphBuilder:
    def __init__(
        self,
        ast_enabled: bool = True,
        reference_edges_enabled: bool = True,
        call_edges_enabled: bool = True,
    ):
        self.ast_enabled = ast_enabled
        self.reference_edges_enabled = reference_edges_enabled
        self.call_edges_enabled = call_edges_enabled
        self.index_kind_resolver = CodeItemIndexKindResolver()

    def build(self, root: Path, items: list[CodeItem]) -> CodeGraph:
        by_id = {item.id: item for item in items}
        by_path: dict[str, list[CodeItem]] = {}
        for item in items:
            by_path.setdefault(item.path, []).append(item)

        edges: list[GraphEdge] = []
        edges.extend(self._same_file_edges(by_path))
        edges.extend(self._file_summary_edges(by_path))
        edges.extend(self._documentation_edges(by_path))
        edges.extend(self._documentation_path_reference_edges(by_path))
        edges.extend(self._import_edges(root, by_path))
        if self.reference_edges_enabled:
            edges.extend(self._reference_edges(items))
        if self.ast_enabled:
            edges.extend(GraphContainmentBuilder().build(by_path))
            if self.call_edges_enabled:
                edges.extend(PythonAstCallGraphBuilder().build(root, by_path))
        return CodeGraph(items=by_id, edges=self._dedupe_edges(edges))

    def _same_file_edges(self, by_path: dict[str, list[CodeItem]]) -> list[GraphEdge]:
        edges: list[GraphEdge] = []
        for chunks in by_path.values():
            sorted_chunks = sorted(
                [item for item in chunks if item.start_line is not None],
                key=lambda item: (item.start_line or 0, item.end_line or 0, item.id),
            )
            for left, right in itertools.pairwise(sorted_chunks):
                edges.append(GraphEdge(source=left.id, target=right.id, kind=EdgeKind.SAME_FILE_NEXT.value, weight=0.6))
        return edges

    def _documentation_edges(self, by_path: dict[str, list[CodeItem]]) -> list[GraphEdge]:
        edges: list[GraphEdge] = []
        for items in by_path.values():
            doc_chunks = self._items_by_index_kind(items, CodeItemIndexKind.DOC_CHUNK)
            if not doc_chunks:
                continue
            for summary in self._items_by_index_kind(items, CodeItemIndexKind.DOC_SUMMARY):
                for chunk in doc_chunks[:80]:
                    edges.append(
                        GraphEdge(source=summary.id, target=chunk.id, kind=EdgeKind.SUMMARIZES.value, weight=0.75)
                    )
            for manifest in self._items_by_index_kind(items, CodeItemIndexKind.DOC_MANIFEST):
                for chunk in doc_chunks[:80]:
                    edges.append(
                        GraphEdge(source=manifest.id, target=chunk.id, kind=EdgeKind.SUMMARIZES.value, weight=0.55)
                    )
        return edges

    def _documentation_path_reference_edges(self, by_path: dict[str, list[CodeItem]]) -> list[GraphEdge]:
        known_paths = set(by_path)
        edges: list[GraphEdge] = []
        for source_path, items in by_path.items():
            doc_items = [item for item in items if self._is_documentation_item(item)]
            if not doc_items:
                continue
            referenced_paths = self._referenced_paths(source_path, doc_items, known_paths)
            targets = [self._path_representative(by_path[path]) for path in referenced_paths]
            for source in doc_items:
                for target in targets[:24]:
                    if source.id == target.id:
                        continue
                    edges.append(
                        GraphEdge(source=source.id, target=target.id, kind=EdgeKind.REFERENCES.value, weight=0.85)
                    )
        return edges

    def _file_summary_edges(self, by_path: dict[str, list[CodeItem]]) -> list[GraphEdge]:
        edges: list[GraphEdge] = []
        for items in by_path.values():
            summaries = [item for item in items if self.index_kind_resolver.resolve(item) == CodeItemIndexKind.FILE_SUMMARY]
            if not summaries:
                continue
            summary = sorted(summaries, key=lambda item: item.id)[0]
            related = [item for item in items if item.id != summary.id]
            related.sort(key=lambda item: (item.start_line is None, item.start_line or 0, item.id))
            for item in related[:80]:
                edges.append(GraphEdge(source=summary.id, target=item.id, kind=EdgeKind.SUMMARIZES.value, weight=0.7))
        return edges

    def _import_edges(self, root: Path, by_path: dict[str, list[CodeItem]]) -> list[GraphEdge]:
        edges: list[GraphEdge] = []
        known_paths = set(by_path)
        jvm_index = self._jvm_class_index(known_paths)
        for path, chunks in by_path.items():
            imports = self._imports_for_file(root, path, jvm_index)
            target_paths = [target for target in imports if target in known_paths][:IMPORT_TARGETS_PER_FILE]
            target_items = [self._path_representative(by_path[target_path]) for target_path in target_paths]
            for source in chunks:
                for target in target_items:
                    edges.append(GraphEdge(source=source.id, target=target.id, kind=EdgeKind.IMPORTS.value, weight=0.8))
        return edges

    def _path_representative(self, items: list[CodeItem]) -> CodeItem:
        sorted_items = sorted(items, key=lambda item: (self._symbol_name(item) != "", item.start_line or 0, item.id))
        return sorted_items[0]

    def _items_by_index_kind(self, items: list[CodeItem], index_kind: str) -> list[CodeItem]:
        return [item for item in items if self.index_kind_resolver.resolve(item) == index_kind]

    def _is_documentation_item(self, item: CodeItem) -> bool:
        return self.index_kind_resolver.resolve(item) in DOCUMENTATION_INDEX_KINDS

    def _referenced_paths(
        self,
        source_path: str,
        doc_items: list[CodeItem],
        known_paths: set[str],
    ) -> list[str]:
        references: list[str] = []
        for item in doc_items:
            references.extend(MARKDOWN_LINK_RE.findall(item.content))
            references.extend(BACKTICK_PATH_RE.findall(item.content))
            references.extend(ARROW_PATH_RE.findall(item.content))
        resolved: list[str] = []
        for reference in references:
            normalized = self._normalize_doc_reference(source_path, reference)
            if normalized in known_paths and normalized != source_path:
                resolved.append(normalized)
        return list(dict.fromkeys(resolved))

    def _normalize_doc_reference(self, source_path: str, reference: str) -> str:
        reference = reference.strip()
        if not reference or "://" in reference or reference.startswith("#"):
            return ""
        reference = reference.split("#", 1)[0].split("?", 1)[0].strip()
        if reference.startswith("/"):
            return Path(reference.lstrip("/")).as_posix()
        return (Path(source_path).parent / reference).as_posix()

    def _imports_for_file(
        self, root: Path, rel_path: str, jvm_index: dict[str, list[str]] | None = None
    ) -> set[str]:
        path = root / rel_path
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return set()
        suffix = path.suffix.lower()
        if suffix == ".py":
            return self._python_imports(rel_path, text)
        if suffix in {".ts", ".tsx", ".js", ".jsx"}:
            return self._ts_imports(rel_path, text)
        if suffix in JVM_SUFFIXES:
            return self._jvm_imports(text, jvm_index or {})
        return set()

    def _jvm_class_index(self, known_paths: set[str]) -> dict[str, list[str]]:
        """Simple class name -> repository paths that could define it.

        A JVM import names a package, not a file, and the package root is not recoverable
        from the layout (``platform/util/src/com/intellij/util/Foo.java`` holds package
        ``com.intellij.util``), so resolution runs backwards: look the class name up, then
        keep only candidates whose path tail matches the imported package.
        """
        index: dict[str, list[str]] = {}
        for path in known_paths:
            if not path.endswith(JVM_SUFFIXES):
                continue
            stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            index.setdefault(stem, []).append(path)
        return index

    def _jvm_imports(self, text: str, jvm_index: dict[str, list[str]]) -> set[str]:
        targets: set[str] = set()
        for dotted in JVM_IMPORT_RE.findall(text):
            targets.update(self._resolve_jvm_import(dotted, jvm_index))
        return targets

    def _resolve_jvm_import(self, dotted: str, jvm_index: dict[str, list[str]]) -> set[str]:
        """Resolve one ``import`` statement to the files it could name.

        Walks the capitalised segments from right to left so that a static member import
        (``a.b.StringUtil.isEmpty``) and a nested class (``a.b.Foo.Bar``) both fall back to
        the enclosing top-level class. Wildcard imports carry no class name and are skipped
        rather than expanded to a whole package.
        """
        segments = dotted.split(".")
        for position in range(len(segments) - 1, -1, -1):
            if not segments[position][:1].isupper():
                continue
            package_path = "/".join(segments[: position + 1])
            resolved = {
                candidate
                for candidate in jvm_index.get(segments[position], ())
                if self._path_holds_package(candidate, package_path)
            }
            if resolved:
                return resolved
        return set()

    @staticmethod
    def _path_holds_package(candidate: str, package_path: str) -> bool:
        without_suffix = candidate.rsplit(".", 1)[0]
        return without_suffix == package_path or without_suffix.endswith("/" + package_path)

    def _python_imports(self, rel_path: str, text: str) -> set[str]:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
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
        max_edges = len(items) * REFERENCE_EDGE_FACTOR
        for source in items:
            if len(edges) >= max_edges:
                break
            source_edges = 0
            tokens = self._reference_tokens(source)
            for name in tokens.intersection(by_name):
                for target in by_name[name]:
                    if source.id == target.id:
                        continue
                    edges.append(
                        GraphEdge(source=source.id, target=target.id, kind=EdgeKind.REFERENCES.value, weight=0.7)
                    )
                    source_edges += 1
                    break
                if source_edges >= REFERENCE_EDGES_PER_SOURCE or len(edges) >= max_edges:
                    break
        return edges

    def _reference_tokens(self, item: CodeItem) -> set[str]:
        tokens: set[str] = set()
        text = f"{item.title}\n{item.content}"
        for index, match in enumerate(IDENTIFIER_RE.finditer(text)):
            if index >= REFERENCE_TOKEN_LIMIT:
                break
            tokens.add(match.group(0))
        return tokens

    def _symbol_name(self, item: CodeItem) -> str:
        metadata_symbol = item.metadata.get("symbol") if isinstance(item.metadata, dict) else None
        if metadata_symbol:
            return str(metadata_symbol).split(".")[-1]
        if self.index_kind_resolver.resolve(item) in NON_SYMBOL_INDEX_KINDS:
            return ""
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
