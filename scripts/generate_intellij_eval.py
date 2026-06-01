from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from code_diver.services import CodeSymbolExtractor


@dataclass(slots=True)
class EvalCaseDraft:
    case_id: str
    query: str
    expected: list[str]
    priority: int


class IntellijEvalGenerator:
    SOURCE_SUFFIXES = {".java", ".kt", ".kts"}
    CONFIG_SUFFIXES = {".xml", ".properties", ".gradle", ".kts", ".json", ".yaml", ".yml"}
    SKIP_PARTS = {
        ".git",
        ".gradle",
        ".idea",
        "build",
        "dist",
        "generated",
        "gen",
        "out",
        "target",
        "node_modules",
        "test",
        "tests",
        "test-data",
        "test-fixtures",
        "testData",
        "testdata",
    }
    ROOT_AREAS = [
        "platform",
        "plugins",
        "java",
        "jvm",
        "python",
        "xml",
        "json",
        "jps",
        "uast",
        "tools",
        "build",
    ]

    def __init__(self, root: Path, limit: int):
        self.root = root.resolve()
        self.limit = limit
        self.symbol_extractor = CodeSymbolExtractor()
        self._candidate_file_cache: list[Path] | None = None

    def build(self) -> list[EvalCaseDraft]:
        groups = [
            self._intent_cases(),
            self._source_symbol_cases(),
            self._config_cases(),
            self._path_intent_cases(),
        ]
        drafts = self._round_robin(groups)
        return self._dedupe(drafts)[: self.limit]

    def _intent_cases(self) -> list[EvalCaseDraft]:
        specs = [
            ("where-indexing", "where is IDE file indexing and dumb mode handled", ["platform/lang-impl/src/com/intellij/openapi/project/DumbServiceImpl.java"]),
            ("where-vfs-refresh", "where does virtual file system refresh happen", ["platform/platform-impl/src/com/intellij/openapi/vfs/newvfs/RefreshQueueImpl.java"]),
            ("where-action-system", "where are IDE actions registered and dispatched", ["platform/platform-impl/src/com/intellij/openapi/actionSystem/impl/ActionManagerImpl.java"]),
            ("where-project-open", "where is project opening orchestrated", ["platform/platform-impl/src/com/intellij/openapi/project/impl/ProjectManagerImpl.kt"]),
            ("where-settings-storage", "where are application settings components persisted", ["platform/platform-impl/src/com/intellij/configurationStore/ComponentStoreImpl.kt"]),
            ("where-message-bus", "where is application message bus implemented", ["platform/core-impl/src/com/intellij/util/messages/impl/MessageBusImpl.java"]),
            ("where-extension-points", "where are extension points registered and resolved", ["platform/extensions/src/com/intellij/openapi/extensions/impl/ExtensionsAreaImpl.java"]),
            ("where-inspections", "where are local inspections executed", ["platform/analysis-impl/src/com/intellij/codeInspection/InspectionEngine.java"]),
            ("where-code-completion", "where does code completion contributor execution happen", ["platform/lang-impl/src/com/intellij/codeInsight/completion/CompletionServiceImpl.java"]),
            ("where-find-usages", "where does find usages search run", ["platform/lang-impl/src/com/intellij/find/findUsages/FindUsagesManager.java"]),
            ("where-refactoring", "where is rename refactoring coordinated", ["platform/lang-impl/src/com/intellij/refactoring/rename/RenameProcessor.java"]),
            ("where-psi-manager", "where is PSI manager implemented", ["platform/core-impl/src/com/intellij/psi/impl/PsiManagerImpl.java"]),
            ("where-editor-caret", "where are editor caret movements handled", ["platform/platform-impl/src/com/intellij/openapi/editor/impl/CaretModelImpl.java"]),
            ("where-command-processor", "where are write commands executed and undone", ["platform/platform-impl/src/com/intellij/openapi/command/impl/CommandProcessorImpl.java"]),
            ("where-daemon-analyzer", "where is background code highlighting daemon implemented", ["platform/lang-impl/src/com/intellij/codeInsight/daemon/impl/DaemonCodeAnalyzerImpl.java"]),
            ("where-file-type", "where are file types detected and registered", ["platform/platform-impl/src/com/intellij/openapi/fileTypes/impl/FileTypeManagerImpl.java"]),
            ("where-plugin-loading", "where are IDE plugins loaded and initialized", ["platform/core-impl/src/com/intellij/ide/plugins/PluginManagerCore.java"]),
            ("where-tool-window", "where are tool windows registered", ["platform/platform-impl/src/com/intellij/openapi/wm/impl/ToolWindowManagerImpl.kt"]),
            ("where-run-configurations", "where are run configurations managed", ["platform/execution-impl/src/com/intellij/execution/impl/RunManagerImpl.kt"]),
            ("where-debugger-session", "where is debugger session lifecycle handled", ["java/debugger/impl/src/com/intellij/debugger/impl/DebuggerSession.java"]),
            ("where-gradle-import", "where does Gradle project import happen", ["plugins/gradle/src/org/jetbrains/plugins/gradle/service/project/GradleProjectResolver.java"]),
            ("where-maven-import", "where does Maven project import happen", ["plugins/maven/src/main/java/org/jetbrains/idea/maven/project/MavenProjectsManager.java"]),
            ("where-git-commit", "where is git commit workflow implemented", ["plugins/git4idea/src/git4idea/commit/GitCommitWorkflowHandler.kt"]),
            ("where-terminal", "where is embedded terminal session created", ["plugins/terminal/src/org/jetbrains/plugins/terminal/TerminalToolWindowFactory.kt"]),
            ("where-python-sdk", "where is Python SDK detection configured", ["python/python-sdk/src/com/jetbrains/python/sdk/PythonSdkUtil.java"]),
            ("where-kotlin-plugin", "where is Kotlin plugin module configured", ["plugins/kotlin/plugin.xml"]),
        ]
        return [
            self._case(case_id, query, [path for path in expected if (self.root / path).exists()], 0)
            for case_id, query, expected in specs
            if any((self.root / path).exists() for path in expected)
        ]

    def _source_symbol_cases(self) -> list[EvalCaseDraft]:
        by_area: dict[str, list[EvalCaseDraft]] = defaultdict(list)
        for path in self._source_files():
            rel_path = path.relative_to(self.root).as_posix()
            text = path.read_text(encoding="utf-8", errors="replace")
            area = self._area_key(rel_path)
            for symbol in self.symbol_extractor.extract(rel_path, text)[:12]:
                words = " ".join(self._words(symbol.name))
                if not words:
                    continue
                if symbol.kind in {"class", "interface", "object", "enum", "record", "annotation"}:
                    query = f"where is {words} implemented in the IDE codebase"
                    priority = 2
                else:
                    query = f"where does the IDE {self._verb_for_symbol(symbol.name)} {words}"
                    priority = 3
                by_area[area].append(self._case(f"symbol-{rel_path}-{symbol.name}", query, [rel_path], priority))
        return self._round_robin([values for _, values in sorted(by_area.items())])

    def _config_cases(self) -> list[EvalCaseDraft]:
        drafts: list[EvalCaseDraft] = []
        for path in self._candidate_files():
            if path.suffix not in self.CONFIG_SUFFIXES:
                continue
            rel_path = path.relative_to(self.root).as_posix()
            words = " ".join(self._words(f"{path.parent.name} {path.stem}"))
            if not words:
                continue
            if path.name == "plugin.xml" or "resources" in path.parts:
                query = f"where is the plugin descriptor or extension configuration for {words}"
            elif "gradle" in path.name:
                query = f"where is the Gradle build configuration for {words}"
            else:
                query = f"where is configuration for {words}"
            drafts.append(self._case(f"config-{rel_path}", query, [rel_path], 1))
        return drafts

    def _path_intent_cases(self) -> list[EvalCaseDraft]:
        by_area: dict[str, list[EvalCaseDraft]] = defaultdict(list)
        for path in self._source_files():
            rel_path = path.relative_to(self.root).as_posix()
            stem_words = " ".join(self._words(path.stem))
            parent_words = " ".join(self._words(path.parent.name))
            if not stem_words:
                continue
            query = f"where is {parent_words} {stem_words} behavior implemented".strip()
            by_area[self._area_key(rel_path)].append(self._case(f"path-{rel_path}", query, [rel_path], 4))
        return self._round_robin([values for _, values in sorted(by_area.items())])

    def _source_files(self) -> list[Path]:
        return [path for path in self._candidate_files() if path.suffix in self.SOURCE_SUFFIXES]

    def _candidate_files(self) -> list[Path]:
        if self._candidate_file_cache is not None:
            return self._candidate_file_cache
        paths: list[Path] = []
        for area in self.ROOT_AREAS:
            area_path = self.root / area
            if not area_path.exists():
                continue
            for path in sorted(area_path.rglob("*")):
                if path.is_file() and not self._skip_path(path):
                    paths.append(path)
        self._candidate_file_cache = paths
        return paths

    def _skip_path(self, path: Path) -> bool:
        rel_parts = path.relative_to(self.root).parts
        if any(part in self.SKIP_PARTS for part in rel_parts):
            return True
        if path.stat().st_size > 1_000_000:
            return True
        return path.suffix not in self.SOURCE_SUFFIXES | self.CONFIG_SUFFIXES | {".md"}

    def _round_robin(self, groups: list[list[EvalCaseDraft]]) -> list[EvalCaseDraft]:
        drafts: list[EvalCaseDraft] = []
        active = [list(group) for group in groups if group]
        while active and len(drafts) < self.limit * 3:
            next_active: list[list[EvalCaseDraft]] = []
            for group in active:
                if not group:
                    continue
                drafts.append(group.pop(0))
                if group:
                    next_active.append(group)
            active = next_active
        return drafts

    def _dedupe(self, drafts: list[EvalCaseDraft]) -> list[EvalCaseDraft]:
        seen: set[str] = set()
        deduped: list[EvalCaseDraft] = []
        for draft in drafts:
            key = draft.case_id
            if key in seen or not draft.expected or not all((self.root / expected).exists() for expected in draft.expected):
                continue
            seen.add(key)
            deduped.append(draft)
        return deduped

    def _case(self, case_id: str, query: str, expected: list[str], priority: int) -> EvalCaseDraft:
        clean_id = re.sub(r"[^a-zA-Z0-9_.-]+", "-", case_id).strip("-").lower()
        clean_query = re.sub(r"\s+", " ", query).strip()
        return EvalCaseDraft(clean_id, clean_query, expected, priority)

    def _area_key(self, rel_path: str) -> str:
        parts = rel_path.split("/")
        return "/".join(parts[: min(3, len(parts))])

    def _verb_for_symbol(self, name: str) -> str:
        words = self._words(name)
        if not words:
            return "handle"
        first = words[0]
        if first in {"get", "set", "create", "build", "find", "load", "save", "run", "execute", "update", "refresh"}:
            return first
        if first.endswith("ed") or first.endswith("ing"):
            return "handle"
        return "handle"

    def _words(self, text: str) -> list[str]:
        spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
        return [word.lower() for word in re.split(r"[^A-Za-z0-9]+", spaced) if len(word) > 1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("../intellij-community"))
    parser.add_argument("--output", type=Path, default=Path("datasets/intellij_eval_1000.jsonl"))
    parser.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()
    cases = IntellijEvalGenerator(args.root, args.limit).build()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(
            json.dumps({"id": case.case_id, "query": case.query, "expected": case.expected}) + "\n"
            for case in cases
        ),
        encoding="utf-8",
    )
    print(f"wrote {len(cases)} cases -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
