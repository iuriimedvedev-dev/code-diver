from __future__ import annotations

import pytest

from code_diver.config import HybridSearchConfig
from code_diver.strategies.hybrid_query_analyzer import HybridQueryAnalyzer

pytestmark = pytest.mark.unit


def test_query_analyzer_leaves_terms_unexpanded_by_default() -> None:
    query = HybridQueryAnalyzer(HybridSearchConfig()).analyze("where do we auth token?")

    assert "auth" in query.terms
    assert "token" in query.terms
    assert "authorization" not in query.terms


def test_query_analyzer_can_expand_configured_aliases() -> None:
    config = HybridSearchConfig(
        query_expansion_enabled=True,
        query_expansion_aliases={"auth": ["authorization", "authentication"], "db": ["database"]},
    )

    query = HybridQueryAnalyzer(config).analyze("auth db")

    assert query.terms == ("auth", "authorization", "authentication", "db", "database")
