"""Real click test: exercises every sidebar button and captures the v4 proofs.

Any unhandled exception inside a Qt slot aborts the process, so this script
installs an excepthook that records failures, patches modal dialogs so the run
cannot block, and asserts the composer invariants (single bullet, no Nuvem).
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
from PyQt6.QtGui import QColor, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QMessageBox, QWidget

OUT = Path(__file__).resolve().parent.parent
SIZE = (1920, 1080)
FAILURES: list[str] = []


def hook(exc_type, exc_value, exc_tb):
    FAILURES.append("".join(traceback.format_exception(exc_type, exc_value, exc_tb)))


sys.excepthook = hook
QDialog.exec = lambda self: 0  # type: ignore[method-assign]
QDialog.open = lambda self: 0  # type: ignore[method-assign]
QMessageBox.exec = lambda self: 0  # type: ignore[method-assign]
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)  # type: ignore[assignment]
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)  # type: ignore[assignment]
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)  # type: ignore[assignment]
QInputDialog.getText = staticmethod(lambda *a, **k: ("", False))  # type: ignore[assignment]
QInputDialog.getItem = staticmethod(lambda *a, **k: ("", False))  # type: ignore[assignment]
QInputDialog.getInt = staticmethod(lambda *a, **k: (0, False))  # type: ignore[assignment]
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: "")  # type: ignore[assignment]
QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: ([], ""))  # type: ignore[assignment]
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: ("", ""))  # type: ignore[assignment]


def pump(app: QApplication, rounds: int = 12) -> None:
    for _ in range(rounds):
        app.processEvents()
        time.sleep(0.004)


def wait_seconds(app: QApplication, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)


def grab(app: QApplication, widget: QWidget, name: str) -> str:
    pump(app, 14)
    widget.repaint()
    pixmap = widget.grab()
    path = OUT / name
    pixmap.save(str(path), "PNG")
    return f"{name}: {pixmap.width()}x{pixmap.height()} ({path.stat().st_size} bytes)"


def visible_widget_texts(window: QWidget) -> list[str]:
    texts: list[str] = []
    for child in window.findChildren(QWidget):
        if not child.isVisible():
            continue
        for getter in ("text", "currentText"):
            method = getattr(child, getter, None)
            if callable(method):
                try:
                    value = str(method())
                except Exception:
                    continue
                if value:
                    texts.append(value)
    return texts


def make_sample_image(path: Path) -> Path:
    pixmap = QPixmap(240, 160)
    pixmap.fill(QColor("#0B0E14"))
    painter = QPainter(pixmap)
    painter.setPen(QColor("#00D8F6"))
    painter.drawRect(12, 12, 216, 136)
    painter.drawLine(12, 148, 228, 12)
    painter.end()
    path.parent.mkdir(parents=True, exist_ok=True)
    pixmap.save(str(path), "PNG")
    return path


def main() -> int:
    app = QApplication(sys.argv)
    from mark.ui.main_window import MainWindow

    window = MainWindow()
    window.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
    window.resize(*SIZE)
    window.show()
    pump(app, 20)
    window.setGeometry(0, 0, SIZE[0], SIZE[1])
    pump(app, 20)

    wait_seconds(app, 4.0)

    bullet_badges = [
        (name, getattr(window, name).text())
        for name in ("routing_target_badge",)
        if getattr(window, name, None) is not None
    ]
    for name, text in bullet_badges:
        print(f"BADGE_{name}: {text!r}")
        assert "●●" not in text, f"caterpillar de bolinhas em {name}"
        assert text.count("●") <= 1, f"mais de um bullet em {name}"

    texts = visible_widget_texts(window)
    nuvem = [text for text in texts if text.strip() == "Nuvem"]
    print("NUVEM_VISIBLE:", nuvem)
    assert not nuvem, "botao Nuvem ainda visivel no composer"

    window.general_nav = getattr(window, "chat_nav_button", None)
    clicks = [
        ("General", window.chat_nav_button, "fhd_v4_1_general_clean.png"),
        ("Engineer", window.engineer_button, "fhd_v4_2_engineer_clicked_ok.png"),
        ("Professor", window.professor_button, "fhd_v4_3_professor_clicked_ok.png"),
        ("Vision", window.vision_nav_button, "fhd_v4_4_vision_clicked_ok.png"),
    ]
    for label, button, image in clicks:
        before = len(FAILURES)
        button.click()
        pump(app, 25)
        wait_seconds(app, 0.35)
        if label == "Vision":
            sample = make_sample_image(Path.home() / ".hermes" / "cache" / "scratch" / "vision_sample.png")
            window._add_attachment_paths([str(sample)])
            pump(app, 20)
            wait_seconds(app, 0.3)
        print(f"CLICK_{label}: exceptions={len(FAILURES) - before} spec={window.current_specialization}")
        print(grab(app, window, image))

    for label, attribute in (
        ("Library", "library_nav_button"),
        ("Evolution", "evolution_nav_button"),
        ("VoiceCall", "call_nav_button"),
        ("Devices", "devices_nav_button"),
        ("Settings", "settings_nav_button"),
    ):
        button = getattr(window, attribute, None)
        if button is None:
            FAILURES.append(f"botao ausente: {attribute}")
            continue
        before = len(FAILURES)
        button.click()
        pump(app, 20)
        wait_seconds(app, 0.2)
        print(f"CLICK_{label}: exceptions={len(FAILURES) - before}")

    window.page_stack.setCurrentWidget(window.chat_page)
    pump(app, 10)
    window.tools_button.click()
    pump(app, 10)
    menu = getattr(window, "tools_menu", None)
    if menu is not None:
        for action in menu.actions():
            if not action.isEnabled() or not action.text():
                continue
            before = len(FAILURES)
            action.trigger()
            pump(app, 15)
            wait_seconds(app, 0.15)
            print(f"MENU_{action.text()[:28]}: exceptions={len(FAILURES) - before}")

    window.page_stack.setCurrentWidget(window.chat_page)
    pump(app, 10)
    window.open_settings()
    pump(app, 15)
    tabs = window.settings_widget.tab_widget
    tabs.setCurrentIndex(tabs.count() - 1)
    pump(app, 15)
    hub = tabs.widget(tabs.count() - 1)
    hub.tabs.setCurrentIndex(1)
    deadline = time.time() + 40
    while time.time() < deadline:
        app.processEvents()
        view = getattr(hub, "hf_view", None)
        if view is not None and view._cards:
            break
        time.sleep(0.05)
    pump(app, 20)
    print("HF_CARDS:", len(getattr(hub.hf_view, "_cards", [])))
    print(grab(app, window, "fhd_v4_5_hf_splitview.png"))

    window.shutdown()
    window.close()
    pump(app, 30)
    print("SHUTDOWN_OK")
    print("TOTAL_EXCEPTIONS:", len(FAILURES))
    for failure in FAILURES[:6]:
        print("EXCEPTION>>>", failure.strip().splitlines()[-1] if failure.strip() else failure)
    return 0 if not FAILURES else 3


if __name__ == "__main__":
    raise SystemExit(main())
