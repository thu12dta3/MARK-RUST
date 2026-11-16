"""Cliente SSE incremental para /v1/chat/completions (stream: true)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable


class StreamCancelled(Exception):
    """Cancelamento solicitado pela UI (botao Stop)."""


def stream_chat(
    url: str,
    payload: dict,
    on_content: Callable[[str], None],
    on_reasoning: Callable[[str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    timeout: float = 600.0,
) -> str:
    """Le o SSE linha a linha e devolve o texto completo ja concatenado."""
    body = dict(payload)
    body["stream"] = True
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json", "accept": "text/event-stream"},
        method="POST",
    )
    full = ""
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("content-type", "")
            if "text/event-stream" not in content_type:
                # Servidor sem SSE: devolve o JSON inteiro para o chamador cair
                # no caminho nao-streaming (fallback limpo, sem inventar chunks).
                raw = response.read().decode("utf-8", "replace")
                try:
                    data = json.loads(raw)
                    text = data["choices"][0]["message"]["content"]
                except (ValueError, KeyError, IndexError, TypeError):
                    return ""
                on_content(text)
                return text
            for raw_line in response:
                if cancelled is not None and cancelled():
                    raise StreamCancelled
                line = raw_line.decode("utf-8", "replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except ValueError:
                    continue
                choices = chunk.get("choices") or []
                if not choices:
                    if chunk.get("error"):
                        raise RuntimeError(str(chunk["error"]))
                    continue
                delta = choices[0].get("delta") or {}
                reasoning = delta.get("reasoning_content") or delta.get("thinking")
                if reasoning and on_reasoning is not None:
                    on_reasoning(str(reasoning))
                content = delta.get("content")
                if content:
                    full += str(content)
                    on_content(str(content))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    return full
