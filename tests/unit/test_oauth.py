"""Unit tests for the self-contained OAuth 2.1 authorization server."""

from __future__ import annotations

import base64
import json
import time
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest

from code_diver.transport import oauth
from code_diver.transport.oauth import (
    READ_SCOPE,
    WRITE_SCOPE,
    OAuthError,
    OAuthProvider,
    OAuthSettings,
    OAuthStore,
    Principal,
    code_challenge_for,
    generate_code_verifier,
    parse_scopes,
    verify_pkce,
)

REDIRECT_URI = "http://127.0.0.1:7777/callback"
SECRET = "s" * 48


@pytest.fixture
def settings() -> OAuthSettings:
    return OAuthSettings(
        enabled=True,
        issuer="http://127.0.0.1:18080",
        resource="http://127.0.0.1:18080/mcp",
        jwt_secret=SECRET,
        consent_secret="operator-code",
        db_path=":memory:",
    )


@pytest.fixture
def provider(settings: OAuthSettings) -> OAuthProvider:
    instance = OAuthProvider(settings, store=OAuthStore(":memory:"))
    yield instance
    instance.close()


def _register(provider: OAuthProvider, scope: str = f"{READ_SCOPE} {WRITE_SCOPE}") -> dict:
    return provider.register_client(
        {
            "client_name": "pytest",
            "redirect_uris": [REDIRECT_URI],
            "scope": scope,
        }
    )


def _authorize(provider: OAuthProvider, client_id: str, scope: str = READ_SCOPE) -> tuple[str, str]:
    verifier = generate_code_verifier()
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": scope,
        "state": "state-1",
        "code_challenge": code_challenge_for(verifier),
        "code_challenge_method": "S256",
    }
    request = provider.validate_authorization_request(params)
    url = provider.approve(request, "operator-code", client_key="test")
    code = parse_qs(urlsplit(url).query)["code"][0]
    assert parse_qs(urlsplit(url).query)["state"] == ["state-1"]
    return code, verifier


# ---------------------------------------------------------------------------
# PKCE / scopes
# ---------------------------------------------------------------------------


def test_pkce_s256_roundtrip() -> None:
    verifier = generate_code_verifier()
    challenge = code_challenge_for(verifier)
    assert len(challenge) == 43
    assert verify_pkce(verifier, challenge) is True
    assert verify_pkce(verifier + "x", challenge) is False
    assert verify_pkce(verifier, challenge, "plain") is False
    assert verify_pkce(None, challenge) is False


def test_pkce_rejects_short_verifier() -> None:
    with pytest.raises(ValueError):
        code_challenge_for("short")


def test_parse_scopes_rejects_unknown_scope() -> None:
    assert parse_scopes("code:read code:write") == frozenset({READ_SCOPE, WRITE_SCOPE})
    with pytest.raises(OAuthError):
        parse_scopes("admin:everything")
    with pytest.raises(OAuthError):
        parse_scopes("code:read;evil")


def test_principal_scope_check() -> None:
    principal = Principal(
        subject="client",
        client_id="client",
        scopes=frozenset({READ_SCOPE}),
        jti="jti",
        expires_at=0,
        resource="http://127.0.0.1:18080/mcp",
    )
    assert principal.has(READ_SCOPE) is True
    assert principal.has(WRITE_SCOPE) is False
    assert principal.has([READ_SCOPE]) is True
    assert principal.has(None) is True


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def test_settings_default_disabled_without_secrets() -> None:
    settings = OAuthSettings.from_env({})
    assert settings.enabled is False
    assert settings.issuer == "http://127.0.0.1:8080"
    assert settings.resource == "http://127.0.0.1:8080/mcp"


def test_settings_enabled_requires_secret() -> None:
    with pytest.raises(ValueError, match="JWT_SECRET"):
        OAuthSettings.from_env(
            {
                "CODE_DIVER_OAUTH_ENABLED": "1",
                "CODE_DIVER_OAUTH_ISSUER": "https://mcp.example.test",
                "CODE_DIVER_OAUTH_CONSENT_SECRET": "consent",
            }
        )


def test_settings_enabled_requires_consent_or_auto_approve() -> None:
    with pytest.raises(ValueError, match="CONSENT_SECRET"):
        OAuthSettings.from_env(
            {
                "CODE_DIVER_OAUTH_ENABLED": "1",
                "CODE_DIVER_OAUTH_ISSUER": "https://mcp.example.test",
                "CODE_DIVER_OAUTH_JWT_SECRET": SECRET,
            }
        )
    settings = OAuthSettings.from_env(
        {
            "CODE_DIVER_OAUTH_ENABLED": "1",
            "CODE_DIVER_OAUTH_ISSUER": "https://mcp.example.test",
            "CODE_DIVER_OAUTH_JWT_SECRET": SECRET,
            "CODE_DIVER_OAUTH_AUTO_APPROVE": "1",
        }
    )
    assert settings.auto_approve is True


def test_settings_rejects_plaintext_non_loopback_issuer() -> None:
    with pytest.raises(ValueError, match="https"):
        OAuthSettings.from_env(
            {
                "CODE_DIVER_OAUTH_ENABLED": "1",
                "CODE_DIVER_OAUTH_ISSUER": "http://mcp.example.test",
                "CODE_DIVER_OAUTH_JWT_SECRET": SECRET,
                "CODE_DIVER_OAUTH_CONSENT_SECRET": "consent",
            }
        )


def test_settings_secret_file(tmp_path) -> None:
    secret_file = tmp_path / "jwt-secret"
    secret_file.write_text(SECRET + "\n", encoding="utf-8")
    settings = OAuthSettings.from_env(
        {
            "CODE_DIVER_OAUTH_ENABLED": "1",
            "CODE_DIVER_OAUTH_ISSUER": "https://mcp.example.test",
            "CODE_DIVER_OAUTH_JWT_SECRET_FILE": str(secret_file),
            "CODE_DIVER_OAUTH_CONSENT_SECRET": "consent",
        }
    )
    assert settings.jwt_secret == SECRET


def test_settings_ttl_validation() -> None:
    with pytest.raises(ValueError, match="CODE_DIVER_OAUTH_ACCESS_TTL"):
        OAuthSettings.from_env({"CODE_DIVER_OAUTH_ACCESS_TTL": "10"})


# ---------------------------------------------------------------------------
# Discovery / DCR
# ---------------------------------------------------------------------------


def test_protected_resource_metadata(provider: OAuthProvider) -> None:
    payload = provider.protected_resource_metadata()
    assert payload["resource"] == "http://127.0.0.1:18080/mcp"
    assert payload["authorization_servers"] == ["http://127.0.0.1:18080"]
    assert payload["scopes_supported"] == [READ_SCOPE, WRITE_SCOPE]
    assert payload["bearer_methods_supported"] == ["header"]
    json.dumps(payload)


def test_authorization_server_metadata(provider: OAuthProvider) -> None:
    payload = provider.authorization_server_metadata()
    assert payload["issuer"] == "http://127.0.0.1:18080"
    assert payload["authorization_endpoint"].endswith("/authorize")
    assert payload["token_endpoint"].endswith("/token")
    assert payload["registration_endpoint"].endswith("/register")
    assert payload["revocation_endpoint"].endswith("/revoke")
    assert payload["code_challenge_methods_supported"] == ["S256"]
    assert payload["grant_types_supported"] == ["authorization_code", "refresh_token"]
    assert "none" in payload["token_endpoint_auth_methods_supported"]


def test_register_public_client(provider: OAuthProvider) -> None:
    response = _register(provider)
    assert response["client_id"].startswith("cd_")
    assert "client_secret" not in response
    assert response["redirect_uris"] == [REDIRECT_URI]
    assert response["token_endpoint_auth_method"] == "none"
    assert response["scope"] == f"{READ_SCOPE} {WRITE_SCOPE}"


def test_register_confidential_client(provider: OAuthProvider) -> None:
    response = provider.register_client(
        {
            "redirect_uris": [REDIRECT_URI],
            "token_endpoint_auth_method": "client_secret_basic",
        }
    )
    assert response["client_secret"]
    assert response["client_secret_expires_at"] == 0


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "http://example.test/callback",
        "ftp://127.0.0.1/callback",
        "http://127.0.0.1:7777/callback#fragment",
        "not-a-url",
    ],
)
def test_register_rejects_unsafe_redirect_uri(provider: OAuthProvider, redirect_uri: str) -> None:
    with pytest.raises(OAuthError, match="redirect_uri"):
        provider.register_client({"redirect_uris": [redirect_uri]})


def test_register_requires_redirect_uris(provider: OAuthProvider) -> None:
    with pytest.raises(OAuthError):
        provider.register_client({"redirect_uris": []})


# ---------------------------------------------------------------------------
# Authorization endpoint
# ---------------------------------------------------------------------------


def test_authorize_requires_s256(provider: OAuthProvider) -> None:
    client = _register(provider)
    params = {
        "response_type": "code",
        "client_id": client["client_id"],
        "redirect_uri": REDIRECT_URI,
        "scope": READ_SCOPE,
        "code_challenge": "a" * 43,
        "code_challenge_method": "plain",
    }
    with pytest.raises(OAuthError, match="S256"):
        provider.validate_authorization_request(params)


def test_authorize_rejects_unregistered_redirect(provider: OAuthProvider) -> None:
    client = _register(provider)
    params = {
        "response_type": "code",
        "client_id": client["client_id"],
        "redirect_uri": "http://127.0.0.1:7777/other",
        "code_challenge": code_challenge_for(generate_code_verifier()),
        "code_challenge_method": "S256",
    }
    with pytest.raises(OAuthError, match="redirect_uri"):
        provider.validate_authorization_request(params)
    assert provider.safe_error_redirect(params, OAuthError("invalid_request", "bad")).status_code == 400


def test_authorize_rejects_scope_escalation(provider: OAuthProvider) -> None:
    client = _register(provider, scope=READ_SCOPE)
    params = {
        "response_type": "code",
        "client_id": client["client_id"],
        "redirect_uri": REDIRECT_URI,
        "scope": WRITE_SCOPE,
        "code_challenge": code_challenge_for(generate_code_verifier()),
        "code_challenge_method": "S256",
    }
    with pytest.raises(OAuthError, match="scope"):
        provider.validate_authorization_request(params)


def test_authorize_rejects_foreign_resource(provider: OAuthProvider) -> None:
    client = _register(provider)
    params = {
        "response_type": "code",
        "client_id": client["client_id"],
        "redirect_uri": REDIRECT_URI,
        "scope": READ_SCOPE,
        "resource": "https://evil.example/mcp",
        "code_challenge": code_challenge_for(generate_code_verifier()),
        "code_challenge_method": "S256",
    }
    with pytest.raises(OAuthError, match="resource"):
        provider.validate_authorization_request(params)


def test_error_redirect_for_valid_client(provider: OAuthProvider) -> None:
    client = _register(provider)
    params = {
        "client_id": client["client_id"],
        "redirect_uri": REDIRECT_URI,
        "state": "abc",
    }
    response = provider.safe_error_redirect(params, OAuthError("invalid_request", "nope"))
    assert response.status_code == 302
    location = response.headers["location"]
    query = parse_qs(urlsplit(location).query)
    assert query["error"] == ["invalid_request"]
    assert query["state"] == ["abc"]


def test_consent_secret_required(provider: OAuthProvider) -> None:
    client = _register(provider)
    request = provider.validate_authorization_request(
        {
            "response_type": "code",
            "client_id": client["client_id"],
            "redirect_uri": REDIRECT_URI,
            "scope": READ_SCOPE,
            "code_challenge": code_challenge_for(generate_code_verifier()),
            "code_challenge_method": "S256",
        }
    )
    with pytest.raises(OAuthError) as exc:
        provider.approve(request, "wrong", client_key="1.2.3.4")
    assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# Token endpoint
# ---------------------------------------------------------------------------


def test_code_exchange_and_single_use(provider: OAuthProvider) -> None:
    client = _register(provider)
    code, verifier = _authorize(provider, client["client_id"])
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": client["client_id"],
        "code_verifier": verifier,
    }
    payload = provider.exchange_token(form)
    assert payload["token_type"] == "Bearer"
    assert payload["scope"] == READ_SCOPE
    principal = provider.authenticate(payload["access_token"])
    assert principal.scopes == frozenset({READ_SCOPE})

    with pytest.raises(OAuthError) as exc:
        provider.exchange_token(form)
    assert exc.value.error == "invalid_grant"


def test_code_exchange_wrong_verifier(provider: OAuthProvider) -> None:
    client = _register(provider)
    code, _ = _authorize(provider, client["client_id"])
    with pytest.raises(OAuthError) as exc:
        provider.exchange_token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": client["client_id"],
                "code_verifier": generate_code_verifier(),
            }
        )
    assert exc.value.error == "invalid_grant"


def test_code_exchange_redirect_mismatch(provider: OAuthProvider) -> None:
    client = _register(provider)
    code, verifier = _authorize(provider, client["client_id"])
    with pytest.raises(OAuthError) as exc:
        provider.exchange_token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "http://127.0.0.1:7777/other",
                "client_id": client["client_id"],
                "code_verifier": verifier,
            }
        )
    assert exc.value.error == "invalid_grant"


def test_code_exchange_wrong_client(provider: OAuthProvider) -> None:
    first = _register(provider)
    second = _register(provider)
    code, verifier = _authorize(provider, first["client_id"])
    with pytest.raises(OAuthError) as exc:
        provider.exchange_token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": second["client_id"],
                "code_verifier": verifier,
            }
        )
    assert exc.value.error == "invalid_grant"


def test_confidential_client_requires_secret(provider: OAuthProvider) -> None:
    client = provider.register_client(
        {"redirect_uris": [REDIRECT_URI], "token_endpoint_auth_method": "client_secret_post"}
    )
    code, verifier = _authorize(provider, client["client_id"])
    with pytest.raises(OAuthError) as exc:
        provider.exchange_token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": client["client_id"],
                "code_verifier": verifier,
            }
        )
    assert exc.value.error == "invalid_client"
    assert exc.value.status_code == 401


def test_expired_authorization_code(provider: OAuthProvider, monkeypatch) -> None:
    client = _register(provider)
    code, verifier = _authorize(provider, client["client_id"])
    monkeypatch.setattr(oauth, "_now", lambda: time.time() + 3600)
    with pytest.raises(OAuthError) as exc:
        provider.exchange_token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": client["client_id"],
                "code_verifier": verifier,
            }
        )
    assert exc.value.error == "invalid_grant"


def test_refresh_token_rotation(provider: OAuthProvider) -> None:
    client = _register(provider)
    code, verifier = _authorize(provider, client["client_id"])
    payload = provider.exchange_token(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client["client_id"],
            "code_verifier": verifier,
        }
    )
    refresh = payload["refresh_token"]
    rotated = provider.exchange_token(
        {"grant_type": "refresh_token", "refresh_token": refresh, "client_id": client["client_id"]}
    )
    assert rotated["refresh_token"] != refresh
    with pytest.raises(OAuthError) as exc:
        provider.exchange_token(
            {"grant_type": "refresh_token", "refresh_token": refresh, "client_id": client["client_id"]}
        )
    assert exc.value.error == "invalid_grant"


def test_refresh_scope_narrowing(provider: OAuthProvider) -> None:
    client = _register(provider)
    code, verifier = _authorize(provider, client["client_id"], scope=f"{READ_SCOPE} {WRITE_SCOPE}")
    payload = provider.exchange_token(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client["client_id"],
            "code_verifier": verifier,
        }
    )
    narrowed = provider.exchange_token(
        {
            "grant_type": "refresh_token",
            "refresh_token": payload["refresh_token"],
            "client_id": client["client_id"],
            "scope": READ_SCOPE,
        }
    )
    assert narrowed["scope"] == READ_SCOPE
    with pytest.raises(OAuthError):
        provider.exchange_token(
            {
                "grant_type": "refresh_token",
                "refresh_token": narrowed["refresh_token"],
                "client_id": client["client_id"],
                "scope": WRITE_SCOPE,
            }
        )


def test_unsupported_grant_type(provider: OAuthProvider) -> None:
    with pytest.raises(OAuthError) as exc:
        provider.exchange_token({"grant_type": "password"})
    assert exc.value.error == "unsupported_grant_type"


# ---------------------------------------------------------------------------
# Bearer validation / revocation
# ---------------------------------------------------------------------------


def test_authenticate_rejects_tampered_token(provider: OAuthProvider) -> None:
    client = _register(provider)
    token = provider.mint_access_token(
        subject=client["client_id"], client_id=client["client_id"], scopes=[READ_SCOPE]
    )
    header, payload, signature = token.split(".")
    tampered = f"{header}.{payload}.{'A' * len(signature)}"
    with pytest.raises(OAuthError) as exc:
        provider.authenticate(tampered)
    assert exc.value.error == "invalid_token"


def test_authenticate_rejects_alg_none(provider: OAuthProvider) -> None:
    claims = {
        "iss": provider.settings.issuer,
        "sub": "attacker",
        "aud": provider.settings.resource,
        "scope": WRITE_SCOPE,
        "jti": "x",
        "exp": int(time.time()) + 300,
        "iat": int(time.time()),
        "token_use": "access",
    }
    unsigned = jwt.encode(claims, key="", algorithm="none")
    with pytest.raises(OAuthError) as exc:
        provider.authenticate(unsigned)
    assert exc.value.error == "invalid_token"


def test_authenticate_rejects_wrong_audience(provider: OAuthProvider) -> None:
    client = _register(provider)
    token = provider.mint_access_token(
        subject=client["client_id"],
        client_id=client["client_id"],
        scopes=[READ_SCOPE],
        resource="https://other.example/mcp",
    )
    with pytest.raises(OAuthError) as exc:
        provider.authenticate(token)
    assert "audience" in exc.value.description


def test_authenticate_rejects_expired_token(settings: OAuthSettings) -> None:
    expired = OAuthSettings(**{**settings.__dict__, "access_token_ttl": -60})
    provider = OAuthProvider(expired, store=OAuthStore(":memory:"))
    token = provider.mint_access_token(subject="client", client_id="client", scopes=[READ_SCOPE])
    with pytest.raises(OAuthError) as exc:
        provider.authenticate(token)
    assert "expired" in exc.value.description.lower()


def test_revoke_access_token(provider: OAuthProvider) -> None:
    client = _register(provider)
    token = provider.mint_access_token(
        subject=client["client_id"], client_id=client["client_id"], scopes=[READ_SCOPE]
    )
    provider.authenticate(token)
    provider.revoke(token, client_id=client["client_id"])
    with pytest.raises(OAuthError) as exc:
        provider.authenticate(token)
    assert "revoked" in exc.value.description


def test_revoke_refresh_token(provider: OAuthProvider) -> None:
    client = _register(provider)
    code, verifier = _authorize(provider, client["client_id"])
    payload = provider.exchange_token(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client["client_id"],
            "code_verifier": verifier,
        }
    )
    provider.revoke(payload["refresh_token"], client_id=client["client_id"])
    with pytest.raises(OAuthError):
        provider.exchange_token(
            {
                "grant_type": "refresh_token",
                "refresh_token": payload["refresh_token"],
                "client_id": client["client_id"],
            }
        )


def test_require_scope(provider: OAuthProvider) -> None:
    client = _register(provider)
    token = provider.mint_access_token(
        subject=client["client_id"], client_id=client["client_id"], scopes=[READ_SCOPE]
    )
    principal = provider.authenticate(token)
    provider.require(principal, READ_SCOPE)
    with pytest.raises(OAuthError) as exc:
        provider.require(principal, WRITE_SCOPE)
    assert exc.value.error == "insufficient_scope"
    assert exc.value.status_code == 403
    assert 'scope="code:write"' in exc.value.headers["WWW-Authenticate"]


def test_challenge_advertises_resource_metadata(provider: OAuthProvider) -> None:
    header = provider.challenge(error="invalid_token", description='bad "token"')
    assert header.startswith("Bearer resource_metadata=")
    assert "http://127.0.0.1:18080/.well-known/oauth-protected-resource" in header
    assert 'error="invalid_token"' in header
    assert "\n" not in header


def test_basic_auth_parsing(provider: OAuthProvider) -> None:
    raw = base64.b64encode(b"client%3Aid:sec%20ret").decode()
    from starlette.requests import Request

    request = Request(
        {"type": "http", "headers": [(b"authorization", f"Basic {raw}".encode())], "method": "POST", "path": "/"}
    )
    from code_diver.transport.oauth import extract_basic_auth

    client_id, secret = extract_basic_auth(request)
    assert client_id == "client:id"
    assert secret == "sec ret"


def test_store_persists_to_sqlite(tmp_path) -> None:
    db = tmp_path / "oauth.sqlite3"
    first = OAuthProvider(
        OAuthSettings(
            enabled=True,
            issuer="http://127.0.0.1:18080",
            resource="http://127.0.0.1:18080/mcp",
            jwt_secret=SECRET,
            consent_secret="operator-code",
            db_path=str(db),
        )
    )
    client = _register(first)
    first.close()
    second = OAuthProvider(
        OAuthSettings(
            enabled=True,
            issuer="http://127.0.0.1:18080",
            resource="http://127.0.0.1:18080/mcp",
            jwt_secret=SECRET,
            consent_secret="operator-code",
            db_path=str(db),
        )
    )
    assert second.store.get_client(client["client_id"]) is not None
    second.close()
    assert oct(db.stat().st_mode & 0o777) == "0o600"
