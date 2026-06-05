from __future__ import annotations

import re
from collections import Counter
from statistics import mean
from typing import Any


class ExplanationMetrics:
    STOP_WORDS = {
        "a",
        "an",
        "and",
        "are",
        "as",
        "by",
        "for",
        "from",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "with",
    }

    def score(self, prediction: str, reference: str) -> dict[str, float]:
        predicted_tokens = self._tokens(prediction)
        reference_tokens = self._tokens(reference)
        predicted_key_tokens = [token for token in predicted_tokens if token not in self.STOP_WORDS]
        reference_key_tokens = [token for token in reference_tokens if token not in self.STOP_WORDS]
        unigram = self._overlap(predicted_tokens, reference_tokens)
        key = self._overlap(predicted_key_tokens, reference_key_tokens)
        bigram = self._overlap(self._ngrams(predicted_tokens, 2), self._ngrams(reference_tokens, 2))
        return {
            "token_precision": unigram["precision"],
            "token_recall": unigram["recall"],
            "token_f1": unigram["f1"],
            "key_token_precision": key["precision"],
            "key_token_recall": key["recall"],
            "key_token_f1": key["f1"],
            "bigram_precision": bigram["precision"],
            "bigram_recall": bigram["recall"],
            "bigram_f1": bigram["f1"],
            "prediction_tokens": float(len(predicted_tokens)),
            "reference_tokens": float(len(reference_tokens)),
        }

    def aggregate(self, rows: list[dict[str, Any]]) -> dict[str, float]:
        metric_keys = (
            [
                key
                for key, value in (rows[0].get("metrics") or {}).items()
                if isinstance(value, (int, float))
            ]
            if rows
            else []
        )
        return {key: mean(float(row["metrics"][key]) for row in rows) for key in metric_keys}

    def _tokens(self, value: str) -> list[str]:
        return [self._normalize_token(token) for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+", value.lower())]

    def _normalize_token(self, token: str) -> str:
        if len(token) > 4 and token.endswith("ies"):
            return f"{token[:-3]}y"
        if len(token) > 4 and token.endswith("es"):
            return token[:-2]
        if len(token) > 3 and token.endswith("s"):
            return token[:-1]
        return token

    def _ngrams(self, tokens: list[str], size: int) -> list[str]:
        if len(tokens) < size:
            return []
        return [" ".join(tokens[index : index + size]) for index in range(0, len(tokens) - size + 1)]

    def _overlap(self, predicted: list[str], reference: list[str]) -> dict[str, float]:
        if not predicted or not reference:
            return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
        predicted_counts = Counter(predicted)
        reference_counts = Counter(reference)
        matches = sum(min(count, reference_counts[token]) for token, count in predicted_counts.items())
        precision = matches / max(len(predicted), 1)
        recall = matches / max(len(reference), 1)
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        return {"precision": precision, "recall": recall, "f1": f1}
