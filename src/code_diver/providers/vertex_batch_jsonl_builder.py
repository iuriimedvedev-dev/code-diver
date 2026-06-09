from __future__ import annotations

import json
from pathlib import Path


class VertexBatchJsonlBuilder:
    def write(
        self,
        output: Path,
        prompts: list[str],
        max_output_tokens: int,
        temperature: float,
    ) -> int:
        output.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with output.open("w", encoding="utf-8") as handle:
            for prompt in prompts:
                handle.write(
                    json.dumps(
                        self._request(prompt, max_output_tokens=max_output_tokens, temperature=temperature),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
                handle.write("\n")
                count += 1
        return count

    def _request(self, prompt: str, max_output_tokens: int, temperature: float) -> dict[str, object]:
        return {
            "request": {
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": prompt}],
                    }
                ],
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": max_output_tokens,
                    "responseMimeType": "application/json",
                },
            }
        }
