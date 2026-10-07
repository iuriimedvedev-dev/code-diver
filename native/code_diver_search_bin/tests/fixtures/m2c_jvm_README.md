# M2c JVM fixtures

Synthetic Java/Kotlin sources and TSV expectations manually derived from
`JvmStrategy.extract_symbols` and `CodeSymbolExtractor` (read-only Python).
No Python implementation was executed. These are not Python-generated catalogs.
Unit tests in `symbols/jvm.rs` additionally cover declaration purpose and ordered
term inputs, first-line-only summary packages, doc adjacency, role and supertype
quirks, legacy empty-strategy fallback, Unicode and routing exclusion of Scala.
The module and summary/manifest hooks are now integrated. Joined offline
validation is green (169 distinct tests / 332 executions; STATUS.md). Current-rule
audit agreement does not resolve historical-reference uncertainty or meet the
>=99% real-reference acceptance target; see PARITY.md.