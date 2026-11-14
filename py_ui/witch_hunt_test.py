"""Witch-hunt audit: exercises the real MainWindow end to end.

Every step is a real call into the application (or a real .click()), records the
exception instead of dying, and the script fails when anything raises.
"""

from __future__ import annotations

import json
import sys
import time
import traceback
import urllib.request
from pathlib import Path

PY_UI = Path(__file__).resolve().parent
if str(PY_UI) not in sys.path:
    sys.path.insert(0, str(PY_UI))

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QMessageBox, QWidget

OUT = Path(__file__).resolve().parent.parent
SIZE = (1920, 1080)
FAILURES: list[tuple[str, str]] = []


def hook(exc_type, exc_value, exc_tb):
    FAILURES.append(("unhandled", "".join(traceback.format_exception(exc_type, exc_value, exc_tb))))


sys.excepthook = hook
QDialog.exec = lambda self: 0  # type: ignore[method-assign]
QDialog.open = lambda self: 0  # type: ignore[method-assign]
QMessageBox.exec = lambda self: 0  # type: ignore[method-assign]
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)  # type: ignore[assignment]
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)  # type: ignore[assignment]
QMessageBox.critical = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)  # type: ignore[assignment]
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)  # type: ignore[assignment]
QInputDialog.getText = staticmethod(lambda *a, **k: ("", False))  # type: ignore[assignment]
QInputDialog.getItem = staticmethod(lambda *a, **k: ("", False))  # type: ignore[assignment]
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: "")  # type: ignore[assignment]
QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: ([], ""))  # type: ignore[assignment]
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: ("", ""))  # type: ignore[assignment]


def pump(app: QApplication, rounds: int = 12) -> None:
    for _ in range(rounds):
        app.processEvents()
        time.sleep(0.004)


def wait(app: QApplication, seconds: float) -> None:
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


def step(label: str, fn) -> None:
    before = len(FAILURES)
    try:
        fn()
    except Exception:
        FAILURES.append((label, traceback.format_exc()))
    new = len(FAILURES) - before
    print(f"STEP {label}: failures={new}")


def main() -> int:
    app = QApplication(sys.argv)
    from mark.config import get_local_inference_params, save_local_inference_params

    _params = dict(get_local_inference_params())
    _params["num_ctx"] = 2097152  # num_ctx_reset
    save_local_inference_params(_params)
    from mark.ui.i18n import set_language
    from mark.ui.main_window import MainWindow

    w = MainWindow()
    w.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
    w.resize(*SIZE)
    w.show()
    pump(app, 20)
    w.setGeometry(0, 0, SIZE[0], SIZE[1])
    pump(app, 20)
    set_language("en")
    w.language_selector.setCurrentIndex(w.language_selector.findData("en"))
    wait(app, 4.0)

    # ---------------------------------------------------------------- invariants
    def invariants() -> None:
        badge = w.routing_target_badge.text()
        assert "●●" not in badge, f"caterpillar: {badge!r}"
        assert badge.count("●") <= 1, f"bullets: {badge!r}"
        texts = []
        for child in w.findChildren(QWidget):
            if child.isVisible():
                getter = getattr(child, "text", None)
                if callable(getter):
                    try:
                        texts.append(str(getter()))
                    except Exception:
                        continue
        assert "Nuvem" not in texts, "botao Nuvem visivel"
        print("   badge:", badge)

    step("invariants", invariants)

    # ------------------------------------------------------------ model selection
    def select_mark() -> None:
        index = next(i for i in range(w.model_selector.count()) if "Mark-Bin-32B" in w.model_selector.itemText(i))
        w.model_selector.setCurrentIndex(index)
        pump(app, 10)
        w.model_selector.showPopup()
        pump(app, 12)
        w.model_selector.hidePopup()
        wait(app, 2.5)
        text = w.model_selector.currentText()
        assert "Mark-Bin-32B" in text, f"selecao revertida para {text!r}"
        assert "CTX: 2M" in w.ctx_status_label.text(), w.ctx_status_label.text()
        print("   after popup+2.5s:", text, "|", w.ctx_status_label.text())

    step("select_mark_persists", select_mark)

    def ctx_per_model() -> None:
        expected = {"Deepseek R1": "128K", "Mark General 1.5B": "4K", "Mark Engineer 1.5B": "16K"}
        for index in range(w.model_selector.count()):
            label = w.model_selector.itemText(index)
            w.model_selector.setCurrentIndex(index)
            wait(app, 0.4)
            shown = w.ctx_status_label.text()
            for prefix, token in expected.items():
                if prefix.lower() in label.lower():
                    assert token in shown, f"{label}: esperado {token}, veio {shown}"
        print("   ctx per model ok")

    step("ctx_per_model", ctx_per_model)

    # ------------------------------------------------------------------ torture
    def torture() -> None:
        seq = [
            ("settings", lambda: w.settings_nav_button.click()),
            ("general", lambda: w.chat_nav_button.click()),
            ("settings", lambda: w.settings_nav_button.click()),
        ]
        for name, action in seq:
            action()
            wait(app, 0.25)
        tabs = w.settings_widget.tab_widget
        for index in range(tabs.count()):
            tabs.setCurrentIndex(index)
            wait(app, 0.25)
        w.back_button.click()
        wait(app, 0.3)
        for name, attr in (
            ("engineer", "engineer_button"),
            ("professor", "professor_button"),
            ("vision", "vision_nav_button"),
        ):
            getattr(w, attr).click()
            wait(app, 0.3)
            w.settings_nav_button.click()
            wait(app, 0.25)
        for attr in ("library_nav_button", "evolution_nav_button", "devices_nav_button"):
            getattr(w, attr).click()
            wait(app, 0.3)
            w.chat_nav_button.click()
            wait(app, 0.25)
        w.call_nav_button.click()
        wait(app, 0.4)
        w.chat_nav_button.click()
        wait(app, 0.3)
        print("   final spec:", w.current_specialization, "page:", w.page_stack.currentIndex())

    step("torture_transitions", torture)

    # ------------------------------------------------------------- sidebar tools
    def sidebar_tools() -> None:
        for attr in ("library_nav_button", "evolution_nav_button", "devices_nav_button"):
            getattr(w, attr).click()
            wait(app, 0.3)
            w.chat_nav_button.click()
            wait(app, 0.2)
        for action in list(getattr(w, "tools_menu", None).actions() if getattr(w, "tools_menu", None) else []):
            if not action.isEnabled() or not action.text():
                continue
            action.trigger()
            wait(app, 0.2)
            w.chat_nav_button.click()
            wait(app, 0.15)

    step("sidebar_tools", sidebar_tools)

    # ----------------------------------------------------------------- settings
    def settings_tabs() -> None:
        w.open_settings()
        wait(app, 0.3)
        tabs = w.settings_widget.tab_widget
        tabs.setCurrentIndex(0)
        pump(app, 10)
        settings = w.settings_widget
        settings.slider_ctx.setValue(min(settings.slider_ctx.max_val, 65536))
        pump(app, 8)
        settings.reload_inference_button.click()
        wait(app, 0.4)
        tabs.setCurrentIndex(2)
        pump(app, 12)
        tabs.setCurrentIndex(3)
        pump(app, 12)
        hub = tabs.widget(3)
        hub.tabs.setCurrentIndex(0)
        pump(app, 12)
        hub.tabs.setCurrentIndex(2)
        pump(app, 12)
        w.chat_nav_button.click()
        wait(app, 0.3)

    step("settings_tabs_roundtrip", settings_tabs)

    # ------------------------------------------------------------------- roles
    def roles_and_hf() -> None:
        w.open_settings()
        wait(app, 0.2)
        tabs = w.settings_widget.tab_widget
        tabs.setCurrentIndex(3)
        hub = tabs.widget(3)
        hub.tabs.setCurrentIndex(0)
        pump(app, 12)
        save = getattr(hub, "btn_save_roles", None) or getattr(hub, "save_roles_button", None)
        if save is not None:
            save.click()
            wait(app, 0.4)
        hub.tabs.setCurrentIndex(1)
        deadline = time.time() + 40
        while time.time() < deadline:
            app.processEvents()
            view = getattr(hub, "hf_view", None)
            if view is not None and len(view._cards) >= 2:
                break
            time.sleep(0.05)
        view = hub.hf_view
        print("   hf cards:", len(view._cards))
        if len(view._cards) >= 2:
            view._cards[1].clicked.emit(view._cards[1]._repo["id"])
            wait(app, 2.0)
            print("   second repo:", view.title_label.text(), "| files:", len(view._files))
        w.chat_nav_button.click()
        wait(app, 0.3)

    step("roles_and_hf", roles_and_hf)

    # ------------------------------------------------------------ local server
    def local_server() -> None:
        from mark.rust_bridge import rust

        started = rust.server_start(8931)
        assert started.get("ok"), started
        with urllib.request.urlopen("http://127.0.0.1:8931/health", timeout=5) as response:
            assert response.status == 200, response.status
        print("   /health:", response.status, "models:", rust.server_status().get("models"))

    step("rust_server_health", local_server)

    # ---------------------------------------------------------------- languages
    def languages() -> None:
        for code in ("en", "pt-BR", "zh", "hi", "es", "fr", "ar"):
            index = w.language_selector.findData(code)
            w.language_selector.setCurrentIndex(index)
            wait(app, 0.25)
            w.settings_nav_button.click()
            wait(app, 0.2)
            w.chat_nav_button.click()
            wait(app, 0.2)
        w.language_selector.setCurrentIndex(w.language_selector.findData("en"))
        wait(app, 0.2)

    step("seven_languages", languages)

    # ------------------------------------------------------------- command palette
    def palette() -> None:
        w.open_command_palette()
        wait(app, 0.4)
        dialog = getattr(w, "command_palette", None)
        if dialog is not None:
            dialog.close()
        w.chat_nav_button.click()
        wait(app, 0.2)

    step("command_palette", palette)

    # -------------------------------------------------------------- screenshots
    w.open_specialized_chat("general")
    wait(app, 0.3)
    index = next(i for i in range(w.model_selector.count()) if "Mark-Bin-32B" in w.model_selector.itemText(i))
    w.model_selector.setCurrentIndex(index)
    wait(app, 1.2)
    print(grab(app, w, "wh_1_32b_selected_ctx2m.png"))

    for i in range(w.model_selector.count()):
        if "Deepseek R1" in w.model_selector.itemText(i):
            w.model_selector.setCurrentIndex(i)
            break
    wait(app, 1.5)
    print("   r1 ctx:", w.ctx_status_label.text())
    print(grab(app, w, "wh_2_r1_8b_selected_ctx128k.png"))

    w.open_settings()
    wait(app, 0.4)
    tabs = w.settings_widget.tab_widget
    for i in range(tabs.count()):
        tabs.setCurrentIndex(i)
        wait(app, 0.25)
    w.chat_nav_button.click()
    wait(app, 0.8)
    print(grab(app, w, "wh_3_after_settings_roundtrip_to_general.png"))

    w.open_settings()
    wait(app, 0.3)
    tabs.setCurrentIndex(3)
    hub = tabs.widget(3)
    hub.tabs.setCurrentIndex(1)
    deadline = time.time() + 40
    while time.time() < deadline:
        app.processEvents()
        if getattr(hub, "hf_view", None) is not None and len(hub.hf_view._cards) >= 2:
            break
        time.sleep(0.05)
    view = hub.hf_view
    picked = False
    for card in view._cards[:12]:
        view.select_repo(card._repo["id"])
        deadline = time.time() + 12
        while time.time() < deadline:
            app.processEvents()
            if view._files:
                break
            time.sleep(0.05)
        if view._files:
            picked = True
            print("   inspector repo:", view.title_label.text(), "files:", len(view._files))
            break
    print("   inspector picked:", picked)
    print(grab(app, w, "wh_4_hf_splitview_and_engineer.png"))

    w.shutdown()
    w.close()
    pump(app, 25)
    print("SHUTDOWN_OK")
    print("TOTAL_FAILURES:", len(FAILURES))
    for label, detail in FAILURES[:8]:
        last = [line for line in detail.strip().splitlines() if line.strip()][-1:]
        print(f"FAIL[{label}]: {last}")
    return 0 if not FAILURES else 3


if __name__ == "__main__":
    raise SystemExit(main())
