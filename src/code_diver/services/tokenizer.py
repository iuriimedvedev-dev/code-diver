from __future__ import annotations

import re

TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+|[^\sA-Za-z0-9_]")


def tokenize(text: str) -> list[str]:
    normalized = text.replace("-", "_")
    tokens: list[str] = []
    for token in TOKEN_RE.findall(normalized):
        tokens.append(token.lower())
        tokens.extend(part.lower() for part in _split_identifier(token))
    return [token for token in tokens if token]


def _split_identifier(token: str) -> list[str]:
    if not token or not any(ch.isalpha() for ch in token):
        return []
    token = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", token)
    return re.split(r"[_\W]+", token)
