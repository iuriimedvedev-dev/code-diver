from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from .defaults import Defaults
from .environment import EnvironmentVariable

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class JbCentralConfig:
    port: int
    secret: str
    config_path: Path


def read_jbcentral_config(
    custom_path: Path | str | None = None,
) -> JbCentralConfig | None:
    path = (
        Path(custom_path).expanduser()
        if custom_path
        else Defaults.JBCENTRAL_CONFIG_PATH.expanduser()
    )
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        port = int(data.get("proxy_port") or Defaults.JBCENTRAL_DEFAULT_PORT)
        secret = str(data.get("proxy_secret") or "").strip()
        return JbCentralConfig(port=port, secret=secret, config_path=path)
    except Exception as exc:
        logger.warning("Failed to parse jbcentral config at %s: %s", path, exc)
        return None


def resolve_litellm_base_url() -> str:
    raw = (
        os.environ.get(EnvironmentVariable.LITELLM_BASE_URL.value)
        or os.environ.get(EnvironmentVariable.LITELLM_URL.value)
        or os.environ.get("LITELLM_API_URL")
        or Defaults.LITELLM_BASE_URL
    )
    url = raw.strip().rstrip("/")
    if not url.endswith("/v1"):
        url = f"{url}/v1"
    return url


def resolve_litellm_key(repo_root: Path | None = None) -> str | None:
    # 1. Environment variables
    for env_var in (
        EnvironmentVariable.LITELLM_API_KEY.value,
        EnvironmentVariable.LITE_LLM_KEY.value,
    ):
        val = os.environ.get(env_var)
        if val and val.strip():
            return val.strip()

    # 2. Candidate .env files
    candidates: list[Path] = []
    if repo_root:
        candidates.append(repo_root / ".env")
    candidates.append(Path.cwd() / ".env")
    candidates.append(Path.home() / ".config" / "opencode" / ".env")
    candidates.append(Path.home() / ".env")

    for path in candidates:
        if not path.is_file():
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                k, v = stripped.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k in ("LITE_LLM_KEY", "LITELLM_API_KEY") and v:
                    return v
        except OSError:
            continue

    # 3. ~/.config/opencode/ config files
    for config_name in ("opencode.json", "opencode.jsonc"):
        cfg_path = Path.home() / ".config" / "opencode" / config_name
        if not cfg_path.is_file():
            continue
        try:
            content = cfg_path.read_text(encoding="utf-8")
            cleaned_lines = [
                line for line in content.splitlines() if not line.strip().startswith("//")
            ]
            data = json.loads("\n".join(cleaned_lines))
            provider_cfg = data.get("provider", {}).get("litellm", {})
            candidate = (
                provider_cfg.get("apiKey")
                or provider_cfg.get("api_key")
                or provider_cfg.get("options", {}).get("apiKey")
                or provider_cfg.get("options", {}).get("api_key")
            )
            if candidate and isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.debug("Failed reading litellm config from %s: %s", cfg_path, exc)
            continue

    return None


@dataclass(frozen=True, slots=True)
class ResolvedEndpoint:
    url: str
    api_key: str | None
    headers: dict[str, str]
    model: str | None


class ProviderResolver:
    """Unified resolver for URLs, authentication keys and models across providers.

    Supported provider kinds:
    - `vertex`: Native GCP Vertex AI
    - `openai`: Official OpenAI API (api.openai.com)
    - `litellm`: JetBrains Labs LiteLLM gateway
    - `local` / `openai_compatible`: Local or self-hosted OpenAI-compatible server (vLLM, Ollama, MLX)
    - `jbcentral`: Local JetBrains Central Wire Proxy
    """

    @classmethod
    def resolve_generation(
        cls,
        provider: str,
        *,
        model: str | None = None,
        url: str | None = None,
        api_key: str | None = None,
        jbcentral_agent: str | None = None,
    ) -> ResolvedEndpoint:
        p = provider.lower().strip()

        if p in ("jbcentral", "jetbrains_central", "jetbrains"):
            cfg = read_jbcentral_config()
            port = cfg.port if cfg else Defaults.JBCENTRAL_DEFAULT_PORT
            secret = cfg.secret if cfg else ""
            agent = (
                jbcentral_agent
                or os.environ.get(EnvironmentVariable.JBCENTRAL_AGENT.value)
                or Defaults.JBCENTRAL_DEFAULT_AGENT
            )
            # Route logic: if agent is codex/openai -> openai/v1/responses (or chat/completions)
            # If agent is antigravity/gemini -> route via gemini protocol or openai compatible endpoint
            if agent in ("antigravity", "gemini"):
                prefix = f"/wire/{secret}/{agent}" if secret else ""
                default_url = f"http://127.0.0.1:{port}{prefix}/openai/v1/chat/completions"
            else:
                prefix = f"/wire/{secret}/{agent}" if secret else ""
                default_url = f"http://127.0.0.1:{port}{prefix}/openai/v1/responses"

            target_url = url or default_url
            resolved_key = api_key or (secret or "jbcentral")
            return ResolvedEndpoint(
                url=target_url,
                api_key=resolved_key,
                headers={"Authorization": f"Bearer {resolved_key}"} if resolved_key else {},
                model=model,
            )

        if p == "litellm":
            target_url = url or f"{resolve_litellm_base_url()}/chat/completions"
            resolved_key = (
                api_key
                or resolve_litellm_key()
                or os.environ.get(EnvironmentVariable.OPENAI_API_KEY.value)
            )
            return ResolvedEndpoint(
                url=target_url,
                api_key=resolved_key,
                headers={"Authorization": f"Bearer {resolved_key}"} if resolved_key else {},
                model=model,
            )

        if p == "local":
            target_url = url or f"{Defaults.LOCAL_OPENAI_BASE_URL}/chat/completions"
            resolved_key = api_key or "local"
            return ResolvedEndpoint(
                url=target_url,
                api_key=resolved_key,
                headers={"Authorization": f"Bearer {resolved_key}"} if resolved_key else {},
                model=model,
            )

        if p == "openai_compatible":
            target_url = url or f"{Defaults.LOCAL_OPENAI_BASE_URL}/chat/completions"
            resolved_key = (
                api_key
                or os.environ.get(EnvironmentVariable.LITE_LLM_KEY.value)
                or os.environ.get(EnvironmentVariable.OPENAI_API_KEY.value)
                or "local"
            )
            return ResolvedEndpoint(
                url=target_url,
                api_key=resolved_key,
                headers={"Authorization": f"Bearer {resolved_key}"} if resolved_key else {},
                model=model,
            )

        if p == "openai":
            target_url = url or Defaults.OPENAI_RESPONSES_URL
            resolved_key = api_key or os.environ.get(EnvironmentVariable.OPENAI_API_KEY.value)
            return ResolvedEndpoint(
                url=target_url,
                api_key=resolved_key,
                headers={"Authorization": f"Bearer {resolved_key}"} if resolved_key else {},
                model=model or Defaults.OPENAI_GENERATION_MODEL,
            )

        # Defaults for other generation providers
        return ResolvedEndpoint(
            url=url or "",
            api_key=api_key,
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            model=model,
        )

    @classmethod
    def resolve_embedding(
        cls,
        provider: str,
        *,
        model: str | None = None,
        url: str | None = None,
        api_key: str | None = None,
        jbcentral_agent: str | None = None,
    ) -> ResolvedEndpoint:
        p = provider.lower().strip()

        if p in ("jbcentral", "jetbrains_central", "jetbrains"):
            cfg = read_jbcentral_config()
            port = cfg.port if cfg else Defaults.JBCENTRAL_DEFAULT_PORT
            secret = cfg.secret if cfg else ""
            agent = (
                jbcentral_agent
                or os.environ.get(EnvironmentVariable.JBCENTRAL_AGENT.value)
                or Defaults.JBCENTRAL_DEFAULT_AGENT
            )
            prefix = f"/wire/{secret}/{agent}" if secret else ""
            default_url = f"http://127.0.0.1:{port}{prefix}/openai/v1/embeddings"
            target_url = url or default_url
            resolved_key = api_key or (secret or "jbcentral")
            return ResolvedEndpoint(
                url=target_url,
                api_key=resolved_key,
                headers={"Authorization": f"Bearer {resolved_key}"} if resolved_key else {},
                model=model,
            )

        if p == "litellm":
            target_url = url or f"{resolve_litellm_base_url()}/embeddings"
            resolved_key = (
                api_key
                or resolve_litellm_key()
                or os.environ.get(EnvironmentVariable.OPENAI_API_KEY.value)
            )
            return ResolvedEndpoint(
                url=target_url,
                api_key=resolved_key,
                headers={"Authorization": f"Bearer {resolved_key}"} if resolved_key else {},
                model=model,
            )

        if p == "local":
            target_url = url or f"{Defaults.LOCAL_OPENAI_BASE_URL}/embeddings"
            resolved_key = api_key or "local"
            return ResolvedEndpoint(
                url=target_url,
                api_key=resolved_key,
                headers={"Authorization": f"Bearer {resolved_key}"} if resolved_key else {},
                model=model,
            )

        if p == "openai_compatible":
            target_url = url or f"{Defaults.LOCAL_OPENAI_BASE_URL}/embeddings"
            resolved_key = (
                api_key
                or os.environ.get(EnvironmentVariable.LITE_LLM_KEY.value)
                or os.environ.get(EnvironmentVariable.OPENAI_API_KEY.value)
                or "local"
            )
            return ResolvedEndpoint(
                url=target_url,
                api_key=resolved_key,
                headers={"Authorization": f"Bearer {resolved_key}"} if resolved_key else {},
                model=model,
            )

        if p == "openai":
            target_url = url or Defaults.OPENAI_EMBEDDINGS_URL
            resolved_key = api_key or os.environ.get(EnvironmentVariable.OPENAI_API_KEY.value)
            return ResolvedEndpoint(
                url=target_url,
                api_key=resolved_key,
                headers={"Authorization": f"Bearer {resolved_key}"} if resolved_key else {},
                model=model or Defaults.OPENAI_EMBEDDING_MODEL,
            )

        return ResolvedEndpoint(
            url=url or "",
            api_key=api_key,
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            model=model,
        )
