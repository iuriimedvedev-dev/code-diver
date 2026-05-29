from __future__ import annotations

from typing import Protocol

from .generation_result import GenerationResult


class GenerationProvider(Protocol):
    @property
    def name(self) -> str:
        pass

    @property
    def model(self) -> str:
        pass

    def generate_json(self, prompt: str) -> str:
        pass

    def generate_json_result(self, prompt: str) -> GenerationResult:
        pass
