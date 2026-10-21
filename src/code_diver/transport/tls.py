"""TLS configuration for the Code Diver HTTP transport.

The HTTP server is TLS-enabled from the environment (or explicit CLI flags) so
the systemd unit can keep secrets out of the process table:

===============================  =============================================
``CODE_DIVER_TLS_CERT``          PEM certificate chain (leaf first)
``CODE_DIVER_TLS_KEY``           PEM private key (unencrypted)
``CODE_DIVER_TLS_CLIENT_CA``     CA bundle used to verify client certificates
``CODE_DIVER_TLS_REQUIRE_CLIENT_CERT``  ``1`` to require mTLS
===============================  =============================================

Both files must be set together; anything else is treated as a configuration
error rather than silently falling back to plaintext.
"""

from __future__ import annotations

import logging
import os
import ssl
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("code_diver.transport.tls")


class TLSConfigError(ValueError):
    """Raised when the TLS configuration is inconsistent or unreadable."""


def _flag(source: Mapping[str, str], key: str, default: bool = False) -> bool:
    raw = source.get(key)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class TLSSettings:
    """Resolved TLS material for uvicorn."""

    certfile: Path | None = None
    keyfile: Path | None = None
    ca_certs: Path | None = None
    require_client_cert: bool = False

    @property
    def enabled(self) -> bool:
        return self.certfile is not None

    @property
    def scheme(self) -> str:
        return "https" if self.enabled else "http"

    def validate(self) -> None:
        if self.certfile is None and self.keyfile is None:
            if self.require_client_cert:
                raise TLSConfigError(
                    "CODE_DIVER_TLS_REQUIRE_CLIENT_CERT requires CODE_DIVER_TLS_CERT and CODE_DIVER_TLS_KEY"
                )
            return
        if self.certfile is None or self.keyfile is None:
            raise TLSConfigError("CODE_DIVER_TLS_CERT and CODE_DIVER_TLS_KEY must be set together")
        for label, path in (("certificate", self.certfile), ("private key", self.keyfile)):
            if not path.is_file():
                raise TLSConfigError(f"TLS {label} file does not exist: {path}")
        if self.require_client_cert:
            if self.ca_certs is None:
                raise TLSConfigError(
                    "Requiring client certificates needs CODE_DIVER_TLS_CLIENT_CA"
                )
            if not self.ca_certs.is_file():
                raise TLSConfigError(f"TLS client CA file does not exist: {self.ca_certs}")
        mode = self.keyfile.stat().st_mode
        if mode & 0o077:
            logger.warning(
                "TLS private key %s is readable by group/other (mode %o); chmod 600 it",
                self.keyfile,
                mode & 0o777,
            )

    def uvicorn_kwargs(self) -> dict[str, Any]:
        """Keyword arguments for ``uvicorn.run``/``uvicorn.Config``."""
        self.validate()
        if not self.enabled:
            return {}
        kwargs: dict[str, Any] = {
            "ssl_certfile": str(self.certfile),
            "ssl_keyfile": str(self.keyfile),
        }
        if self.ca_certs is not None:
            kwargs["ssl_ca_certs"] = str(self.ca_certs)
        if self.require_client_cert:
            kwargs["ssl_cert_reqs"] = ssl.CERT_REQUIRED
        return kwargs

    def base_url(self, host: str, port: int) -> str:
        display_host = "127.0.0.1" if host in {"0.0.0.0", "::", ""} else host  # noqa: S104 - display only
        return f"{self.scheme}://{display_host}:{port}"

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        cert: str | Path | None = None,
        key: str | Path | None = None,
        client_ca: str | Path | None = None,
        require_client_cert: bool | None = None,
    ) -> TLSSettings:
        source = os.environ if env is None else env
        cert_value = cert if cert is not None else source.get("CODE_DIVER_TLS_CERT")
        key_value = key if key is not None else source.get("CODE_DIVER_TLS_KEY")
        ca_value = client_ca if client_ca is not None else source.get("CODE_DIVER_TLS_CLIENT_CA")
        require = (
            require_client_cert
            if require_client_cert is not None
            else _flag(source, "CODE_DIVER_TLS_REQUIRE_CLIENT_CERT")
        )
        settings = cls(
            certfile=Path(cert_value).expanduser() if cert_value else None,
            keyfile=Path(key_value).expanduser() if key_value else None,
            ca_certs=Path(ca_value).expanduser() if ca_value else None,
            require_client_cert=bool(require),
        )
        settings.validate()
        return settings
