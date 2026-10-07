# M3 request body provenance

Synthetic, manually recorded from reading Python CodeItem.to_embedding_text,
EmbeddingTextPreparer.prepare and OpenAIEmbeddingProvider._bounded_prefixed/_embed.
No Python process or real model request was executed; this is not an independently
captured Python HTTP request. The short input is below both truncation boundaries.
Long-input Rust parity is only with Python's tokenizer-unavailable character
fallback: cap each preparation at min(max_input_chars, (max_input_tokens - 32)*3),
then prefix and cap again. No exact Qwen token counts are claimed.