"""Resolucao deterministica do motor de um modelo.

O seletor manual de engine esta oculto, entao esta funcao e a unica fonte de
verdade: ela precisa acertar para qualquer formato e nunca depender de ordem de
sinais da interface. A resolucao e pura (sem I/O de rede); o chamador passa as
dicas que ja tem em maos (caminho do scanner, origem do scanner, tags do Ollama
e modelos de API sincronizados).
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

#: Fragmentos que identificam o checkpoint nativo SVID / Mark-Bin-32B.
RUST_KEYS: tuple[str, ...] = (
    "mark-bin",
    "mark_bin",
    "markbin",
    "mkbin",
    "svid",
    "1-bit",
    "1bit",
    "32b_1bit",
    "mark_32b",
    "mark-32b",
    "mark-svid",
)

#: Prefixos de provedor: identificador com barra e sempre modelo remoto.
API_PREFIXES: tuple[str, ...] = (
    "openai/",
    "anthropic/",
    "google/",
    "openrouter/",
    "groq/",
    "mistral/",
    "mistralai/",
    "xai/",
    "azure/",
    "together/",
    "cohere/",
    "perplexity/",
    "deepseek/",
    "meta-llama/",
    "meta/",
    "nvidia/",
    "nebius/",
    "fireworks/",
    "huggingface/",
    "qwen/",
    "moonshotai/",
)

#: Familias de modelo que so existem via API (sem barra no identificador).
API_FAMILIES: tuple[str, ...] = (
    "gpt-",
    "chatgpt",
    "o1",
    "o3",
    "o4",
    "claude-",
    "gemini-",
    "grok-",
    "command-",
    "deepseek-",
    "sonar",
    "text-davinci",
    "text-embedding",
    "voyage-",
)

GGUF_SUFFIX = ".gguf"
MK_BIN_SUFFIX = ".mkbin"
SVID_MARKER = "isometric_gpu_core.safetensors"

ENGINE_RUST = "rust"
ENGINE_LLAMACPP = "llamacpp"
ENGINE_OLLAMA = "ollama"
ENGINE_API = "api"


def normalise(model_id: str | None) -> str:
    """Identificador sem prefixo `ollama:` e em minusculas."""
    raw = str(model_id or "").strip()
    if raw.lower().startswith("ollama:"):
        raw = raw.split(":", 1)[1]
    return raw.lower()


def _matches_any(text: str, needles: Iterable[str]) -> bool:
    return any(needle in text for needle in needles)


def _is_path_like(raw: str) -> bool:
    return raw.startswith("/") or raw.startswith("~") or raw.startswith("./") or raw.startswith("../")


def looks_like_ollama_tag(raw: str) -> bool:
    """`<nome>:<tag>` sem barra e sem esquema de URL e uma tag do Ollama."""
    if not raw or "://" in raw.lower():
        return False
    if "/" in raw or "\\" in raw:
        return False
    if raw.count(":") != 1:
        return False
    name, _sep, tag = raw.partition(":")
    return bool(name.strip()) and bool(tag.strip())


def _path_engine(raw: str, exists_check: bool) -> str | None:
    """Engine de um identificador que aponta para um arquivo ou diretorio."""
    candidate = Path(raw).expanduser()
    if exists_check and not candidate.exists():
        return None
    if candidate.is_dir():
        if (candidate / SVID_MARKER).is_file():
            return ENGINE_RUST
        return None
    suffix = candidate.suffix.lower()
    if suffix == MK_BIN_SUFFIX:
        return ENGINE_RUST
    if suffix == GGUF_SUFFIX:
        return ENGINE_LLAMACPP
    return None


def resolve_engine(
    model_id: str | None,
    *,
    local_path: str | None = None,
    scanner_source: str | None = None,
    local_gguf: Iterable[str] = (),
    ollama_tags: Iterable[str] = (),
    api_models: Iterable[str] = (),
) -> str:
    """Devolve `rust`, `llamacpp`, `ollama` ou `api` de forma deterministica.

    A ordem das regras e fixa e cada uma e mais especifica que a seguinte:
    lista de API sincronizada, caminho real no disco, checkpoint SVID,
    extensao local, dicas do scanner, tag do Ollama, familia remota.
    """
    raw = str(model_id or "").strip()
    if not raw:
        return ENGINE_API
    mid = normalise(raw)

    # 1. Modelo de API sincronizado com a chave do provedor: decisao explicita.
    known_api = {normalise(item) for item in api_models if item}
    if mid in known_api:
        return ENGINE_API

    # 2. Caminho que existe no disco: o formato do arquivo decide.
    from_path = _path_engine(raw, exists_check=True)
    if from_path is not None:
        return from_path
    if local_path:
        from_hint = _path_engine(str(local_path), exists_check=False)
        if from_hint is not None:
            return from_hint

    # 3. Checkpoint nativo SVID / Mark-Bin-32B, por nome ou por marcador.
    if _matches_any(mid, RUST_KEYS):
        return ENGINE_RUST

    # 4. Extensao local mesmo que o arquivo tenha saido do disco: um `.gguf`
    #    nunca pode cair no Ollama, e um `.mkbin` e sempre o motor Rust.
    suffix = Path(mid).suffix
    if suffix == GGUF_SUFFIX:
        return ENGINE_LLAMACPP
    if suffix == MK_BIN_SUFFIX:
        return ENGINE_RUST

    # 5. Dicas do scanner (origem real do modelo).
    source = (scanner_source or "").strip().lower()
    if source in ("gguf", "llamacpp"):
        return ENGINE_LLAMACPP
    if source in ("ollama",):
        return ENGINE_OLLAMA
    if source in ("huggingface", "safetensors", "svid"):
        return ENGINE_RUST if source in ("svid",) else ENGINE_LLAMACPP

    known_gguf = {normalise(item) for item in local_gguf if item}
    if mid in known_gguf or any(mid.endswith(item) for item in known_gguf if item.endswith(GGUF_SUFFIX)):
        return ENGINE_LLAMACPP

    # 6. Barra no identificador e namespace de provedor: sempre remoto.
    if "/" in mid:
        return ENGINE_API
    if _matches_any(mid, API_PREFIXES):
        return ENGINE_API

    # 7. Tag instalada no Ollama local, antes das familias remotas, para que
    #    `deepseek-coder:latest` local nao vire `deepseek-*` de API.
    known_tags = {normalise(item) for item in ollama_tags if item}
    if mid in known_tags:
        return ENGINE_OLLAMA
    if looks_like_ollama_tag(raw):
        return ENGINE_OLLAMA

    # 8. Familias que so existem por API.
    if _matches_any(mid, API_FAMILIES):
        return ENGINE_API

    # 9. Fallback seguro: sem caminho, sem tag e sem familia local conhecida, o
    #    identificador so pode ser remoto.
    if _is_path_like(raw):
        return ENGINE_LLAMACPP if suffix else ENGINE_API
    return ENGINE_API


def engine_label(engine: str) -> str:
    """Rotulo curto e estavel do motor resolvido."""
    return {
        ENGINE_RUST: "Rust 1-Bit (GPU)",
        ENGINE_LLAMACPP: "llama.cpp (GGUF local)",
        ENGINE_OLLAMA: "Ollama (local)",
        ENGINE_API: "API remota",
    }.get(engine, "API remota")
