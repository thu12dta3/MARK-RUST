"""Wayland check: Engineer selector lock, thinking rotator, boot time."""

from __future__ import annotations

import sys
import time
from pathlib import Path

PY_UI = Path(__file__).resolve().parent
if str(PY_UI) not in sys.path:
    sys.path.insert(0, str(PY_UI))

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QMessageBox

QDialog.exec = lambda self: 0  # type: ignore[method-assign]
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)  # type: ignore[assignment]
QInputDialog.getText = staticmethod(lambda *a, **k: ("", False))  # type: ignore[assignment]
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: "")  # type: ignore[assignment]

FAIL: list[str] = []


def pump(app, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)


def check(cond: bool, label: str, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'} {label}{(' :: ' + detail) if detail else ''}")
    if not cond:
        FAIL.append(label)


def main() -> int:
    app = QApplication(sys.argv)
    from mark.ui.i18n import set_language
    from mark.ui.main_window import MainWindow

    t0 = time.perf_counter()
    window = MainWindow()
    window.resize(1600, 900)
    window.show()
    pump(app, 2.0)
    print(f"BOOT_TO_VISIBLE_MS={(time.perf_counter() - t0) * 1000:.0f}")
    set_language("en")
    pump(app, 0.5)

    window.open_specialized_chat("engineer")
    pump(app, 0.6)
    check(not window.engine_button.isEnabled(), "engine travado no Engineer")
    check(not window.model_selector.isEnabled(), "modelo travado no Engineer")
    check(bool(window.engine_button.toolTip()), "tooltip explicativo", window.engine_button.toolTip())

    window.open_specialized_chat("general")
    pump(app, 0.6)
    check(window.engine_button.isEnabled(), "engine liberado no General")
    check(window.model_selector.isEnabled(), "modelo liberado no General")

    window.input.setPlainText("oi")
    window.send_message()
    pump(app, 0.8)
    first = window.connection_label.text()
    pump(app, 2.6)
    second = window.connection_label.text()
    check(first != second, "rotador de pensamento troca a frase", f"{first!r} -> {second!r}")
    check(window._thinking_timer.isActive(), "timer do rotador ativo")

    window._cancel_generation()
    pump(app, 0.6)
    check(not window._thinking_timer.isActive(), "rotador para ao cancelar")
    check("■" not in window.send_button.text(), "botao restaurado", window.send_button.text())

    print("FAILURES:", FAIL)
    window.shutdown()
    window.close()
    pump(app, 0.5)
    return 0 if not FAIL else 3


if __name__ == "__main__":
    raise SystemExit(main())
