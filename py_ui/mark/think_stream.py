"""Extrator incremental de raciocinio de um stream de texto.

Aceita as duas formas usadas pelos modelos reais:

* `reasoning_content` / `thinking` em campo separado (OpenAI, DeepSeek, Ollama);
* tags `think` escritas dentro do proprio conteudo (Mark-Bin-32B, GGUF).

Nada e inventado: se o stream nao trouxer raciocinio, nenhum fragmento de
raciocinio e emitido e a caixa de pensamento permanece oculta.
"""

from __future__ import annotations

OPEN_TAG = "<" + "think" + ">"
CLOSE_TAG = "<" + "/" + "think" + ">"


class ThinkStreamParser:
    """Separa raciocinio de resposta final mantendo estado entre chunks."""

    def __init__(self) -> None:
        self._buffer = ""
        self._in_reasoning = False
        self._started = False

    @property
    def in_reasoning(self) -> bool:
        return self._in_reasoning

    @property
    def saw_reasoning(self) -> bool:
        return self._started

    def feed_reasoning(self, chunk: str) -> list[tuple[str, str]]:
        """Fragmento vindo de `reasoning_content`/`thinking`."""
        if not chunk:
            return []
        self._started = True
        self._in_reasoning = True
        return [("reasoning", chunk)]

    def feed(self, chunk: str) -> list[tuple[str, str]]:
        """Fragmento de `delta.content`, possivelmente com tags `think`."""
        if not chunk:
            return []
        self._buffer += chunk
        events: list[tuple[str, str]] = []
        while self._buffer:
            if self._in_reasoning:
                end = self._buffer.find(CLOSE_TAG)
                if end < 0:
                    # Tag de fechamento ainda incompleta: guarda o sufixo.
                    keep = _partial_suffix(self._buffer, CLOSE_TAG)
                    emit = self._buffer[: len(self._buffer) - keep]
                    if emit:
                        self._started = True
                        events.append(("reasoning", emit))
                    self._buffer = self._buffer[len(self._buffer) - keep :]
                    break
                body = self._buffer[:end]
                if body:
                    self._started = True
                    events.append(("reasoning", body))
                self._buffer = self._buffer[end + len(CLOSE_TAG) :]
                self._in_reasoning = False
                continue
            start = self._buffer.find(OPEN_TAG)
            if start < 0:
                keep = _partial_suffix(self._buffer, OPEN_TAG)
                emit = self._buffer[: len(self._buffer) - keep]
                if emit:
                    events.append(("content", emit))
                self._buffer = self._buffer[len(self._buffer) - keep :]
                break
            if start > 0:
                events.append(("content", self._buffer[:start]))
            self._buffer = self._buffer[start + len(OPEN_TAG) :]
            self._in_reasoning = True
            self._started = True
        return [(kind, text) for kind, text in events if text]

    def finalize(self) -> list[tuple[str, str]]:
        """Descarrega o resto do buffer no canal corrente."""
        if not self._buffer:
            return []
        kind = "reasoning" if self._in_reasoning else "content"
        rest, self._buffer = self._buffer, ""
        return [(kind, rest)]


def _partial_suffix(text: str, tag: str) -> int:
    """Quantos caracteres finais de `text` sao prefixo parcial de `tag`."""
    limit = min(len(tag) - 1, len(text))
    for size in range(limit, 0, -1):
        if text.endswith(tag[:size]):
            return size
    return 0
