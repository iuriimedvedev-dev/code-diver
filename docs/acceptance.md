# M6 acceptance — 0.5.0

## Opt-in real-machine run (not performed by CI)

Requires Bash, jq, curl, a built `code-diver`, compatible llama-server, access to
verified model downloads, a team profile file with shared artifact metadata, and
a supplied private key file. Use a read-only team collection and authorized
artifact endpoint. Setup can download large models and index artifacts; `--yes`
may install llama.cpp through brew if missing. Preinstall llama-server to avoid
that host-level effect. This is not a provisioner for a real cluster.

```sh
ACCEPTANCE_QDRANT_URL=https://qdrant.example.test:19438 \
ACCEPTANCE_COLLECTION=team_shared \
CODE_DIVER_BIN=/absolute/path/to/code-diver \
bash scripts/acceptance.sh /absolute/path/to/team.toml /absolute/path/to/key
```

Credentials must never appear in the URL, query, profile or command arguments;
use the key file (0600) or the CLI's named `QDRANT_API_KEY` environment reference.
The script still requires a key file as its second argument; env credentials can
take precedence according to CLI resolution. It never prints child stdout/stderr,
key contents, config, MCP result text or URLs. Do not invoke it with shell tracing.
Private temporary logs are deleted even after failure, so diagnose failures using
doctor separately in an authorized environment rather than exposing raw logs.

`HOME` is protected and **never changed**. A throwaway `CODE_DIVER_HOME` plus XDG
directories isolate application state, secrets, models, service files and host
paths; explicit `--config` prevents ambient `CODE_DIVER_CONFIG` reuse. This is
application-path isolation, not an OS sandbox: external tools can still consult
the real HOME. Fake `systemctl`/`launchctl` commands intercept service management;
`--no-register` prevents MCP registration. No real OS service is installed.
The temporary base uses its physical path to avoid macOS `/var`/`/tmp` symlink
aliases rejected by runtime path safety checks.

The default daemon port is **19437**, configurable through `ACCEPTANCE_PORT`;
Qdrant must be supplied explicitly. Ports 8090, 8001, 8081, 18081, 8002 and 6333
are rejected in daemon selection, supplied URL and profile endpoint text. Both
search and MCP explicitly use the daemon's embedding/reranking routes. Choose
unused ports and a profile without redirects to reserved endpoints; the script
is not a network firewall and cannot validate remote redirect destinations.

Sequence:

1. `setup --yes --no-register --profile FILE --key-file FILE`, with explicit
   isolated config, port and shared collection. During setup the fake manager
   starts one PID-recorded foreground daemon for setup's own final doctor.
2. Stop that bootstrap daemon; run `update-index` against the supplied artifacts.
3. Start `daemon --foreground` in the background and await its JSON health.
4. `doctor --json`: require a passing report with nonempty checks.
5. Search the supplied shared collection with required reranking, daemon URLs
   and autostart disabled. Require successful nonempty CLI output.
6. MCP stdio: initialize, initialized notification, tools/list, then
   `code_diver_search`; validate matching JSON-RPC IDs, no errors and result content.
7. Stop owned daemons/MCP/watchdog and delete only the owned temporary directory.

Every checked stage prints a PASS/FAIL table entry. Any stage or teardown failure
returns nonzero. `ACCEPTANCE_TIMEOUT` defaults to 600 seconds per command/RPC;
daemon readiness has a 60-attempt limit. PASS means those checks passed, not a
ranking benchmark: CLI output and MCP content do not prove nonempty relevant hits.
The profile/doctor remain responsible for actual artifact/model compatibility.

## Offline evidence (no cluster)

```sh
bash -n scripts/acceptance.sh scripts/acceptance-manager.sh scripts/tests/acceptance_test.sh scripts/tests/mock-code-diver.sh scripts/tests/mock-curl.sh
bash scripts/tests/acceptance_test.sh
```

Nine cases: complete success; setup, update-index, doctor process, doctor JSON,
CLI search, MCP initialize, MCP tools/list and MCP search failures. Shell mocks
execute the entire success sequence, assert foreground PIDs exit, application
home disappears, caller HOME/key remain unchanged, and a deliberately hostile
secret-bearing stderr is never forwarded or present in recorded argv. curl and
the CLI are mocked; these tests do not establish real daemon/model/Qdrant behavior.

CI uses both real crates' fmt/Clippy/tests on Ubuntu and macOS, then these shell
tests. Release publication is restricted to version tags after all four build
jobs succeed; manual dispatch builds only. `actionlint` was unavailable locally:
workflow triggers, expressions, permissions, target matrix, artifact paths and
tag gating were carefully reviewed instead. No release was pushed or published.