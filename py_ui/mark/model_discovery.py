"""Descoberta real de modelos nos provedores configurados (sem vazar segredos)."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from .config.llm_config import LLMKeyVault
from .logging_sanitizer import sanitize_log_text

logger = logging.getLogger("mark.model_discovery")

DEFAULT_ENDPOINTS: dict[str, str] = {
    "openai": "https://api.openai.com/v1/models",
    "openrouter": "https://openrouter.ai/api/v1/models",
    "deepseek": "https://api.deepseek.com/v1/models",
    "groq": "https://api.groq.com/openai/v1/models",
    "mistral": "https://api.mistral.ai/v1/models",
    "together": "https://api.together.xyz/v1/models",
}

#: Provedores sem endpoint OpenAI-compativel de listagem.
NON_LISTING: tuple[str, ...] = ("anthropic", "google", "gemini")


def _extract_ids(payload: Any) -> list[str]:
    """IDs de modelos de uma resposta `/v1/models` ou `{data|models: [...]}`."""
    items: list[Any] = []
    if isinstance(payload, dict):
        for key in ("data", "models", "result"):
            value = payload.get(key)
            if isinstance(value, list):
                items = value
                break
    elif isinstance(payload, list):
        items = payload
    ids: list[str] = []
    for item in items:
        if isinstance(item, str):
            ids.append(item)
        elif isinstance(item, dict):
            for key in ("id", "name", "model"):
                value = item.get(key)
                if isinstance(value, str) and value:
                    ids.append(value)
                    break
    return sorted({item for item in ids if item})


def discover_models(
    base_url: str,
    api_key: str,
    provider: str = "",
    timeout: float = 6.0,
) -> dict[str, Any]:
    """Consulta o endpoint de listagem com timeout curto; nunca loga a chave."""
    url = (base_url or "").strip()
    if not url:
        return {"ok": False, "provider": provider, "models": [], "error": "endpoint vazio"}
    if not url.rstrip("/").endswith("/models"):
        url = url.rstrip("/") + "/models"
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(2 * 1024 * 1024).decode("utf-8", "replace")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
        message = sanitize_log_text(str(exc))
        logger.warning("descoberta de modelos falhou em %s: %s", url, message)
        return {"ok": False, "provider": provider, "models": [], "error": message}
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        return {"ok": False, "provider": provider, "models": [], "error": str(exc)}
    models = _extract_ids(payload)
    return {"ok": bool(models), "provider": provider, "models": models, "url": url}


def discover_configured_providers(timeout: float = 6.0) -> dict[str, Any]:
    """Varre os provedores com chave no cofre e devolve os modelos descobertos."""
    vault = LLMKeyVault()
    found: dict[str, list[str]] = {}
    errors: dict[str, str] = {}
    for provider, endpoint in DEFAULT_ENDPOINTS.items():
        try:
            api_key = vault.get_key(provider)
        except Exception as exc:  # cofre fechado/corrompido nao pode derrubar a UI
            errors[provider] = sanitize_log_text(str(exc))
            continue
        if not api_key:
            continue
        result = discover_models(endpoint, api_key, provider, timeout=timeout)
        if result["ok"]:
            found[provider] = result["models"]
        else:
            errors[provider] = str(result.get("error") or "")
    for provider in NON_LISTING:
        try:
            if vault.get_key(provider):
                errors.setdefault(provider, "endpoint de listagem nao implementado")
        except Exception:
            continue
    return {"ok": bool(found), "providers": found, "errors": errors}
