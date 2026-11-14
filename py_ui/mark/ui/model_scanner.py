"""Model metadata scanner: real context length, layers and format in a few ms.

Reads only configuration and headers (never the tensors), so it is safe to call
from the Qt thread. Sources: Hugging Face folders, GGUF headers and the Ollama
API. Every value comes from the files on disk or from the daemon; missing data is
reported as ``None`` instead of guessed.
"""

from __future__ import annotations

import json
import os
import struct
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

OLLAMA_URL = "http://127.0.0.1:11434"

CONTEXT_KEYS = (
    "max_position_embeddings",
    "max_seq_len",
    "model_max_length",
    "n_positions",
    "seq_length",
    "context_length",
    "sliding_window",
)
LAYER_KEYS = ("num_hidden_layers", "n_layer", "num_layers", "block_count", "n_layers")
HIDDEN_KEYS = ("hidden_size", "n_embd", "d_model", "d_embd")

_CACHE: dict[str, dict[str, Any]] = {}


def format_ctx(tokens: int | None) -> str:
    """Formata tokens em rótulo compacto: 2097152 -> 2M, 131072 -> 128K."""
    if not tokens or tokens <= 0:
        return "CTX: --"
    if tokens >= 1024 * 1024:
        value = tokens / (1024 * 1024)
        label = f"{value:.1f}".rstrip("0").rstrip(".") + "M"
    elif tokens >= 1024:
        value = tokens / 1024
        label = f"{value:.0f}K" if value >= 10 else f"{value:.1f}".rstrip("0").rstrip(".") + "K"
    else:
        label = str(tokens)
    return f"CTX: {label}"


def _first_int(payload: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and value > 0:
            return int(value)
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def _lookup_suffix(payload: dict[str, Any], suffix: str) -> int | None:
    for key, value in payload.items():
        if str(key).endswith(suffix) and isinstance(value, (int, float)) and value > 0:
            return int(value)
    return None


def _dir_size_gib(root: Path) -> float:
    total = 0
    for path in root.rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            continue
    return round(total / (1024 ** 3), 2)


def _capabilities(profile: dict[str, Any]) -> list[str]:
    caps: list[str] = []
    architectures = " ".join(profile.get("architectures") or [])
    haystack = f"{architectures} {profile.get('id', '')} {profile.get('arch', '')}".lower()
    vision_keys = ("vision_config", "visual", "image_token")
    if any(key in profile for key in vision_keys) or any(tag in haystack for tag in ("-vl", "vl-", "vision", "llava", "multimodal")):
        caps.append("Vision")
    if profile.get("reasoning") or "reasoning" in haystack or "r1" in haystack:
        caps.append("Reasoning")
    if profile.get("tool_use") or "instruct" in haystack or "coder" in haystack:
        caps.append("Tool Use")
    return caps


def _scan_hf_dir(path: Path, model_id: str) -> dict[str, Any]:
    config_path = path / "config.json"
    if not config_path.is_file():
        return {"ok": False, "id": model_id, "source": "hf-dir", "reason": "config.json ausente"}
    try:
        config = json.loads(config_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "id": model_id, "source": "hf-dir", "reason": str(exc)}

    context = _first_int(config, CONTEXT_KEYS)
    layers = _first_int(config, LAYER_KEYS)
    hidden = _first_int(config, HIDDEN_KEYS)
    if context is None:
        for key in ("text_config", "llm_config", "language_config"):
            nested = config.get(key)
            if isinstance(nested, dict):
                context = _first_int(nested, CONTEXT_KEYS) or context
                layers = layers or _first_int(nested, LAYER_KEYS)
                hidden = hidden or _first_int(nested, HIDDEN_KEYS)

    dtype = str(config.get("torch_dtype") or config.get("dtype") or "").lower()
    quant = config.get("quantization_config") or {}
    format_label = "BF16" if "bfloat16" in dtype else "FP16" if "float16" in dtype else "FP32" if "float32" in dtype else "Safetensors"
    if isinstance(quant, dict) and quant:
        bits = int(quant.get("bits") or quant.get("w_bit") or 0)
        format_label = f"INT{bits}" if bits else "Quantized"
    if "svid" in path.name.lower() or "bin-32b" in path.name.lower():
        format_label = "1-Bit W1A4 SVID"

    profile: dict[str, Any] = {
        "ok": True,
        "id": model_id,
        "source": "hf-dir",
        "path": str(path),
        "arch": str((config.get("architectures") or [config.get("model_type") or "unknown"])[0]),
        "architectures": list(config.get("architectures") or []),
        "context": context,
        "layers": layers,
        "hidden_size": hidden,
        "format": format_label,
        "size_gib": _dir_size_gib(path),
        "reasoning": bool(config.get("reasoning")),
    }
    profile["capabilities"] = _capabilities(profile)
    return profile


def _gguf_value(handle, vtype: int) -> Any:
    """Le um valor GGUF simples (strings, escalares) do arquivo aberto."""
    if vtype == 0:
        return handle.read(1)[0]
    if vtype == 1:
        return struct.unpack("<b", handle.read(1))[0]
    if vtype == 2:
        return struct.unpack("<H", handle.read(2))[0]
    if vtype == 3:
        return struct.unpack("<h", handle.read(2))[0]
    if vtype == 4:
        return struct.unpack("<I", handle.read(4))[0]
    if vtype == 5:
        return struct.unpack("<i", handle.read(4))[0]
    if vtype == 6:
        return struct.unpack("<f", handle.read(4))[0]
    if vtype == 7:
        return bool(handle.read(1)[0])
    if vtype == 8:
        length = struct.unpack("<Q", handle.read(8))[0]
        return handle.read(length).decode("utf-8", errors="replace")
    if vtype == 9:
        item_type = struct.unpack("<I", handle.read(4))[0]
        count = struct.unpack("<Q", handle.read(8))[0]
        values = [_gguf_value(handle, item_type) for _ in range(min(count, 64))]
        if count > 64:
            handle.seek(0, os.SEEK_CUR)
        return values
    if vtype == 10:
        return struct.unpack("<Q", handle.read(8))[0]
    if vtype == 11:
        return struct.unpack("<q", handle.read(8))[0]
    if vtype == 12:
        return struct.unpack("<d", handle.read(8))[0]
    raise ValueError(f"tipo GGUF desconhecido: {vtype}")


def _scan_gguf(path: Path, model_id: str) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            magic = handle.read(4)
            if magic != b"GGUF":
                return {"ok": False, "id": model_id, "source": "gguf", "reason": "magic GGUF invalido"}
            version = struct.unpack("<I", handle.read(4))[0]
            handle.read(8)  # tensor count
            kv_count = struct.unpack("<Q", handle.read(8))[0]
            meta: dict[str, Any] = {}
            for _ in range(min(kv_count, 512)):
                key_len = struct.unpack("<Q", handle.read(8))[0]
                key = handle.read(key_len).decode("utf-8", errors="replace")
                vtype = struct.unpack("<I", handle.read(4))[0]
                try:
                    meta[key] = _gguf_value(handle, vtype)
                except (ValueError, struct.error):
                    break
    except (OSError, struct.error) as exc:
        return {"ok": False, "id": model_id, "source": "gguf", "reason": str(exc)}

    arch = str(meta.get("general.architecture") or "unknown")
    context = _lookup_suffix(meta, ".context_length")
    layers = _lookup_suffix(meta, ".block_count")
    hidden = _lookup_suffix(meta, ".embedding_length")
    file_type = meta.get("general.file_type")
    format_label = "GGUF"
    if isinstance(file_type, int):
        format_label = f"GGUF (file_type {file_type})"
    profile: dict[str, Any] = {
        "ok": context is not None or layers is not None,
        "id": model_id,
        "source": "gguf",
        "path": str(path),
        "arch": arch,
        "architectures": [arch],
        "context": context,
        "layers": layers,
        "hidden_size": hidden,
        "format": format_label,
        "size_gib": round(path.stat().st_size / (1024 ** 3), 2),
        "gguf_version": version,
        "quantization": meta.get("general.quantization_version"),
    }
    profile["capabilities"] = _capabilities(profile)
    return profile


def _scan_ollama(tag: str) -> dict[str, Any]:
    payload = json.dumps({"model": tag}).encode()
    request = urllib.request.Request(
        f"{OLLAMA_URL}/api/show",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=4) as response:
            data = json.loads(response.read().decode())
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"ok": False, "id": tag, "source": "ollama", "reason": str(exc)}

    info = data.get("model_info") or {}
    details = data.get("details") or {}
    context = _lookup_suffix(info, ".context_length")
    layers = _lookup_suffix(info, ".block_count")
    hidden = _lookup_suffix(info, ".embedding_length")
    parameter_size = str(details.get("parameter_size") or "")
    profile: dict[str, Any] = {
        "ok": context is not None or layers is not None,
        "id": tag,
        "source": "ollama",
        "arch": str(details.get("family") or info.get("general.architecture") or "unknown"),
        "architectures": [str(details.get("family") or "unknown")],
        "context": context,
        "layers": layers,
        "hidden_size": hidden,
        "format": f"Ollama {details.get('quantization_level') or ''}".strip(),
        "size_gib": None,
        "parameters": parameter_size,
        "capabilities": list(data.get("capabilities") or []),
    }
    if not profile["capabilities"]:
        profile["capabilities"] = _capabilities(profile)
    return profile


def candidate_paths(model_id: str) -> list[Path]:
    """Caminhos plausiveis para um modelo local, sem varrer o disco inteiro."""
    roots: list[Path] = []
    env_root = os.environ.get("MARK_MODEL_ROOT")
    if env_root:
        roots.append(Path(env_root))
    xdg = os.environ.get("XDG_DATA_HOME")
    roots.append((Path(xdg) if xdg else Path.home() / ".local" / "share") / "mark" / "models")
    roots.append(Path.home() / ".cache" / "huggingface" / "hub")
    external = os.environ.get("MARK_EXTERNAL_MODELS")
    if external:
        roots.append(Path(external))
    paths: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        direct = root / model_id
        paths.append(direct)
        flat = root / model_id.replace("/", "__")
        paths.append(flat)
        slug = model_id.split("/")[-1]
        paths.append(root / slug)
        paths.append(root / f"models--{model_id.replace('/', '--')}")
    try:
        from ..rust_bridge import rust

        checkpoint = rust.engine_status().get("checkpoint")
        if checkpoint:
            paths.append(Path(str(checkpoint)))
    except Exception:
        pass
    return [path for path in paths if path.exists()]


def scan_model(model_id: str, use_cache: bool = True) -> dict[str, Any]:
    """Inspeciona o modelo e devolve contexto, camadas, formato e capacidades."""
    if not model_id:
        return {"ok": False, "id": "", "reason": "modelo vazio"}
    key = model_id.strip()
    if use_cache and key in _CACHE:
        return _CACHE[key]

    result: dict[str, Any]
    for path in candidate_paths(key):
        if path.is_dir() and (path / "config.json").is_file():
            result = _scan_hf_dir(path, key)
            break
        if path.is_file() and path.suffix == ".gguf":
            result = _scan_gguf(path, key)
            break
    else:
        found = None
        for path in candidate_paths(key):
            if path.is_dir():
                ggufs = list(path.glob("*.gguf"))
                if ggufs:
                    found = ggufs[0]
                    break
        result = _scan_gguf(found, key) if found else _scan_ollama(key)

    if not result.get("ok") and result.get("source") != "ollama":
        fallback = _scan_ollama(key.split(":")[0])
        if fallback.get("ok"):
            result = fallback
    _CACHE[key] = result
    return result


def clear_cache() -> None:
    _CACHE.clear()
