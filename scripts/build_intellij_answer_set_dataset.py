from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


EXTRA_EXPECTED: dict[str, list[str]] = {
    "where-project-open": [
        "platform/ide-core-impl/src/com/intellij/ide/impl/OpenProjectTask.kt",
        "platform/platform-impl/src/com/intellij/ide/impl/ProjectUtil.kt",
        "platform/ide-core/src/com/intellij/openapi/project/ProjectUtil.kt",
    ],
    "where-inspections": [
        "platform/lang-impl/src/com/intellij/codeInsight/daemon/impl/LocalInspectionsPass.java",
        "platform/lang-impl/src/com/intellij/codeInsight/daemon/impl/InspectionRunner.java",
        "platform/lang-impl/src/com/intellij/codeInsight/daemon/impl/LocalInspectionsPassFactory.java",
    ],
    "where-editor-caret": [
        "platform/platform-impl/src/com/intellij/openapi/editor/actions/MoveCaretUpOrDownHandler.java",
        "platform/platform-impl/src/com/intellij/openapi/editor/actions/MoveCaretLeftOrRightHandler.java",
        "platform/platform-impl/src/com/intellij/openapi/editor/impl/EditorCaretMoveProcessor.kt",
    ],
    "where-command-processor": [
        "platform/core-api/src/com/intellij/openapi/command/WriteCommandAction.java",
        "platform/platform-impl/src/com/intellij/openapi/command/impl/UndoManagerImpl.java",
        "platform/platform-impl/src/com/intellij/openapi/command/impl/Undo.java",
        "platform/platform-impl/src/com/intellij/openapi/command/impl/UndoRedo.java",
        "platform/core-api/src/com/intellij/openapi/command/coroutines.kt",
    ],
    "where-daemon-analyzer": [
        "platform/analysis-impl/src/com/intellij/codeInsight/daemon/impl/TextEditorBackgroundHighlighter.java",
        "platform/analysis-impl/src/com/intellij/codeInsight/daemon/impl/BackgroundUpdateHighlightersUtil.java",
        "platform/lang-impl/src/com/intellij/codeInsight/highlighting/BackgroundHighlighter.kt",
    ],
    "where-file-type": [
        "platform/platform-impl/src/com/intellij/openapi/fileTypes/impl/FileTypeDetectionService.java",
        "platform/core-api/src/com/intellij/openapi/fileTypes/FileTypeRegistry.java",
        "platform/ide-core/src/com/intellij/ide/highlighter/FileTypeRegistrar.java",
    ],
    "where-run-configurations": [
        "platform/execution-impl/src/com/intellij/execution/impl/RunConfigurationSchemeManager.kt",
        "platform/execution-impl/src/com/intellij/execution/impl/RunConfigurationStorageUi.java",
        "platform/execution-impl/src/com/intellij/execution/RunManagerConfig.java",
        "platform/execution-impl/src/com/intellij/execution/actions/ChooseRunConfigurationManager.java",
        "platform/execution/src/com/intellij/execution/configurations/RunConfigurationsSettings.java",
    ],
    "where-gradle-import": [
        "plugins/gradle/src/org/jetbrains/plugins/gradle/service/project/open/GradleProjectImportUtil.kt",
        "plugins/gradle/java/src/service/project/wizard/GradleProjectImportProvider.java",
        "plugins/gradle/java/src/service/project/wizard/GradleProjectImportBuilder.java",
        "plugins/gradle/java/src/service/project/wizard/JavaGradleProjectImportBuilder.kt",
        "plugins/gradle/java/src/service/project/wizard/JavaGradleProjectImportProvider.kt",
    ],
    "where-maven-import": [
        "plugins/maven/src/main/java/org/jetbrains/idea/maven/wizards/MavenProjectImportProvider.java",
        "plugins/maven/src/main/java/org/jetbrains/idea/maven/importing/MavenProjectImporter.kt",
        "plugins/maven/src/main/java/org/jetbrains/idea/maven/importing/MavenProjectImporterUtil.kt",
        "plugins/maven/src/main/java/org/jetbrains/idea/maven/importing/MavenImporter.java",
    ],
    "path-java-debugger-memory-agent-src-com-intellij-memory-agent-package-info.java": [
        "glob:**/agent/**/package-info.java",
    ],
    "path-java-java-bookmarks-src-com-intellij-java-bookmarks-packagebookmark.kt": [
        "platform/bookmarks/src/com/intellij/ide/bookmarks/BookmarkManager.java",
        "platform/bookmarks/src/com/intellij/ide/bookmark/BookmarksManagerImpl.kt",
        "platform/lang-api/src/com/intellij/ide/bookmark/BookmarksManager.java",
        "platform/bookmarks/src/com/intellij/ide/bookmarks/Bookmark.java",
    ],
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("datasets/intellij_eval_1000.multi_expected.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("datasets/intellij_eval_1000.answer_sets.jsonl"))
    args = parser.parse_args()

    rows = [json.loads(line) for line in args.input.read_text(encoding="utf-8").splitlines() if line.strip()]
    for row in rows:
        expected = list(row.get("expected") or [])
        if "plugin descriptor or extension configuration" in str(row.get("query", "")) and "meta inf plugin" in str(row.get("query", "")):
            expected.append("glob:**/resources/META-INF/plugin.xml")
        if "metadata storage impl" in str(row.get("query", "")):
            expected.append("glob:**/MetadataStorageImpl.kt")
        expected.extend(EXTRA_EXPECTED.get(str(row.get("id")), []))
        row["expected"] = _unique(expected)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    print(f"wrote {len(rows)} cases -> {args.output}")
    return 0


def _unique(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    rows: list[str] = []
    for value in values:
        text = str(value)
        if text in seen:
            continue
        seen.add(text)
        rows.append(text)
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
