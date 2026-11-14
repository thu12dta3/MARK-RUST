"""Diagnose the stray top-level windows that appear in Engineer and Vision."""

from __future__ import annotations

import sys
import time
from pathlib import Path

PY_UI = Path(__file__).resolve().parent
if str(PY_UI) not in sys.path:
    sys.path.insert(0, str(PY_UI))

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QMessageBox

QDialog.exec = lambda self: 0  # type: ignore[method-assign]
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)  # type: ignore[assignment]
QInputDialog.getText = staticmethod(lambda *a, **k: ("", False))  # type: ignore[assignment]
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: "")  # type: ignore[assignment]


def pump(app: QApplication, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)


def dump(app: QApplication, label: str) -> None:
    print(f"--- {label} ---")
    for widget in app.topLevelWidgets():
        if not widget.isVisible():
            continue
        geom = widget.geometry()
        print(
            f"  {widget.__class__.__name__:24} name={widget.objectName()!r:24} "
            f"title={widget.windowTitle()!r:28} geom=({geom.x()},{geom.y()},{geom.width()}x{geom.height()}) "
            f"parent={widget.parent().__class__.__name__ if widget.parent() else None}"
        )


def main() -> int:
    app = QApplication(sys.argv)
    from mark.ui.main_window import MainWindow

    window = MainWindow()
    window.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
    window.resize(1920, 1080)
    window.show()
    pump(app, 1.0)
    window.setGeometry(0, 0, 1920, 1080)

    dump(app, "boot")
    for label, attribute in (
        ("Engineer", "engineer_button"),
        ("Vision", "vision_nav_button"),
        ("General", "chat_nav_button"),
    ):
        button = getattr(window, attribute)
        print(f"click {label}")
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        pump(app, 2.5)
        dump(app, label)

    window.shutdown()
    window.close()
    pump(app, 0.5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
