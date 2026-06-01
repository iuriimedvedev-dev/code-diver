from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPrice:
    input_per_million: float
    output_per_million: float


class ModelCostEstimator:
    DEFAULT_PRICE = ModelPrice(input_per_million=1.50, output_per_million=9.00)
    MODEL_PRICES = {
        "gemini-3.1-flash-lite": ModelPrice(input_per_million=0.25, output_per_million=1.50),
        "gemini-3.5-flash": DEFAULT_PRICE,
        "gemini-3-flash-preview": ModelPrice(input_per_million=0.50, output_per_million=3.00),
        "gemini-2.5-flash": ModelPrice(input_per_million=0.30, output_per_million=2.50),
        "gpt-5.1-mini": ModelPrice(input_per_million=0.25, output_per_million=2.00),
        "gpt-5.1": ModelPrice(input_per_million=1.25, output_per_million=10.00),
        "claude-opus-4-8": ModelPrice(input_per_million=15.00, output_per_million=75.00),
        "claude-haiku-4-5": ModelPrice(input_per_million=0.80, output_per_million=4.00),
    }

    def estimate(self, model: str, input_tokens: int, output_tokens: int) -> float:
        price = self.price_for(model)
        return (input_tokens / 1_000_000) * price.input_per_million + (
            output_tokens / 1_000_000
        ) * price.output_per_million

    def price_for(self, model: str) -> ModelPrice:
        normalized = model.lower().strip()
        for model_prefix, price in self.MODEL_PRICES.items():
            if normalized.startswith(model_prefix):
                return price
        if normalized.startswith(("local", "ollama", "mxbai")) or "local" in normalized:
            return ModelPrice(input_per_million=0.0, output_per_million=0.0)
        return self.DEFAULT_PRICE
