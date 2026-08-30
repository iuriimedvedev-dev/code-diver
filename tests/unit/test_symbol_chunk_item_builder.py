from __future__ import annotations

import pytest

from code_diver.domain import CodeItemIndexKind
from code_diver.services import CodeSymbolExtractor, SymbolChunkItemBuilder

pytestmark = pytest.mark.unit


def _kotlin_source(body_methods: str, filler_lines: int = 240) -> str:
    filler = "\n".join(f"  // filler {index}" for index in range(filler_lines))
    return (
        "package com.intellij.openapi.actionSystem.impl\n"
        "\n"
        "/**\n"
        " * Registers and looks up actions. Second sentence is dropped.\n"
        " */\n"
        "open class ActionManagerImpl : ActionManagerEx() {\n"
        f"{body_methods}\n"
        f"{filler}\n"
        "}\n"
    )


def _build(text: str, rel_path: str = "platform/impl/ActionManagerImpl.kt", **kwargs):
    symbols = CodeSymbolExtractor().extract(rel_path, text)
    return SymbolChunkItemBuilder(**kwargs).build(rel_path, text, symbols)


def test_builder_emits_a_point_per_type_and_public_callable() -> None:
    text = _kotlin_source(
        "  fun registerAction(actionId: String, action: AnAction) {\n"
        "    val registered = actionRegistrar.register(actionId)\n"
        "    listeners.forEach { it.onRegistered(registered) }\n"
        "    return registered\n"
        "  }\n"
    )

    items = _build(text)

    assert [item.metadata["symbol"] for item in items] == ["ActionManagerImpl", "registerAction"]
    assert {item.metadata["index_kind"] for item in items} == {CodeItemIndexKind.SYMBOL_CHUNK}


def test_chunk_keeps_the_full_file_path_so_dedup_and_path_scoring_still_work() -> None:
    text = _kotlin_source(
        "  fun registerAction(actionId: String) {\n"
        "    val registered = actionRegistrar.register(actionId)\n"
        "    listeners.forEach { it.onRegistered(registered) }\n"
        "  }\n"
    )

    items = _build(text)

    assert {item.path for item in items} == {"platform/impl/ActionManagerImpl.kt"}
    # The embedded `file:` line is shortened for the 500-char budget, the item path is not.
    assert "file: platform/impl/ActionManagerImpl.kt" in items[0].content


def test_chunk_text_leads_with_the_symbol_identity_split_into_words() -> None:
    text = _kotlin_source(
        "  fun registerAction(actionId: String) {\n"
        "    val registered = actionRegistrar.register(actionId)\n"
        "    listeners.forEach { it.onRegistered(registered) }\n"
        "  }\n"
    )

    method = next(item for item in _build(text) if item.metadata["symbol"] == "registerAction")

    first_line = method.content.splitlines()[0]
    assert first_line.startswith("symbol: function ActionManagerImpl.registerAction")
    # The name is split into words; "action" is already contributed by the enclosing class.
    assert first_line.endswith("action manager impl register")
    assert "signature: fun registerAction(actionId: String) {" in method.content


def test_chunk_text_uses_the_first_kdoc_sentence_as_purpose() -> None:
    text = _kotlin_source(
        "  /**\n"
        "   * Registers one action under the given id. Ignored tail.\n"
        "   */\n"
        "  fun registerAction(actionId: String) {\n"
        "    val registered = actionRegistrar.register(actionId)\n"
        "    listeners.forEach { it.onRegistered(registered) }\n"
        "  }\n"
    )

    method = next(item for item in _build(text) if item.metadata["symbol"] == "registerAction")

    assert "purpose: Registers one action under the given id." in method.content
    assert "Ignored tail" not in method.content


def test_chunk_text_stays_inside_the_embedding_budget() -> None:
    text = _kotlin_source(
        "  fun registerAction(actionId: String) {\n"
        + "".join(f"    val value{index} = computeSomethingVerbose{index}()\n" for index in range(40))
        + "  }\n"
    )

    assert all(len(item.content) <= 500 for item in _build(text))


def test_small_files_produce_no_chunks() -> None:
    text = _kotlin_source(
        "  fun registerAction(actionId: String) {\n"
        "    val registered = actionRegistrar.register(actionId)\n"
        "    listeners.forEach { it.onRegistered(registered) }\n"
        "  }\n",
        filler_lines=10,
    )

    assert _build(text) == []


def test_private_and_trivial_accessors_are_skipped() -> None:
    text = _kotlin_source(
        "  private fun internalRebuild(actionId: String) {\n"
        "    val registered = actionRegistrar.register(actionId)\n"
        "    listeners.forEach { it.onRegistered(registered) }\n"
        "  }\n"
        "  fun getActionIds(): List<String> {\n"
        "    return ids\n"
        "  }\n"
    )

    assert [item.metadata["symbol"] for item in _build(text)] == ["ActionManagerImpl"]


def test_chunks_per_file_are_capped() -> None:
    methods = "".join(
        f"  fun handleEvent{index}(actionId: String) {{\n"
        f"    val registered = actionRegistrar.register(actionId)\n"
        f"    listeners.forEach {{ it.onRegistered(registered) }}\n"
        f"  }}\n"
        for index in range(30)
    )

    assert len(_build(_kotlin_source(methods), max_chunks_per_file=5)) == 5


def test_non_source_files_produce_no_chunks() -> None:
    text = _kotlin_source(
        "  fun registerAction(actionId: String) {\n"
        "    val registered = actionRegistrar.register(actionId)\n"
        "    listeners.forEach { it.onRegistered(registered) }\n"
        "  }\n"
    )

    assert _build(text, rel_path="docs/ActionManagerImpl.md") == []
