"""Checks that the model a local server is actually serving is the one that was asked for.

Local ports are reused heavily: port 8012 is named by four different generation models
across the shipped configs, 8016 by five, 8080 by three. Only one server can hold a port,
so pointing a config at a port some other model currently occupies silently evaluates the
wrong model and files the results under the requested model's name. Nothing in a report
distinguishes that from a genuine result.

Port bookkeeping cannot prevent this -- the config and the running server are edited and
launched independently. Comparing the served model id against the configured one can, and
it costs nothing because chat responses already carry `model`.

Exact string comparison is not possible: the same weights are advertised as
`mlx-community/gemma-4-e2b-it-4bit` by mlx_lm and `gemma-4-E2B-it-qat-UD-Q4_K_XL` by
llama.cpp. So both ids are reduced to the tokens that identify the *model*, after dropping
tokens that only describe packaging (quantization, format, tuning suffix). Two ids are
considered the same model when neither fingerprint contains a token the other contradicts.
"""

from __future__ import annotations

import re
from typing import Final

# Tokens that describe how the weights were packaged, not which model they are.
_PACKAGING_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "4bit",
        "8bit",
        "6bit",
        "3bit",
        "bf16",
        "fp16",
        "f16",
        "fp32",
        "q2",
        "q3",
        "q4",
        "q5",
        "q6",
        "q8",
        "k",
        "km",
        "ks",
        "kl",
        "kxl",
        "xl",
        "s",
        "m",
        "l",
        "ud",
        "gguf",
        "mlx",
        "safetensors",
        "it",
        "instruct",
        "chat",
        "qat",
        "dwq",
        "awq",
        "gptq",
        "optiq",
        # Publisher namespaces: the same weights ship under several of these.
        "community",
        "unsloth",
        "google",
        "mlxcommunity",
    }
)


class ServedModelIdentity:
    def fingerprint(self, model_id: str) -> frozenset[str]:
        """Reduce a model id to the tokens that identify the model itself."""
        tail = model_id.strip().replace("\\", "/").rsplit("/", 1)[-1]
        tail = re.sub(r"\.(gguf|safetensors|bin|npz)$", "", tail, flags=re.IGNORECASE)
        tokens = {token for token in re.split(r"[^0-9a-zA-Z.]+", tail.lower()) if token}
        return frozenset(tokens - _PACKAGING_TOKENS)

    def same_model(self, configured: str, served: str) -> bool:
        configured_tokens = self.fingerprint(configured)
        served_tokens = self.fingerprint(served)
        if not configured_tokens or not served_tokens:
            # Nothing identifying survived on one side; refusing to guess is safer than
            # failing a run over an id we cannot read.
            return True
        smaller, larger = sorted((configured_tokens, served_tokens), key=len)
        return smaller <= larger

    def mismatch_message(self, configured: str, served: str, url: str) -> str:
        return (
            f"The server at {url} is serving {served!r}, but the config asked for {configured!r}. "
            "Local ports are reused across configs, so this is usually a server left running from "
            "another experiment. Results would be recorded under the wrong model name. "
            "Restart the server with the configured model, or point the config at the right port."
        )
