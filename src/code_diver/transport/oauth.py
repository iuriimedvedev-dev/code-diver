"""Self-contained OAuth 2.1 authorization server for the Code Diver MCP endpoint.

The module implements just enough of the OAuth 2.1 / MCP authorization
specification to protect ``/mcp`` without an external identity provider:

* RFC 9728 protected-resource metadata
* RFC 8414 authorization-server metadata
* RFC 7591 dynamic client registration (public clients + PKCE S256)
* authorization-code grant with mandatory PKCE S256
* refresh-token grant with rotation
* RFC 7009 token revocation
* RFC 6750 bearer-token authentication with ``WWW-Authenticate`` challenges

Access tokens are HS256 JWTs (PyJWT) carrying a ``scope`` claim; refresh
tokens and authorization codes are opaque random strings stored as SHA-256
hashes in SQLite, so a database leak does not leak usable credentials.

OAuth is disabled unless ``CODE_DIVER_OAUTH_ENABLED=1``. When enabled the
operator must provide a signing secret and (unless auto-approval is enabled)
a consent secret that gates ``/authorize``.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import html
import json
import logging
import os
import re
import secrets
import sqlite3
import threading
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote_plus, urlencode, urlsplit

import jwt
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

logger = logging.getLogger("code_diver.transport.oauth")

READ_SCOPE = "code:read"
WRITE_SCOPE = "code:write"
SUPPORTED_SCOPES: tuple[str, ...] = (READ_SCOPE, WRITE_SCOPE)

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TYPE = "at+jwt"

_SCOPE_RE = re.compile(r"^[A-Za-z0-9._:-]+$")
_PKCE_CHALLENGE_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
_PKCE_VERIFIER_RE = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")
_CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9._~-]{8,128}$")

DEFAULT_ACCESS_TOKEN_TTL = 900
DEFAULT_REFRESH_TOKEN_TTL = 30 * 24 * 3600
DEFAULT_AUTH_CODE_TTL = 60
DEFAULT_MAX_CLIENTS = 500
DEFAULT_MAX_REDIRECT_URIS = 10
DEFAULT_MAX_SESSIONS = 256


def _now() -> float:
    """Wall clock in epoch seconds (indirection kept patchable in tests)."""
    return time.time()


def _b64url_sha256(value: str) -> str:
    digest = hashlib.sha256(value.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def code_challenge_for(verifier: str) -> str:
    """Return the RFC 7636 S256 challenge for a code verifier."""
    if not _PKCE_VERIFIER_RE.match(verifier):
        raise ValueError("code_verifier must be 43-128 characters of [A-Za-z0-9._~-]")
    return _b64url_sha256(verifier)


def verify_pkce(verifier: str | None, challenge: str, method: str = "S256") -> bool:
    """Constant-time PKCE verification; only S256 is accepted."""
    if method != "S256" or not verifier or not challenge:
        return False
    if not _PKCE_VERIFIER_RE.match(verifier):
        return False
    return hmac.compare_digest(_b64url_sha256(verifier), challenge)


def generate_code_verifier() -> str:
    """Generate a spec-compliant PKCE verifier (used by tests and docs)."""
    return secrets.token_urlsafe(64)[:96]


def parse_scopes(raw: str | Iterable[str] | None) -> frozenset[str]:
    """Parse a space-delimited scope string into a set of known scopes."""
    if raw is None:
        return frozenset()
    tokens = raw.split() if isinstance(raw, str) else [token for value in raw for token in str(value).split()]
    scopes: set[str] = set()
    for token in tokens:
        if not _SCOPE_RE.match(token):
            raise OAuthError("invalid_scope", f"Malformed scope: {token!r}")
        if token not in SUPPORTED_SCOPES:
            raise OAuthError("invalid_scope", f"Unsupported scope: {token}")
        scopes.add(token)
    return frozenset(scopes)


def format_scopes(scopes: Iterable[str]) -> str:
    """Render scopes in canonical order as a space-delimited string."""
    return " ".join(scope for scope in SUPPORTED_SCOPES if scope in set(scopes))


class OAuthError(Exception):
    """OAuth protocol error carrying the RFC 6749 error code and HTTP status."""

    def __init__(
        self,
        error: str,
        description: str = "",
        status_code: int = 400,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(description or error)
        self.error = error
        self.description = description
        self.status_code = status_code
        self.headers = dict(headers or {})

    def to_response(self) -> JSONResponse:
        payload: dict[str, Any] = {"error": self.error}
        if self.description:
            payload["error_description"] = self.description
        headers = {"Cache-Control": "no-store", "Pragma": "no-cache", **self.headers}
        return JSONResponse(payload, status_code=self.status_code, headers=headers)


@dataclass(frozen=True)
class OAuthSettings:
    """Resolved OAuth configuration (env-driven in production)."""

    enabled: bool = False
    issuer: str = "http://127.0.0.1:8080"
    resource: str = ""
    jwt_secret: str = ""
    consent_secret: str | None = None
    auto_approve: bool = False
    access_token_ttl: int = DEFAULT_ACCESS_TOKEN_TTL
    refresh_token_ttl: int = DEFAULT_REFRESH_TOKEN_TTL
    auth_code_ttl: int = DEFAULT_AUTH_CODE_TTL
    db_path: str = ""
    protect_rest: bool = True
    max_clients: int = DEFAULT_MAX_CLIENTS
    max_redirect_uris: int = DEFAULT_MAX_REDIRECT_URIS
    allow_insecure_issuer: bool = False

    @property
    def protected_resource_metadata_url(self) -> str:
        return f"{self.issuer}/.well-known/oauth-protected-resource"

    @property
    def authorization_server_metadata_url(self) -> str:
        return f"{self.issuer}/.well-known/oauth-authorization-server"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> OAuthSettings:
        source = os.environ if env is None else env
        enabled = _env_flag(source, "CODE_DIVER_OAUTH_ENABLED", False)
        issuer = (source.get("CODE_DIVER_OAUTH_ISSUER") or "http://127.0.0.1:8080").rstrip("/")
        if not issuer:
            raise ValueError("CODE_DIVER_OAUTH_ISSUER must not be empty")
        parts = urlsplit(issuer)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError(f"CODE_DIVER_OAUTH_ISSUER must be an absolute http(s) URL, got {issuer!r}")
        allow_insecure = _env_flag(source, "CODE_DIVER_OAUTH_ALLOW_INSECURE_ISSUER", False)
        if parts.scheme != "https" and not allow_insecure and not _is_loopback(parts.hostname):
            raise ValueError(
                "CODE_DIVER_OAUTH_ISSUER must use https outside loopback "
                "(set CODE_DIVER_OAUTH_ALLOW_INSECURE_ISSUER=1 only for trusted LAN setups)"
            )
        secret = source.get("CODE_DIVER_OAUTH_JWT_SECRET", "")
        secret_file = source.get("CODE_DIVER_OAUTH_JWT_SECRET_FILE", "")
        if secret_file:
            secret = Path(secret_file).expanduser().read_text(encoding="utf-8").strip()
        if enabled and len(secret) < 32:
            raise ValueError(
                "CODE_DIVER_OAUTH_JWT_SECRET must be set to at least 32 characters when OAuth is enabled "
                "(or provide CODE_DIVER_OAUTH_JWT_SECRET_FILE)"
            )
        consent = source.get("CODE_DIVER_OAUTH_CONSENT_SECRET") or None
        auto_approve = _env_flag(source, "CODE_DIVER_OAUTH_AUTO_APPROVE", False)
        if enabled and not consent and not auto_approve:
            raise ValueError(
                "CODE_DIVER_OAUTH_CONSENT_SECRET is required when OAuth is enabled; "
                "it gates the /authorize consent form. Set CODE_DIVER_OAUTH_AUTO_APPROVE=1 only for "
                "throwaway local instances."
            )
        db_path = source.get("CODE_DIVER_OAUTH_DB") or str(
            Path.home() / ".local" / "share" / "code-diver" / "oauth.sqlite3"
        )
        resource = (source.get("CODE_DIVER_OAUTH_RESOURCE") or f"{issuer}/mcp").rstrip("/")
        return cls(
            enabled=enabled,
            issuer=issuer,
            resource=resource,
            jwt_secret=secret,
            consent_secret=consent,
            auto_approve=auto_approve,
            access_token_ttl=_env_int(source, "CODE_DIVER_OAUTH_ACCESS_TTL", DEFAULT_ACCESS_TOKEN_TTL, minimum=60),
            refresh_token_ttl=_env_int(
                source, "CODE_DIVER_OAUTH_REFRESH_TTL", DEFAULT_REFRESH_TOKEN_TTL, minimum=300
            ),
            auth_code_ttl=_env_int(source, "CODE_DIVER_OAUTH_CODE_TTL", DEFAULT_AUTH_CODE_TTL, minimum=10),
            db_path=db_path,
            protect_rest=_env_flag(source, "CODE_DIVER_OAUTH_PROTECT_REST", True),
            max_clients=_env_int(source, "CODE_DIVER_OAUTH_MAX_CLIENTS", DEFAULT_MAX_CLIENTS, minimum=1),
            max_redirect_uris=_env_int(
                source, "CODE_DIVER_OAUTH_MAX_REDIRECT_URIS", DEFAULT_MAX_REDIRECT_URIS, minimum=1
            ),
            allow_insecure_issuer=allow_insecure,
        )


def _env_flag(source: Mapping[str, str], key: str, default: bool) -> bool:
    raw = source.get(key)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(source: Mapping[str, str], key: str, default: int, *, minimum: int) -> int:
    raw = source.get(key)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{key} must be an integer, got {raw!r}") from exc
    if value < minimum:
        raise ValueError(f"{key} must be >= {minimum}, got {value}")
    return value


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    return host in {"localhost", "127.0.0.1", "::1"} or host.startswith("127.")


@dataclass(frozen=True)
class Principal:
    """Authenticated bearer-token identity attached to a request."""

    subject: str
    client_id: str
    scopes: frozenset[str]
    jti: str
    expires_at: int
    resource: str

    def has(self, required: str | Iterable[str] | None) -> bool:
        if required is None:
            return True
        if isinstance(required, str):
            return required in self.scopes
        return set(required).issubset(self.scopes)


@dataclass(frozen=True)
class AuthorizationRequest:
    """Validated ``/authorize`` request."""

    client_id: str
    client_name: str
    redirect_uri: str
    scope: str
    state: str | None
    code_challenge: str
    resource: str
    fields: dict[str, str] = field(default_factory=dict)


class OAuthStore:
    """SQLite-backed storage for clients, authorization codes and refresh tokens."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.RLock()
        if path != ":memory:":
            db_path = Path(path).expanduser()
            db_path.parent.mkdir(parents=True, exist_ok=True)
            with contextlib.suppress(OSError):  # best effort on exotic filesystems
                db_path.parent.chmod(0o700)
            self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
            with contextlib.suppress(OSError):
                db_path.chmod(0o600)
            self._conn.execute("PRAGMA journal_mode=WAL")
        else:
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS clients (
                    client_id TEXT PRIMARY KEY,
                    client_secret_hash TEXT,
                    client_name TEXT NOT NULL DEFAULT '',
                    redirect_uris TEXT NOT NULL,
                    grant_types TEXT NOT NULL,
                    response_types TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    token_endpoint_auth_method TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS auth_codes (
                    code_hash TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    redirect_uri TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    code_challenge TEXT NOT NULL,
                    code_challenge_method TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS refresh_tokens (
                    token_hash TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS revoked_access (
                    jti TEXT PRIMARY KEY,
                    expires_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_refresh_client ON refresh_tokens(client_id);
                """
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # --- clients -----------------------------------------------------------
    def insert_client(self, record: Mapping[str, Any]) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO clients (client_id, client_secret_hash, client_name, redirect_uris, grant_types, "
                "response_types, scope, token_endpoint_auth_method, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record["client_id"],
                    record.get("client_secret_hash"),
                    record.get("client_name", ""),
                    json.dumps(record["redirect_uris"]),
                    json.dumps(record["grant_types"]),
                    json.dumps(record["response_types"]),
                    record["scope"],
                    record["token_endpoint_auth_method"],
                    int(record["created_at"]),
                ),
            )

    def get_client(self, client_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM clients WHERE client_id = ?", (client_id,)).fetchone()
        if row is None:
            return None
        return {
            "client_id": row["client_id"],
            "client_secret_hash": row["client_secret_hash"],
            "client_name": row["client_name"],
            "redirect_uris": json.loads(row["redirect_uris"]),
            "grant_types": json.loads(row["grant_types"]),
            "response_types": json.loads(row["response_types"]),
            "scope": row["scope"],
            "token_endpoint_auth_method": row["token_endpoint_auth_method"],
            "created_at": row["created_at"],
        }

    def count_clients(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM clients").fetchone()
        return int(row["n"])

    # --- authorization codes ----------------------------------------------
    def insert_code(self, record: Mapping[str, Any]) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO auth_codes (code_hash, client_id, subject, redirect_uri, scope, code_challenge, "
                "code_challenge_method, resource, expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record["code_hash"],
                    record["client_id"],
                    record["subject"],
                    record["redirect_uri"],
                    record["scope"],
                    record["code_challenge"],
                    record["code_challenge_method"],
                    record["resource"],
                    int(record["expires_at"]),
                    int(record["created_at"]),
                ),
            )

    def consume_code(self, code_hash: str, now: float) -> dict[str, Any] | None:
        """Delete and return an authorization code atomically (single use)."""
        with self._lock, self._conn:
            row = self._conn.execute("SELECT * FROM auth_codes WHERE code_hash = ?", (code_hash,)).fetchone()
            if row is None:
                return None
            self._conn.execute("DELETE FROM auth_codes WHERE code_hash = ?", (code_hash,))
        if int(row["expires_at"]) < int(now):
            return None
        return dict(row)

    # --- refresh tokens ----------------------------------------------------
    def insert_refresh(self, record: Mapping[str, Any]) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO refresh_tokens (token_hash, client_id, subject, scope, resource, expires_at, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    record["token_hash"],
                    record["client_id"],
                    record["subject"],
                    record["scope"],
                    record["resource"],
                    int(record["expires_at"]),
                    int(record["created_at"]),
                ),
            )

    def consume_refresh(self, token_hash: str, now: float) -> dict[str, Any] | None:
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT * FROM refresh_tokens WHERE token_hash = ?", (token_hash,)
            ).fetchone()
            if row is None:
                return None
            self._conn.execute("DELETE FROM refresh_tokens WHERE token_hash = ?", (token_hash,))
        if int(row["expires_at"]) < int(now):
            return None
        return dict(row)

    def get_refresh(self, token_hash: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM refresh_tokens WHERE token_hash = ?", (token_hash,)
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def delete_refresh(self, token_hash: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM refresh_tokens WHERE token_hash = ?", (token_hash,))
        return cur.rowcount > 0

    # --- access-token revocation ------------------------------------------
    def revoke_jti(self, jti: str, expires_at: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO revoked_access (jti, expires_at) VALUES (?, ?)",
                (jti, int(expires_at)),
            )

    def is_revoked(self, jti: str) -> bool:
        with self._lock:
            row = self._conn.execute("SELECT 1 FROM revoked_access WHERE jti = ?", (jti,)).fetchone()
        return row is not None

    def purge_expired(self, now: float) -> None:
        stamp = int(now)
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM auth_codes WHERE expires_at < ?", (stamp,))
            self._conn.execute("DELETE FROM refresh_tokens WHERE expires_at < ?", (stamp,))
            self._conn.execute("DELETE FROM revoked_access WHERE expires_at < ?", (stamp,))


class _ConsentThrottle:
    """Tiny in-memory brute-force guard for the consent form."""

    def __init__(self, max_attempts: int = 5, window_seconds: int = 60) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._lock = threading.Lock()
        self._attempts: dict[str, list[float]] = {}

    def check(self, key: str, now: float) -> bool:
        with self._lock:
            stamps = [stamp for stamp in self._attempts.get(key, []) if now - stamp < self.window_seconds]
            self._attempts[key] = stamps
            return len(stamps) < self.max_attempts

    def record_failure(self, key: str, now: float) -> None:
        with self._lock:
            self._attempts.setdefault(key, []).append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)


class OAuthProvider:
    """OAuth 2.1 authorization server bound to a single MCP resource."""

    def __init__(self, settings: OAuthSettings, store: OAuthStore | None = None) -> None:
        if not settings.jwt_secret and settings.enabled:
            raise ValueError("OAuthProvider requires a JWT secret")
        self.settings = settings
        self.store = store or OAuthStore(settings.db_path or ":memory:")
        self._throttle = _ConsentThrottle()

    # --- metadata ----------------------------------------------------------
    def protected_resource_metadata(self) -> dict[str, Any]:
        return {
            "resource": self.settings.resource,
            "authorization_servers": [self.settings.issuer],
            "scopes_supported": list(SUPPORTED_SCOPES),
            "bearer_methods_supported": ["header"],
            "resource_name": "code-diver MCP",
            "resource_documentation": "https://github.com/iuriimedvedev-dev/code-diver",
        }

    def authorization_server_metadata(self) -> dict[str, Any]:
        issuer = self.settings.issuer
        return {
            "issuer": issuer,
            "authorization_endpoint": f"{issuer}/authorize",
            "token_endpoint": f"{issuer}/token",
            "registration_endpoint": f"{issuer}/register",
            "revocation_endpoint": f"{issuer}/revoke",
            "scopes_supported": list(SUPPORTED_SCOPES),
            "response_types_supported": ["code"],
            "response_modes_supported": ["query"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none", "client_secret_basic", "client_secret_post"],
            "revocation_endpoint_auth_methods_supported": [
                "none",
                "client_secret_basic",
                "client_secret_post",
            ],
            "service_documentation": "https://github.com/iuriimedvedev-dev/code-diver/blob/main/docs/http-mcp.md",
        }

    # --- dynamic client registration --------------------------------------
    def register_client(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if self.store.count_clients() >= self.settings.max_clients:
            raise OAuthError("invalid_client_metadata", "Client registration limit reached", status_code=429)
        redirect_uris = payload.get("redirect_uris")
        if not isinstance(redirect_uris, list) or not redirect_uris:
            raise OAuthError("invalid_redirect_uri", "redirect_uris must be a non-empty array")
        if len(redirect_uris) > self.settings.max_redirect_uris:
            raise OAuthError(
                "invalid_redirect_uri",
                f"At most {self.settings.max_redirect_uris} redirect URIs are allowed",
            )
        cleaned: list[str] = []
        for uri in redirect_uris:
            if not isinstance(uri, str):
                raise OAuthError("invalid_redirect_uri", "redirect_uris entries must be strings")
            cleaned.append(_validate_redirect_uri(uri))
        auth_method = payload.get("token_endpoint_auth_method", "none")
        if auth_method not in {"none", "client_secret_basic", "client_secret_post"}:
            raise OAuthError("invalid_client_metadata", f"Unsupported token_endpoint_auth_method: {auth_method}")
        grant_types = payload.get("grant_types") or ["authorization_code", "refresh_token"]
        if not isinstance(grant_types, list) or any(
            grant not in {"authorization_code", "refresh_token"} for grant in grant_types
        ):
            raise OAuthError("invalid_client_metadata", "Unsupported grant_types")
        if "authorization_code" not in grant_types:
            raise OAuthError("invalid_client_metadata", "grant_types must include authorization_code")
        response_types = payload.get("response_types") or ["code"]
        if response_types != ["code"]:
            raise OAuthError("invalid_client_metadata", "Only response_type=code is supported")
        try:
            scope = parse_scopes(payload.get("scope") or format_scopes(SUPPORTED_SCOPES))
        except OAuthError as exc:
            raise OAuthError("invalid_client_metadata", exc.description) from exc
        if not scope:
            raise OAuthError("invalid_client_metadata", "At least one scope must be granted")
        client_id = f"cd_{secrets.token_urlsafe(24)}"
        if not _CLIENT_ID_RE.match(client_id):  # pragma: no cover - defensive
            raise OAuthError("invalid_client_metadata", "Generated client_id is malformed")
        client_secret = secrets.token_urlsafe(32) if auth_method != "none" else None
        now = int(_now())
        record = {
            "client_id": client_id,
            "client_secret_hash": _sha256(client_secret) if client_secret else None,
            "client_name": str(payload.get("client_name") or "MCP client")[:120],
            "redirect_uris": cleaned,
            "grant_types": grant_types,
            "response_types": response_types,
            "scope": format_scopes(scope),
            "token_endpoint_auth_method": auth_method,
            "created_at": now,
        }
        self.store.insert_client(record)
        logger.info("oauth: registered client %s (%s)", client_id, record["client_name"])
        response: dict[str, Any] = {
            "client_id": client_id,
            "client_id_issued_at": now,
            "client_name": record["client_name"],
            "redirect_uris": cleaned,
            "grant_types": grant_types,
            "response_types": response_types,
            "scope": record["scope"],
            "token_endpoint_auth_method": auth_method,
        }
        if client_secret:
            response["client_secret"] = client_secret
            response["client_secret_expires_at"] = 0
        return response

    # --- authorization endpoint -------------------------------------------
    def validate_authorization_request(self, params: Mapping[str, str]) -> AuthorizationRequest:
        client_id = params.get("client_id") or ""
        client = self.store.get_client(client_id)
        if client is None:
            raise OAuthError("invalid_client", "Unknown client_id", status_code=400)
        redirect_uri = params.get("redirect_uri") or ""
        if redirect_uri not in client["redirect_uris"]:
            raise OAuthError("invalid_request", "redirect_uri is not registered for this client")
        if params.get("response_type") != "code":
            raise OAuthError("unsupported_response_type", "Only response_type=code is supported")
        try:
            requested = parse_scopes(params.get("scope") or client["scope"])
        except OAuthError:
            raise
        if not requested.issubset(parse_scopes(client["scope"])):
            raise OAuthError("invalid_scope", "Requested scope exceeds the registered client scope")
        challenge = params.get("code_challenge") or ""
        method = params.get("code_challenge_method") or ""
        if not _PKCE_CHALLENGE_RE.match(challenge):
            raise OAuthError("invalid_request", "code_challenge must be a 43-char S256 challenge")
        if method != "S256":
            raise OAuthError("invalid_request", "code_challenge_method must be S256")
        resource = params.get("resource") or self.settings.resource
        if resource.rstrip("/") not in {self.settings.resource, self.settings.issuer}:
            raise OAuthError("invalid_target", "resource does not match this MCP server")
        state = params.get("state")
        if state is not None and (len(state) > 512 or any(ord(ch) < 0x20 for ch in state)):
            raise OAuthError("invalid_request", "state is malformed")
        fields = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": format_scopes(requested),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "resource": self.settings.resource,
        }
        if state:
            fields["state"] = state
        return AuthorizationRequest(
            client_id=client_id,
            client_name=client["client_name"],
            redirect_uri=redirect_uri,
            scope=format_scopes(requested),
            state=state,
            code_challenge=challenge,
            resource=self.settings.resource,
            fields=fields,
        )

    def consent_page(self, request: AuthorizationRequest, *, error: str | None = None) -> HTMLResponse:
        hidden = "\n".join(
            f'<input type="hidden" name="{html.escape(name)}" value="{html.escape(value)}">'
            for name, value in request.fields.items()
        )
        scopes = "".join(
            f"<li><code>{html.escape(scope)}</code> — "
            f"{'read-only search, read, grep, tree, symbols' if scope == READ_SCOPE else 'index trigger and remote ingest'}</li>"
            for scope in request.scope.split()
        )
        error_block = (
            f'<p class="error" role="alert">{html.escape(error)}</p>' if error else ""
        )
        page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Authorize code-diver</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: ui-sans-serif, system-ui, sans-serif; margin: 0; display: grid; place-items: center; min-height: 100vh; background: #0f1115; color: #e7e9ee; }}
  main {{ width: min(30rem, calc(100vw - 3rem)); background: #171a21; border: 1px solid #2a2f3a; border-radius: 14px; padding: 2rem; }}
  h1 {{ font-size: 1.2rem; margin: 0 0 .25rem; }}
  p {{ color: #a8b0be; font-size: .92rem; line-height: 1.5; }}
  p.error {{ color: #ff9a9a; background: #2a1717; border: 1px solid #5a2b2b; padding: .6rem .8rem; border-radius: 8px; }}
  ul {{ color: #cdd3de; font-size: .9rem; }}
  input[type=password] {{ width: 100%; box-sizing: border-box; margin: .4rem 0 1.1rem; padding: .7rem .8rem; border-radius: 8px; border: 1px solid #333a47; background: #0f1115; color: inherit; font: inherit; }}
  button {{ width: 100%; padding: .75rem; border: 0; border-radius: 8px; background: #4f8cff; color: #06101f; font: inherit; font-weight: 600; cursor: pointer; }}
  code {{ background: #0f1115; padding: .1rem .35rem; border-radius: 4px; }}
  small {{ color: #78818f; display: block; margin-top: 1rem; }}
</style>
</head>
<body>
<main>
  <h1>Authorize {html.escape(request.client_name)}</h1>
  <p>The MCP client wants access to this Code Diver index.</p>
  <ul>{scopes}</ul>
  {error_block}
  <form method="post" action="/authorize">
    {hidden}
    <label for="consent">Operator access code</label>
    <input id="consent" name="consent" type="password" autocomplete="current-password" required autofocus>
    <button type="submit">Authorize</button>
  </form>
  <small>Set with <code>CODE_DIVER_OAUTH_CONSENT_SECRET</code>. Nothing is approved without it.</small>
</main>
</body>
</html>"""
        return HTMLResponse(
            page,
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer",
            },
        )

    def approve(self, request: AuthorizationRequest, consent: str, *, client_key: str) -> str:
        """Validate consent and mint the redirect URL carrying the code."""
        now = _now()
        if not self.settings.auto_approve:
            if not self._throttle.check(client_key, now):
                raise OAuthError("access_denied", "Too many attempts; retry later", status_code=429)
            if not self.settings.consent_secret or not hmac.compare_digest(
                consent, self.settings.consent_secret
            ):
                self._throttle.record_failure(client_key, now)
                logger.warning("oauth: rejected consent attempt from %s", client_key)
                raise OAuthError("access_denied", "Invalid operator access code", status_code=401)
        self._throttle.reset(client_key)
        code = f"ac_{secrets.token_urlsafe(32)}"
        self.store.insert_code(
            {
                "code_hash": _sha256(code),
                "client_id": request.client_id,
                "subject": request.client_id,
                "redirect_uri": request.redirect_uri,
                "scope": request.scope,
                "code_challenge": request.code_challenge,
                "code_challenge_method": "S256",
                "resource": request.resource,
                "expires_at": int(now + self.settings.auth_code_ttl),
                "created_at": int(now),
            }
        )
        query = {"code": code}
        if request.state:
            query["state"] = request.state
        separator = "&" if urlsplit(request.redirect_uri).query else "?"
        return f"{request.redirect_uri}{separator}{urlencode(query)}"

    # --- token endpoint ----------------------------------------------------
    def exchange_token(
        self,
        form: Mapping[str, str],
        *,
        basic_client_id: str | None = None,
        basic_client_secret: str | None = None,
    ) -> dict[str, Any]:
        grant_type = form.get("grant_type") or ""
        if grant_type == "authorization_code":
            return self._exchange_code(form, basic_client_id, basic_client_secret)
        if grant_type == "refresh_token":
            return self._exchange_refresh(form, basic_client_id, basic_client_secret)
        raise OAuthError("unsupported_grant_type", f"Unsupported grant_type: {grant_type!r}")

    def _resolve_client(
        self,
        form: Mapping[str, str],
        basic_client_id: str | None,
        basic_client_secret: str | None,
    ) -> dict[str, Any]:
        body_id = form.get("client_id")
        body_secret = form.get("client_secret")
        client_id = basic_client_id or body_id
        if not client_id:
            raise OAuthError("invalid_client", "client_id is required", status_code=401)
        if basic_client_id and body_id and basic_client_id != body_id:
            raise OAuthError("invalid_client", "Conflicting client identifiers", status_code=401)
        client = self.store.get_client(client_id)
        if client is None:
            raise OAuthError("invalid_client", "Unknown client", status_code=401)
        method = client["token_endpoint_auth_method"]
        if client["client_secret_hash"]:
            supplied = basic_client_secret if basic_client_id else body_secret
            if not supplied or not hmac.compare_digest(
                client["client_secret_hash"], _sha256(supplied)
            ):
                raise OAuthError(
                    "invalid_client",
                    "Client authentication failed",
                    status_code=401,
                    headers={"WWW-Authenticate": 'Basic realm="code-diver-oauth"'},
                )
        elif method != "none":
            raise OAuthError("invalid_client", "Client is misconfigured", status_code=401)
        return client

    def _exchange_code(
        self,
        form: Mapping[str, str],
        basic_client_id: str | None,
        basic_client_secret: str | None,
    ) -> dict[str, Any]:
        client = self._resolve_client(form, basic_client_id, basic_client_secret)
        code = form.get("code") or ""
        if not code:
            raise OAuthError("invalid_request", "code is required")
        record = self.store.consume_code(_sha256(code), _now())
        if record is None:
            raise OAuthError("invalid_grant", "Authorization code is invalid or expired")
        if record["client_id"] != client["client_id"]:
            raise OAuthError("invalid_grant", "Authorization code was issued to another client")
        redirect_uri = form.get("redirect_uri") or ""
        if redirect_uri != record["redirect_uri"]:
            raise OAuthError("invalid_grant", "redirect_uri mismatch")
        if not verify_pkce(
            form.get("code_verifier"), record["code_challenge"], record["code_challenge_method"]
        ):
            raise OAuthError("invalid_grant", "PKCE verification failed")
        return self._issue_tokens(
            client_id=record["client_id"],
            subject=record["subject"],
            scope=record["scope"],
            resource=record["resource"],
        )

    def _exchange_refresh(
        self,
        form: Mapping[str, str],
        basic_client_id: str | None,
        basic_client_secret: str | None,
    ) -> dict[str, Any]:
        client = self._resolve_client(form, basic_client_id, basic_client_secret)
        raw = form.get("refresh_token") or ""
        if not raw:
            raise OAuthError("invalid_request", "refresh_token is required")
        record = self.store.consume_refresh(_sha256(raw), _now())
        if record is None:
            raise OAuthError("invalid_grant", "Refresh token is invalid, expired or already used")
        if record["client_id"] != client["client_id"]:
            raise OAuthError("invalid_grant", "Refresh token was issued to another client")
        scope = record["scope"]
        if form.get("scope"):
            requested = parse_scopes(form["scope"])
            if not requested.issubset(parse_scopes(scope)):
                raise OAuthError("invalid_scope", "Requested scope exceeds the refresh token scope")
            scope = format_scopes(requested)
        return self._issue_tokens(
            client_id=record["client_id"],
            subject=record["subject"],
            scope=scope,
            resource=record["resource"],
        )

    def _issue_tokens(self, *, client_id: str, subject: str, scope: str, resource: str) -> dict[str, Any]:
        now = int(_now())
        access = self.mint_access_token(subject=subject, client_id=client_id, scopes=scope, resource=resource)
        refresh = f"rt_{secrets.token_urlsafe(48)}"
        self.store.insert_refresh(
            {
                "token_hash": _sha256(refresh),
                "client_id": client_id,
                "subject": subject,
                "scope": scope,
                "resource": resource,
                "expires_at": now + self.settings.refresh_token_ttl,
                "created_at": now,
            }
        )
        logger.info("oauth: issued tokens for client=%s scope=%s", client_id, scope)
        return {
            "access_token": access,
            "token_type": "Bearer",
            "expires_in": self.settings.access_token_ttl,
            "refresh_token": refresh,
            "scope": scope,
        }

    def mint_access_token(
        self,
        *,
        subject: str,
        client_id: str,
        scopes: str | Iterable[str],
        resource: str | None = None,
    ) -> str:
        """Sign an access token (also used by ops tooling and tests)."""
        now = int(_now())
        granted = parse_scopes(scopes)
        claims = {
            "iss": self.settings.issuer,
            "sub": subject,
            "aud": resource or self.settings.resource,
            "client_id": client_id,
            "scope": format_scopes(granted),
            "jti": secrets.token_urlsafe(24),
            "iat": now,
            "nbf": now,
            "exp": now + self.settings.access_token_ttl,
            "token_use": "access",
        }
        return jwt.encode(claims, self.settings.jwt_secret, algorithm=JWT_ALGORITHM, headers={"typ": ACCESS_TOKEN_TYPE})

    # --- revocation --------------------------------------------------------
    def revoke(self, token: str, client_id: str | None = None) -> None:
        """RFC 7009 revocation; unknown tokens are a no-op."""
        if not token:
            raise OAuthError("invalid_request", "token is required")
        if token.startswith("rt_"):
            record = self.store.get_refresh(_sha256(token))
            if record is not None and client_id and record["client_id"] != client_id:
                raise OAuthError("invalid_client", "Token belongs to another client", status_code=401)
            self.store.delete_refresh(_sha256(token))
            return
        try:
            claims = jwt.decode(
                token,
                self.settings.jwt_secret,
                algorithms=[JWT_ALGORITHM],
                audience=self.settings.resource,
                issuer=self.settings.issuer,
                options={"verify_exp": False, "verify_aud": False, "verify_iss": False},
            )
        except jwt.PyJWTError:
            return
        jti = claims.get("jti")
        exp = claims.get("exp")
        if jti and isinstance(exp, int):
            self.store.revoke_jti(str(jti), exp)
            logger.info("oauth: revoked access token jti=%s client=%s", jti, claims.get("client_id"))

    # --- bearer authentication --------------------------------------------
    def authenticate(self, token: str) -> Principal:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise OAuthError("invalid_token", "Malformed bearer token", status_code=401) from exc
        if header.get("alg") != JWT_ALGORITHM or header.get("typ") not in {ACCESS_TOKEN_TYPE, "JWT"}:
            raise OAuthError("invalid_token", "Unexpected token type", status_code=401)
        try:
            claims = jwt.decode(
                token,
                self.settings.jwt_secret,
                algorithms=[JWT_ALGORITHM],
                audience=self.settings.resource,
                issuer=self.settings.issuer,
                leeway=5,
                options={"require": ["exp", "iat", "iss", "aud", "sub", "jti"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise OAuthError("invalid_token", "Token expired", status_code=401) from exc
        except jwt.InvalidAudienceError as exc:
            raise OAuthError("invalid_token", "Token audience mismatch", status_code=401) from exc
        except jwt.PyJWTError as exc:
            raise OAuthError("invalid_token", "Token validation failed", status_code=401) from exc
        if claims.get("token_use") != "access":
            raise OAuthError("invalid_token", "Not an access token", status_code=401)
        jti = str(claims["jti"])
        if self.store.is_revoked(jti):
            raise OAuthError("invalid_token", "Token has been revoked", status_code=401)
        try:
            scopes = parse_scopes(claims.get("scope"))
        except OAuthError as exc:
            raise OAuthError("invalid_token", "Token carries an unknown scope", status_code=401) from exc
        return Principal(
            subject=str(claims["sub"]),
            client_id=str(claims.get("client_id", "")),
            scopes=scopes,
            jti=jti,
            expires_at=int(claims["exp"]),
            resource=str(claims.get("aud", self.settings.resource)),
        )

    def challenge(
        self,
        *,
        error: str | None = None,
        description: str | None = None,
        scope: str | None = None,
    ) -> str:
        parts = [f'Bearer resource_metadata="{self.settings.protected_resource_metadata_url}"']
        if error:
            parts.append(f'error="{_escape_header(error)}"')
        if description:
            parts.append(f'error_description="{_escape_header(description)}"')
        if scope:
            parts.append(f'scope="{_escape_header(scope)}"')
        return ", ".join(parts)

    def require(self, principal: Principal | None, scope: str) -> Principal:
        if principal is None:
            raise OAuthError("invalid_token", "Bearer token required", status_code=401)
        if not principal.has(scope):
            raise OAuthError(
                "insufficient_scope",
                f"Scope {scope!r} is required",
                status_code=403,
                headers={"WWW-Authenticate": self.challenge(error="insufficient_scope", scope=scope)},
            )
        return principal

    def safe_error_redirect(
        self, params: Mapping[str, str], error: OAuthError
    ) -> RedirectResponse | JSONResponse:
        """Surface an authorize error via the validated redirect URI when possible.

        RFC 6749 §4.1.2.1 forbids redirecting to an unvalidated URI, so any
        failure before the client/redirect check returns a JSON 400 instead.
        """
        try:
            client = self.store.get_client(params.get("client_id") or "")
            redirect_uri = params.get("redirect_uri") or ""
            if client is None or redirect_uri not in client["redirect_uris"]:
                raise LookupError
            request = AuthorizationRequest(
                client_id=client["client_id"],
                client_name=client["client_name"],
                redirect_uri=redirect_uri,
                scope="",
                state=params.get("state"),
                code_challenge="",
                resource=self.settings.resource,
            )
        except LookupError:
            return error.to_response()
        return redirect_with_error(request, error.error, error.description)

    # --- HTTP routes -------------------------------------------------------
    def register_routes(self, app: FastAPI) -> None:
        """Attach discovery, registration, authorization, token and revocation routes."""
        settings = self.settings
        no_store = {"Cache-Control": "no-store", "Pragma": "no-cache"}

        @app.get("/.well-known/oauth-protected-resource", include_in_schema=False)
        @app.get("/.well-known/oauth-protected-resource/mcp", include_in_schema=False)
        async def protected_resource_metadata() -> JSONResponse:
            return JSONResponse(
                self.protected_resource_metadata(),
                headers={"Cache-Control": "public, max-age=300"},
            )

        @app.get("/.well-known/oauth-authorization-server", include_in_schema=False)
        @app.get("/.well-known/oauth-authorization-server/mcp", include_in_schema=False)
        async def authorization_server_metadata() -> JSONResponse:
            return JSONResponse(
                self.authorization_server_metadata(),
                headers={"Cache-Control": "public, max-age=300"},
            )

        @app.post("/register", include_in_schema=False)
        async def register(request: Request) -> JSONResponse:
            try:
                payload = await request.json()
            except Exception:
                return OAuthError("invalid_client_metadata", "Body must be JSON").to_response()
            if not isinstance(payload, dict):
                return OAuthError("invalid_client_metadata", "Body must be a JSON object").to_response()
            try:
                result = self.register_client(payload)
            except OAuthError as exc:
                logger.warning("oauth: registration rejected: %s", exc.description)
                return exc.to_response()
            return JSONResponse(result, status_code=201, headers=no_store)

        @app.get("/authorize", include_in_schema=False)
        async def authorize(request: Request) -> Response:
            params = merge_query(request.query_params)
            try:
                authorization = self.validate_authorization_request(params)
            except OAuthError as exc:
                return self.safe_error_redirect(params, exc)
            if settings.auto_approve:
                url = self.approve(authorization, consent="", client_key="auto-approve")
                return RedirectResponse(url, status_code=302, headers=no_store)
            return self.consent_page(authorization)

        @app.post("/authorize", include_in_schema=False)
        async def authorize_submit(request: Request) -> Response:
            form = dict(await request.form())
            try:
                authorization = self.validate_authorization_request(form)
            except OAuthError as exc:
                return self.safe_error_redirect(form, exc)
            client_key = request.client.host if request.client else "unknown"
            try:
                url = self.approve(authorization, str(form.get("consent") or ""), client_key=client_key)
            except OAuthError as exc:
                if exc.status_code in {401, 429}:
                    page = self.consent_page(authorization, error=exc.description or exc.error)
                    page.status_code = exc.status_code
                    return page
                return exc.to_response()
            return RedirectResponse(url, status_code=302, headers=no_store)

        @app.post("/token", include_in_schema=False)
        async def token(request: Request) -> Response:
            form = {key: str(value) for key, value in (await request.form()).items()}
            basic_id, basic_secret = extract_basic_auth(request)
            try:
                payload = self.exchange_token(
                    form, basic_client_id=basic_id, basic_client_secret=basic_secret
                )
            except OAuthError as exc:
                logger.info("oauth: token request rejected: %s", exc.error)
                return exc.to_response()
            return JSONResponse(payload, headers=no_store)

        @app.post("/revoke", include_in_schema=False)
        async def revoke(request: Request) -> Response:
            form = {key: str(value) for key, value in (await request.form()).items()}
            basic_id, _ = extract_basic_auth(request)
            try:
                self.revoke(form.get("token", ""), form.get("client_id") or basic_id)
            except OAuthError as exc:
                return exc.to_response()
            return Response(status_code=200, headers=no_store)

        logger.info(
            "oauth: enabled issuer=%s resource=%s metadata=%s",
            settings.issuer,
            settings.resource,
            settings.protected_resource_metadata_url,
        )

    def close(self) -> None:
        self.store.close()


def _escape_header(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', "'").replace("\r", " ").replace("\n", " ")


def _validate_redirect_uri(uri: str) -> str:
    if len(uri) > 2048:
        raise OAuthError("invalid_redirect_uri", "redirect_uri is too long")
    parts = urlsplit(uri)
    if not parts.scheme or not parts.netloc:
        raise OAuthError("invalid_redirect_uri", "redirect_uri must be absolute")
    if parts.fragment:
        raise OAuthError("invalid_redirect_uri", "redirect_uri must not contain a fragment")
    if parts.scheme == "https":
        return uri
    if parts.scheme == "http" and _is_loopback(parts.hostname):
        return uri
    raise OAuthError(
        "invalid_redirect_uri",
        "redirect_uri must use https (http is allowed only for loopback redirects)",
    )


def extract_basic_auth(request: Request) -> tuple[str | None, str | None]:
    """Return (client_id, client_secret) from an HTTP Basic header, if present."""
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("basic "):
        return None, None
    raw = header[6:].strip()
    try:
        decoded = base64.b64decode(raw, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None, None
    if ":" not in decoded:
        return None, None
    client_id, secret = decoded.split(":", 1)
    return unquote_plus(client_id), unquote_plus(secret)


def parse_form_urlencoded(body: bytes) -> dict[str, str]:
    """Parse an already-read urlencoded body (kept tiny for tests)."""
    parsed = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
    return {key: values[-1] for key, values in parsed.items()}


def merge_query(params: Mapping[str, Any]) -> dict[str, str]:
    """Flatten Starlette query params (last value wins, like most servers)."""
    return {key: str(value) for key, value in params.items()}


def redirect_with_error(request: AuthorizationRequest | None, error: str, description: str) -> RedirectResponse | HTMLResponse:
    """Build an RFC 6749 error response, redirecting only to a validated URI."""
    if request is None:
        return JSONResponse(
            {"error": error, "error_description": description},
            status_code=400,
            headers={"Cache-Control": "no-store"},
        )
    query = {"error": error, "error_description": description}
    if request.state:
        query["state"] = request.state
    separator = "&" if urlsplit(request.redirect_uri).query else "?"
    target = f"{request.redirect_uri}{separator}{urlencode(query)}"
    return RedirectResponse(target, status_code=302, headers={"Cache-Control": "no-store"})


def protected_path_scope(path: str, *, protect_rest: bool) -> str | None:
    """Return the HTTP-layer scope for a path, or None when the path is public."""
    if path == "/mcp" or path.startswith("/mcp/"):
        return READ_SCOPE
    if protect_rest and path.startswith("/api/"):
        if path.startswith("/api/v1/index/"):
            return WRITE_SCOPE
        return READ_SCOPE
    return None


def bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if not header:
        return None
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


def quote_redirect(uri: str) -> str:
    """Quote a redirect URI for logging without leaking query parameters."""
    return quote(uri, safe=":/")


def _debug_payload(**kwargs: Any) -> str:  # pragma: no cover - debugging helper
    return json.dumps(kwargs, default=str)
