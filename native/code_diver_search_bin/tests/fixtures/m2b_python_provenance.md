# M2b Python lane

The source and TSV are synthetic, manually derived from the complete
`src/code_diver/indexing/languages/python.py` symbol extraction contract.
No Python indexer was executed. TSV columns are decorator-start line, kind,
name, signature. Physical definition text is preserved; decorators are
normalized independently. The `stub` declaration also exercises `.pyi` syntax;
extension routing belongs to the native integration owner.

The parser has no additional dependencies. Neither RustPython nor the Python
tree-sitter grammar was available in the local Cargo source cache at inspection.
Adding either would require dependency coordination and offline availability;
no dependency manifests or lockfiles were modified.

Unit tests in `python.rs` cover the golden, immediate class parent qualification,
nested functions, async methods, control suites, decorator order/calls/strings,
multiline headers, continuations, malformed input, comments/docstrings,
CRLF, BOM rejection, tabs, soft keywords, and Unicode signature truncation.
The parent must join and wire the module before running these tests:

```
cargo test --offline --manifest-path native/code_diver_search_bin/Cargo.toml catalog_builder::symbols::python
```

## Remaining parity risks

This is a tolerant token/suite parser, not a complete Python grammar. It rejects
lexical errors, unmatched brackets, missing declaration colons/names, missing
suites, inconsistent dedents, dangling decorators and common incomplete
expressions. It does **not** detect every input that `ast.parse` rejects (for
example invalid argument grammar or invalid expressions inside a balanced
statement). Thus SyntaxError-to-empty is implemented for detected errors, not
yet guaranteed for arbitrary malformed Python.

Decorator formatting covers common names, attributes, calls, keyword arguments,
lists/dicts and simple quoted strings. It is not a full `ast.unparse` replacement:
redundant grouping, operator precedence, complex literals/escape normalization,
f-strings, adjacent literal concatenation, comprehensions and tuple trailing
commas can differ. Unicode identifier normalization and exact XID validation
are also not implemented. No docstrings become symbols.

No real-catalog content/token/embed comparison was run in this worker. The
required >=99% target is **unverified**, not claimed. Parent integration and
real-catalog comparison should gate acceptance, especially decorated symbols.
Tests are intentionally deferred until the parent's join as requested.