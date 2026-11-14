"""Captures the four visual proofs of the MARK PyQt6 interface.

Run with the project virtualenv on a live display:
    python py_ui/capture_proof.py
Each PNG is 1280x850 and comes from a real widget grab of the running window.
"""

from __future__ import annotations

import sys
from pathlib import Path

PY_UI = Path(__file__).resolve().parent
if str(PY_UI) not in sys.path:
    sys.path.insert(0, str(PY_UI))

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QTabWidget, QWidget

OUT = Path(__file__).resolve().parent.parent
SIZE = (1280, 850)


def pump(app: QApplication, rounds: int = 12) -> None:
    for _ in range(rounds):
        app.processEvents()


def find_tabs(widget: QWidget, predicate) -> QTabWidget | None:
    for tabs in widget.findChildren(QTabWidget):
        if predicate(tabs):
            return tabs
    return None


def grab(app: QApplication, window: QWidget, path: Path) -> str:
    pump(app)
    window.repaint()
    pump(app, 6)
    pixmap = window.grab()
    path.parent.mkdir(parents=True, exist_ok=True)
    pixmap.save(str(path), "PNG")
    return f"{path.name}: {pixmap.width()}x{pixmap.height()} ({path.stat().st_size} bytes)"


def main() -> int:
    app = QApplication(sys.argv)
    from mark.ui.i18n import set_language
    from mark.ui.main_window import MainWindow

    window = MainWindow()
    window.resize(*SIZE)
    window.show()
    set_language("en")
    pump(app, 25)

    print(grab(app, window, OUT / "peak_1_chat_en.png"))

    window.open_settings()
    settings = window.settings_widget
    tabs = settings.tab_widget
    print("SETTINGS_TABS:", [tabs.tabText(i) for i in range(tabs.count())])

    vault_index = 1
    for i in range(tabs.count()):
        label = tabs.tabText(i).lower()
        if "vault" in label or "cofre" in label:
            vault_index = i
            break
    tabs.setCurrentIndex(vault_index)
    pump(app, 20)
    print(grab(app, window, OUT / "peak_2_vault_modes.png"))

    hub_index = tabs.count() - 1
    tabs.setCurrentIndex(hub_index)
    pump(app, 20)
    hub = tabs.widget(hub_index)
    hub_tabs = getattr(hub, "tabs", None) or find_tabs(hub, lambda t: t.count() >= 3)
    if hub_tabs is None:
        print("NO_HUB_TABS")
        return 4
    print("HUB_TABS:", [hub_tabs.tabText(i) for i in range(hub_tabs.count())])
    hf_index = 1
    for i in range(hub_tabs.count()):
        label = hub_tabs.tabText(i).lower()
        if "hugging" in label or "hf" in label:
            hf_index = i
            break
    hub_tabs.setCurrentIndex(hf_index)
    for _ in range(30):
        pump(app, 4)
    print(grab(app, window, OUT / "peak_3_hf_all_models.png"))

    roles_index = 0
    hub_tabs.setCurrentIndex(roles_index)
    window.language_selector.setCurrentIndex(window.language_selector.findData("pt-BR"))
    pump(app, 25)
    print(grab(app, window, OUT / "peak_4_roles_ptbr.png"))

    set_language("en")
    window.language_selector.setCurrentIndex(window.language_selector.findData("en"))
    QTimer.singleShot(150, app.quit)
    app.exec()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
