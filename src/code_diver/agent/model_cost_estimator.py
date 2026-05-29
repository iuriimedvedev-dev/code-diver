from __future__ import annotations


class ModelCostEstimator:
    # Conservative research estimate per one million tokens. Keep pricing configurable later.
    DEFAULT_INPUT_PER_MILLION = 1.50
    DEFAULT_OUTPUT_PER_MILLION = 9.00

    def estimate(self, model: str, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens / 1_000_000) * self.DEFAULT_INPUT_PER_MILLION + (
            output_tokens / 1_000_000
        ) * self.DEFAULT_OUTPUT_PER_MILLION
