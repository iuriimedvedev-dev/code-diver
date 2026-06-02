from __future__ import annotations

import pytest

from code_diver.domain import CodeItem
from code_diver.graph import CodeGraph
from code_diver.services import IdentifierAliasLocator


pytestmark = pytest.mark.unit


def test_identifier_alias_locator_finds_symbol_owner_from_informal_query() -> None:
    graph = CodeGraph(
        items={
            "project": CodeItem(
                id="project",
                path="platform/projectModel-impl/src/com/intellij/openapi/project/impl/ProjectManagerImpl.kt",
                title="platform/projectModel-impl/src/com/intellij/openapi/project/impl/ProjectManagerImpl.kt::file_manifest",
                content="""
file: platform/projectModel-impl/src/com/intellij/openapi/project/impl/ProjectManagerImpl.kt
filename: ProjectManagerImpl.kt
path_tokens: platform project model impl openapi project impl project manager impl kt
package: com.intellij.openapi.project.impl
symbols:
- class ProjectManagerImpl: class ProjectManagerImpl
- function openProject: fun openProject()
""".strip(),
                metadata={"index_kind": "file_manifest"},
            ),
            "action": CodeItem(
                id="action",
                path="platform/projectModel-impl/src/com/intellij/openapi/project/actions/OpenProjectAction.kt",
                title="OpenProjectAction.kt::file_manifest",
                content="symbols:\n- class OpenProjectAction\n- function actionPerformed",
                metadata={"index_kind": "file_manifest"},
            ),
        },
        edges=[],
    )

    results = IdentifierAliasLocator(graph).search("where is project opening managed", 5)

    assert results[0].path.endswith("ProjectManagerImpl.kt")
    assert results[0].score > results[1].score


def test_identifier_alias_locator_finds_resource_descriptor() -> None:
    graph = CodeGraph(
        items={
            "plugin": CodeItem(
                id="plugin",
                path="platform/platform-resources/src/META-INF/plugin.xml",
                title="platform/platform-resources/src/META-INF/plugin.xml::file_manifest",
                content="""
file: platform/platform-resources/src/META-INF/plugin.xml
filename: plugin.xml
directories: platform / platform-resources / src / META-INF
path_tokens: platform resources src meta inf plugin xml
config_keys:
- idea-plugin
- extensions
- applicationService
""".strip(),
                metadata={"index_kind": "file_manifest"},
            ),
            "bundle": CodeItem(
                id="bundle",
                path="platform/platform-resources/src/messages/CoreBundle.properties",
                title="CoreBundle.properties::file_manifest",
                content="filename: CoreBundle.properties\nconfig_keys:\n- error.project.open.failed",
                metadata={"index_kind": "file_manifest"},
            ),
        },
        edges=[],
    )

    results = IdentifierAliasLocator(graph).search("plugin descriptor extension configuration meta inf plugin", 5)

    assert results[0].path.endswith("META-INF/plugin.xml")
    assert "plugin" in results[0].matched_aliases


def test_identifier_alias_locator_uses_token_candidates_only() -> None:
    graph = CodeGraph(
        items={
            "auth": CodeItem(
                id="auth",
                path="src/auth/AuthTokenService.kt",
                title="AuthTokenService.kt::file_manifest",
                content="filename: AuthTokenService.kt\nsymbols:\n- class AuthTokenService",
                metadata={"index_kind": "file_manifest"},
            ),
            "billing": CodeItem(
                id="billing",
                path="src/billing/BillingLedger.kt",
                title="BillingLedger.kt::file_manifest",
                content="filename: BillingLedger.kt\nsymbols:\n- class BillingLedger",
                metadata={"index_kind": "file_manifest"},
            ),
        },
        edges=[],
    )

    results = IdentifierAliasLocator(graph).search("auth token", 10)

    assert [result.path for result in results] == ["src/auth/AuthTokenService.kt"]
