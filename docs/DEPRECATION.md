# Deprecation status — 0.5.0

The single Rust `code-diver` executable is the supported path for new installation,
setup, daemon, shared-index refresh, doctor, search and MCP stdio usage.
The Python package, Python launch commands and historical research services are
deprecated for new installations. They remain in the repository for historical
research and compatibility; this milestone does not delete them or claim parity
for every experimental command. Existing deployments must validate their own
profiles, model identity and collection before migrating.

Rust CI has no Python dependency. Release assets are not claimed published;
successful four-target builds, tag publication and real-machine shared-collection
acceptance are still release gates. See [acceptance](acceptance.md) and the dated
[rewrite status](rust-rewrite/STATUS.md). Historical benchmark versions are not
the current product version and are intentionally preserved.