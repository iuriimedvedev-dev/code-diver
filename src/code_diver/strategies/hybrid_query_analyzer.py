from __future__ import annotations

from ..config import HybridSearchConfig
from ..services.tokenizer import tokenize
from .hybrid_query import HybridQuery


class HybridQueryAnalyzer:
    def __init__(self, config: HybridSearchConfig):
        self.config = config

    def analyze(self, query: str) -> HybridQuery:
        stop_words = {word.lower() for word in self.config.stop_words}
        tokens = [
            token
            for token in tokenize(query)
            if len(token) >= self.config.min_token_length
            and token not in stop_words
            and any(char.isalnum() for char in token)
        ]
        terms = tuple(dict.fromkeys(tokens))
        return HybridQuery(text=query, terms=terms)
