"""Mouse-level torture test: real clicks on every sidebar entry.

PyQt6 aborts when a slot raises during a real mouseReleaseEvent, so this test
drives QTest.mouseClick (the same C++ path as the user) instead of .click(), and
prints every guard log line produced along the way.
"""

from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

PY_UI = Path(__file__).resolve().parent
if str(PY_UI) not in sys.path:
    sys.path.insert(0, str(PY_UI))

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QMessageBox, QWidget

LOG = Path.home() / ".local" / "state" / "mark" / "crash_fault.log"
ERRORS: list[str] = []


def hook(t, v, tb):
    detail = "".join(traceback.format_exception(t, v, tb))
    ERRORS.append(detail)
    print("UNHANDLED>>>", detail.strip().splitlines()[-1], flush=True)


sys.excepthook = hook
QDialog.exec = lambda self: 0  # type: ignore[method-assign]
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)  # type: ignore[assignment]
QInputDialog.getText = staticmethod(lambda *a, **k: ("", False))  # type: ignore[assignment]
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: "")
QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: ([], ""))
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: ("", ""))  # type: ignore[assignment]


def pump(app: QApplication, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)


def log_size() -> int:
    return LOG.stat().st_size if LOG.is_file() else 0


def main() -> int:
    app = QApplication(sys.argv)
    from mark.ui.i18n import set_language
    from mark.ui.main_window import MainWindow
    from mark.ui.safety import install_guards

    window = MainWindow()
    window.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
    window.resize(1920, 1080)
    window.show()
    pump(app, 0.4)
    window.setGeometry(0, 0, 1920, 1080)
    install_guards(app)
    set_language("en")
    pump(app, 2.0)

    baseline = log_size()
    targets = [
        ("General", "chat_nav_button"),
        ("Engineer", "engineer_button"),
        ("Professor", "professor_button"),
        ("Vision", "vision_nav_button"),
        ("Library", "library_nav_button"),
        ("Evolution", "evolution_nav_button"),
        ("VoiceCall", "call_nav_button"),
        ("Devices", "devices_nav_button"),
        ("Settings", "settings_nav_button"),
        ("General", "chat_nav_button"),
    ]
    for label, attribute in targets:
        button = getattr(window, attribute, None)
        if button is None:
            print(f"MISSING {label}")
            continue
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        pump(app, 2.5)
        now = log_size()
        print(f"CLICK {label}: spec={window.current_specialization} new_log={now - baseline} alive=True")
        baseline = now

    # botoes do composer e da barra do Engineer com clique real
    for label, attribute in (
        ("attach", "attach_button"),
        ("refresh", "refresh_button"),
        ("send", "send_button"),
        ("engine", "engine_button"),
    ):
        widget = getattr(window, attribute, None)
        if widget is None:
            continue
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
        pump(app, 0.6)
        print(f"WIDGET {label}: clicked")

    window.open_specialized_chat("engineer")
    pump(app, 0.8)
    bar = window.engineer_bar
    for label, widget in (
        ("permission", bar.permission_combo),
        ("web", bar.web_button),
        ("project", bar.project_button),
    ):
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
        pump(app, 0.5)
        print(f"BAR {label}: clicked")

    window.chat_nav_button.click()
    pump(app, 2.0)
    print("ALIVE_FINAL:", window.isVisible(), "errors:", len(ERRORS))
    print("LOG_BYTES:", log_size() - baseline)
    window.shutdown()
    window.close()
    pump(app, 0.6)
    return 0 if not ERRORS else 3


if __name__ == "__main__":
    raise SystemExit(main())
