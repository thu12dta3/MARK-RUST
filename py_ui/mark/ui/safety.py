"""Crash guards for the Qt application.

PyQt6 aborts the process (qFatal) when a Python exception escapes a slot invoked
from C++, which is what killed the app on a real mouse click. ``GuardedApplication``
catches those exceptions at the event boundary, logs the full traceback and keeps
the window alive; ``install_guards`` additionally covers sys.excepthook and
threading.excepthook and redirects them to the same log.
"""

from __future__ import annotations

import sys
import threading
import traceback
from pathlib import Path
from typing import Any, Callable

from PyQt6.QtCore import QEvent, QObject, QTimer, Qt, qInstallMessageHandler
from PyQt6.QtWidgets import QApplication

LOG_PATH = Path.home() / ".local" / "state" / "mark" / "crash_fault.log"
_FALLBACK_HANDLER: Callable[[str], None] | None = None


def log_failure(label: str) -> None:
    """Grava o traceback completo, nunca engole a causa."""
    detail = traceback.format_exc()
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"\n=== {label} ===\n{detail}\n")
    sys.stderr.write(f"[MARK guard] {label}: {detail.splitlines()[-1]}\n")
    if _FALLBACK_HANDLER is not None:
        try:
            _FALLBACK_HANDLER(f"{label}: {detail.splitlines()[-1]}")
        except Exception:
            pass


def install_guards(app: QApplication, on_error: Callable[[str], None] | None = None) -> None:
    """Instala guards globais de excecao para o processo inteiro."""
    global _FALLBACK_HANDLER
    _FALLBACK_HANDLER = on_error

    def _hook(exc_type, exc_value, exc_tb):
        detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(f"\n=== unhandled ===\n{detail}\n")
        sys.stderr.write(f"[MARK guard] unhandled: {detail.splitlines()[-1]}\n")

    def _thread_hook(args: Any) -> None:
        detail = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(f"\n=== thread {args.thread.name if args.thread else '?'} ===\n{detail}\n")
        sys.stderr.write(f"[MARK guard] thread: {detail.splitlines()[-1]}\n")

    sys.excepthook = _hook
    threading.excepthook = _thread_hook
    app.setProperty("mark_guards", True)


def guarded(widget: QObject, slot: Callable[..., Any], label: str = "") -> Callable[..., Any]:
    """Envolve um slot para que uma excecao vire log em vez de abort."""

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return slot(*args, **kwargs)
        except Exception:
            log_failure(label or getattr(slot, "__name__", "slot"))
            return None

    return wrapper


class GuardedApplication(QApplication):
    """QApplication que converte excecoes de slot em log."""

    def notify(self, receiver: QObject, event: Any) -> bool:  # noqa: N802
        try:
            return super().notify(receiver, event)
        except Exception:
            log_failure(f"event {event.type().name} on {type(receiver).__name__}")
            return False


def show_error_toast(window: Any, message: str) -> None:
    """Mostra o erro no rodape sem interromper o fluxo."""

    def _apply() -> None:
        try:
            label = getattr(window, "connection_label", None)
            if label is not None:
                label.setText(f"MARK · {message}"[:160])
        except RuntimeError:
            return

    QTimer.singleShot(0, _apply)


class WheelGuard(QObject):
    """Impede que a roda do mouse altere QComboBox/QSlider sem foco explicito."""

    def eventFilter(self, obj: QObject, event: Any) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Wheel:
            try:
                if hasattr(obj, "view") and obj.view() is not None and obj.view().isVisible():
                    return False
            except RuntimeError:
                return False
            event.ignore()
            return True
        return False


def install_wheel_guards(root: Any) -> int:
    """Instala o guard em todos os combos e sliders de uma arvore de widgets."""
    from PyQt6.QtWidgets import QComboBox, QSlider

    guard = WheelGuard(root)
    count = 0
    for widget in root.findChildren(QComboBox) + root.findChildren(QSlider):
        widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        widget.installEventFilter(guard)
        count += 1
    setattr(root, "_wheel_guard", guard)
    return count


def install_qt_message_handler() -> None:
    """Grava avisos/fatais do Qt no crash log (inclui abort de QThread/QObject)."""

    def handler(mode: Any, context: Any, message: str) -> None:
        try:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with LOG_PATH.open("a", encoding="utf-8") as handle:
                handle.write(f"\n=== qt {mode.name} ===\n{message}\n")
        except OSError:
            pass
        sys.stderr.write(f"[MARK qt] {message}\n")

    qInstallMessageHandler(handler)
