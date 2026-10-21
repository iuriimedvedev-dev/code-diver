# Native MCP Streamable HTTP server (TLS + OAuth 2.1)

`code-diver serve` exposes the same retrieval engine that powers the stdio MCP
server, but over the network:

- **Standard MCP Streamable HTTP** at `POST/GET/DELETE /mcp` (protocol revisions
  2024-11-05 … 2025-11-25, session header `Mcp-Session-Id`, SSE streaming).
- **Legacy JSON-RPC aliases** at `POST /mcp/rpc` and `POST /` for pre-spec
  clients (still the same tools, still the same runtime).
- **REST** endpoints (`/api/v1/search`, `/api/v1/grep`, …) and **ACP**
  (`/acp/v1/rpc`) unchanged.
- Optional **HTTPS** (including optional client certificates) and optional
  **OAuth 2.1** with dynamic client registration, PKCE and scopes.

Everything runs in one process with **one lazily created `SearchRuntime`**.
Sessions are cheap records; they never spawn a child process or reload the
index.

```
                       one uvicorn worker (one process)
  ┌──────────────────────────────────────────────────────────────────────┐
  │  FastAPI app (transport/http_server.py)                              │
  │                                                                      │
  │  CORS ──> OAuth guard ──> routes                                     │
  │                              │                                       │
  │   /mcp (Streamable HTTP) ────┤                                       │
  │   /mcp/rpc, / (legacy) ──────┼──> RemoteToolService ──┐              │
  │   /api/v1/* (REST) ──────────┤                        │              │
  │   /acp/v1/* (ACP) ───────────┘                        v              │
  │                                              get_runtime()           │
  │                                              (single instance)       │
  │                                                      │              │
  │                                                      v              │
  │                                            SearchRuntime            │
  │                                     strategies + vector store       │
  │                                     + graph + reranker (lazy)       │
  └──────────────────────────────────────────────────────────────────────┘
        ^                    ^                        ^
   MCP session 1       MCP session 2           MCP session N
   (client A)          (client B)              (client C)
```

`GET /api/v1/runtime/stats` returns `runtime.runtime_id`, `runtime_loads`,
`mcp_sessions` and per-tool counters. `runtime_loads` stays at `1` no matter how
many clients connect — that is the observable proof of the shared runtime.

## Quick start

```bash
# HTTP, no auth, spare port (do not disturb a running service)
code-diver serve \
  --config ~/.config/code-diver/cortex.yml \
  --host 127.0.0.1 --http-port 18080 --grpc-port 0

curl -s http://127.0.0.1:18080/health
curl -s http://127.0.0.1:18080/api/v1/runtime/stats | jq
```

Point an MCP client at `http://127.0.0.1:18080/mcp`:

```jsonc
// Claude Desktop / Cursor / OpenCode style configuration
{
  "mcpServers": {
    "code-diver": {
      "type": "http",
      "url": "https://mcp.example.internal:18080/mcp"
    }
  }
}
```

Clients that support MCP authorization discover the OAuth metadata from the
`WWW-Authenticate` challenge on the first `401`, register themselves via DCR,
open `/authorize`, and store the refresh token.

### Upgrade note: the old `/mcp` behaviour

Before this change `POST /mcp` was a plain JSON-RPC endpoint with no session
handshake. It remains available:

- Clients that send `Accept: application/json, text/event-stream` (the MCP SDK
  always does) get the **standard** transport.
- Clients that POST bare JSON without an SSE-capable `Accept` header are routed
  to the **legacy** handler, unchanged.
- Explicit legacy aliases `POST /mcp/rpc` and `POST /` are always legacy.
  `POST /` is disabled when OAuth is enabled, because it would bypass scopes.

## Transport details

| Aspect | Behaviour |
| --- | --- |
| `POST /mcp` | JSON-RPC request/notification. Returns `application/json`, or `text/event-stream` when the client accepts only SSE. |
| `GET /mcp` | Server→client SSE stream for an established session (keepalive pings). `Last-Event-ID` resumption is not implemented; a reconnect gets a fresh stream. |
| `DELETE /mcp` | Terminates the session (`204`). |
| Session | `initialize` creates one and returns `Mcp-Session-Id`. Later requests without it get `400`; unknown/expired/deleted ids get `404`. Sessions are bound to the bearer subject. |
| Protocol version | `Mcp-Protocol-Version` is validated for established sessions; unknown values get `400` with the supported list. Supported: `2024-11-05`, `2025-03-26`, `2025-06-18`, `2025-11-25`. |
| Modern probes | A `server/discover` probe (2026-era clients) returns JSON-RPC `-32601`, which tells the official SDK to fall back to the `initialize` handshake. |
| Notifications | Acknowledged with `202` and an empty body. |
| Limits | Body size (`CODE_DIVER_MCP_MAX_BODY`, 4 MiB), sessions (`CODE_DIVER_MCP_MAX_SESSIONS`, 256), idle expiry (`CODE_DIVER_MCP_SESSION_IDLE`, 1800 s). |
| CORS / Origin | `CODE_DIVER_CORS_ORIGINS` (comma list). Default: the issuer origin when OAuth is on, `*` otherwise. When restricted, `/mcp` rejects cross-origin browser requests with `403`, not just at the CORS layer. |

Tools exposed over HTTP: `code_diver_search`, `code_diver_grep`,
`code_diver_read`, `code_diver_symbols`, `code_diver_tree`, `code_diver_info`,
the async task tools (`code_diver_submit_agent_search`,
`code_diver_task_status`, `code_diver_task_result`, `code_diver_task_cancel`,
`code_diver_tasks_list`), plus the write tools `code_diver_index_trigger` and
`code_diver_index_ingest`.

## Scopes

| Scope | Grants |
| --- | --- |
| `code:read` | Search, grep, read, symbols, tree, info, async task tools. Read-only. |
| `code:write` | `code_diver_index_trigger` (spawns the canonical `code-diver index` job) and `code_diver_index_ingest` (writes under `<root>/.code_diver_remote_ingest`, path-traversal safe). |

`tools/list` only advertises tools the caller can use. Calling a write tool with
a read token returns JSON-RPC error `-32003` (`insufficient_scope`) with
`data.required_scope = "code:write"`. The REST write endpoints
(`/api/v1/index/*`) are protected by the same scope when OAuth is enabled.

## OAuth 2.1 flow

OAuth is **off by default**. Enable it explicitly:

```bash
export CODE_DIVER_OAUTH_ENABLED=1
export CODE_DIVER_OAUTH_ISSUER=https://mcp.example.internal:18080
export CODE_DIVER_OAUTH_JWT_SECRET_FILE=$HOME/.config/code-diver/oauth-jwt.secret   # >= 32 chars
export CODE_DIVER_OAUTH_CONSENT_SECRET='one-time-operator-code'
export CODE_DIVER_OAUTH_DB=$HOME/.local/share/code-diver/oauth.sqlite3
```

Then:

```
Client                                   Server
  │  POST /mcp                            │
  │──────────────────────────────────────>│  401
  │  WWW-Authenticate: Bearer             │
  │    resource_metadata="…/oauth-        │
  │    protected-resource"                │
  │                                       │
  │  GET /.well-known/oauth-protected-resource    (RFC 9728)
  │  GET /.well-known/oauth-authorization-server  (RFC 8414)
  │                                       │
  │  POST /register  (DCR, RFC 7591)      │
  │<──────────────────────────────────────│  client_id (+ secret for confidential clients)
  │                                       │
  │  GET /authorize?response_type=code&…&code_challenge=…&code_challenge_method=S256
  │<──────────────────────────────────────│  HTML consent form
  │  POST /authorize  (operator code)     │
  │──────────────────────────────────────>│  302 redirect_uri?code=…&state=…
  │                                       │
  │  POST /token  grant_type=authorization_code + code_verifier
  │<──────────────────────────────────────│  access_token (JWT, 15 min) + refresh_token
  │                                       │
  │  POST /mcp  Authorization: Bearer …   │
  │──────────────────────────────────────>│  200 + Mcp-Session-Id
```

Manual walk-through with `curl` (HTTP example; replace with `https://` and add
`--cacert` for TLS):

```bash
ISSUER=http://127.0.0.1:18080
curl -s $ISSUER/.well-known/oauth-protected-resource | jq
curl -s $ISSUER/.well-known/oauth-authorization-server | jq

CLIENT=$(curl -s -X POST $ISSUER/register \
  -H 'content-type: application/json' \
  -d '{"client_name":"curl","redirect_uris":["http://127.0.0.1:9999/cb"],"scope":"code:read"}' \
  | jq -r .client_id)

VERIFIER=$(python3 -c 'import secrets;print(secrets.token_urlsafe(64))')
CHALLENGE=$(printf %s "$VERIFIER" | openssl dgst -sha256 -binary | openssl base64 -A | tr '+/' '-_' | tr -d '=')

curl -s -G $ISSUER/authorize --data-urlencode response_type=code \
  --data-urlencode client_id=$CLIENT \
  --data-urlencode redirect_uri=http://127.0.0.1:9999/cb \
  --data-urlencode scope=code:read \
  --data-urlencode code_challenge=$CHALLENGE \
  --data-urlencode code_challenge_method=S256          # shows the consent form

# Submit the form (approval):
curl -s -o /dev/null -D - -X POST $ISSUER/authorize \
  -d response_type=code -d client_id=$CLIENT \
  -d redirect_uri=http://127.0.0.1:9999/cb -d scope=code:read \
  -d code_challenge=$CHALLENGE -d code_challenge_method=S256 \
  -d consent='one-time-operator-code'                   # 302 with ?code=…

curl -s -X POST $ISSUER/token \
  -d grant_type=authorization_code -d code=$CODE \
  -d redirect_uri=http://127.0.0.1:9999/cb \
  -d client_id=$CLIENT -d code_verifier=$VERIFIER
```

### Security semantics

- **Consent is never open.** `/authorize` renders a form gated by
  `CODE_DIVER_OAUTH_CONSENT_SECRET`; failures are rate-limited per peer
  (5 attempts / 60 s). `CODE_DIVER_OAUTH_AUTO_APPROVE=1` exists only for
  throwaway local instances and is loudly documented as unsafe.
- **PKCE S256 is mandatory** for every client. Plain challenges are rejected.
- Access tokens are HS256 JWTs with `iss`, `aud` (= the MCP resource URL),
  `exp`, `jti`, `scope`, `client_id` and `typ: at+jwt`. Algorithm and type are
  pinned during validation; `alg: none` and audience confusion are rejected.
- Refresh tokens are opaque, stored as SHA-256 hashes, rotated on every use
  (the old one stops working) and revocable. Authorization codes are single-use
  and expire after 60 s.
- Revocation (`POST /revoke`, RFC 7009) records the access-token `jti` or
  deletes the refresh token; revoked tokens fail immediately.
- Dynamic registration only accepts `https` redirect URIs, except loopback
  `http://127.0.0.1`/`localhost` (native clients). Fragments are rejected.
- The issuer must be `https` for non-loopback hosts unless
  `CODE_DIVER_OAUTH_ALLOW_INSECURE_ISSUER=1`.
- The SQLite store is created with `0600` in a `0700` directory.
- Access tokens are bearer credentials: HTTPS is strongly recommended whenever
  OAuth is enabled. `cmd_serve` refuses to start with TLS + OAuth when the
  issuer is not `https`.

### Configuration reference

| Variable | Default | Meaning |
| --- | --- | --- |
| `CODE_DIVER_OAUTH_ENABLED` | `0` | Master switch. Off keeps every existing deployment working. |
| `CODE_DIVER_OAUTH_ISSUER` | `http://127.0.0.1:8080` | Public URL used in metadata and JWT `iss`. Must match what clients reach. |
| `CODE_DIVER_OAUTH_RESOURCE` | `<issuer>/mcp` | RFC 8707 resource / JWT audience. |
| `CODE_DIVER_OAUTH_JWT_SECRET` | — | HS256 secret, ≥ 32 chars (required). |
| `CODE_DIVER_OAUTH_JWT_SECRET_FILE` | — | File alternative to the secret (preferred for systemd). |
| `CODE_DIVER_OAUTH_CONSENT_SECRET` | — | Operator code for `/authorize` (required unless auto-approve). |
| `CODE_DIVER_OAUTH_AUTO_APPROVE` | `0` | Skip the consent form (unsafe; local only). |
| `CODE_DIVER_OAUTH_ACCESS_TTL` | `900` | Access-token lifetime (seconds). |
| `CODE_DIVER_OAUTH_REFRESH_TTL` | `2592000` | Refresh-token lifetime (seconds). |
| `CODE_DIVER_OAUTH_CODE_TTL` | `60` | Authorization-code lifetime (seconds). |
| `CODE_DIVER_OAUTH_DB` | `~/.local/share/code-diver/oauth.sqlite3` | Client/token store. |
| `CODE_DIVER_OAUTH_PROTECT_REST` | `1` | Also require `code:read`/`code:write` on `/api/*`. |
| `CODE_DIVER_OAUTH_MAX_CLIENTS` | `500` | Registration cap. |
| `CODE_DIVER_OAUTH_ALLOW_INSECURE_ISSUER` | `0` | Allow `http` issuer on non-loopback hosts. |
| `CODE_DIVER_MCP_MAX_SESSIONS` | `256` | Concurrent sessions. |
| `CODE_DIVER_MCP_SESSION_IDLE` | `1800` | Idle expiry (seconds). |
| `CODE_DIVER_MCP_SSE_PING` | `15` | SSE keepalive interval (seconds). |
| `CODE_DIVER_MCP_MAX_BODY` | `4194304` | Max POST body (bytes). |
| `CODE_DIVER_CORS_ORIGINS` | issuer / `*` | Comma-separated allowed origins. |
| `CODE_DIVER_INDEX_TIMEOUT` | `3600` | Timeout for a triggered index job (seconds). |
| `CODE_DIVER_INGEST_MAX_FILES` | `500` | Max files per ingest call. |

CLI flags `code-diver serve`: `--tls-cert`, `--tls-key`, `--tls-client-ca`,
`--require-client-cert`, `--oauth-issuer`, `--no-oauth`. Flags win over the
matching `CODE_DIVER_TLS_*` values where both exist.

## TLS

| Variable | Meaning |
| --- | --- |
| `CODE_DIVER_TLS_CERT` | PEM certificate chain, leaf first. |
| `CODE_DIVER_TLS_KEY` | PEM private key (unencrypted, `chmod 600`). |
| `CODE_DIVER_TLS_CLIENT_CA` | CA bundle for client certificates. |
| `CODE_DIVER_TLS_REQUIRE_CLIENT_CERT` | `1` to require mTLS. |

Both cert and key must be set together; missing files or a key readable by
group/other is reported (the latter as a warning). Requiring client certs
without a CA is a hard error.

### Local certificates with mkcert

```bash
mkcert -install
mkdir -p ~/.config/code-diver/tls
mkcert -cert-file ~/.config/code-diver/tls/server.pem \
       -key-file  ~/.config/code-diver/tls/server.key \
       127.0.0.1 mcp.example.internal
chmod 600 ~/.config/code-diver/tls/server.key

export CODE_DIVER_TLS_CERT=$HOME/.config/code-diver/tls/server.pem
export CODE_DIVER_TLS_KEY=$HOME/.config/code-diver/tls/server.key
export CODE_DIVER_OAUTH_ISSUER=https://mcp.example.internal:18080
code-diver serve --config ~/.config/code-diver/cortex.yml \
  --host 127.0.0.1 --http-port 18080 --grpc-port 0
```

Verify:

```bash
curl --cacert "$(mkcert -CAROOT)/rootCA.pem" https://127.0.0.1:18080/health
```

For a private CA or mTLS, use the CA bundle in `CODE_DIVER_TLS_CLIENT_CA` and
give clients a certificate signed by it. Never commit keys or certificates.

## systemd user service (migration and rollback)

The unit is additive: it does **not** touch the existing
`code-diver-daemon@<project>.service` (stdio shim over a unix socket) or the
model daemons. The HTTP server binds loopback and a spare port, so both can run
side by side during migration.

```bash
install -Dm644 deploy/systemd-user/code-diver-http@.service \
  ~/.config/systemd/user/code-diver-http@.service
install -Dm600 deploy/systemd-user/code-diver-http.env.example \
  ~/.config/code-diver/cortex.http.env
$EDITOR ~/.config/code-diver/cortex.http.env     # port, TLS, OAuth, issuer
systemctl --user daemon-reload
systemctl --user enable --now code-diver-http@cortex.service
systemctl --user status code-diver-http@cortex.service --no-pager
curl -fsS http://127.0.0.1:18080/health
```

Switch clients (Claude Desktop/Cursor/OpenCode) from the stdio command to the
HTTP URL, verify a tool call, then keep the stdio daemon if you still want
local agents.

**Rollback** is two commands and does not require a rebuild:

```bash
systemctl --user disable --now code-diver-http@cortex.service
# optional: remove ~/.config/code-diver/cortex.http.env
```

Point clients back to the stdio configuration. The OAuth store at
`~/.local/share/code-diver/oauth.sqlite3` can be deleted to invalidate every
client token at once.

## Verification checklist

```bash
# 1. shared runtime: after N clients, loads stays 1
curl -s http://127.0.0.1:18080/api/v1/runtime/stats | jq '.runtime_loads, .mcp_sessions'

# 2. 401 challenge
curl -si -X POST http://127.0.0.1:18080/mcp -H 'accept: application/json, text/event-stream' \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' | head -5

# 3. metadata
curl -s http://127.0.0.1:18080/.well-known/oauth-protected-resource | jq

# 4. real tool call (with a token from the flow above)
curl -s -X POST http://127.0.0.1:18080/mcp \
  -H "authorization: Bearer $ACCESS_TOKEN" \
  -H 'accept: application/json, text/event-stream' \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}' \
  -D /tmp/headers.txt | jq
```

Run the test suite for the transport module:

```bash
pytest tests/unit/test_oauth.py tests/unit/test_mcp_http.py tests/unit/test_tls.py \
       tests/e2e/test_http_mcp_oauth_e2e.py -q
```

## Known limits

- One uvicorn worker. Multiple workers would each own a `SearchRuntime`;
  scale vertically (bigger host) or run one process per project/port. The
  shared-runtime guarantee is per process by design.
- SSE resumption (`Last-Event-ID`) is not implemented; clients reconnect and
  re-initialize.
- The gRPC transport is not covered by OAuth. Bind it to loopback or disable
  it with `--grpc-port 0` when exposing HTTP publicly.
- OAuth tokens are bearer tokens: terminate TLS at the server (or a reverse
  proxy you control) and keep the issuer URL exact — clients reject metadata
  whose `issuer` differs from the URL they used.
