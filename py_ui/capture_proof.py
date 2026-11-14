"""Captures the four visual proofs of the MARK PyQt6 interface.

Run with the MARK-RUST virtualenv on a live display:
    /home/thu12/MARK-RUST/.venv/bin/python py_ui/capture_proof.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PY_UI = Path(__file__).resolve().parent
if str(PY_UI) not in sys.path:
    sys.path.insert(0, str(PY_UI))

from PyQt6.QtWidgets import QApplication, QWidget

OUT = Path(__file__).resolve().parent.parent
SIZE = (1280, 850)


def pump(app: QApplication, rounds: int = 12) -> None:
    for _ in range(rounds):
        app.processEvents()


def grab(app: QApplication, window: QWidget, name: str) -> str:
    pump(app)
    window.repaint()
    pump(app, 6)
    pixmap = window.grab()
    path = OUT / name
    pixmap.save(str(path), "PNG")
    return f"{name}: {pixmap.width()}x{pixmap.height()} ({path.stat().st_size} bytes)"


def main() -> int:
    app = QApplication(sys.argv)
    from mark.ui.i18n import set_language
    from mark.ui.main_window import MainWindow

    window = MainWindow()
    window.resize(*SIZE)
    window.show()
    set_language("en")
    window.language_selector.setCurrentIndex(window.language_selector.findData("en"))
    pump(app, 30)

    items = [window.model_selector.itemText(i) for i in range(window.model_selector.count())]
    print("COMPOSER_MODELS:", items)
    print("PILL:", window.routing_target_badge.text())
    print("CONNECTION:", window.connection_label.text())
    print("PLACEHOLDER:", window.input.placeholderText())
    print("REASONING:", [window.reasoning_selector.itemText(i) for i in range(window.reasoning_selector.count())])
    print(grab(app, window, "fixed_1_chat_en.png"))

    window.open_settings()
    tabs = window.settings_widget.tab_widget
    print("SETTINGS_TABS:", [tabs.tabText(i) for i in range(tabs.count())])
    vault_index = 1
    for i in range(tabs.count()):
        if "vault" in tabs.tabText(i).lower():
            vault_index = i
    tabs.setCurrentIndex(vault_index)
    pump(app, 25)
    print(grab(app, window, "fixed_2_vault_rust.png"))

    tabs.setCurrentIndex(tabs.count() - 1)
    pump(app, 20)
    hub = tabs.widget(tabs.count() - 1)
    hub_tabs = getattr(hub, "tabs", None)
    print("HUB_TABS:", [hub_tabs.tabText(i) for i in range(hub_tabs.count())])

    hub_tabs.setCurrentIndex(1)
    for _ in range(12):
        pump(app, 5)
    print(grab(app, window, "fixed_3_hf_global.png"))

    hub_tabs.setCurrentIndex(0)
    pump(app, 25)
    roles = [w.currentText() for w in hub.findChildren(QWidget) if w.metaObject().className() == "QComboBox"][:8]
    print("ROLE_SELECTORS:", roles)
    print(grab(app, window, "fixed_4_roles_and_server.png"))

    from mark.rust_bridge import rust

    started = rust.server_start(8931, "mark-svid-1bit")
    print("SERVER_START:", started)
    hub_tabs.setCurrentIndex(2)
    for _ in range(14):
        pump(app, 5)
    refresh = getattr(hub, "_refresh_server_status", None) or getattr(hub, "_update_server_status", None)
    if callable(refresh):
        refresh()
    pump(app, 20)
    status = rust.server_status()
    print("SERVER_STATUS:", status)
    print(grab(app, window, "fixed_5_server_online.png"))
    rust.server_stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
