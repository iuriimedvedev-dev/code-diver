from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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
            target_url = url or f"{Defaults.LITELLM_BASE_URL}/chat/completions"
            resolved_key = (
                api_key
                or os.environ.get(EnvironmentVariable.LITE_LLM_KEY.value)
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
            target_url = url or f"{Defaults.LITELLM_BASE_URL}/embeddings"
            resolved_key = (
                api_key
                or os.environ.get(EnvironmentVariable.LITE_LLM_KEY.value)
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
