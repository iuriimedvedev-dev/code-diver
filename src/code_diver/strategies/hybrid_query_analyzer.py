from __future__ import annotations

from ..config import HybridSearchConfig
from ..services.tokenizer import tokenize
from .hybrid_query import HybridQuery
from .hybrid_query_expander import HybridQueryExpander


class HybridQueryAnalyzer:
    def __init__(self, config: HybridSearchConfig):
        self.config = config
        self.expander = HybridQueryExpander(config.query_expansion_aliases)

    def analyze(self, query: str) -> HybridQuery:
        stop_words = {word.lower() for word in self.config.stop_words}
        tokens = [
            token
            for token in tokenize(query)
            if self._keep_token(token, stop_words)
        ]
        if self.config.query_expansion_enabled:
            tokens = self.expander.expand(tokens)
        terms = tuple(dict.fromkeys(tokens))
        return HybridQuery(text=query, terms=terms)

    def _keep_token(self, token: str, stop_words: set[str]) -> bool:
        return (
            (len(token) >= self.config.min_token_length or token in self.config.query_expansion_aliases)
            and token not in stop_words
            and any(char.isalnum() for char in token)
        )
