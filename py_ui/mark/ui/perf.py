"""Performance helpers: adaptive frame pacing plus non-blocking caches.

Every value here is measured from the live machine. Nothing blocks the Qt GUI
thread: slow probes run on daemon threads and the UI reads the last snapshot.
"""

from __future__ import annotations

import subprocess
import threading
import time
from typing import Any, Callable

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QGuiApplication

MIN_FPS = 30
MAX_FPS = 120
_DEFAULT_RATE = 60

_state: dict[str, Any] = {
    "fps": _DEFAULT_RATE,
    "interval_ms": max(8, int(1000 / _DEFAULT_RATE)),
    "screen": "",
    "listeners": [],
}


def clamp_fps(rate: float | int | None) -> int:
    """Converte a taxa do monitor em FPS util, entre 30 e 120."""
    try:
        value = int(round(float(rate or _DEFAULT_RATE)))
    except (TypeError, ValueError):
        value = _DEFAULT_RATE
    return min(max(value, MIN_FPS), MAX_FPS)


def frame_interval_ms() -> int:
    """Intervalo entre frames em milissegundos, nunca abaixo de 8 ms."""
    return max(8, int(1000 / _state["fps"]))


def current_fps() -> int:
    return int(_state["fps"])


def screen_info() -> dict[str, Any]:
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return {"fps": _DEFAULT_RATE, "interval_ms": frame_interval_ms(), "screen": ""}
    return {
        "fps": current_fps(),
        "interval_ms": frame_interval_ms(),
        "screen": screen.name(),
        "rate": screen.refreshRate(),
        "size": f"{screen.size().width()}x{screen.size().height()}",
        "dpr": screen.devicePixelRatio(),
    }


def apply_screen_rate(screen: Any | None = None) -> int:
    """Atualiza o pacing a partir da tela ativa e notifica os listeners."""
    target = screen or QGuiApplication.primaryScreen()
    rate = getattr(target, "refreshRate", lambda: _DEFAULT_RATE)() if target is not None else _DEFAULT_RATE
    _state["fps"] = clamp_fps(rate)
    _state["interval_ms"] = frame_interval_ms()
    if target is not None:
        _state["screen"] = target.name()
    for callback in list(_state["listeners"]):
        try:
            callback(_state["fps"])
        except Exception:
            continue
    return int(_state["fps"])


def on_fps_change(callback: Callable[[int], None]) -> None:
    if callback not in _state["listeners"]:
        _state["listeners"].append(callback)


def install_refresh_tracking() -> int:
    """Conecta refreshRateChanged de todas as telas e devolve o FPS atual."""
    app = QGuiApplication.instance()
    fps = apply_screen_rate()
    if app is None:
        return fps
    for screen in app.screens():
        try:
            screen.refreshRateChanged.connect(lambda _rate, s=screen: apply_screen_rate(s))
        except AttributeError:
            continue
    try:
        app.primaryScreenChanged.connect(apply_screen_rate)
    except AttributeError:
        pass
    return fps


class SnapshotCache:
    """Cache de valores caros atualizado por uma thread daemon."""

    def __init__(self, loader: Callable[[], Any], interval: float = 20.0, initial: Any = None) -> None:
        self._loader = loader
        self._interval = max(2.0, float(interval))
        self._value = initial
        self._stamp = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> "SnapshotCache":
        if self._thread is not None:
            return self
        self._thread = threading.Thread(target=self._loop, name="mark-cache", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.refresh()
            self._stop.wait(self._interval)

    def refresh(self) -> None:
        try:
            value = self._loader()
        except Exception:
            return
        with self._lock:
            self._value = value
            self._stamp = time.time()

    def get(self, default: Any = None) -> Any:
        with self._lock:
            return self._value if self._value is not None else default

    def age(self) -> float:
        with self._lock:
            return time.time() - self._stamp if self._stamp else float("inf")


def default_model_loader() -> list[str]:
    """Lista modelos do Ollama em background (nunca na thread da interface)."""
    try:
        proc = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=6,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    names: list[str] = []
    for line in proc.stdout.splitlines()[1:]:
        parts = line.split()
        if parts:
            names.append(parts[0])
    return names


MODEL_CACHE = SnapshotCache(default_model_loader, interval=25.0, initial=[])


def start_background_caches() -> None:
    """Sobe os caches em background uma unica vez por processo."""
    MODEL_CACHE.start()


def defer(callback: Callable[[], Any], delay_ms: int = 0) -> None:
    """Agenda trabalho fora do handler de clique, devolvendo o controle ao Qt."""
    QTimer.singleShot(max(0, delay_ms), callback)
