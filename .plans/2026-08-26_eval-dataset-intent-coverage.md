# Eval Dataset Intent Coverage — Verification and Expansion Plan

Date: 2026-08-26
Status: Investigation complete (Task 1), expansion plan drafted (Task 2), no dataset files
written yet — this is a plan, not the deliverable dataset.
Related: `.session/2026-08-25_jbcontext-comparison-report.md` (the comparison this concern was
raised against, §4/§6/§8 in particular — the "sibling-family cannibalization" finding is the
direct motivation for the near-duplicate-discrimination design in §3 below).

## 0. Verdict up front

The concern raised — that the dataset is heavily skewed toward "where is X located" queries
plus mechanically-generated categories, with almost no multi-hop, comparative,
exact-symbol/error-string, near-duplicate-discrimination, or usage-pattern ("how do I")
queries — is **confirmed, not refuted**, by direct inspection of the generator and the data.
Every one of the five explicitly-checked-for query types came back at **exactly zero** real
occurrences in the current 1125-case corpus (1065 + 60 multi-file). This is a genuine,
material gap, not an exaggerated claim.

## 1. Task 1 — Verified composition of the current dataset

### 1.1 Method

- Read `scripts/generate_intellij_eval.py` end to end (176 lines, `IntellijEvalGenerator`
  class).
- Loaded and programmatically counted every row (not sampled) in
  `datasets/intellij_eval_1000.answer_sets.jsonl` (1065 rows) and
  `datasets/intellij_eval_multifile.jsonl` (60 rows). `intellij_eval_where_only.jsonl` (79
  rows) is a strict subset of the 1065-row file's `where-*` cases, not an independent set.
- Random-sampled 20 `symbol-*`, 15 `config-*`, 15 `path-*` queries (`random.seed` fixed for
  reproducibility) and read all 79 `where-*` queries and all 60 `multi-*` queries in full
  (small enough to read exhaustively rather than sample).
- Grepped the full text of both files for the five specifically-named-absent query shapes,
  using multiple keyword patterns per shape (see 1.3), not a single narrow regex.

### 1.2 Exact counts

| Source file | Category (id prefix) | Count | Generation method (from generator source) |
|---|---|---|---|
| `intellij_eval_1000.answer_sets.jsonl` | `symbol-*` | 329 | Mechanical: extracts class/method/field symbol names via `CodeSymbolExtractor`, tokenizes camelCase into words, wraps in template `"where is {words} implemented in the IDE codebase"` (classes) or `"where does the IDE {verb} {words}"` (methods/fields). |
| same | `config-*` | 329 | Mechanical: for every `.xml`/`.properties`/`.gradle`/`.json`/`.yaml` file, tokenizes `{parent-dir} {filename-stem}` into a fixed template (`"where is the plugin descriptor or extension configuration for {words}"` / `"where is the Gradle build configuration for {words}"` / `"where is configuration for {words}"`). |
| same | `path-*` | 328 | Mechanical: tokenizes `{parent-dir-name} {file-stem}` into `"where is {parent} {stem} behavior implemented"`. |
| same | `where-*` | 79 | Hand-written: 26 originally hard-coded `(case_id, query, expected_path)` tuples in `_intent_cases()`, expanded to 79 this-session (per the comparison report) by hand-writing realistic developer questions and file-verifying paths. |
| `intellij_eval_multifile.jsonl` | `multi-*` | 60 | Hand-written this session: "which files implement X end-to-end" queries requiring 2-4 correct files, mean 2.47 files/case. |
| **Total (1065 + 60)** | | **1125** | |

Composition: **986/1125 (87.6%)** of all cases are the three mechanical categories
(`symbol`+`config`+`path`). **79/1125 (7.0%)** are hand-written single-file `where-*` queries.
**60/1125 (5.3%)** are hand-written multi-file `multi-*` queries. There is no category outside
these three id families in either file — confirmed by exhaustive `Counter()` over every row's
`id.split('-')[0]`.

Spot-check of id-prefix-to-actual-query-style fidelity: 20/20 `symbol-*`, 15/15 `config-*`,
15/15 `path-*` samples matched their expected template exactly (verified by reading the raw
query strings, e.g. `symbol-...-actionmanager` → `"where is action manager implemented in the
IDE codebase"`; `config-...` → `"where is the plugin descriptor or extension configuration for
resources intellij platform collaboration tools"`). No mislabeled prefixes found.

### 1.3 Lexical vs. genuine-reasoning breakdown

Question asked: how many of the 1125 cases require reasoning beyond "does this query's tokens
appear in this file's path/symbol/name" vs. how many are near-exact lexical recovery of the
target file's own identifiers?

- **986 (87.6%)** — `symbol`/`config`/`path` — the query is **built directly from tokenizing
  the target file's own class name, filename, or parent directory name**. E.g. query `"where is
  driver illegal state exception implemented in the IDE codebase"` for target
  `DriverIllegalStateException.kt` — the query literally is the file's own symbol name with
  spaces inserted. These are lexical-recovery tasks, not semantic/intent tasks, by construction.
- **79 (7.0%)** (`where-*`) — hand-written paraphrases ("where is rename refactoring
  coordinated" → `RenameProcessor.java`) — genuinely require some domain knowledge (the query
  doesn't literally contain "Processor" or "Rename" tokens verbatim in every case), but every
  single one of the 79 is still a **single-subsystem locate query** ("where is/are/does X"), not
  multi-hop, comparative, or usage-pattern.
- **60 (5.3%)** (`multi-*`) — "which files implement X end-to-end" — requires the most
  architectural understanding of any category (knowing that a feature spans a Handler + Dialog +
  Processor + extension point, for instance) but is still fundamentally a **location query**
  ("which files are involved"), not a data-flow, comparative, or how-to query.

**Total requiring any domain/semantic reasoning beyond pure lexical recovery: 139/1125 (12.4%).
Zero of those 139 are multi-hop, comparative, exact-string-lookup, near-duplicate-discrimination,
or usage-pattern queries** — see 1.4.

### 1.4 Explicit check for the five claimed-near-absent query types

All five were checked with multiple grep patterns (not a single guess) across both dataset
files' full query text, then manually verified against the underlying generator code:

| Query type | Found? | Evidence |
|---|---|---|
| **Multi-hop** ("how is X's data used after Y processes it") | **Zero.** | Grepped for ` after `, ` once `, ` before `, ` then ` (temporal/causal connectives). The only hits were substring artifacts of class names containing "before"/"run" (e.g. `CompileStepBeforeRun.java` → query "where is compile step before run implemented" — this is a symbol-tokenization coincidence, not a multi-hop question; it does not ask what happens *after* something else runs). No query in either file describes a two-stage pipeline and asks about the second stage. |
| **Comparative** ("what's the difference between A and B") | **Zero true comparatives.** 7 near-misses. | Grepped for "differ", "difference", "versus", " vs ". Found 7 `multi-*` cases phrased `"where is the interface vs implementation split for X"` (e.g. `multi-bookmarks-api-impl`, `multi-git-repository-api-impl`). These use the word "vs" but ask for **both files as a location answer**, not for an explanation of behavioral/semantic differences — a correct response is "file A and file B", not "A does X while B does Y". No case asks the model to reason about *how* two structurally similar files differ in behavior. |
| **Exact-symbol / error-string lookup (grep-style)** | **Zero.** | Grepped for "exception", "error message", "stack trace", "threw"/"thrown". 9 hits, all of the form `"where is {ClassName}Exception implemented"` (e.g. `AlienFormFileException`, `VcsContentAnnotationExceptionFilter`) — these are `symbol-*`/`path-*` mechanical cases whose target happens to be a class named `*Exception`. None of them are queries built from an actual literal error message string, log message, or stack-trace fragment (which is what "grep-style lookup" means and is exactly the kind of query a developer pastes from a terminal/log). |
| **Near-duplicate discrimination** (multiple structurally-similar `*Impl`/`*Handler` siblings, only one is correct) | **Zero.** | No case in either file presents a query where 2+ near-identical sibling files exist in the same directory and only fine-grained semantic content of the query distinguishes the correct one from equally-plausible wrong siblings. The closest analog, the 7 "interface vs implementation split" `multi-*` cases, ask for **both** members of a 2-file pair (interface + impl) as the correct answer set — there is no case with 3+ siblings where 1 is correct and N-1 are structurally-identical distractors. |
| **"How do I implement X" (usage-pattern, not location)** | **Zero.** | Grepped for "how do i", "how to ", "how can i". Zero matches in either file. Every query in both files is phrased as a locate/identify question ("where is...", "which files implement...") — none ask "how do I add/extend/plug into X" (the usage/extension-point framing a developer would actually type when trying to *do* something in the codebase, as opposed to *find* something). |

## 2. Task 2 — Expansion plan

Target: 100-200 new hand-verified cases, one new dataset file per category (matching the
existing convention of `intellij_eval_multifile.jsonl` as a standalone file rather than merging
into the 1065-case file), all paths checked with `os.path.isfile`-equivalent verification
against the live `~/Work/intellij-community` checkout at commit
`693e76f0a37ade9509c9edcf505c446672c9c0b1` (same revision used in the jbcontext comparison).
Every path cited below as "verified" was checked in this session via a real `test -f` /
`find` / `grep` filesystem check against that checkout, not invented — the working commands are
shown inline for auditability.

### 2.1 Category: Near-duplicate discrimination — highest priority

This is the most direct test of the exact ranking weakness found in the jbcontext comparison
(§6 of the session report: "sibling-family cannibalization" — path/symbol scores tie across a
Handler/Dialog/Processor family, and the one semantically load-bearing word in the query doesn't
match any candidate's path/symbol tokens, so ties break arbitrarily instead of toward the
correct sibling).

- **Target count: 40-50 cases.**
- **Generation method: cannot be mechanically generated — must be hand-authored.** The whole
  point is that path/symbol lexical overlap is high across the distractor family, so any
  generation process that derives the query from the target file's own tokens (like `symbol-*`/
  `path-*`) would trivially defeat the test. Each case requires a human (or an LLM given the
  sibling file list and told to write a discriminating query) to: (1) find a real directory with
  3+ structurally similar `*Processor`/`*Handler`/`*Dialog` files, (2) read enough of each to
  know their actual distinct role, (3) write a query whose only correct match is one specific
  sibling, using semantic content (a verb, a distinguishing noun) that a naive lexical/path
  matcher would not privilege over the other siblings.
- **Verified example cases** (all paths confirmed to exist via `test -f` against the live
  checkout; sibling context confirmed by reading class declarations/methods):

  1. Query: *"which file performs the actual undo/redo execution of user commands, as opposed to
     the dialog that reports why an undo could not be performed"*
     Expected: `platform/platform-impl/src/com/intellij/openapi/command/impl/UndoManagerImpl.java`
     Distractor siblings in the same directory (`.../openapi/command/impl/`): `CannotUndoReportDialog.kt`
     (a `DialogWrapper` that only reports failure — `class CannotUndoReportDialog(... problemText ...) : DialogWrapper`),
     `DefaultUndoReportHandler.java`, `Undo.java`/`Redo.java` (thin action classes), `UndoRedo.java`.
     Verified: `UndoManagerImpl.java` declared `public class UndoManagerImpl extends UndoManager
     implements Disposable` (line 42) — the real stateful manager; `CannotUndoReportDialog.kt`
     confirmed to be UI-only (line 27-31, extends `DialogWrapper`).

  2. Query: *"which class does the actual extraction of a duplicated code fragment into a new
     method, not the diff preview shown before confirming"*
     Expected: `java/java-impl-refactorings/src/com/intellij/refactoring/extractMethod/ExtractMethodProcessor.java`
     Distractor siblings: `java/java-impl-refactorings/src/com/intellij/refactoring/extractMethod/preview/ExtractMethodPreviewManager.java`
     (confirmed `public final class ExtractMethodPreviewManager` with `ContentManager` field —
     UI-only), plus `ExtractMethodDialog.java`, `JavaDuplicatesExtractMethodProcessor.java` (a
     related but distinct subclass — a good "close but wrong" distractor for a stricter variant
     of this query).

  3. Query: *"which class in the rename refactoring pipeline actually rewrites each found usage
     occurrence to the new name, after usages have already been collected"*
     Expected: `platform/refactoring/src/com/intellij/refactoring/rename/RenameUtil.java`
     Distractor siblings: `platform/lang-impl/src/com/intellij/refactoring/rename/RenameProcessor.java`
     (orchestrates the whole refactoring — collects usages, shows the dialog, invokes
     `RenameUtil`, but does not itself do the per-usage rewrite), `RenamePsiElementProcessor.java`
     (an extension-point base class for customizing *how* a given element type is renamed, not a
     usage-rewriter). Verified: `RenameUtil.java` (`platform/refactoring/src/.../RenameUtil.java`,
     line 73 `public final class RenameUtil`) has `static void doRename(...)` (line 260) and
     `static void rename(UsageInfo info, ...)` (line 296) — the actual per-usage mutation methods.
     Note this doubles as a **multi-hop** example (2.2) since it requires knowing the two-stage
     pipeline.

  4. Query: *"which class actually finds usages and deletes the element for Safe Delete, versus
     the class that only shows the confirmation dialog"*
     Expected: `platform/lang-impl/src/com/intellij/refactoring/safeDelete/SafeDeleteProcessor.java`
     Distractor siblings (same directory): `SafeDeleteDialog.java` (UI confirmation only),
     `SafeDeleteHandler.java` (confirmed `public final class SafeDeleteHandler implements
     RefactoringActionHandler` with static `invoke(...)` entry points — the action-invocation
     glue, not the engine), `SafeDeleteProcessorDelegateBase.java` (extension-point base, not the
     concrete engine). Verified `SafeDeleteProcessor.java` (line 71) has both `findUsages()`
     (line 139, calls `delegate.findUsages(...)`) and `performRefactoring(UsageInfo[] usages)`
     (line 400) — confirms it does both stages, making it the correct single answer versus its
     three siblings.

  5. Query: *"which Java-specific class plugs into the generic Safe Delete engine as its
     language delegate, rather than the engine itself"*
     Expected: `java/java-impl-refactorings/src/com/intellij/refactoring/safeDelete/JavaSafeDeleteProcessor.java`
     Distractor: `platform/lang-impl/src/com/intellij/refactoring/safeDelete/SafeDeleteProcessor.java`
     (the generic, language-agnostic engine from example 4 — a *deliberately* strong distractor
     since "SafeDeleteProcessor" is a lexical substring of "JavaSafeDeleteProcessor"), and
     `java/java-impl-refactorings/src/com/intellij/refactoring/safeDelete/JavaSafeDeleteDelegateImpl.java`
     (a related but distinct delegate — verified to exist in the same directory listing).

  All five verified present via direct `test -f` checks in this session; class-role claims
  verified via `grep -n "class ... " -A3` / method-signature greps quoted above, not assumed
  from filenames alone.

- **Scale-up guidance**: repeat this pattern in other feature areas with a known
  Handler/Dialog/Processor/Delegate shape — confirmed available families include `inline/`
  (`InlineMethodProcessor.java`, `InlineConstantFieldProcessor.java`,
  `InlineToAnonymousClassProcessor.java`, `InlineObjectProcessor.java`,
  `InlineParameterExpressionProcessor.java` — 5+ siblings, verified via `find` in this session),
  `changeSignature/` (`ChangeSignatureProcessor.java`,
  `JavaChangeSignatureUsageProcessor.java`, `JavaChangeSignatureHandler.java` — verified present),
  and the `rename/` family more broadly (`RenamePsiFileProcessor.java` vs
  `RenamePsiElementProcessor.java` vs `RenameProcessor.java` — all three verified present, three-
  way discrimination). Each new case still requires a human to read the actual class role before
  writing the query — this cannot be templated away without reintroducing the lexical-shortcut
  problem this category exists to close.

### 2.2 Category: Multi-hop / data-flow queries

- **Target count: 20-30 cases.**
- **Generation method: hand-authored, but can be semi-guided.** A workable process: pick a
  `where-*` or `multi-*` case that already documents a 2+-stage pipeline (many of the existing
  hand-written queries implicitly describe one stage of a longer pipeline — e.g.
  "where-refactoring" → `RenameProcessor.java` — read the target file's own logic, identify the
  *next* stage it hands off to, and write a new query that asks specifically about that next
  stage instead of the stage already covered. This reuses existing domain research rather than
  starting from zero, but the query text and target-file selection still must be written and
  verified by hand — there's no structural signal (e.g. file naming) that mechanically
  identifies "the file one hop downstream" the way `symbol-*`/`path-*` derive queries from a
  filename.
- **Verified example**:
  1. Query: *"once RenameProcessor has collected all usages of a renamed element, which class
     performs the actual low-level rewrite of each usage occurrence to the new name"*
     Expected: `platform/refactoring/src/com/intellij/refactoring/rename/RenameUtil.java`
     (same verification as 2.1 example 3 — this is the same pair reused with multi-hop framing
     instead of pure-discrimination framing, showing the two category designs can share
     verified ground truth while testing different reasoning).
  2. Query: *"after Safe Delete's usage search finds all references to an element marked for
     deletion, which class carries out removing the element and rewriting/cleaning up those
     usages"*
     Expected: `platform/lang-impl/src/com/intellij/refactoring/safeDelete/SafeDeleteProcessor.java`
     (verified above — `findUsages()` then `performRefactoring()` in the same class; a slightly
     harder variant of this query would ask specifically about a case where find and perform are
     in different classes, which the discrimination family in 2.1 could supply once more classes
     are read).
  3. Note on genuinely-harder 3-hop cases (not yet found/verified — flagged honestly as unverified
     leads for scale-up rather than fabricated): a VFS-change → PSI-reparse → daemon-highlighting-
     restart chain (`RefreshQueueImpl.java` → `PsiManagerImpl`-family listeners → possibly a
     `PsiTreeChangePreprocessor` implementation → `DaemonCodeAnalyzerImpl.java`) looks like a
     promising real 3-stage pipeline but was **not verified this session** — the intermediate
     listener class was not located and confirmed, so no query is proposed for it here. Any
     agent scaling this category up should read the actual call chain (not assume it from
     class names) before writing the query, per the same discipline used for 2.1's examples.

### 2.3 Category: Exact-symbol / error-string lookup (grep-style)

- **Target count: 20-30 cases.**
- **Generation method: semi-mechanical — the only new category that can be substantially
  automated.** Real, distinctive, single-line values from `*Bundle.properties` message files
  (or literal string-constant values in source, e.g. `LOG.error("...")`/exception message
  literals) can be extracted programmatically: for each `*.properties` file under a
  `resources/messages/` directory, take property values that (a) are human-readable English
  sentences ≥ 4 words, (b) doneed apostrophe-quote args are not the only content, (c) are not
  generic ("OK", "Cancel"). Use the value verbatim (or lightly wrapped, e.g. quoted) as the
  query text, and the owning `.properties` file as the expected answer — this is exactly the
  kind of query a developer pastes from an IDE error dialog or log line into a search box,
  which is a plausible and common real-world retrieval scenario this dataset currently has zero
  coverage for. Still needs a human pass to filter out placeholder-heavy or ambiguous strings
  (e.g. ones that also appear near-verbatim in multiple bundles) before finalizing — not
  fully unattended.
- **Verified example cases** (each `.properties` file confirmed present, each string confirmed
  present verbatim in that file via `grep -n` shown below):

  1. Query: *"Caret should be positioned at the name of method or class to be refactored"*
     Expected: `platform/refactoring/resources/messages/RefactoringBundle.properties`
     Verified: line 9, key `error.wrong.caret.position.method.or.class.name`.

  2. Query: *"Select files to commit and specify commit message"*
     Expected: `platform/vcs-api/vcs-api-core/resources/messages/VcsBundle.properties`
     Verified: line 18, key `error.no.changes.no.commit.message`.

  3. Query: *"Project has no JDK configured."*
     Expected: `platform/execution/resources/messages/ExecutionBundle.properties`
     Verified: line 9, key `project.has.no.jdk.configured.error.message`.

  4. Query: *"Some modules have a circular dependency."*
     Expected: `platform/execution/resources/messages/ExecutionBundle.properties`
     Verified: line 8, key `some.modules.has.circular.dependency.error.message` (same file as
     #3, distinct string — deliberately included to test whether retrieval returns the same
     correct file for two different literal strings, not a fluke single hit).

  5. Query: *"Cannot perform the refactoring.\nThe refactoring should be invoked on the class or
     members to be refactored."* (or the single-line variant without the literal `\n`, since a
     developer pasting from a dialog would see it as two lines/one paragraph, not the raw
     properties-escape form)
     Expected: `platform/refactoring/resources/messages/RefactoringBundle.properties`
     Verified: line 12, key `error.select.class.to.be.refactored`.

- **Scale-up note**: at 1000+ `.properties` files under `resources/messages/` across the
  checkout (rough estimate from the existing `config-*` category's file discovery, not
  re-counted exhaustively here), this category alone could support several hundred cases if
  ever needed — 20-30 is a conservative first slice sampled across different plugin areas
  (refactoring, VCS, execution) rather than clustered in one bundle.

### 2.4 Category: Comparative ("what's the difference between A and B")

- **Target count: 15-20 cases.**
- **Generation method: hand-authored, and the hardest to make "correct" as a retrieval eval**
  (not just a generation problem). Unlike the other categories, a comparative query's *correct
  file-level answer* is ambiguous by nature — "what's the difference between X and Y" is
  legitimately answered by retrieving **both** X and Y (so the retrieval-only metric already
  used elsewhere in this dataset, precision/recall over an expected-file set, still applies
  cleanly), but the interesting failure mode this category should probe is whether the retriever
  surfaces *both* siblings rather than fixating on one at the expense of the other (a plausible
  echo of the sibling-cannibalization failure, but in the opposite direction — union coverage
  instead of single-item precision). Recommend reusing the `multi-*` file's existing 2-expected-
  file schema rather than inventing a new one.
- **Verified example cases** (extending the existing "interface vs implementation" pattern
  already in `multi-*`, but rephrased as genuine behavioral-difference questions rather than
  pure location questions):

  1. Query: *"what's the difference in responsibility between SafeDeleteProcessor and
     JavaSafeDeleteProcessor in the Safe Delete refactoring"*
     Expected: `["platform/lang-impl/src/com/intellij/refactoring/safeDelete/SafeDeleteProcessor.java",
     "java/java-impl-refactorings/src/com/intellij/refactoring/safeDelete/JavaSafeDeleteProcessor.java"]`
     (both verified present; roles verified above — generic engine vs. Java-specific delegate).

  2. Query: *"what's the difference between RenameProcessor and RenamePsiElementProcessor in the
     rename refactoring pipeline"*
     Expected: `["platform/lang-impl/src/com/intellij/refactoring/rename/RenameProcessor.java",
     "platform/lang-impl/src/com/intellij/refactoring/rename/RenamePsiElementProcessor.java"]`
     (both verified present; `RenamePsiElementProcessor` confirmed `public abstract class
     RenamePsiElementProcessor extends RenamePsiElementProcessorBase` — an extension point, vs.
     `RenameProcessor`'s concrete orchestration role).

  3. Query: *"what's the difference between ExtractMethodProcessor and
     ExtractMethodPreviewManager in the Extract Method refactoring"*
     Expected: `["java/java-impl-refactorings/src/com/intellij/refactoring/extractMethod/ExtractMethodProcessor.java",
     "java/java-impl-refactorings/src/com/intellij/refactoring/extractMethod/preview/ExtractMethodPreviewManager.java"]`
     (both verified present, roles verified above — actual extraction engine vs. preview-UI
     manager).

  Note: 3/3 examples above reuse pairs already verified in 2.1's discrimination work — this is
  intentional (the two categories are two different question-framings, "which one" vs. "how do
  they differ", over the same verified sibling-pair ground truth) and demonstrates the
  categories can share a verification pass rather than needing independent research per pair.

### 2.5 Category: "How do I implement X" (usage-pattern, not location)

- **Target count: 15-20 cases.**
- **Generation method: hand-authored.** These queries target the same extension-point/plug-in
  pattern already implicit in several `multi-*` cases (e.g. `multi-icon-provider-ep-java`,
  `multi-java-breadcrumbs`) but reframe the question from "which files implement the existing
  X" to "how would I add my own X" — testing whether retrieval surfaces the extension-point
  *contract* file (the one a developer needs to read/implement against) rather than only an
  existing concrete implementation.
- **Verified example cases**:

  1. Query: *"how do I write a custom rename processor that changes how renaming works for my
     own PSI element type"*
     Expected: `platform/lang-impl/src/com/intellij/refactoring/rename/RenamePsiElementProcessor.java`
     Verified: confirmed `public abstract class RenamePsiElementProcessor extends
     RenamePsiElementProcessorBase` — an extension-point base class, i.e. exactly the file a
     developer extending this behavior needs to find (contrast with the location-framed
     `where-*`/`multi-*` queries, which ask about the existing concrete usage, not "how do I add
     mine").

  2. Query: *"how do I plug a language-specific delegate into the generic Safe Delete
     refactoring for a new element type"*
     Expected: `platform/lang-impl/src/com/intellij/refactoring/safeDelete/SafeDeleteProcessorDelegate.java`
     Verified present via `test -f` in this session (the extension-point interface class, as
     distinct from `SafeDeleteProcessor.java`, the engine, and
     `JavaSafeDeleteProcessor.java`/`JavaSafeDeleteDelegateImpl.java`, the concrete Java
     implementations — a fourth, "how do I" framing of the same verified sibling family used in
     2.1/2.4).

  3. Query: *"how do I add a new live-template context so my template only becomes available
     inside Java string literals"*
     Expected: `java/java-impl/src/com/intellij/codeInsight/template/JavaStringContextType.java`
     Verified present via `test -f` in this session (also referenced, with location framing, by
     the existing `multi-java-live-template-contexts` case — reused here with usage-pattern
     framing).

## 3. Summary of proposed new dataset

| New category | File (proposed) | Target count | Generable how |
|---|---|---|---|
| Near-duplicate discrimination | `intellij_eval_discrimination.jsonl` | 40-50 | Hand-authored only |
| Multi-hop / data-flow | `intellij_eval_multihop.jsonl` | 20-30 | Hand-authored (can reuse existing case research as a starting point) |
| Exact-symbol/error-string lookup | `intellij_eval_exact_lookup.jsonl` | 20-30 | Semi-mechanical (extract from `*Bundle.properties`, human-filtered) |
| Comparative | `intellij_eval_comparative.jsonl` | 15-20 | Hand-authored |
| Usage-pattern ("how do I") | `intellij_eval_howto.jsonl` | 15-20 | Hand-authored |
| **Total new cases** | | **110-150** | within the requested 100-200 range |

All 16 concrete example cases shown above (5 discrimination + 2 multi-hop + 5 exact-lookup + 3
comparative + 3 how-to = 18 total, several pairs intentionally shared across categories to
demonstrate reuse) are real, filesystem-verified against `~/Work/intellij-community` at commit
`693e76f0a37ade9509c9edcf505c446672c9c0b1` — none are invented. Scaling each category to its
target count requires the same per-case discipline (read the actual code, don't infer roles from
names alone, verify every path with a real filesystem check) applied by a human or an agent
explicitly instructed to do so — none of these five categories can be safely bulk-generated the
way `symbol-*`/`config-*`/`path-*` are, and pretending otherwise would reintroduce exactly the
lexical-shortcut problem this expansion exists to fix.
