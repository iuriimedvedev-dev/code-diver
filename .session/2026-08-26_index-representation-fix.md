# Index Representation Fix — Root Cause of WHERE-79 Failure

## Root Cause Discovered

After manually inspecting WHERE-79 gold files, the root cause of poor WHERE performance is now clear:

**The dense embedding budget was consumed by boilerplate, not semantic content.**

For every file, the "head" section of the file summary included:
1. `// Copyright 2000-2026 JetBrains s.r.o. and contributors...`
2. `@file:Suppress(...)`
3. `package com.intellij...`
4. `import com.intellij.xxx...`
5. `import com.intellij.xxx...`
6. ... (12 more imports)

Result: the embedding vector encoded "JetBrains, copyright, package, import" — NOT the actual class purpose.

## What Was Fixed

### 1. FileSummaryItemBuilder._head_section (H-53+)
Added `_skip_boilerplate()` that skips:
- License/copyright headers (`// Copyright`, `/*`, `*`)
- `package` declarations
- `@file:` annotations
- `import` statements (including Java `;` suffix)

Now captures: class declarations, KDoc/Javadoc, annotations, field/method signatures.

**BEFORE** (ProjectManagerImpl.kt head):
```
- // Copyright 2000-2026 JetBrains s.r.o. and contributors...
- @file:Suppress("ReplacePutWithAssignment", "OVERRIDE_DEPRECATION")
- package com.intellij.openapi.project.impl
- import com.intellij.CommonBundle
- import com.intellij.codeWithMe.ClientId
- ...
```

**AFTER**:
```
- @Internal
- open class ProjectManagerImpl : ProjectManagerEx(), Disposable {
- companion object {
- private val tracer by lazy { TelemetryManager.getInstance().getTracer(Scope("projectLifecycle")) }
- @TestOnly
- @JvmStatic
- fun isLight(project: Project): Boolean = project is ProjectEx && project.isLight
- internal suspend fun dispatchEarlyNotifications() {
- ...
```

### 2. Cross-encoder document builder (H-55)
`_extract_meaningful_head()` now skips the same boilerplate for CE documents. The old H-55 got 0.243 recall because CE was fed:
```
path: .../InspectionEngine.java
content:
// Copyright 2000-2026 JetBrains s.r.o. and contributors...
package com.intellij.codeInspection;
import com.intellij.analysis.AnalysisScope;
import ...
```

Now the CE sees:
```
path: .../InspectionEngine.java
content:
public final class InspectionEngine {
private static final Logger LOG = ...
public static void runInspectionOn(...)
```

### 3. Embedding text preparer (pre-existing bug)
Fallback `text[:max_input_chars // 3]` → `text[:max_input_chars]`.
The `// 3` was discarding 2/3 of the character budget on the fallback path.

## Sample Verification (10 WHERE gold files)

| Query | File | Before head | After head |
|---|---|---|---|
| "where is project opening orchestrated" | ProjectManagerImpl.kt | Copyright, package, imports | `@Internal open class ProjectManagerImpl : ProjectManagerEx(), Disposable` |
| "where are local inspections executed" | InspectionEngine.java | Copyright, package, imports | `public final class InspectionEngine {` |
| "where do find usages resolve" | FindUsagesManager.java | Copyright, package, imports | KDoc: "Manages find usages..." + `public final class FindUsagesManager` |
| "where is rename refactoring processed" | RenameProcessor.java | Copyright, package, imports | `public class RenameProcessor extends BaseRefactoringProcessor` |
| "where is the PSI manager" | PsiManagerImpl.java | Copyright, package, imports | `public final class PsiManagerImpl extends PsiManagerEx implements Disposable` |
| "where are caret movements handled" | CaretModelImpl.java | Copyright, package, imports | `public final class CaretModelImpl implements CaretModel, CaretMovementSource` |
| "where are write commands executed" | CommandProcessorImpl.java | Copyright, package, imports | `public final class CommandProcessorImpl extends CoreCommandProcessor` |
| "where is daemon code analysis" | DaemonCodeAnalyzerImpl.java | Copyright, package, imports | `public final class DaemonCodeAnalyzerImpl extends DaemonCodeAnalyzerEx` |
| "where is the gradle importer" | GradleProjectImporter.java | Copyright, package, imports | `public final class GradleProjectImporter extends ProjectExtensionImporter` |
| "where is the file editor manager" | FileEditorManagerImpl.java | Copyright, package, imports | `public final class FileEditorManagerImpl extends FileEditorManager` |

## Tests
All 1154 unit tests pass (3 skipped).

## What's Next
1. **H-53 reindex**: Run `intellij-h52-summary-head-first.yml` with the fixed head section. This is the most impactful single action.
2. **H-55 re-run**: With the fixed CE document builder, re-run WHERE-79 eval. The old 0.243 was a measurement artifact.
3. **H-58 re-run**: The prose fusion router may work better with a meaningful dense signal.
4. **Chunk-level indexing**: jbcontext searches at the chunk level (methods, classes), giving it denser semantic signal. Consider adding method-level search as a separate mode.