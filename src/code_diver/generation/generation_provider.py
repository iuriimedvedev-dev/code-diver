from __future__ import annotations

from typing import Protocol


class GenerationProvider(Protocol):
    @property
    def name(self) -> str:
        pass

    @property
    def model(self) -> str:
        pass

    def generate_json(self, prompt: str) -> str:
        pass
