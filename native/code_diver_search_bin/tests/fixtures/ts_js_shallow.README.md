# TS/JS shallow-symbol golden

Synthetic source and expected TSV are manually derived from the ordered regexes in
`src/code_diver/indexing/languages/ts_js.py`; Python was not executed. TSV columns
are one-based line, kind, name, and stripped signature. This is a reasoned symbol
oracle, not an independently Python-generated catalog or measured parity result.

Classes/interfaces/types precede const functions, standard functions, and exported
values. Exported arrows that fail the shallow regex fall through to `symbol`;
non-exported values disappear. Only the first declaration on a line is recognized.
Comment filtering checks line prefixes only, so line 14 leaks from a block comment.
Indentation is stripped but inline comments remain. Identifier starts are ASCII
letters/underscore/dollar; continuations permit Unicode alphanumeric and dollar.
Names retain source-line order rather than global alphabetical order.

The same extractor applies to `.ts`, `.tsx`, `.js`, `.jsx`, `.mjs`, `.cjs`, `.mts`,
and `.cts`; extension routing is owned by integration. Unit tests additionally
cover Unicode 240-code-point truncation, Python splitlines/whitespace, BOM,
unsupported modifiers, nested generic/parameter failures, and function-boundary
quirks. End lines/spans and import evidence are not part of the catalog interface.