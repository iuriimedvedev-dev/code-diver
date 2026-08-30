from __future__ import annotations

import pytest

from code_diver.domain import CodeSymbol
from code_diver.services.file_summary_item_builder import (
    TRUNCATION_MARKER,
    FileSummaryItemBuilder,
)

pytestmark = pytest.mark.unit


def test_head_section_caps_a_single_extremely_long_line() -> None:
    text = "x" * 50_000 + "\n"

    item = FileSummaryItemBuilder(
        max_head_line_chars=200, max_head_block_chars=4000
    ).build("huge.js", text, symbols=[])

    assert len(item.content) < 4000
    assert TRUNCATION_MARKER in item.content


def test_head_section_caps_overall_block_even_with_many_short_lines() -> None:
    text = "\n".join(f"line {index}" for index in range(1000))

    item = FileSummaryItemBuilder(
        max_head_lines=1000, max_head_line_chars=200, max_head_block_chars=4000
    ).build("many_lines.py", text, symbols=[])

    # With symbols-first ordering, symbols come before head
    symbols_start = item.content.index("symbols:")
    head_start = item.content.index("head:", symbols_start)
    # Find end of head block: next section marker after head
    imports_start = item.content.index("imports:", head_start)
    head_block = item.content[head_start:imports_start].rstrip("\n")
    assert len(head_block) <= 4000
    assert TRUNCATION_MARKER in head_block


def test_symbols_section_occurs_before_head_section() -> None:
    head_text = "known head text"
    symbol_text = "known symbol text"

    item = FileSummaryItemBuilder().build(
        "ordered.py",
        head_text,
        symbols=[
            CodeSymbol(
                name=symbol_text,
                kind="function",
                start_line=1,
                end_line=1,
                signature="known symbol signature",
            )
        ],
    )

    # symbols section precedes head section in the stable summary order
    assert item.content.index(f"symbols:\n- function {symbol_text}: known symbol signature") < item.content.index(
        f"head:\n- {head_text}"
    )


def test_build_places_symbols_section_before_head() -> None:
    head_text = "distinct text-file head marker"
    dense_prose = "dense prose body marker " * 20

    item = FileSummaryItemBuilder().build(
        "ordered.txt",
        f"{head_text}\n{dense_prose}",
        symbols=[
            CodeSymbol(
                name="parse_document",
                kind="function",
                start_line=1,
                end_line=1,
                signature="parse_document(text: str) -> Document",
            )
        ],
    )

    # symbols section precedes head section in the stable summary order
    assert item.content.index(
        "symbols:\n- function parse_document: parse_document(text: str) -> Document"
    ) < item.content.index(f"head:\n- {head_text}")


def test_build_uses_complete_stable_section_order() -> None:
    item = FileSummaryItemBuilder().build(
        "ordered.py",
        "from package import value\nhead marker",
        symbols=[
            CodeSymbol(
                name="parse",
                kind="function",
                start_line=1,
                end_line=1,
                signature="parse()",
            )
        ],
    )

    sections = ["file:", "extension:", "purpose:", "terms:", "symbols:", "head:", "imports:"]
    positions = [item.content.index(section) for section in sections]
    assert positions == sorted(positions)


def test_head_section_is_unchanged_for_a_normal_small_file() -> None:
    text = (
        "from services.auth import authorize\n"
        "\n"
        "class UserService:\n"
        "    def create_user(self):\n"
        "        return authorize()"
    )

    before = FileSummaryItemBuilder(max_head_lines=24).build(
        "app.py", text, symbols=[]
    )
    after = FileSummaryItemBuilder(
        max_head_lines=24, max_head_line_chars=200, max_head_block_chars=4000
    ).build("app.py", text, symbols=[])

    assert after.content == before.content
    assert TRUNCATION_MARKER not in after.content


def test_purpose_section_uses_path_derived_fallback_for_non_jvm_file() -> None:
    item = FileSummaryItemBuilder().build(
        "service.py",
        "# Copyright 2024\n\n@file: service\nclass Service:\n    pass",
        symbols=[],
    )

    assert "purpose: service" in item.content


def test_purpose_section_uses_path_for_empty_source() -> None:
    item = FileSummaryItemBuilder().build("empty.py", "\n# Copyright 2024\n", symbols=[])

    assert "purpose: empty" in item.content


def test_purpose_section_ignores_source_text_for_non_jvm_file() -> None:
    item = FileSummaryItemBuilder(max_head_line_chars=10).build(
        "long.py", "class " + "x" * 100, symbols=[]
    )

    assert "purpose: long" in item.content


def test_purpose_section_extracts_multiline_kdoc_before_kotlin_class() -> None:
    text = (
        "package com.example.service\n\n"
        "/**\n"
        " * Coordinates account synchronization.\n"
        " * It retries transient failures before reporting an error.\n"
        " */\n"
        "class AccountSyncService\n"
    )

    item = FileSummaryItemBuilder().build("AccountSyncService.kt", text, symbols=[])

    assert "purpose: Coordinates account synchronization." in item.content


def test_purpose_section_uses_manager_role_suffix() -> None:
    item = FileSummaryItemBuilder().build(
        "FooManager.kt",
        "class FooManager\n",
        symbols=[],
    )

    assert "purpose: manager FooManager" in item.content


def test_purpose_section_treats_service_impl_as_service_implementation() -> None:
    item = FileSummaryItemBuilder().build(
        "FooServiceImpl.kt",
        "class FooServiceImpl\n",
        symbols=[],
    )

    assert "purpose: service implementation FooServiceImpl" in item.content


def test_purpose_section_uses_action_role_suffix() -> None:
    item = FileSummaryItemBuilder().build(
        "FooAction.kt",
        "class FooAction\n",
        symbols=[],
    )

    assert "purpose: action FooAction" in item.content


def test_purpose_section_ignores_kotlin_primary_constructor_parameters() -> None:
    item = FileSummaryItemBuilder().build(
        "FooManager.kt",
        "class FooManager @Internal constructor(val project: Project, scope: CoroutineScope) : Disposable {\n",
        symbols=[],
    )
    purpose = item.content.split("purpose: ", 1)[1].splitlines()[0]

    assert purpose.startswith("manager FooManager for Disposable")
    assert "CoroutineScope" not in purpose
    assert ")" not in purpose


def test_purpose_section_omits_supertypes_for_multiline_constructor_declaration() -> None:
    item = FileSummaryItemBuilder().build(
        "FooManager.kt",
        "class FooManager(\n  val project: Project,\n) : Disposable {\n",
        symbols=[],
    )
    purpose = item.content.split("purpose: ", 1)[1].splitlines()[0]

    assert purpose.startswith("manager FooManager")
    assert " for " not in purpose


def test_purpose_section_uses_first_sentence_from_class_javadoc() -> None:
    text = (
        "/** Coordinates account synchronization.\n"
        " * This second sentence must not be included.\n"
        " */\n"
        "class AccountSync\n"
    )

    item = FileSummaryItemBuilder().build(
        "AccountSync.java", text, symbols=[]
    )

    purpose = item.content.split("purpose: ", 1)[1].splitlines()[0]
    assert purpose.startswith("Coordinates account sync")
    assert TRUNCATION_MARKER not in purpose
    assert "second sentence" not in purpose


def test_purpose_section_truncates_javadoc_at_a_word_boundary_with_220_char_cap() -> None:
    first_sentence = "Coordinates account synchronization across every tenant and region " * 5
    text = f"/** {first_sentence}.\n * A second sentence must not be included.\n */\nclass AccountSync\n"

    item = FileSummaryItemBuilder().build("AccountSync.java", text, symbols=[])
    purpose = item.content.split("purpose: ", 1)[1].splitlines()[0]

    assert len(purpose) <= 220
    assert TRUNCATION_MARKER in purpose
    assert purpose.removesuffix(TRUNCATION_MARKER).endswith((" ", ".")) is False
    assert "second sentence" not in purpose


def test_terms_section_includes_path_components() -> None:
    item = FileSummaryItemBuilder().build("src/auth/UserService.py", "pass", symbols=[])

    assert "terms: user service src auth py" in item.content


def test_terms_section_includes_symbol_names_and_signatures() -> None:
    item = FileSummaryItemBuilder().build(
        "handlers.py",
        "pass",
        symbols=[
            CodeSymbol(
                name="parseRequest",
                kind="function",
                start_line=1,
                end_line=1,
                signature="parseRequest(request: Request) -> Response",
            )
        ],
    )

    assert "parse request" in item.content
    assert "response" in item.content


def test_terms_section_lowercases_deduplicates_and_ignores_short_tokens() -> None:
    item = FileSummaryItemBuilder().build(
        "src/API/APIClient.py",
        "pass",
        symbols=[
            CodeSymbol(
                name="ApiClient",
                kind="class",
                start_line=1,
                end_line=1,
                signature="ApiClient(x: X)",
            )
        ],
    )
    terms = item.content[item.content.index("terms: ") :].splitlines()[0]

    assert terms.split().count("api") == 1
    assert "client" in terms
    assert " x " not in f" {terms} "


def test_terms_section_respects_max_symbols() -> None:
    item = FileSummaryItemBuilder(max_symbols=1).build(
        "symbols.py",
        "pass",
        symbols=[
            CodeSymbol("firstSymbol", "function", 1, 1, "firstSymbol()"),
            CodeSymbol("secondSymbol", "function", 2, 2, "secondSymbol()"),
        ],
    )

    assert "first symbol" in item.content
    assert "second" not in item.content


def test_terms_section_has_stable_first_occurrence_order() -> None:
    item = FileSummaryItemBuilder().build("src/auth/Auth.py", "pass", symbols=[])
    terms = item.content[item.content.index("terms: ") :].splitlines()[0]

    assert terms == "terms: auth src py"


def test_terms_section_splits_camel_case_into_lowercase_terms() -> None:
    item = FileSummaryItemBuilder().build(
        "CamelCase.py",
        "pass",
        symbols=[CodeSymbol("loadUserProfile", "function", 1, 1, "loadUserProfile()")],
    )
    terms = item.content[item.content.index("terms: ") :].splitlines()[0]

    assert "load user profile" in terms
    assert terms == terms.lower()


def test_terms_section_splits_snake_case_into_lowercase_terms() -> None:
    item = FileSummaryItemBuilder().build(
        "snake_case.py",
        "pass",
        symbols=[CodeSymbol("load_user_profile", "function", 1, 1, "load_user_profile()")],
    )
    terms = item.content[item.content.index("terms: ") :].splitlines()[0]

    assert "snake case" in terms
    assert "load user profile" in terms
    assert terms == terms.lower()


def test_terms_section_deduplicates_repeated_terms_in_first_occurrence_order() -> None:
    item = FileSummaryItemBuilder().build(
        "src/auth/Auth.py",
        "pass",
        symbols=[CodeSymbol("authUser", "function", 1, 1, "authUser(auth)")],
    )
    terms = item.content[item.content.index("terms: ") :].splitlines()[0]

    assert terms == "terms: auth src py user"


def test_terms_section_caps_length_and_word_count_for_many_long_symbol_names() -> None:
    symbols = [
        CodeSymbol(
            f"VeryLongSymbolNameNumber{index}WithAdditionalWords",
            "function",
            index,
            index,
            f"VeryLongSymbolNameNumber{index}WithAdditionalWords()",
        )
        for index in range(1, 100)
    ]

    item = FileSummaryItemBuilder().build("symbols.py", "pass", symbols=symbols)
    terms = item.content[item.content.index("terms: ") :].splitlines()[0]

    assert len(terms) <= 220
    assert len(terms.split()) - 1 <= 40


def test_purpose_section_uses_path_fallback_without_jvm_declaration() -> None:
    item = FileSummaryItemBuilder().build(
        "src/user_profile/UserProfile.kt",
        "\n// Copyright 2024\npackage com.example.profile\nfun loadUserProfile() {}\n",
        symbols=[],
    )

    assert "purpose: user profile" in item.content


def test_purpose_section_uses_path_fallback_for_generated_non_jvm_text() -> None:
    item = FileSummaryItemBuilder().build(
        "generated/api_client.txt",
        "generated output with no declarations\n",
        symbols=[],
    )

    assert "purpose: api client" in item.content


def test_terms_section_is_none_when_path_has_no_terms() -> None:
    item = FileSummaryItemBuilder().build("a", "pass", symbols=[])

    assert "terms: none" in item.content


COMPACT_KT_TEXT = """
// Copyright 2024 JetBrains
package com.intellij.openapi.project.impl

import com.intellij.openapi.Disposable

open class ProjectManagerImpl : ProjectManagerEx(), Disposable {
    override fun isLight(project: Project): Boolean = false
}
"""

COMPACT_KT_PATH = "platform/platform-impl/src/com/intellij/openapi/project/impl/ProjectManagerImpl.kt"


def test_compact_budget_puts_purpose_first_and_shortens_the_embedded_path() -> None:
    item = FileSummaryItemBuilder(compact_budget=True).build(
        COMPACT_KT_PATH, COMPACT_KT_TEXT, symbols=[]
    )

    assert item.content.startswith("purpose: ")
    assert "file: project/impl/ProjectManagerImpl.kt" in item.content
    assert f"file: {COMPACT_KT_PATH}" not in item.content
    assert item.path == COMPACT_KT_PATH
    assert item.title == f"{COMPACT_KT_PATH}::file_summary"


def test_compact_budget_drops_keyword_and_path_noise_from_terms() -> None:
    item = FileSummaryItemBuilder(compact_budget=True).build(
        COMPACT_KT_PATH,
        COMPACT_KT_TEXT,
        symbols=[CodeSymbol("isLight", "function", 8, 8, "fun isLight(project: Project): Boolean")],
    )
    terms = item.content[item.content.index("terms: ") :].splitlines()[0].split()[1:]

    for noise in ("open", "class", "fun", "override", "src", "com", "intellij", "kt", "impl"):
        assert noise not in terms
    assert terms[:2] == ["project", "manager"]
    assert "disposable" in terms


def test_compact_budget_is_off_by_default() -> None:
    item = FileSummaryItemBuilder().build(COMPACT_KT_PATH, COMPACT_KT_TEXT, symbols=[])

    assert item.content.startswith(f"file: {COMPACT_KT_PATH}")
