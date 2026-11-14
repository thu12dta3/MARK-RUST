"""Quick reproduction of the three desktop bugs reported by the user."""

from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PyQt6.QtWidgets import QApplication

ERRORS: list[str] = []


def hook(t, v, tb):
    ERRORS.append("".join(traceback.format_exception(t, v, tb)))


sys.excepthook = hook


def pump(app, rounds=15):
    for _ in range(rounds):
        app.processEvents()
        time.sleep(0.004)


def main() -> int:
    app = QApplication(sys.argv)
    from mark.ui.main_window import MainWindow

    w = MainWindow()
    w.show()
    pump(app, 25)

    print("1) SELECTION TEST")
    for index in range(w.model_selector.count()):
        if "Mark-Bin-32B" in w.model_selector.itemText(index):
            print("   found mark at", index)
            w.model_selector.setCurrentIndex(index)
            pump(app, 10)
            print("   immediately after set:", w.model_selector.currentText())
            time.sleep(2.0)
            pump(app, 20)
            print("   after 2s:", w.model_selector.currentText(), "| CTX:", w.ctx_status_label.text())
            break

    print("2) CTX PER MODEL")
    for index in range(min(5, w.model_selector.count())):
        w.model_selector.setCurrentIndex(index)
        pump(app, 8)
        print(f"   [{index}] {w.model_selector.itemText(index)[:48]} -> {w.ctx_status_label.text()}")

    print("3) SETTINGS ROUNDTRIP")
    w.settings_nav_button.click()
    pump(app, 20)
    print("   settings visible:", w.page_stack.currentWidget() is w.settings_page)
    tabs = w.settings_widget.tab_widget
    for i in range(tabs.count()):
        tabs.setCurrentIndex(i)
        pump(app, 12)
    print("   tabs cycled")
    w.chat_nav_button.click()
    pump(app, 25)
    print("   back to chat:", w.page_stack.currentWidget() is w.chat_page)
    w.open_settings()
    pump(app, 15)
    w.back_button.click()
    pump(app, 20)
    print("   back_button ->", w.page_stack.currentWidget() is w.chat_page)
    w.engineer_button.click()
    pump(app, 15)
    w.settings_nav_button.click()
    pump(app, 15)
    w.professor_button.click()
    pump(app, 15)
    w.settings_nav_button.click()
    pump(app, 15)
    w.vision_nav_button.click()
    pump(app, 15)
    print("   mode hops ok, spec:", w.current_specialization)
    w.chat_nav_button.click()
    pump(app, 15)
    print("   final:", w.current_specialization)

    print("ERRORS:", len(ERRORS))
    for err in ERRORS[:4]:
        print("---", err.strip().splitlines()[-3:])
    return 0 if not ERRORS else 2


if __name__ == "__main__":
    raise SystemExit(main())
