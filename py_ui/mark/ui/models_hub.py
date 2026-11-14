"""MARK Models Hub: role model cards, Hugging Face browser/downloader and local API server.

Four behaviours live in this module:

1. Roles tab (General / Engineer / Professor / Vision) with primary + secondary
   selectors restricted to the allowed local model set.
2. Persisting that role matrix and refreshing the chat model selector.
3. Browsing the whole Hugging Face Hub (not only the Miceworks collection),
   inspecting real repository files, VRAM fit versus 8.0 GiB and resumable
   downloads written to the models root on disk.
4. Starting and stopping the local OpenAI-compatible server through the Rust
   bridge (``mark-server``) and falling back to the Python HTTP server.

Every network call runs inside a QThread; the GUI thread never blocks on HTTP.
"""

from __future__ import annotations

import atexit
import json
import os
from pathlib import Path
import socket
import threading
import time
from typing import Any, Callable, Iterable, NamedTuple
import urllib.error
import urllib.parse
import urllib.request

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

try:
    from ..rust_bridge import rust as rust_client
except Exception:  # bridge module optional at import time
    rust_client = None

from ..config import CONFIG_FILE, load_config
from ..config.llm_config import ROLE_KEYS, get_role_models_config, save_role_models_config
from ..hf_hub_manager import MICEWORKS_OFFICIAL_MODELS, HuggingFaceHubManager
from ..local_server import GLOBAL_LOCAL_SERVER, get_server_logs
from .i18n import tr

try:
    import mark_core as _MARK_CORE
except ImportError:
    _MARK_CORE = None


# ---------------------------------------------------------------------------
# Palette (mirrors ui/theme_manager.py tokens)
# ---------------------------------------------------------------------------

C_CANVAS = "#121417"
C_PANEL = "#16191D"
C_SURFACE = "#1A1D22"
C_BORDER = "#1E2228"
C_BORDER_ACTIVE = "#262B33"
C_TEXT = "#EDEDED"
C_TEXT_SECONDARY = "#8E95A0"
C_TEXT_MUTED = "#5F6672"
C_ACCENT = "#00D8F6"
C_GREEN = "#3FB950"
C_RED = "#F85149"
C_AMBER = "#F59E0B"

# ---------------------------------------------------------------------------
# Model catalogue
# ---------------------------------------------------------------------------

class ModelChoice(NamedTuple):
    """One selectable local model: identifier, display label and group."""

    model_id: str
    label: str
    group: str


MARK_MODEL_CHOICES: tuple[tuple[str, str], ...] = (
    ("mark-bin-32b", "Mark-Bin-32B (1-Bit W1A4, 2M context)"),
    ("mark-rust-4b", "Mark-Rust-4B"),
    ("mark-slm-v3-150m", "Mark-SLM-V3-150M"),
    ("mark-engineer-1.5b", "Mark-Engineer-1.5B"),
    ("mark-general-1.5b", "Mark-General-1.5B"),
    ("mark-vl-2.2b", "Mark-VL-2.2B (vision)"),
    ("mark-slm-v2-302m", "Mark-SLM-V2-302M"),
    ("mark-engineer-302m", "Mark-Engineer-302M"),
)

DEEPSEEK_V2_CHOICES: tuple[tuple[str, str], ...] = (
    ("deepseek-coder-v2-lite-instruct", "DeepSeek-Coder-V2-Lite-Instruct"),
    ("deepseek-v2-lite-chat", "DeepSeek-V2-Lite-Chat"),
)

DEEPSEEK_R1_CHOICES: tuple[tuple[str, str], ...] = (
    ("deepseek-r1:8b-q3_k_l", "DeepSeek R1 8B"),
)

# Models explicitly banned from the role selectors.
BLOCKED_MODEL_MARKERS: tuple[str, ...] = (
    "llama3.2",
    "llama-3.2",
    "gpt-4o",
    "claude-3-5-sonnet",
    "claude-3",
    "qwen2.5-coder:7b",
    "gemini",
    "test-mark",
    "markvl-2.2b",
)

GROUP_ORDER: tuple[str, ...] = ("mark", "deepseek-v2", "deepseek-r1", "local")

GROUP_TITLES: dict[str, str] = {
    "mark": "Mark models",
    "deepseek-v2": "DeepSeek V2",
    "deepseek-r1": "DeepSeek R1 8B",
    "local": "Downloaded or imported locally",
}

ROLE_TITLES: dict[str, str] = {
    "general": "General",
    "engineer": "Engineer",
    "professor": "Professor",
    "vision": "Vision",
}

ROLE_HINTS: dict[str, str] = {
    "general": "Everyday conversation, planning and quick questions.",
    "engineer": "Code, systems work and repository changes.",
    "professor": "Teaching, explanations and study material.",
    "vision": "Images, screenshots and screen understanding.",
}

ROLE_FALLBACKS: dict[str, tuple[str, str]] = {
    "general": ("mark-bin-32b", "mark-slm-v3-150m"),
    "engineer": ("mark-engineer-1.5b", "mark-rust-4b"),
    "professor": ("mark-general-1.5b", "mark-slm-v3-150m"),
    "vision": ("mark-vl-2.2b", "mark-bin-32b"),
}

DOWNLOAD_MANIFEST_NAME = "mark_downloads.json"
VRAM_BUDGET_GIB = 8.0
VRAM_HEADROOM_GIB = 0.9

# Live QThread objects are kept in a module registry so that neither the widget
# nor the interpreter can destroy a thread while it is still running.
_ACTIVE_THREADS: set[QThread] = set()


def register_thread(thread: QThread) -> None:
    """Track a running thread so shutdown can wait for or terminate it."""
    _ACTIVE_THREADS.add(thread)


def unregister_thread(thread: QThread) -> None:
    """Forget a thread once it reported completion."""
    _ACTIVE_THREADS.discard(thread)


def shutdown_active_threads(timeout_ms: int = 2000) -> None:
    """Cancel and join every tracked thread; last resort is termination."""
    for thread in list(_ACTIVE_THREADS):
        cancel = getattr(thread, "cancel", None)
        if callable(cancel):
            try:
                cancel()
            except Exception:
                continue
        thread.requestInterruption()
        if not thread.wait(timeout_ms):
            thread.terminate()
            thread.wait(500)
        _ACTIVE_THREADS.discard(thread)


atexit.register(shutdown_active_threads)


def is_blocked_model(model_id: str) -> bool:
    """Return ``True`` for retired models that must never be offered again."""
    lowered = model_id.strip().lower()
    if not lowered:
        return True
    return any(marker in lowered for marker in BLOCKED_MODEL_MARKERS)


def quant_hint(name: str) -> str:
    """Extract a short quantisation hint such as ``IQ1_S`` from a file name."""
    lowered = name.lower()
    for marker in ("iq1_s", "iq1_m", "iq2_xxs", "q2_k", "q3_k_l", "q3_k_m", "q4_k_m", "q5_k_m", "q8_0"):
        if marker in lowered:
            return marker.upper()
    if "1-bit" in lowered or "1bit" in lowered or "svid" in lowered:
        return "1-BIT"
    if "gguf" in lowered:
        return "GGUF"
    return ""


GENERIC_WEIGHT_STEMS: tuple[str, ...] = (
    "model",
    "weights",
    "pytorch_model",
    "consolidated",
    "model-00001-of-00001",
)


def local_model_id(path_value: str) -> str:
    """Derive a stable model id from a local checkpoint path or file name."""
    path = Path(str(path_value).strip())
    if path.suffix.lower() in {".gguf", ".bin", ".safetensors", ".pth"}:
        stem = path.stem
        if stem.lower() in GENERIC_WEIGHT_STEMS or len(stem) < 5:
            parent = path.parent.name
            if parent:
                return parent.replace("__", "/")
        return stem
    return path.name.replace("__", "/")


def candidate_models(extra_paths: Iterable[str] = ()) -> list[ModelChoice]:
    """Pure function: allowed role models in deterministic order plus extras.

    ``extra_paths`` carries local checkpoints (downloaded here or imported by
    hand); each entry becomes an extra selectable model. No filesystem or
    network access happens inside this function.
    """
    ordered: list[ModelChoice] = []
    seen: set[str] = set()

    def add(model_id: str, label: str, group: str) -> None:
        cleaned = model_id.strip()
        key = cleaned.lower()
        if not cleaned or key in seen or is_blocked_model(key):
            return
        seen.add(key)
        ordered.append(ModelChoice(cleaned, label, group))

    for model_id, label in MARK_MODEL_CHOICES:
        add(model_id, label, "mark")
    for model_id, label in DEEPSEEK_V2_CHOICES:
        add(model_id, label, "deepseek-v2")
    for model_id, label in DEEPSEEK_R1_CHOICES:
        add(model_id, label, "deepseek-r1")

    for raw in sorted({str(item).strip() for item in extra_paths if str(item).strip()}, key=str.lower):
        derived = local_model_id(raw)
        if "mark-bin-32b" in derived.lower():
            # The canonical mark-bin-32b entry already points at this checkpoint.
            continue
        hint = quant_hint(Path(raw).name)
        label = f"{derived} ({hint})" if hint and hint.lower() not in derived.lower() else derived
        add(derived, label, "local")

    return ordered


def resolve_model_root() -> Path:
    """Resolve the models root: ``MARK_MODEL_ROOT``, mark_core or user data dir."""
    env_root = os.environ.get("MARK_MODEL_ROOT") or os.environ.get("MARK_MODELS_DIR")
    if env_root:
        return Path(env_root).expanduser()
    for attribute in ("model_root", "models_root", "model_dir", "models_dir"):
        getter = getattr(_MARK_CORE, attribute, None)
        if not callable(getter):
            continue
        try:
            value = getter()
        except TypeError:
            continue
        if value:
            return Path(str(value)).expanduser()
    return Path.home() / ".local/share/mark/models"


def mark_bin_32b_checkpoint_dir(root: Path | None = None) -> Path:
    """Checkpoint directory ``Mark-Bin-32B`` under the resolved models root."""
    base = root if root is not None else resolve_model_root()
    preferred = base / "Mark-Bin-32B"
    if preferred.exists():
        return preferred
    if base.is_dir():
        for child in sorted(base.iterdir()):
            if child.is_dir() and "mark-bin-32b" in child.name.lower():
                return child
    return preferred


def collect_local_model_paths(root: Path) -> list[str]:
    """Local checkpoint paths: download manifest plus one level of the hub dir."""
    found: list[str] = []
    manifest = root / DOWNLOAD_MANIFEST_NAME
    if manifest.is_file():
        try:
            raw = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = []
        if isinstance(raw, list):
            for entry in raw:
                if isinstance(entry, dict):
                    value = str(entry.get("path") or "").strip()
                    if value:
                        found.append(value)
    if root.is_dir():
        for child in sorted(root.iterdir()):
            if child.is_file():
                if child.suffix.lower() in {".gguf", ".safetensors", ".bin"}:
                    found.append(str(child))
                continue
            if not child.is_dir():
                continue
            shards = sorted(child.glob("*.gguf"))
            if shards:
                found.extend(str(shard) for shard in shards)
                continue
            if (child / "config.json").is_file() and any(child.glob("*.safetensors")):
                found.append(str(child))
    return found


def provider_for_model(model_id: str) -> str:
    """Route a model id to the provider used by the chat dispatcher."""
    lowered = model_id.strip().lower()
    if "bin-32b" in lowered or "1bit" in lowered or "1-bit" in lowered:
        return "mark"
    if lowered.endswith((".gguf", ".safetensors", ".bin")) or "/" in lowered:
        return "local"
    return "ollama"


def persist_roles_matrix(config_file: Path, matrix: dict[str, dict[str, Any]]) -> Path:
    """Write ``roles_matrix`` into the MARK config file with 0600 permissions."""
    config: dict[str, Any] = {}
    try:
        config = dict(load_config())
    except Exception:
        config = {}
    config["roles_matrix"] = matrix
    payload = json.dumps(config, indent=2, ensure_ascii=False)
    config_file.parent.mkdir(parents=True, exist_ok=True)
    staging = config_file.with_name(config_file.name + ".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    descriptor = os.open(staging, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(payload)
    os.replace(staging, config_file)
    return config_file


def register_downloaded_model(root: Path, repo_id: str, filename: str, saved_path: Path) -> Path:
    """Append a finished download to the local manifest used by the role cards."""
    manifest_path = root / DOWNLOAD_MANIFEST_NAME
    entries: list[dict[str, Any]] = []
    if manifest_path.is_file():
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = []
        if isinstance(raw, list):
            entries = [entry for entry in raw if isinstance(entry, dict)]
    size_bytes = saved_path.stat().st_size if saved_path.is_file() else 0
    record = {
        "repo_id": repo_id,
        "filename": filename,
        "path": str(saved_path),
        "size_bytes": size_bytes,
        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    entries = [entry for entry in entries if str(entry.get("path") or "") != record["path"]]
    entries.append(record)
    payload = json.dumps(entries, indent=2, ensure_ascii=False)
    staging = manifest_path.with_name(manifest_path.name + ".tmp")
    descriptor = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(payload)
    os.replace(staging, manifest_path)
    return manifest_path


# ---------------------------------------------------------------------------
# Hugging Face helpers (never touch the widgets directly)
# ---------------------------------------------------------------------------

HF_API = "https://huggingface.co/api/models"
HF_USER_AGENT = "MARK-Desktop-Hub/2.1 (PyQt6; RTX-2060-Super)"

FULL_HUB_QUERIES: tuple[dict[str, Any], ...] = (
    {"sort": "downloads", "direction": -1, "limit": 60, "filter": "text-generation"},
    {"sort": "downloads", "direction": -1, "limit": 40, "pipeline_tag": "text-generation", "filter": "gguf"},
    {"sort": "downloads", "direction": -1, "limit": 20, "pipeline_tag": "text-generation", "filter": "safetensors"},
    {"sort": "downloads", "direction": -1, "limit": 20, "search": "1-bit"},
    {"sort": "downloads", "direction": -1, "limit": 20, "search": "DeepSeek"},
    {"sort": "downloads", "direction": -1, "limit": 20, "search": "Qwen"},
    {"sort": "downloads", "direction": -1, "limit": 20, "search": "Llama"},
    {"sort": "downloads", "direction": -1, "limit": 20, "search": "Mistral"},
)


def fetch_json(url: str, timeout: float = 25.0) -> Any:
    """GET a JSON document from the Hub with an explicit user agent."""
    request = urllib.request.Request(url, headers={"User-Agent": HF_USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310
        return json.loads(response.read().decode("utf-8"))


def normalize_repository(item: dict[str, Any]) -> dict[str, Any] | None:
    """Flatten one Hub API record into the dict consumed by the repo list."""
    repo_id = str(item.get("id") or item.get("modelId") or "").strip()
    if not repo_id:
        return None
    tags = [str(tag).lower() for tag in item.get("tags", []) if tag]
    if "gguf" in tags:
        fmt = "GGUF"
    elif "safetensors" in tags:
        fmt = "Safetensors"
    else:
        fmt = "HF"
    return {
        "id": repo_id,
        "downloads": int(item.get("downloads") or 0),
        "likes": int(item.get("likes") or 0),
        "pipeline": str(item.get("pipeline_tag") or ""),
        "fmt": fmt,
        "tags": tags[:8],
    }


def fetch_popular_repositories(limit: int = 150) -> list[dict[str, Any]]:
    """Popular models from the whole Hub, merged across the filter queries."""
    merged: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    for query in FULL_HUB_QUERIES:
        url = f"{HF_API}?{urllib.parse.urlencode(query)}"
        try:
            payload = fetch_json(url)
        except (urllib.error.HTTPError, urllib.error.URLError, ValueError, OSError) as exc:
            failures.append(str(exc))
            continue
        if not isinstance(payload, list):
            continue
        for item in payload:
            if not isinstance(item, dict):
                continue
            record = normalize_repository(item)
            if record is None:
                continue
            previous = merged.get(record["id"])
            if previous is None or record["downloads"] > previous["downloads"]:
                merged[record["id"]] = record
    if not merged:
        detail = failures[0] if failures else "empty response"
        raise RuntimeError(detail)
    ordered = sorted(merged.values(), key=lambda entry: entry["downloads"], reverse=True)
    return ordered[:limit]


def search_repositories(query: str, limit: int = 40) -> list[dict[str, Any]]:
    """Search any Hub repository id or keyword."""
    params = {"search": query.strip(), "limit": limit, "sort": "downloads", "direction": -1}
    payload = fetch_json(f"{HF_API}?{urllib.parse.urlencode(params)}")
    if not isinstance(payload, list):
        return []
    results: list[dict[str, Any]] = []
    for item in payload:
        if isinstance(item, dict):
            record = normalize_repository(item)
            if record is not None:
                results.append(record)
    return results


def fetch_repo_files(repo_id: str) -> list[dict[str, Any]]:
    """Real file list for one repository (``?blobs=true`` gives sizes)."""
    quoted = urllib.parse.quote(repo_id, safe="/")
    payload = fetch_json(f"{HF_API}/{quoted}?blobs=true")
    if not isinstance(payload, dict):
        return []
    files: list[dict[str, Any]] = []
    for entry in payload.get("siblings") or []:
        if not isinstance(entry, dict):
            continue
        filename = str(entry.get("rfilename") or "").strip()
        if not filename:
            continue
        if Path(filename).suffix.lower() not in {".gguf", ".safetensors", ".bin", ".pth"}:
            continue
        lfs = entry.get("lfs") or {}
        size_bytes = int(entry.get("size") or (lfs.get("size") if isinstance(lfs, dict) else 0) or 0)
        files.append(
            {
                "repo_id": repo_id,
                "filename": filename,
                "size_bytes": size_bytes,
                "url": f"https://huggingface.co/{quoted}/resolve/main/{urllib.parse.quote(filename)}",
            }
        )
    files.sort(key=lambda item: (-item["size_bytes"], item["filename"]))
    return files


def vram_fit(size_bytes: int, budget_gib: float = VRAM_BUDGET_GIB) -> dict[str, Any]:
    """Fit verdict for one model file against the 8.0 GiB VRAM budget."""
    used_gib = float(size_bytes) / (1024 ** 3) if size_bytes > 0 else 0.0
    if size_bytes <= 0:
        return {"state": "unknown", "used_gib": 0.0, "budget_gib": budget_gib}
    fits = used_gib + VRAM_HEADROOM_GIB <= budget_gib
    return {"state": "fits" if fits else "exceeds", "used_gib": used_gib, "budget_gib": budget_gib}


def format_bytes(size_bytes: float) -> str:
    """Human readable size with one decimal place."""
    value = float(size_bytes)
    if value < 1024:
        return f"{int(value)} B"
    for unit in ("KB", "MB", "GB", "TB"):
        value /= 1024.0
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
    return f"{value:.1f} TB"


def format_eta(seconds: float) -> str:
    """``MM:SS`` or ``H:MM:SS`` remaining-time label."""
    if seconds <= 0:
        return "--:--"
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_count(value: int) -> str:
    """Compact download counter such as ``1.2M``."""
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(value)


def port_is_free(port: int) -> bool:
    """Probe whether a TCP port can still be bound on the loopback interface."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


class HubFetchWorker(QThread):
    """Runs one Hub HTTP request outside the GUI thread."""

    reposReady = pyqtSignal(str, object)
    filesReady = pyqtSignal(str, object)
    failed = pyqtSignal(str)

    def __init__(self, mode: str, payload: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.mode = mode
        self.payload = payload

    def run(self) -> None:
        try:
            if self.mode == "popular":
                self.reposReady.emit("popular", fetch_popular_repositories())
            elif self.mode == "search":
                self.reposReady.emit("search", search_repositories(self.payload))
            elif self.mode == "files":
                self.filesReady.emit(self.payload, fetch_repo_files(self.payload))
        except urllib.error.HTTPError as exc:
            self.failed.emit(tr("Hub request failed: HTTP {code} {reason}").format(code=exc.code, reason=exc.reason))
        except urllib.error.URLError as exc:
            self.failed.emit(tr("Cannot reach the Hugging Face Hub: {detail}").format(detail=str(exc.reason)))
        except Exception as exc:
            self.failed.emit(tr("Hub request failed: {detail}").format(detail=str(exc)))


class DownloadWorker(QThread):
    """Resumable HTTP download with live throughput and ETA reporting."""

    progressed = pyqtSignal(int, int, float, float)
    downloadFinished = pyqtSignal(bool, str, str)

    def __init__(
        self,
        url: str,
        dest_path: Path,
        expected_size: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.url = url
        self.dest_path = Path(dest_path)
        self.expected_size = int(expected_size or 0)
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        part_path = self.dest_path.with_name(self.dest_path.name + ".part")
        try:
            self.dest_path.parent.mkdir(parents=True, exist_ok=True)
            resume_from = part_path.stat().st_size if part_path.is_file() else 0
            headers = {"User-Agent": HF_USER_AGENT}
            if resume_from > 0:
                headers["Range"] = f"bytes={resume_from}-"
            request = urllib.request.Request(self.url, headers=headers)
            with urllib.request.urlopen(request, timeout=60) as response:  # nosec B310
                status_code = int(getattr(response, "status", 200) or 200)
                content_length = int(response.headers.get("Content-Length") or 0)
                resuming = resume_from > 0 and status_code == 206
                if not resuming:
                    resume_from = 0
                total = resume_from + content_length if content_length else self.expected_size
                mode = "ab" if resuming else "wb"
                downloaded = resume_from
                started = time.time()
                with open(part_path, mode) as handle:
                    while not self._cancel.is_set():
                        chunk = response.read(262144)
                        if not chunk:
                            break
                        handle.write(chunk)
                        downloaded += len(chunk)
                        elapsed = max(0.001, time.time() - started)
                        speed = (downloaded - resume_from) / (1024 * 1024) / elapsed
                        remaining = max(0, total - downloaded) if total else 0
                        eta = remaining / (1024 * 1024) / speed if speed > 0.01 else 0.0
                        self.progressed.emit(downloaded, max(total, downloaded), round(speed, 2), round(eta, 1))
            if self._cancel.is_set():
                self.downloadFinished.emit(False, "", tr("Download cancelled."))
                return
            if part_path.is_file():
                os.replace(part_path, self.dest_path)
            self.downloadFinished.emit(True, str(self.dest_path), "")
        except urllib.error.HTTPError as exc:
            self.downloadFinished.emit(False, "", tr("HTTP {code} {reason}").format(code=exc.code, reason=exc.reason))
        except urllib.error.URLError as exc:
            self.downloadFinished.emit(False, "", tr("Network error: {detail}").format(detail=str(exc.reason)))
        except OSError as exc:
            self.downloadFinished.emit(False, "", str(exc))


class ServerActionWorker(QThread):
    """Starts or stops the local OpenAI server without blocking the GUI thread."""

    finishedAction = pyqtSignal(bool, str, int, str)

    def __init__(self, action: str, backend: str, host: str, port: int) -> None:
        super().__init__()
        self.action = action
        self.backend = backend
        self.host = host
        self.port = int(port)

    def run(self) -> None:
        if self.action == "start":
            self._run_start()
        else:
            self._run_stop()

    def _run_start(self) -> None:
        if self.backend == "rust" and rust_client is not None:
            try:
                result = dict(rust_client.server_start(self.port) or {})
            except Exception as exc:
                result = {"ok": False, "message": str(exc)}
            if result.get("ok"):
                self.finishedAction.emit(True, "", int(result.get("port") or self.port), "rust")
                return
            rust_message = str(result.get("message") or "")
            stop = getattr(rust_client, "server_stop", None)
            if callable(stop):
                try:
                    stop()
                except Exception:
                    rust_message = rust_message or tr("the Rust server could not be stopped")
            deadline = time.time() + 5
            while time.time() < deadline and not port_is_free(self.port):
                time.sleep(0.25)
            started = GLOBAL_LOCAL_SERVER.start(self.host, self.port)
            self.finishedAction.emit(bool(started), rust_message, self.port, "python" if started else "none")
            return
        started = GLOBAL_LOCAL_SERVER.start(self.host, self.port)
        self.finishedAction.emit(bool(started), "", self.port, "python" if started else "none")

    def _run_stop(self) -> None:
        if self.backend == "rust" and rust_client is not None:
            try:
                result = dict(rust_client.server_stop() or {})
            except Exception as exc:
                result = {"ok": False, "message": str(exc)}
            self.finishedAction.emit(bool(result.get("ok", True)), str(result.get("message") or ""), 0, "rust")
            return
        GLOBAL_LOCAL_SERVER.stop()
        self.finishedAction.emit(True, "", 0, "python")


# ---------------------------------------------------------------------------
# Widget
# ---------------------------------------------------------------------------

class ModelsHubWidget(QWidget):
    """Central de Modelos: papeis, Hugging Face e servidor local OpenAI."""

    rolesUpdated = pyqtSignal()

    def __init__(self, on_roles_changed: Callable[[], None] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.on_roles_changed = on_roles_changed
        self.models_root = resolve_model_root()
        try:
            self.models_root.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.models_root = Path.home() / ".local/share/mark/models"
            self.models_root.mkdir(parents=True, exist_ok=True)
        self.hub = HuggingFaceHubManager(models_dir=self.models_root)
        self._role_widgets: dict[str, dict[str, Any]] = {}
        self._workers: list[HubFetchWorker] = []
        self._download_worker: DownloadWorker | None = None
        self._server_worker: ServerActionWorker | None = None
        self._server_action = ""
        self._rust_logs: list[str] = []
        self._active_backend: str | None = None
        self._last_badge_state: bool | None = None
        self._last_live_port: int = -1
        self._server_page: QWidget | None = None

        self.setObjectName("modelsHub")
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(12)
        title_column = QVBoxLayout()
        title_column.setSpacing(2)
        title = QLabel(tr("Models Hub, 1-Bit Engine & Local Server"))
        title.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {C_TEXT}; background: transparent;")
        title_column.addWidget(title)
        subtitle = QLabel(tr("Role models, Hugging Face downloads and an OpenAI-compatible endpoint."))
        subtitle.setStyleSheet(f"color: {C_TEXT_SECONDARY}; font-size: 12px; background: transparent;")
        subtitle.setWordWrap(True)
        title_column.addWidget(subtitle)
        header.addLayout(title_column, 1)

        self.bench_btn = QPushButton(tr("1-Bit engine benchmark (XNOR-POPCNT)"))
        self.bench_btn.setObjectName("btnBench1Bit")
        self.bench_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.bench_btn.setStyleSheet(
            f"background: {C_PANEL}; color: {C_ACCENT}; border: 1px solid {C_ACCENT}; "
            "border-radius: 6px; padding: 6px 12px; font-weight: 600;"
        )
        self.bench_btn.clicked.connect(self._run_1bit_benchmark)
        header.addWidget(self.bench_btn)
        root.addLayout(header)

        self.status_label = QLabel(tr("Ready."))
        self.status_label.setObjectName("modelsHubStatus")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(f"color: {C_GREEN}; font-size: 12px; font-weight: 500; background: transparent;")
        root.addWidget(self.status_label)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("modelsHubTabs")
        self.tabs.setStyleSheet(
            f"QTabWidget::pane {{ border: 1px solid {C_BORDER}; background: {C_PANEL}; border-radius: 8px; }}"
            f"QTabBar::tab {{ background: {C_SURFACE}; color: {C_TEXT_SECONDARY}; padding: 8px 16px; "
            "border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 4px; }"
            f"QTabBar::tab:selected {{ background: {C_PANEL}; color: {C_ACCENT}; font-weight: 600; "
            f"border-bottom: 2px solid {C_ACCENT}; }}"
        )
        self.tabs.addTab(self._build_roles_tab(), tr("Roles & Available Models"))
        self.tabs.addTab(self._build_hf_downloader_tab(), tr("Download from Hugging Face"))
        self._server_page = self._build_local_server_tab()
        self.tabs.addTab(self._server_page, tr("Local Server (OpenAI API)"))
        self.tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self.tabs, 1)

        self._server_timer = QTimer(self)
        self._server_timer.setInterval(2000)
        self._server_timer.timeout.connect(self._poll_server_status)
        self._server_timer.start()

        application = QApplication.instance()
        if application is not None:
            application.aboutToQuit.connect(self._shutdown_threads)

        self.load_popular_models()

    # -- helpers ----------------------------------------------------------

    def _set_status(self, message: str, kind: str = "info") -> None:
        colors = {"info": C_ACCENT, "ok": C_GREEN, "warn": C_AMBER, "error": C_RED}
        self.status_label.setStyleSheet(
            f"color: {colors.get(kind, C_ACCENT)}; font-size: 12px; font-weight: 500; background: transparent;"
        )
        self.status_label.setText(message)

    def _role_model_choices(self) -> list[ModelChoice]:
        return candidate_models(collect_local_model_paths(self.models_root))

    def _run_1bit_benchmark(self) -> None:
        try:
            if _MARK_CORE is None:
                raise RuntimeError(tr("mark_core extension is not available"))
            gsops = float(_MARK_CORE.mark_1bit_benchmark_gsops(1024, 2048))
        except Exception as exc:
            self._set_status(tr("Benchmark failed: {detail}").format(detail=str(exc)), "error")
            return
        self._set_status(
            tr("1-Bit W1A4 XNOR-POPCNT benchmark finished: {gsops} GSOP/s.").format(gsops=f"{gsops:.2f}"),
            "ok",
        )

    # -- roles tab --------------------------------------------------------

    def _build_roles_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        info = QLabel(
            tr(
                "Only local Mark models, DeepSeek V2, DeepSeek R1 8B and models downloaded or imported "
                "here can be chosen for a role."
            )
        )
        info.setWordWrap(True)
        info.setStyleSheet(f"color: {C_TEXT_SECONDARY}; font-size: 12px; background: transparent;")
        layout.addWidget(info)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        grid = QGridLayout(container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)

        roles_cfg = get_role_models_config()
        choices = self._role_model_choices()
        for position, role_key in enumerate(ROLE_KEYS):
            card = self._build_role_card(role_key, roles_cfg.get(role_key, {}), choices)
            grid.addWidget(card, position // 2, position % 2)
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

        save_btn = QPushButton(tr("Save Role Configuration & Update Chat Selector"))
        save_btn.setObjectName("btnSaveRoles")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet(
            f"background: {C_GREEN}; color: #0B0F14; font-weight: 700; font-size: 13px; "
            "padding: 10px 18px; border-radius: 6px;"
        )
        save_btn.clicked.connect(self._save_all_roles)
        layout.addWidget(save_btn)

        self.roles_status = QLabel("")
        self.roles_status.setObjectName("rolesStatus")
        self.roles_status.setWordWrap(True)
        self.roles_status.setStyleSheet(f"color: {C_TEXT_SECONDARY}; font-size: 12px; background: transparent;")
        layout.addWidget(self.roles_status)
        return page

    def _build_role_card(self, role_key: str, role_cfg: dict[str, Any], choices: list[ModelChoice]) -> QFrame:
        card = QFrame()
        card.setObjectName(f"roleCard_{role_key}")
        card.setStyleSheet(
            f"QFrame {{ background: {C_PANEL}; border: 1px solid {C_BORDER_ACTIVE}; border-radius: 8px; }}"
            f"QFrame QLabel {{ background: transparent; border: none; }}"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        title = QLabel(tr(ROLE_TITLES[role_key]))
        title.setStyleSheet(f"color: {C_ACCENT}; font-size: 14px; font-weight: 700; background: transparent;")
        layout.addWidget(title)

        hint = QLabel(tr(ROLE_HINTS[role_key]))
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {C_TEXT_MUTED}; font-size: 11px; background: transparent;")
        layout.addWidget(hint)
        layout.addSpacing(4)

        primary_label = QLabel(tr("Primary model"))
        primary_label.setStyleSheet(f"color: {C_TEXT}; font-size: 11px; font-weight: 600; background: transparent;")
        layout.addWidget(primary_label)
        primary_combo = QComboBox()
        primary_combo.setObjectName(f"primaryModel_{role_key}")
        self._fill_model_combo(primary_combo, choices, str(role_cfg.get("primary_model") or ""), role_key)
        layout.addWidget(primary_combo)

        secondary_label = QLabel(tr("Secondary model (fallback)"))
        secondary_label.setStyleSheet(f"color: {C_TEXT}; font-size: 11px; font-weight: 600; background: transparent;")
        layout.addWidget(secondary_label)
        secondary_combo = QComboBox()
        secondary_combo.setObjectName(f"secondaryModel_{role_key}")
        self._fill_model_combo(secondary_combo, choices, str(role_cfg.get("secondary_model") or ""), role_key)
        layout.addWidget(secondary_combo)

        if role_key == "general":
            checkpoint = mark_bin_32b_checkpoint_dir(self.models_root)
            path_hint = QLabel(tr("Mark-Bin-32B checkpoint: {path}").format(path=str(checkpoint)))
            path_hint.setWordWrap(True)
            path_hint.setStyleSheet(f"color: {C_TEXT_MUTED}; font-size: 10px; background: transparent;")
            layout.addWidget(path_hint)

        layout.addStretch(1)

        self._role_widgets[role_key] = {"primary": primary_combo, "secondary": secondary_combo}
        return card

    def _fill_model_combo(
        self, combo: QComboBox, choices: list[ModelChoice], selected_id: str, role_key: str
    ) -> None:
        combo.blockSignals(True)
        combo.clear()
        previous_group = ""
        for choice in choices:
            if choice.group != previous_group:
                if combo.count() > 0:
                    combo.insertSeparator(combo.count())
                combo.addItem(tr(GROUP_TITLES.get(choice.group, choice.group)))
                header_index = combo.count() - 1
                header = combo.model().item(header_index)
                if header is not None:
                    header.setEnabled(False)
                previous_group = choice.group
            combo.addItem(tr(choice.label), choice.model_id)
            combo.setItemData(combo.count() - 1, choice.model_id, Qt.ItemDataRole.ToolTipRole)
        combo.blockSignals(False)

        wanted = self._resolve_selected_id(selected_id, choices, role_key)
        index = combo.findData(wanted)
        if index >= 0:
            combo.setCurrentIndex(index)
        elif combo.count() > 0:
            combo.setCurrentIndex(0)

    def _resolve_selected_id(self, selected_id: str, choices: list[ModelChoice], role_key: str) -> str:
        available = {choice.model_id for choice in choices}
        if selected_id and selected_id in available and not is_blocked_model(selected_id):
            return selected_id
        for fallback in ROLE_FALLBACKS.get(role_key, ()):
            if fallback in available:
                return fallback
        return choices[0].model_id if choices else ""

    def _refresh_role_model_combos(self) -> None:
        choices = self._role_model_choices()
        for role_key, widgets in self._role_widgets.items():
            for key in ("primary", "secondary"):
                combo = widgets.get(key)
                if isinstance(combo, QComboBox):
                    current = str(combo.currentData() or "")
                    self._fill_model_combo(combo, choices, current, role_key)

    # -- save -------------------------------------------------------------

    def _save_all_roles(self) -> None:
        matrix: dict[str, dict[str, Any]] = {}
        for role_key in ROLE_KEYS:
            widgets = self._role_widgets.get(role_key)
            if not widgets:
                continue
            primary = str(widgets["primary"].currentData() or "").strip()
            secondary = str(widgets["secondary"].currentData() or "").strip()
            if not primary:
                continue
            ordered = list(dict.fromkeys([primary, secondary or primary]))
            matrix[role_key] = {
                "primary_provider": provider_for_model(primary),
                "primary_model": primary,
                "secondary_model": secondary or primary,
                "available_models": ordered,
            }
        if not matrix:
            self._set_roles_status(tr("No role could be saved: no model is selected."), "error")
            return

        used_fallback = False
        try:
            for role_key, data in matrix.items():
                save_role_models_config(
                    role_key,
                    data["primary_model"],
                    data["secondary_model"],
                    data["available_models"],
                    primary_provider=data["primary_provider"],
                )
        except Exception:
            used_fallback = True
            try:
                persist_roles_matrix(CONFIG_FILE, matrix)
            except Exception as exc:
                self._set_roles_status(tr("Could not save the role configuration: {detail}").format(detail=str(exc)), "error")
                return

        refreshed = self._refresh_chat_selector()
        self.rolesUpdated.emit()
        if self.on_roles_changed is not None:
            try:
                self.on_roles_changed()
            except Exception as exc:
                self._set_status(tr("Chat refresh callback failed: {detail}").format(detail=str(exc)), "warn")
        if used_fallback:
            state = tr("saved directly to {path}").format(path=str(CONFIG_FILE))
        else:
            state = tr("saved to {path}").format(path=str(CONFIG_FILE))
        if refreshed:
            message = tr("Role configuration {state}; chat selector refreshed ({count} selector(s)).").format(
                state=state, count=refreshed
            )
        else:
            message = tr("Role configuration {state}; no chat selector is open in this window.").format(state=state)
        self._set_roles_status(message, "ok")
        self._set_status(tr("Role configuration updated."), "ok")

    def _set_roles_status(self, message: str, kind: str = "info") -> None:
        colors = {"info": C_TEXT_SECONDARY, "ok": C_GREEN, "warn": C_AMBER, "error": C_RED}
        self.roles_status.setStyleSheet(
            f"color: {colors.get(kind, C_TEXT_SECONDARY)}; font-size: 12px; background: transparent;"
        )
        self.roles_status.setText(message)

    def _refresh_chat_selector(self) -> int:
        refreshed = 0
        for window in QApplication.topLevelWidgets():
            for combo in window.findChildren(QComboBox):
                if combo.objectName() != "modelSelector":
                    continue
                populate = getattr(combo, "populate_from_config", None)
                if callable(populate):
                    try:
                        populate()
                        refreshed += 1
                    except Exception:
                        continue
                role_filter = getattr(combo, "set_role_filter", None)
                role_getter = getattr(combo, "current_role", None)
                if callable(role_filter) and callable(role_getter):
                    try:
                        role_filter(str(role_getter()))
                    except Exception:
                        continue
        return refreshed

    # -- Hugging Face tab -------------------------------------------------

    def _build_hf_downloader_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self.hf_search_input = QLineEdit()
        self.hf_search_input.setObjectName("hfSearchInput")
        self.hf_search_input.setPlaceholderText(
            tr("Search any Hugging Face repository, for example Qwen/Qwen3-4B-GGUF")
        )
        self.hf_search_input.returnPressed.connect(self._search_hf)
        search_row.addWidget(self.hf_search_input, 1)

        btn_search = QPushButton(tr("Search"))
        btn_search.setObjectName("btnHfSearch")
        btn_search.clicked.connect(self._search_hf)
        search_row.addWidget(btn_search)

        btn_popular = QPushButton(tr("Popular in the whole Hub"))
        btn_popular.setObjectName("btnHfPopular")
        btn_popular.clicked.connect(self.load_popular_models)
        search_row.addWidget(btn_popular)

        btn_mice = QPushButton(tr("Miceworks Collection"))
        btn_mice.setObjectName("btnHfMiceworks")
        btn_mice.setStyleSheet(
            f"background: {C_PANEL}; color: {C_ACCENT}; border: 1px solid {C_ACCENT}; "
            "border-radius: 6px; padding: 6px 12px; font-weight: 600;"
        )
        btn_mice.clicked.connect(self._load_miceworks_models)
        search_row.addWidget(btn_mice)
        layout.addLayout(search_row)

        budget = QLabel(tr("VRAM fit budget: {budget} GiB for downloads on this machine.").format(budget=f"{VRAM_BUDGET_GIB:.1f}"))
        budget.setStyleSheet(f"color: {C_TEXT_SECONDARY}; font-size: 12px; background: transparent;")
        layout.addWidget(budget)

        lists_row = QHBoxLayout()
        lists_row.setSpacing(10)
        self.repo_list = QListWidget()
        self.repo_list.setObjectName("hfRepoList")
        self.repo_list.itemClicked.connect(self._on_repo_selected)
        lists_row.addWidget(self.repo_list, 1)

        self.files_list = QListWidget()
        self.files_list.setObjectName("hfFilesList")
        lists_row.addWidget(self.files_list, 1)
        layout.addLayout(lists_row, 1)

        progress_row = QHBoxLayout()
        progress_row.setSpacing(10)
        self.dl_progress = QProgressBar()
        self.dl_progress.setObjectName("hfDownloadProgress")
        self.dl_progress.setRange(0, 100)
        self.dl_progress.setValue(0)
        progress_row.addWidget(self.dl_progress, 1)

        self.dl_speed_label = QLabel(tr("Idle"))
        self.dl_speed_label.setStyleSheet(f"color: {C_TEXT_SECONDARY}; font-size: 12px; background: transparent;")
        progress_row.addWidget(self.dl_speed_label)
        layout.addLayout(progress_row)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(8)
        self.btn_download = QPushButton(tr("Download Selected File"))
        self.btn_download.setObjectName("btnHfDownload")
        self.btn_download.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_download.setStyleSheet(
            f"background: {C_ACCENT}; color: #0B0F14; font-weight: 700; padding: 8px 14px; border-radius: 6px;"
        )
        self.btn_download.clicked.connect(self._start_selected_download)
        buttons_row.addWidget(self.btn_download)

        self.btn_cancel_dl = QPushButton(tr("Cancel download"))
        self.btn_cancel_dl.setObjectName("btnHfCancel")
        self.btn_cancel_dl.clicked.connect(self._cancel_download)
        buttons_row.addWidget(self.btn_cancel_dl)
        buttons_row.addStretch(1)

        self.models_root_label = QLabel(tr("Models root: {path}").format(path=str(self.models_root)))
        self.models_root_label.setStyleSheet(f"color: {C_TEXT_MUTED}; font-size: 11px; background: transparent;")
        buttons_row.addWidget(self.models_root_label)
        layout.addLayout(buttons_row)
        return page

    def load_popular_models(self) -> None:
        self._set_hf_status(tr("Loading popular models from the whole Hugging Face Hub."), "info")
        self._start_worker("popular")

    def _load_miceworks_models(self) -> None:
        self.repo_list.clear()
        for entry in MICEWORKS_OFFICIAL_MODELS:
            record = {
                "id": str(entry.get("id") or ""),
                "downloads": int(entry.get("downloads") or 0),
                "likes": 0,
                "pipeline": "text-generation",
                "fmt": str(entry.get("quant") or "HF"),
                "tags": [],
            }
            if not record["id"]:
                continue
            label = f"{record['id']}  ·  {entry.get('params', '')}  ·  {record['fmt']}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, record)
            self.repo_list.addItem(item)
        self.files_list.clear()
        self._set_hf_status(
            tr("{count} repositories from the Miceworks collection.").format(count=self.repo_list.count()),
            "ok",
        )

    def _search_hf(self) -> None:
        query = self.hf_search_input.text().strip()
        if not query:
            self.load_popular_models()
            return
        self._set_hf_status(tr("Searching the Hub for {query}.").format(query=query), "info")
        self._start_worker("search", query)

    def _start_worker(self, mode: str, payload: str = "") -> None:
        worker = HubFetchWorker(mode, payload)
        worker.reposReady.connect(self._on_repos_ready)
        worker.filesReady.connect(self._on_files_ready)
        worker.failed.connect(self._on_hub_error)
        worker.finished.connect(lambda: self._reap_worker(worker))
        self._workers.append(worker)
        register_thread(worker)
        worker.start()

    def _reap_worker(self, worker: HubFetchWorker) -> None:
        unregister_thread(worker)
        if worker in self._workers:
            self._workers.remove(worker)
        worker.deleteLater()

    def _on_repos_ready(self, mode: str, items: list[dict[str, Any]]) -> None:
        self.repo_list.clear()
        for record in items:
            downloads = format_count(int(record.get("downloads") or 0))
            label = f"{record.get('id', '')}  ·  {record.get('fmt', 'HF')}  ·  {downloads} downloads"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, record)
            if record.get("pipeline"):
                item.setToolTip(f"{record.get('pipeline')} · likes {record.get('likes', 0)}")
            self.repo_list.addItem(item)
        self.files_list.clear()
        if mode == "popular":
            message = tr("{count} popular repositories from the whole Hub.")
        else:
            message = tr("{count} repositories match the search.")
        self._set_hf_status(message.format(count=len(items)), "ok" if items else "warn")

    def _on_files_ready(self, repo_id: str, files: list[dict[str, Any]]) -> None:
        self.files_list.clear()
        if not files:
            self._set_hf_status(tr("No downloadable weights found in {repo}.").format(repo=repo_id), "warn")
            return
        fits_count = 0
        for entry in files:
            verdict = vram_fit(int(entry.get("size_bytes") or 0))
            if verdict["state"] == "fits":
                fits_count += 1
                badge = tr("FITS {used} of {budget} GiB").format(
                    used=f"{verdict['used_gib']:.1f}", budget=f"{verdict['budget_gib']:.1f}"
                )
                color = C_GREEN
            elif verdict["state"] == "exceeds":
                badge = tr("EXCEEDS {used} of {budget} GiB").format(
                    used=f"{verdict['used_gib']:.1f}", budget=f"{verdict['budget_gib']:.1f}"
                )
                color = C_RED
            else:
                badge = tr("SIZE UNKNOWN")
                color = C_TEXT_MUTED
            item = QListWidgetItem(
                f"{entry['filename']}  ·  {format_bytes(int(entry.get('size_bytes') or 0))}  ·  {badge}"
            )
            item.setData(Qt.ItemDataRole.UserRole, entry)
            item.setForeground(QColor(color))
            self.files_list.addItem(item)
        self._set_hf_status(
            tr("{count} files in {repo}; {fits} fit in {budget} GiB of VRAM.").format(
                count=len(files), repo=repo_id, fits=fits_count, budget=f"{VRAM_BUDGET_GIB:.1f}"
            ),
            "ok",
        )

    def _on_hub_error(self, message: str) -> None:
        self._set_hf_status(message, "error")

    def _set_hf_status(self, message: str, kind: str = "info") -> None:
        colors = {"info": C_ACCENT, "ok": C_GREEN, "warn": C_AMBER, "error": C_RED}
        self._set_status(message, kind)
        self.dl_speed_label.setStyleSheet(
            f"color: {colors.get(kind, C_TEXT_SECONDARY)}; font-size: 12px; background: transparent;"
        )

    def _on_repo_selected(self, item: QListWidgetItem) -> None:
        record = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(record, dict):
            return
        repo_id = str(record.get("id") or "")
        if not repo_id:
            return
        self.files_list.clear()
        self._set_hf_status(tr("Loading files for {repo}.").format(repo=repo_id), "info")
        self._start_worker("files", repo_id)

    def _start_selected_download(self) -> None:
        current = self.files_list.currentItem()
        if current is None:
            self._set_hf_status(tr("Select a file to download first."), "warn")
            return
        entry = current.data(Qt.ItemDataRole.UserRole)
        if not isinstance(entry, dict):
            self._set_hf_status(tr("Select a file to download first."), "warn")
            return
        if self._download_worker is not None and self._download_worker.isRunning():
            self._set_hf_status(tr("A download is already running."), "warn")
            return
        repo_id = str(entry.get("repo_id") or "")
        filename = str(entry.get("filename") or "")
        url = str(entry.get("url") or "")
        if not repo_id or not filename or not url:
            self._set_hf_status(tr("This file cannot be downloaded: missing repository metadata."), "error")
            return
        target_dir = self.models_root / repo_id.replace("/", "__")
        destination = target_dir / Path(filename).name
        self.dl_progress.setValue(0)
        self.btn_download.setEnabled(False)
        self.btn_cancel_dl.setEnabled(True)
        self._download_worker = DownloadWorker(url, destination, int(entry.get("size_bytes") or 0))
        self._download_worker.progressed.connect(self._on_download_progress)
        self._download_worker.downloadFinished.connect(self._on_download_finished)
        register_thread(self._download_worker)
        self._download_worker.start()
        self._set_hf_status(
            tr("Downloading {file} from {repo} to {dest}.").format(
                file=filename, repo=repo_id, dest=str(destination)
            ),
            "info",
        )

    def _cancel_download(self) -> None:
        if self._download_worker is not None and self._download_worker.isRunning():
            self._download_worker.cancel()
            self._set_hf_status(tr("Cancelling the download..."), "warn")
            return
        self._set_hf_status(tr("No download is running."), "info")

    def _on_download_progress(self, downloaded: int, total: int, speed: float, eta: float) -> None:
        percent = int((downloaded / total) * 100) if total > 0 else 0
        self.dl_progress.setValue(max(0, min(100, percent)))
        self.dl_speed_label.setText(
            tr("{percent}% · {done} of {total} · {speed} MB/s · ETA {eta}").format(
                percent=percent,
                done=format_bytes(downloaded),
                total=format_bytes(total),
                speed=f"{speed:.2f}",
                eta=format_eta(eta),
            )
        )

    def _on_download_finished(self, ok: bool, saved_path: str, message: str) -> None:
        self.btn_download.setEnabled(True)
        self.btn_cancel_dl.setEnabled(False)
        if self._download_worker is not None:
            unregister_thread(self._download_worker)
            self._download_worker.deleteLater()
            self._download_worker = None
        if not ok or not saved_path:
            self.dl_progress.setValue(0)
            self._set_hf_status(tr("Download failed: {detail}").format(detail=message or tr("unknown error")), "error")
            return
        path = Path(saved_path)
        entry = self.files_list.currentItem()
        record = entry.data(Qt.ItemDataRole.UserRole) if entry is not None else None
        if isinstance(record, dict):
            try:
                register_downloaded_model(
                    self.models_root,
                    str(record.get("repo_id") or ""),
                    str(record.get("filename") or path.name),
                    path,
                )
            except OSError as exc:
                self._set_hf_status(tr("Download finished but the manifest was not updated: {detail}").format(detail=str(exc)), "warn")
                return
        self.dl_progress.setValue(100)
        self._refresh_role_model_combos()
        self._set_hf_status(tr("Download finished and registered: {path}").format(path=str(path)), "ok")

    # -- local server tab -------------------------------------------------

    def _build_local_server_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addWidget(QLabel(tr("Host")))
        self.srv_host = QComboBox()
        self.srv_host.setObjectName("srvHost")
        self.srv_host.addItems(["127.0.0.1", "0.0.0.0"])
        controls.addWidget(self.srv_host)

        controls.addWidget(QLabel(tr("Port")))
        self.srv_port = QSpinBox()
        self.srv_port.setObjectName("srvPort")
        self.srv_port.setRange(1024, 65535)
        self.srv_port.setValue(1234)
        controls.addWidget(self.srv_port)

        self.srv_status_badge = QLabel(tr("OFFLINE"))
        self.srv_status_badge.setObjectName("srvStatusBadge")
        self._style_server_badge(False)
        controls.addWidget(self.srv_status_badge)

        self.btn_toggle_srv = QPushButton(tr("Start Server"))
        self.btn_toggle_srv.setObjectName("btnToggleServer")
        self.btn_toggle_srv.setCursor(Qt.CursorShape.PointingHandCursor)
        self._style_server_button(False)
        self.btn_toggle_srv.clicked.connect(self._toggle_local_server)
        controls.addWidget(self.btn_toggle_srv)
        controls.addStretch(1)
        layout.addLayout(controls)

        info_row = QHBoxLayout()
        info_row.setSpacing(16)
        self.srv_backend_label = QLabel(tr("Backend: {backend}").format(backend=self._backend_name()))
        self.srv_backend_label.setStyleSheet(f"color: {C_TEXT_SECONDARY}; font-size: 12px; background: transparent;")
        info_row.addWidget(self.srv_backend_label)

        self.srv_live_port = QLabel(tr("Live port: -"))
        self.srv_live_port.setStyleSheet(f"color: {C_ACCENT}; font-size: 12px; font-weight: 600; background: transparent;")
        info_row.addWidget(self.srv_live_port)
        info_row.addStretch(1)
        layout.addLayout(info_row)

        endpoints = QLabel(
            tr("Endpoints while ONLINE: GET /v1/models | POST /v1/chat/completions | POST /v1/completions | GET /v1/health")
        )
        endpoints.setWordWrap(True)
        endpoints.setStyleSheet(f"color: {C_ACCENT}; font-size: 12px; background: transparent;")
        layout.addWidget(endpoints)

        self.srv_models_label = QLabel(tr("Model ids reported by the server: none yet."))
        self.srv_models_label.setObjectName("srvModelsLabel")
        self.srv_models_label.setWordWrap(True)
        self.srv_models_label.setStyleSheet(f"color: {C_TEXT_SECONDARY}; font-size: 11px; background: transparent;")
        layout.addWidget(self.srv_models_label)

        self.srv_logs_view = QTextEdit()
        self.srv_logs_view.setObjectName("srvLogsView")
        self.srv_logs_view.setReadOnly(True)
        self.srv_logs_view.setStyleSheet(
            f"background: {C_CANVAS}; color: {C_TEXT}; font-family: 'JetBrains Mono', monospace; "
            f"font-size: 12px; border: 1px solid {C_BORDER};"
        )
        layout.addWidget(self.srv_logs_view, 1)
        return page

    def _backend_name(self) -> str:
        return tr("Rust engine (mark-server)") if self._rust_server_binary() else tr("Python fallback server")

    def _rust_server_binary(self) -> bool:
        """True only when the compiled ``mark-server`` binary is reachable."""
        if rust_client is None:
            return False
        lookup = getattr(rust_client, "binary", None)
        if callable(lookup):
            try:
                return bool(lookup("mark-server"))
            except Exception:
                return False
        return self._rust_available()

    def _style_server_badge(self, running: bool) -> None:
        if running:
            self.srv_status_badge.setStyleSheet(
                f"background: #064E3B; color: {C_GREEN}; padding: 4px 10px; border-radius: 6px; font-weight: 700;"
            )
        else:
            self.srv_status_badge.setStyleSheet(
                f"background: {C_BORDER_ACTIVE}; color: {C_TEXT_SECONDARY}; padding: 4px 10px; border-radius: 6px; font-weight: 700;"
            )

    def _style_server_button(self, running: bool) -> None:
        if running:
            self.btn_toggle_srv.setStyleSheet(
                f"background: {C_RED}; color: #0B0F14; font-weight: 700; padding: 8px 16px; border-radius: 6px;"
            )
        else:
            self.btn_toggle_srv.setStyleSheet(
                f"background: {C_GREEN}; color: #0B0F14; font-weight: 700; padding: 8px 16px; border-radius: 6px;"
            )

    def _rust_available(self) -> bool:
        if rust_client is None:
            return False
        probe = getattr(rust_client, "available", None)
        if not callable(probe):
            return False
        try:
            return bool(probe())
        except Exception:
            return False

    def _local_server_status(self) -> dict[str, Any]:
        backend = self._active_backend
        if backend is None:
            backend = "rust" if self._rust_server_binary() else "python"
        if backend == "rust" and self._rust_server_binary():
            try:
                status = rust_client.server_status()
            except Exception as exc:
                return {"running": False, "port": 0, "pid": None, "models": [], "backend": "rust", "error": str(exc)}
            payload = dict(status or {})
            payload["backend"] = "rust"
            payload.setdefault("models", [])
            return payload
        return {
            "running": bool(getattr(GLOBAL_LOCAL_SERVER, "running", False)),
            "port": int(getattr(GLOBAL_LOCAL_SERVER, "port", 0) or 0),
            "pid": None,
            "models": [],
            "backend": "python",
        }

    def _toggle_local_server(self) -> None:
        if self._server_worker is not None and self._server_worker.isRunning():
            self._set_status(tr("Local server action already in progress."), "warn")
            return
        status = self._local_server_status()
        running = bool(status.get("running"))
        action = "stop" if running else "start"
        if running:
            backend = str(status.get("backend") or "python")
        else:
            backend = "rust" if self._rust_server_binary() else "python"
        worker = ServerActionWorker(action, backend, self.srv_host.currentText(), int(self.srv_port.value()))
        self._server_action = action
        worker.finishedAction.connect(self._on_server_action_done)
        worker.finished.connect(lambda: self._reap_server_worker(worker))
        self._server_worker = worker
        register_thread(worker)
        self.btn_toggle_srv.setEnabled(False)
        if action == "start":
            self._set_status(tr("Starting the local server..."), "info")
        else:
            self._set_status(tr("Stopping the local server..."), "info")
        worker.start()

    def _reap_server_worker(self, worker: ServerActionWorker) -> None:
        unregister_thread(worker)
        if worker is self._server_worker:
            self._server_worker = None
        worker.deleteLater()

    def _on_server_action_done(self, ok: bool, message: str, port: int, backend: str) -> None:
        self.btn_toggle_srv.setEnabled(True)
        action = self._server_action
        if action == "start":
            if ok and backend == "rust":
                self._active_backend = "rust"
                text = tr("Rust mark-server listening on port {port}.").format(port=port)
                self._set_status(text, "ok")
            elif ok and backend == "python":
                self._active_backend = "python"
                text = tr("Python fallback server listening on port {port}.").format(port=port)
                if message:
                    text = tr("Rust server unavailable ({detail}); {fallback}").format(detail=message, fallback=text)
                self._set_status(text, "ok")
            else:
                self._active_backend = None
                if message:
                    text = tr("Could not start any local server. Rust: {detail}. Python: port {port} busy.").format(
                        detail=message, port=port
                    )
                else:
                    text = tr("Could not bind the Python fallback server on port {port}.").format(port=port)
                self._set_status(text, "error")
            self._append_log(self.status_label.text())
        else:
            if backend == "rust":
                if ok:
                    self._active_backend = None
                    self._append_log(tr("Rust mark-server stopped."))
                    self._set_status(tr("Rust mark-server stopped."), "ok")
                else:
                    detail = message or tr("unknown error")
                    self._append_log(tr("Rust server stop failed: {detail}").format(detail=detail))
                    self._set_status(tr("Rust server stop failed: {detail}").format(detail=detail), "error")
            else:
                self._active_backend = None
                self._append_log(tr("Python fallback server stopped."))
                self._set_status(tr("Python fallback server stopped."), "ok")
        self._poll_server_status()

    def _append_log(self, message: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {message}"
        self._rust_logs.append(line)
        if len(self._rust_logs) > 400:
            self._rust_logs = self._rust_logs[-400:]
        self.srv_logs_view.setPlainText("\n".join(self._rust_logs))

    def _poll_server_status(self) -> None:
        if self._server_page is not None and self.tabs.currentWidget() is not self._server_page:
            return
        try:
            status = self._local_server_status()
        except Exception as exc:
            self._set_status(tr("Server status unavailable: {detail}").format(detail=str(exc)), "warn")
            return
        running = bool(status.get("running"))
        port = int(status.get("port") or 0)
        self.srv_status_badge.setText(tr("ONLINE") if running else tr("OFFLINE"))
        self._style_server_badge(running)
        self.btn_toggle_srv.setText(tr("Stop Server") if running else tr("Start Server"))
        self._style_server_button(running)
        if running != self._last_badge_state:
            self._last_badge_state = running
            self.srv_port.setEnabled(not running)
            self.srv_host.setEnabled(not running)
        self.srv_live_port.setText(
            tr("Live port: {port}").format(port=port) if running else tr("Live port: -")
        )
        if running and port != self._last_live_port:
            self._last_live_port = port
            if 1024 <= port <= 65535:
                self.srv_port.setValue(port)
        models = [str(item) for item in (status.get("models") or []) if str(item).strip()]
        if models:
            preview = ", ".join(models[:12])
            extra = tr(" (+{count} more)").format(count=len(models) - 12) if len(models) > 12 else ""
            self.srv_models_label.setText(tr("Model ids reported by the server: {models}{extra}").format(models=preview, extra=extra))
        elif running:
            self.srv_models_label.setText(tr("Model ids reported by the server: not published by this backend."))
        else:
            self.srv_models_label.setText(tr("Model ids reported by the server: none yet."))
        if status.get("backend") == "python":
            logs = [line for line in get_server_logs() if line]
            if logs:
                self.srv_logs_view.setPlainText("\n".join(logs))
        if status.get("error"):
            self._set_status(tr("Server status unavailable: {detail}").format(detail=str(status["error"])), "warn")

    def _on_tab_changed(self, index: int) -> None:
        if self._server_page is not None and self.tabs.widget(index) is self._server_page:
            self._poll_server_status()

    # -- lifecycle --------------------------------------------------------

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        if not self._server_timer.isActive():
            self._server_timer.start()
        self.srv_backend_label.setText(tr("Backend: {backend}").format(backend=self._backend_name()))
        self._poll_server_status()

    def hideEvent(self, event: Any) -> None:
        self._server_timer.stop()
        super().hideEvent(event)

    def _shutdown_threads(self) -> None:
        self._server_timer.stop()
        shutdown_active_threads()
        self._workers.clear()
        self._download_worker = None
        self._server_worker = None

    def closeEvent(self, event: Any) -> None:
        self._shutdown_threads()
        super().closeEvent(event)
