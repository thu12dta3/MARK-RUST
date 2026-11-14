"""Stress test for the Settings -> General transition with real timer waits.

Runs on the live display (Wayland when available), leaves the Settings page open
long enough for the 1.5 s timer and background threads to fire, and asserts the
physical QSlider range matches the scanned model ceiling.
"""

from __future__ import annotations

import faulthandler
import sys
import threading
import time
import traceback
from pathlib import Path

PY_UI = Path(__file__).resolve().parent
if str(PY_UI) not in sys.path:
    sys.path.insert(0, str(PY_UI))

FAULT_LOG = Path.home() / ".local" / "state" / "mark" / "crash_fault.log"
FAULT_LOG.parent.mkdir(parents=True, exist_ok=True)
_fault = open(FAULT_LOG, "a", buffering=1)
faulthandler.enable(file=_fault, all_threads=True)

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QMessageBox, QWidget

ERRORS: list[str] = []


def hook(t, v, tb):
    detail = "".join(traceback.format_exception(t, v, tb))
    ERRORS.append(detail)
    print("UNHANDLED>>>", detail.strip().splitlines()[-1], flush=True)


sys.excepthook = hook
QDialog.exec = lambda self: 0  # type: ignore[method-assign]
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)  # type: ignore[assignment]
QInputDialog.getText = staticmethod(lambda *a, **k: ("", False))  # type: ignore[assignment]
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: "")  # type: ignore[assignment]


def pump(app: QApplication, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)


def main() -> int:
    app = QApplication(sys.argv)
    from mark.ui.i18n import set_language
    from mark.ui.main_window import MainWindow

    window = MainWindow()
    window.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
    window.resize(1920, 1080)
    window.show()
    pump(app, 0.4)
    window.setGeometry(0, 0, 1920, 1080)
    set_language("en")
    pump(app, 4.0)

    selector = window.model_selector
    index = None
    for i in range(selector.count()):
        if "Mark Engineer 1.5B" in selector.itemText(i):
            index = i
            break
    assert index is not None, "Mark Engineer 1.5B ausente no seletor"
    selector.setCurrentIndex(index)
    pump(app, 0.6)
    print("MODEL:", selector.currentText())

    window.open_settings()
    pump(app, 0.8)
    settings = window.settings_widget
    ctx = settings.slider_ctx
    print("CTX_RANGE:", ctx.slider.minimum(), ctx.slider.maximum(), "value:", ctx.value())
    assert ctx.slider.maximum() == 16384, f"maximum fisico = {ctx.slider.maximum()}"
    assert ctx.slider.minimum() == 512, ctx.slider.minimum()

    ctx.slider.setValue(9893)
    pump(app, 0.4)
    span = ctx.slider.maximum() - ctx.slider.minimum()
    ratio = (ctx.slider.value() - ctx.slider.minimum()) / max(1, span)
    print(f"RATIO: {ratio:.3f} (valor {ctx.slider.value()} de {ctx.slider.maximum()})")
    assert 0.58 <= ratio <= 0.61, f"posicao fisica errada: {ratio:.4f}"

    gpu = settings.slider_gpu
    from mark.ui.model_scanner import scan_model

    layers = scan_model("mark-engineer-1.5b:latest").get("layers")
    print("GPU_RANGE:", gpu.slider.minimum(), gpu.slider.maximum(), "value:", gpu.value(), "| layers:", layers)
    assert layers and gpu.slider.maximum() == layers, f"faixa do GPU offload = {gpu.slider.maximum()} (layers {layers})"

    print("WAIT_SETTINGS_2.5s")
    pump(app, 2.5)

    window.chat_nav_button.click()
    pump(app, 2.5)
    print("BACK_TO_CHAT_PAGE:", window.page_stack.currentWidget() is window.chat_page, "spec:", window.current_specialization)

    for cycle in range(2):
        window.settings_nav_button.click()
        pump(app, 0.5)
        tabs = settings.tab_widget
        for tab_index in range(tabs.count()):
            tabs.setCurrentIndex(tab_index)
            pump(app, 1.0)
            print(f"CYCLE{cycle}_TAB{tab_index}_OK")
        ctx.slider.setValue(8192)
        pump(app, 0.4)
        window.chat_nav_button.click()
        pump(app, 2.0)
        print(f"CYCLE{cycle}_GENERAL_OK page={window.page_stack.currentWidget() is window.chat_page}")

    window.open_settings()
    pump(app, 0.6)
    window.back_button.click()
    pump(app, 2.0)
    print("BACK_BUTTON_OK:", window.page_stack.currentWidget() is window.chat_page)

    print("THREADS:", [t.name for t in threading.enumerate()])
    print("FAULT_LOG_BYTES:", FAULT_LOG.stat().st_size)
    print("EXCEPTIONS:", len(ERRORS))
    for err in ERRORS[:3]:
        print("ERR>>>", err.strip().splitlines()[-1])
    window.shutdown()
    window.close()
    pump(app, 0.6)
    return 0 if not ERRORS else 3


if __name__ == "__main__":
    raise SystemExit(main())
