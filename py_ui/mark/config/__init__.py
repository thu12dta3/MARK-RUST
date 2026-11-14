from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
from urllib.parse import quote, urlsplit


HOME = Path.home()
ROOT = Path(__file__).resolve().parents[3]
CONFIG_FILE = Path(os.environ.get("MARK_CONFIG", HOME / ".config/mark/config.json"))

HERETIC_GENERAL_MODEL = "haervwe/qwen3-vl-4b-heretic:latest"
HERETIC_ENGINEER_MODEL = "mark-engineer-1.5b"


def get_hardware_cpu_limit() -> int:
    """Retorna o total de cores lógicos detectados no sistema, com fallback seguro."""
    return max(1, os.cpu_count() or 4)


LOCAL_INFERENCE_LIMITS: dict[str, dict[str, Any]] = {
    "num_ctx": {"min": 512, "max": 2097152, "type": int},
    "num_gpu": {"min": 0, "max": 99, "type": int},
    "num_thread": {"min": 1, "max_func": get_hardware_cpu_limit, "type": int},
    "num_batch": {"min": 128, "max": 8192, "type": int},
    "physical_batch_size": {"min": 64, "max": 2048, "type": int},
    "max_concurrent_predictions": {"min": 1, "max": 16, "type": int},
    "context_checkpoints": {"min": 0, "max": 128, "type": int},
}

LOCAL_INFERENCE_DEFAULTS: dict[str, Any] = {
    "num_ctx": 4096,
    "num_gpu": 16,
    "num_thread": min(3, get_hardware_cpu_limit()),
    "num_batch": 2048,
    "physical_batch_size": 512,
    "max_concurrent_predictions": 4,
    "unified_kv_cache": True,
    "context_checkpoints": 32,
    "reasoning_budget_message": "",
    "rope_freq_base": None,
    "rope_freq_scale": None,
    "offload_kv_cache": True,
    "keep_model_in_memory": True,
    "use_mmap": True,
    "seed": None,
    "speculative_decoding": "Off",
    "chat_template": "auto",
    "flash_attn": True,
}

local_inference_params: dict[str, Any] = dict(LOCAL_INFERENCE_DEFAULTS)
local_inference_params["limits"] = {
    k: {"min": v["min"], "max": v["max_func"]() if "max_func" in v else v["max"]}
    for k, v in LOCAL_INFERENCE_LIMITS.items()
}


def clamp_inference_parameter(name: str, value: Any) -> Any:
    """Aplica limites rígidos anti-quebra (Anti-OOM) a um parâmetro específico de inferência."""
    if name in LOCAL_INFERENCE_LIMITS:
        rule = LOCAL_INFERENCE_LIMITS[name]
        min_val = rule["min"]
        max_val = rule["max_func"]() if "max_func" in rule else rule["max"]
        try:
            val_int = int(value)
            return max(min_val, min(max_val, val_int))
        except (ValueError, TypeError):
            return LOCAL_INFERENCE_DEFAULTS.get(name, min_val)

    if name in {"flash_attn", "use_mmap", "offload_kv_cache", "keep_model_in_memory", "unified_kv_cache"}:
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes", "on")
        return bool(value)

    if name in {"rope_freq_base", "rope_freq_scale"}:
        if value is None or value == "" or value == "auto":
            return None
        try:
            v_float = float(value)
            return v_float if v_float > 0 else None
        except (ValueError, TypeError):
            return None

    if name == "seed":
        if value is None or value == "" or value == "auto" or value == -1:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    if name == "reasoning_budget_message":
        return str(value or "")[:500]

    if name == "speculative_decoding":
        val_str = str(value).strip()
        allowed = {"Off", "Draft Model", "Prompt Lookup"}
        return val_str if val_str in allowed else "Off"

    if name == "chat_template":
        return str(value or "auto").strip()

    return value


def validate_and_clamp_inference_params(params: dict[str, Any]) -> dict[str, Any]:
    """Valida e trunca todos os parâmetros de inferência recebidos para limites estritos seguros."""
    clamped = dict(LOCAL_INFERENCE_DEFAULTS)
    for k, v in params.items():
        if k in clamped or k in LOCAL_INFERENCE_LIMITS:
            clamped[k] = clamp_inference_parameter(k, v)
    return clamped


def get_local_inference_params(cfg: dict | None = None) -> dict[str, Any]:
    """Retorna os parâmetros de inferência local atuais do MARK, com garantia de limites seguros."""
    if cfg is None:
        try:
            cfg = load_config()
        except Exception:
            cfg = {}
    saved_params = cfg.get("local_inference") or {}
    return validate_and_clamp_inference_params(saved_params)


def save_local_inference_params(params: dict[str, Any], config_path: Path | None = None) -> dict[str, Any]:
    """Trunca e salva com segurança os parâmetros de inferência no arquivo de configuração do MARK."""
    clamped = validate_and_clamp_inference_params(params)
    target_file = Path(config_path) if config_path else CONFIG_FILE

    target_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    existing_data: dict[str, Any] = {}
    if target_file.is_file():
        try:
            with target_file.open(encoding="utf-8") as f:
                existing_data = json.load(f)
        except Exception:
            existing_data = {}

    existing_data["local_inference"] = clamped
    ollama_block = existing_data.setdefault("ollama", {})
    if "num_ctx" in clamped:
        ollama_block["num_ctx"] = clamped["num_ctx"]
    if "keep_model_in_memory" in clamped:
        ollama_block["keep_alive"] = -1 if clamped["keep_model_in_memory"] else 0

    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(target_file, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(existing_data, f, indent=2, ensure_ascii=False)

    local_inference_params.update(clamped)
    return clamped


DEFAULTS = {
    "ollama": {"url": "http://127.0.0.1:11434", "model": HERETIC_GENERAL_MODEL, "timeout": 180,
               "num_predict": 2048, "num_ctx": 8192, "temperature": 0.7,
               "top_p": 0.8, "top_k": 20, "repeat_penalty": 1.0, "keep_alive": 0},
    "models": {"chat": HERETIC_GENERAL_MODEL, "call": HERETIC_GENERAL_MODEL,
               "engineer": HERETIC_ENGINEER_MODEL, "vision": "markvl-2.2b"},
    "thinking": {"chat": False, "call": False},
    "camera": {"source": "auto", "device": "", "size": "1280x720", "fps": 10, "url": "", "scheme": "rtsps", "tls_verify": False, "timeout": 20},
    "audio": {
        "sample_rate": 16000, "frame_ms": 30, "threshold": 500,
        "min_speech_seconds": 0.18, "end_silence_seconds": 0.75,
        "max_utterance_seconds": 12, "calibration_seconds": 2,
        "source": "default", "sink": "",
    },
    "whisper": {
        "binary": "whisper-cli",
        "timeout": 90,
        "wake_model": str(HOME / ".local/share/mark/ggml-base.bin"),
        "command_model": str(HOME / ".local/share/mark/ggml-small.bin"),
    },
    "tts": {
        "python": str(HOME / ".local/share/mark/piper-env/bin/python"),
        "voice_pt": str(HOME / ".local/share/mark/voices/pt_BR-faber-medium.onnx"),
        "voice_en": str(HOME / ".local/share/mark/voices/en_US-lessac-medium.onnx"),
        "synth_timeout": 60, "playback_timeout": 180, "fallback_timeout": 60,
    },
    "cognition": {"enabled": True, "model_provider": "ollama", "telemetry": False,
                  "knowledge_db": str(HOME / ".local/state/mark/cognition/knowledge.sqlite3")},

    "free_ai": {"enabled": False, "mode": "explicit", "timeout": 15,
                "max_attempts": 2, "daily_per_endpoint": 10},

    "honcho": {"enabled": False, "share_conversations": False,
               "base_url": "https://api.honcho.dev", "workspace_id": "mark",
               "owner_peer_id": "owner", "assistant_peer_id": "mark",
               "session_id": "shared", "timeout_seconds": 4},

    "sentinel": {"share_hash_with_virustotal": False, "virustotal_api_key": ""},
    "web": {"enabled": True, "timeout": 5}, "plugins": {},
    "memory": {"max_messages": 6, "storage_path": str(HOME / ".mark/memory")},
    "memory_storage_path": str(HOME / ".mark/memory"),
    "paths": {"tmp": str(ROOT / "tmp"), "logs": str(ROOT / "logs")},
    "local_inference": dict(LOCAL_INFERENCE_DEFAULTS),
    "reasoning_level": "medium",
}

REASONING_LEVELS = ("instant", "medium", "high")
DEFAULT_REASONING_LEVEL = "medium"


def normalize_reasoning_level(level: Any) -> str:
    """Normaliza o nível de raciocínio; valores inválidos caem no padrão seguro."""
    value = str(level or "").strip().lower()
    return value if value in REASONING_LEVELS else DEFAULT_REASONING_LEVEL


def get_reasoning_level(cfg: dict | None = None) -> str:
    """Lê o nível de raciocínio salvo em disco (ou do cfg informado)."""
    if cfg is None:
        cfg = load_config()
    return normalize_reasoning_level(cfg.get("reasoning_level"))


def set_reasoning_level(level: str, config_path: Path | None = None) -> str:
    """Valida e grava imediatamente o nível de raciocínio no config.json."""
    value = normalize_reasoning_level(level)
    target_file = Path(config_path) if config_path else CONFIG_FILE
    target_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    if target_file.is_file():
        try:
            with target_file.open(encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = {}
    existing["reasoning_level"] = value
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(target_file, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)
    return value



def load_config() -> dict:

    cfg = json.loads(json.dumps(DEFAULTS))
    if CONFIG_FILE.is_file():
        with CONFIG_FILE.open(encoding="utf-8") as f:
            local = json.load(f)
        for section, values in local.items():
            if isinstance(values, dict) and section in cfg:
                cfg[section].update(values)
        if "reasoning_level" in local:
            cfg["reasoning_level"] = normalize_reasoning_level(local["reasoning_level"])
        for scalar_key in ("engine", "selected_model"):
            if scalar_key in local:
                cfg[scalar_key] = local[scalar_key]
    if "local_inference" in cfg and isinstance(cfg["local_inference"], dict):
        cfg["local_inference"] = validate_and_clamp_inference_params(cfg["local_inference"])
    if os.getenv("MARK_KNOWLEDGE_DB"):
        cfg["cognition"]["knowledge_db"] = os.environ["MARK_KNOWLEDGE_DB"]
    if os.getenv("MARK_CAMERA_URL"):
        cfg["camera"]["url"] = os.environ["MARK_CAMERA_URL"]
    if os.getenv("MARK_OLLAMA_URL"):
        cfg["ollama"]["url"] = os.environ["MARK_OLLAMA_URL"]
    if os.getenv("MARK_WEB"):
        cfg["web"]["enabled"] = os.environ["MARK_WEB"].lower() not in {"0", "false", "no"}
    if os.getenv("MARK_AUDIO_SOURCE"):
        cfg["audio"]["source"] = os.environ["MARK_AUDIO_SOURCE"]
    if os.getenv("MARK_AUDIO_SINK"):
        cfg["audio"]["sink"] = os.environ["MARK_AUDIO_SINK"]
    if os.getenv("MARK_VT_API_KEY"):
        cfg["sentinel"]["virustotal_api_key"] = os.environ["MARK_VT_API_KEY"]
    validate_heretic_profiles(cfg)
    return cfg


def validate_heretic_profiles(cfg: dict) -> None:

    models = cfg.get("models")
    fallback = cfg.get("ollama", {}).get("model")
    if not isinstance(models, dict) or not models:
        raise ValueError("O MARK precisa de perfis locais Heretic ou Mark configurados.")
    names = [fallback, *models.values()]
    allowed = ("heretic", "mark", "qwen")
    if any(not isinstance(name, str) or not any(a in name.casefold() for a in allowed) for name in names):
        raise ValueError("Todos os perfis locais do MARK devem usar modelos Heretic ou Mark.")
    chat_model = str(models.get("chat", "")).lower()
    if any(k in chat_model for k in ("markvl", "mark-vl")):
        raise ValueError("O MarkVL é um modelo de percepção visual exclusiva e não pode ser selecionado para chat normal.")


def camera_url(cfg: dict) -> str:

    cam = cfg["camera"]
    if cam.get("url"):
        url = str(cam["url"])
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError:
            raise ValueError("A URL da câmera tem uma porta inválida; use uma porta entre 1 e 65535.") from None
        if parsed.scheme not in {"rtsp", "rtsps"} or not parsed.hostname:
            raise ValueError("A URL da câmera deve usar RTSP/RTSPS e informar um host válido.")
        if port is not None and not 1 <= port <= 65535:
            raise ValueError("A porta RTSP/RTSPS da câmera deve ser um número entre 1 e 65535.")
        return url
    host = cam.get("host", "")
    if not host:
        return ""
    scheme = str(cam.get("scheme", "rtsps")).lower()
    if scheme not in {"rtsp", "rtsps"}:
        raise ValueError("O protocolo da câmera deve ser RTSP ou RTSPS.")
    user = quote(str(cam.get("username", "")), safe="")
    password = quote(str(cam.get("password", "")), safe="")
    auth = f"{user}:{password}@" if user or password else ""
    default_port = 554 if scheme == "rtsp" else 8554
    try:
        port = int(cam.get("port", default_port))
    except (TypeError, ValueError):
        raise ValueError("A porta RTSP/RTSPS da câmera deve ser um número entre 1 e 65535.") from None
    if not 1 <= port <= 65535:
        raise ValueError("A porta RTSP/RTSPS da câmera deve ser um número entre 1 e 65535.")
    path = str(cam.get("path", "/live"))
    if not path.startswith("/"):
        path = "/" + path
    return f"{scheme}://{auth}{host}:{port}{path}"


def get_memory_storage_path(cfg: dict | None = None) -> Path:
    """Retorna o diretório configurado de armazenamento de memória ou o padrão seguro."""
    if cfg is None:
        try:
            cfg = load_config()
        except Exception:
            cfg = {}
    path_val = (
        (cfg.get("memory") or {}).get("storage_path")
        or cfg.get("memory_storage_path")
        or os.environ.get("MARK_MEMORY_PATH")
        or str(HOME / ".mark/memory")
    )
    return Path(path_val).expanduser()


def migrate_memory_storage(source_dir: Path | str, target_dir: Path | str) -> list[str]:
    """Copia com segurança arquivos .sqlite3, .db e .index para a nova pasta e remove os antigos."""
    src = Path(source_dir).expanduser().resolve()
    dst = Path(target_dir).expanduser().resolve()

    if src == dst:
        return []

    dst.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        if dst.stat().st_uid == os.getuid():
            dst.chmod(0o700)
    except OSError:
        pass

    migrated: list[str] = []
    if not src.exists() or not src.is_dir():
        return migrated

    valid_extensions = {".sqlite3", ".db", ".index"}

    for item in src.iterdir():
        if item.is_file() and item.suffix in valid_extensions:
            dest_file = dst / item.name
            shutil.copy2(item, dest_file)
            if dest_file.exists() and dest_file.stat().st_size == item.stat().st_size:
                try:
                    dest_file.chmod(0o600)
                except OSError:
                    pass
                item.unlink()
                migrated.append(item.name)
            else:
                raise IOError(f"Falha na integridade ao migrar arquivo {item.name}")

    return migrated


def set_memory_storage_path(new_path: str | Path, migrate: bool = True) -> dict:
    """Atualiza a pasta de memória na configuração e migra os arquivos existentes."""
    target = Path(new_path).expanduser().resolve()
    target.mkdir(mode=0o700, parents=True, exist_ok=True)

    current_cfg = load_config()
    old_path = get_memory_storage_path(current_cfg)

    migrated_files = []
    if migrate and old_path.exists() and old_path != target:
        migrated_files = migrate_memory_storage(old_path, target)

    CONFIG_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    existing_data = {}
    if CONFIG_FILE.is_file():
        try:
            with CONFIG_FILE.open(encoding="utf-8") as f:
                existing_data = json.load(f)
        except Exception:
            existing_data = {}

    existing_data.setdefault("memory", {})["storage_path"] = str(target)
    existing_data["memory_storage_path"] = str(target)

    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(CONFIG_FILE, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(existing_data, f, indent=2, ensure_ascii=False)

    return {
        "old_path": str(old_path),
        "new_path": str(target),
        "migrated_files": migrated_files,
    }


from .llm_config import (
    AgentProfileConfig,
    LLMConfig,
    LLMKeyVault,
    ProviderProfile,
    get_llm_config,
)

__all__ = [
    "AgentProfileConfig",
    "CONFIG_FILE",
    "DEFAULTS",
    "HERETIC_ENGINEER_MODEL",
    "HERETIC_GENERAL_MODEL",
    "HOME",
    "LLMConfig",
    "LLMKeyVault",
    "LOCAL_INFERENCE_DEFAULTS",
    "LOCAL_INFERENCE_LIMITS",
    "ProviderProfile",
    "ROOT",
    "camera_url",
    "clamp_inference_parameter",
    "get_hardware_cpu_limit",
    "get_llm_config",
    "get_local_inference_params",
    "get_memory_storage_path",
    "load_config",
    "local_inference_params",
    "migrate_memory_storage",
    "save_local_inference_params",
    "set_memory_storage_path",
    "validate_and_clamp_inference_params",
    "validate_heretic_profiles",
]


from .llm_config import get_role_models_config, save_role_models_config


def save_config(cfg: dict[str, Any], config_path: Path | None = None) -> dict[str, Any]:
    """Grava a configuracao inteira em JSON 0600, de forma atomica."""
    target = Path(config_path) if config_path is not None else CONFIG_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(cfg or {})
    staging = target.with_name(target.name + ".tmp")
    staging.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.chmod(staging, 0o600)
    staging.replace(target)
    return payload


def save_role_models_config(
    role_key: str,
    primary_model: str,
    secondary_model: str,
    available_models: list[str],
    primary_provider: str | None = None,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """Persiste um papel (modelo primario/secundario) na configuracao real."""
    cfg = load_config()
    roles = cfg.get("roles_matrix")
    if not isinstance(roles, dict):
        roles = {}
    entry = {
        "role": role_key,
        "primary_model": primary_model,
        "secondary_model": secondary_model,
        "available_models": list(available_models),
    }
    if primary_provider:
        entry["primary_provider"] = primary_provider
    roles[role_key] = entry
    cfg["roles_matrix"] = roles
    legacy = cfg.get("roles")
    if not isinstance(legacy, dict):
        legacy = {}
    legacy[role_key] = {"primary_model": primary_model, "secondary_model": secondary_model}
    cfg["roles"] = legacy
    return save_config(cfg, config_path)
