# M2a Go symbol fixture

Synthetic source and expected TSV were manually reasoned from the read-only
`src/code_diver/indexing/languages/go.py` extractor; Python was never executed.
TSV columns: Python splitlines start line, kind, name, stripped signature.
Grouped aliases and generic receivers are deliberately absent from the expected
Go strategy output. The shared router must apply generic fallback only when the
entire Go strategy result is empty, as `CodeSymbolExtractor.extract` does.
These fixtures assert catalog-facing symbols, not unused evidence or end spans.