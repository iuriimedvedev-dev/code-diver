from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from ...domain import CodeSymbol
from .base import LanguageEvidence, LanguageStrategy, StructuralSpan
from .cpp import CppStrategy
from .generic import GenericStrategy
from .go import GoStrategy
from .jvm import JvmStrategy
from .python import PythonStrategy
from .rust import RustStrategy
from .ts_js import TsJsStrategy


class LanguageIndexingRouter:
    def __init__(
        self,
        strategies: list[LanguageStrategy] | None = None,
        fallback: LanguageStrategy | None = None,
    ) -> None:
        self._registry: dict[str, LanguageStrategy] = {}
        self._fallback: LanguageStrategy = fallback or GenericStrategy()
        if strategies:
            for strategy in strategies:
                self.register(strategy)

    @property
    def registry(self) -> Mapping[str, LanguageStrategy]:
        return self._registry

    @property
    def fallback(self) -> LanguageStrategy:
        return self._fallback

    def register(self, strategy: LanguageStrategy) -> None:
        for ext in strategy.supported_extensions:
            self._registry[ext.lower()] = strategy

    def get_strategy(self, path: str | Path) -> LanguageStrategy:
        ext = Path(path).suffix.lower()
        return self._registry.get(ext, self._fallback)

    def resolve(self, path: str | Path) -> LanguageStrategy:
        return self.get_strategy(path)

    def extract_symbols(self, rel_path: str, text: str) -> list[CodeSymbol]:
        strategy = self.get_strategy(rel_path)
        return strategy.extract_symbols(rel_path, text)

    def extract_spans(self, rel_path: str, text: str, line_count: int) -> list[StructuralSpan]:
        strategy = self.get_strategy(rel_path)
        return strategy.extract_spans(rel_path, text, line_count)

    def extract_evidence(self, rel_path: str, text: str) -> LanguageEvidence:
        strategy = self.get_strategy(rel_path)
        return strategy.extract_evidence(rel_path, text)


_GLOBAL_ROUTER: LanguageIndexingRouter | None = None


def get_language_router() -> LanguageIndexingRouter:
    global _GLOBAL_ROUTER  # noqa: PLW0603
    if _GLOBAL_ROUTER is None:
        router = LanguageIndexingRouter()
        router.register(PythonStrategy())
        router.register(JvmStrategy())
        router.register(RustStrategy())
        router.register(GoStrategy())
        router.register(CppStrategy())
        router.register(TsJsStrategy())
        _GLOBAL_ROUTER = router
    return _GLOBAL_ROUTER
