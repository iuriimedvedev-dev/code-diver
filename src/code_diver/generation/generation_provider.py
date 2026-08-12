from __future__ import annotations

from typing import Any, Protocol

from .generation_result import GenerationResult


class GenerationProvider(Protocol):
    @property
    def name(self) -> str:
        pass

    @property
    def model(self) -> str:
        pass

    def generate_json(self, prompt: str, *, schema: dict[str, Any] | None = None) -> str:
        pass

    def generate_json_result(self, prompt: str, *, schema: dict[str, Any] | None = None) -> GenerationResult:
        """Generate a JSON response, optionally constrained to `schema`.

        `schema` is a request, not a guarantee: llama.cpp compiles it into a decoding
        grammar, the Gemini and OpenAI APIs enforce it server-side, and `mlx_lm` ignores
        it outright. Providers that cannot enforce it accept and ignore the argument;
        `SchemaGuardedGenerationProvider` supplies validate-and-repair on top so that
        passing a schema means the same thing regardless of backend.
        """
