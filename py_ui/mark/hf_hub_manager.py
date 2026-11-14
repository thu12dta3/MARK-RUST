from __future__ import annotations

import json
import logging
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

MICEWORKS_OFFICIAL_MODELS: list[dict[str, Any]] = [
    {
        "id": "miceworks/Mark-Bin-32B",
        "name": "Mark-Bin-32B (1-Bit W1A4 Native - 2M Context)",
        "params": "32.2B (6.3B ativos)",
        "size_mb": 4362,
        "quant": "1-Bit SVID + H64",
        "role": "general",
        "is_1bit": True,
    },
    {
        "id": "miceworks/Mark-Rust-4B",
        "name": "Mark-Rust-4B (MoE Top-4 + H-MLA)",
        "params": "4.05B (844M ativos)",
        "size_mb": 2650,
        "quant": "Q4_K_M / 1-Bit",
        "role": "engineer",
        "is_1bit": True,
    },
    {
        "id": "miceworks/Mark-SLM-V3-150M",
        "name": "Mark-SLM-V3-150M (Open SLM Leaderboard)",
        "params": "148M",
        "size_mb": 296,
        "quant": "BF16 / F16 / IQ4_NL",
        "role": "general",
        "is_1bit": False,
    },
    {
        "id": "miceworks/Mark-Engineer-1.5B",
        "name": "Mark-Engineer-1.5B (Sistemas & Codigo)",
        "params": "1.5B",
        "size_mb": 1120,
        "quant": "Q4_K_M / F16",
        "role": "engineer",
        "is_1bit": False,
    },
    {
        "id": "miceworks/Mark-General-1.5B",
        "name": "Mark-General-1.5B (Dialogo & Professor)",
        "params": "1.5B",
        "size_mb": 1120,
        "quant": "Q4_K_M / F16",
        "role": "professor",
        "is_1bit": False,
    },
    {
        "id": "miceworks/Mark-VL-2.2B",
        "name": "Mark-VL-2.2B (Visao Multimodal SigLIP AnyRes)",
        "params": "2.2B",
        "size_mb": 1640,
        "quant": "Q4_K_M",
        "role": "vision",
        "is_1bit": False,
    },
    {
        "id": "miceworks/Mark-SLM-V2-302M",
        "name": "Mark-SLM-V2-302M",
        "params": "302M",
        "size_mb": 340,
        "quant": "Q8_0",
        "role": "general",
        "is_1bit": False,
    },
    {
        "id": "miceworks/Mark-Engineer-302M",
        "name": "Mark-Engineer-302M",
        "params": "302M",
        "size_mb": 340,
        "quant": "Q8_0",
        "role": "engineer",
        "is_1bit": False,
    },
]


def evaluate_hardware_fit(size_mb: float, is_1bit: bool = False) -> dict[str, str]:
    """Calcula compatibilidade fisica para RTX 2060 Super (8 GB VRAM) + 16 GB RAM."""
    if is_1bit and size_mb <= 5500:
        return {
            "badge": "Nativo 1-Bit XNOR-POPCNT (Cabe em 8GB VRAM)",
            "color": "#00b4d8",
            "tier": "1bit_native",
        }
    if size_mb <= 6200:
        return {
            "badge": "Cabe 100% na GPU (RTX 2060 Super 8GB)",
            "color": "#10b981",
            "tier": "full_gpu",
        }
    if size_mb <= 14000:
        return {
            "badge": "Offload Hibrido GPU + RAM (16GB)",
            "color": "#f59e0b",
            "tier": "hybrid",
        }
    return {
        "badge": "Excede 16GB RAM Local",
        "color": "#ef4444",
        "tier": "heavy",
    }


class HuggingFaceHubManager:
    """Gerenciador estilo LM Studio para buscar, inspecionar e baixar modelos do Hugging Face."""

    USER_AGENT = "MARK-Desktop-Hub/2.0 (Garuda Linux; RTX-2060-Super)"

    def __init__(self, models_dir: Path | None = None) -> None:
        self.models_dir = models_dir or (Path.home() / ".local/share/mark/models")
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self._cancel_event = threading.Event()

    def search_models(self, query: str = "", limit: int = 20) -> list[dict[str, Any]]:
        clean = query.strip()
        if not clean or clean.lower() in ("miceworks", "mark", "oficial"):
            return list(MICEWORKS_OFFICIAL_MODELS)

        params = urllib.parse.urlencode({"search": clean, "limit": limit, "sort": "downloads", "direction": "-1"})
        url = f"https://huggingface.co/api/models?{params}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": self.USER_AGENT})
            with urllib.request.urlopen(req, timeout=10) as resp:  # nosec: B310
                data = json.loads(resp.read().decode("utf-8"))
            results = []
            for item in data:
                repo_id = item.get("id", "")
                downloads = item.get("downloads", 0)
                tags = item.get("tags", [])
                quant = "GGUF" if "gguf" in tags else ("Safetensors" if "safetensors" in tags else "HF")
                results.append({
                    "id": repo_id,
                    "name": f"{repo_id} ({downloads} downloads)",
                    "params": quant,
                    "size_mb": 1500,
                    "quant": quant,
                    "role": "general",
                    "is_1bit": "1bit" in repo_id.lower() or "bin-32b" in repo_id.lower(),
                })
            return results
        except Exception as exc:
            logger.warning(f"Erro ao buscar no HF Hub: {exc}")
            return [m for m in MICEWORKS_OFFICIAL_MODELS if clean.lower() in m["id"].lower()]

    def list_repo_files(self, repo_id: str) -> list[dict[str, Any]]:
        url = f"https://huggingface.co/api/models/{repo_id}/tree/main"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": self.USER_AGENT})
            with urllib.request.urlopen(req, timeout=10) as resp:  # nosec: B310
                tree = json.loads(resp.read().decode("utf-8"))
            files = []
            for entry in tree:
                path = entry.get("path", "")
                if any(path.endswith(ext) for ext in (".gguf", ".safetensors", ".bin")):
                    size_bytes = int(entry.get("size") or entry.get("lfs", {}).get("size") or 0)
                    size_mb = round(size_bytes / (1024 * 1024), 1)
                    is_1bit = "bin-32b" in repo_id.lower() or "1bit" in path.lower()
                    fit = evaluate_hardware_fit(size_mb, is_1bit=is_1bit)
                    files.append({
                        "repo_id": repo_id,
                        "filename": path,
                        "size_mb": size_mb,
                        "badge": fit["badge"],
                        "color": fit["color"],
                        "download_url": f"https://huggingface.co/{repo_id}/resolve/main/{urllib.parse.quote(path)}",
                    })
            return files
        except Exception as exc:
            logger.warning(f"Falha ao listar arquivos de {repo_id}: {exc}")
            return []

    def cancel_download(self) -> None:
        self._cancel_event.set()

    def download_file(
        self,
        repo_id: str,
        filename: str,
        progress_cb: Callable[[int, int, float], None] | None = None,
    ) -> Path | None:
        self._cancel_event.clear()
        target_dir = self.models_dir / repo_id.replace("/", "__")
        target_dir.mkdir(parents=True, exist_ok=True)
        dest_path = target_dir / Path(filename).name
        url = f"https://huggingface.co/{repo_id}/resolve/main/{urllib.parse.quote(filename)}"

        existing_bytes = dest_path.stat().st_size if dest_path.exists() else 0
        headers = {"User-Agent": self.USER_AGENT}
        if existing_bytes > 0:
            headers["Range"] = f"bytes={existing_bytes}-"

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:  # nosec: B310
                total_len = int(resp.headers.get("Content-Length") or 0) + existing_bytes
                mode = "ab" if existing_bytes > 0 and resp.status == 206 else "wb"
                downloaded = existing_bytes if mode == "ab" else 0
                t0 = time.time()
                with open(dest_path, mode) as f:
                    while not self._cancel_event.is_set():
                        chunk = resp.read(262144)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        elapsed = max(0.001, time.time() - t0)
                        speed_mbps = (downloaded - existing_bytes) / (1024 * 1024) / elapsed
                        if progress_cb:
                            progress_cb(downloaded, max(downloaded, total_len), round(speed_mbps, 2))
            if self._cancel_event.is_set():
                return None
            return dest_path
        except Exception as exc:
            logger.error(f"Erro no download de {repo_id}/{filename}: {exc}")
            return None

    def list_installed_models(self) -> list[dict[str, Any]]:
        installed: list[dict[str, Any]] = []
        if self.models_dir.exists():
            for p in sorted(self.models_dir.rglob("*")):
                if p.is_file() and p.suffix.lower() in (".gguf", ".safetensors", ".bin"):
                    sz = round(p.stat().st_size / (1024 * 1024), 1)
                    installed.append({
                        "id": p.stem,
                        "name": f"{p.parent.name.replace('__', '/')} :: {p.name}",
                        "path": str(p),
                        "size_mb": sz,
                        "source": "HuggingFace Local",
                    })
        try:
            req = urllib.request.Request("http://127.0.0.1:11434/api/tags", headers={"User-Agent": self.USER_AGENT})
            with urllib.request.urlopen(req, timeout=2) as resp:  # nosec: B310
                data = json.loads(resp.read().decode("utf-8"))
                for m in data.get("models", []):
                    name = m.get("name", "")
                    sz = round(int(m.get("size", 0)) / (1024 * 1024), 1)
                    installed.append({
                        "id": name,
                        "name": f"Ollama :: {name}",
                        "path": f"ollama://{name}",
                        "size_mb": sz,
                        "source": "Ollama",
                    })
        except Exception:
            pass
        return installed
