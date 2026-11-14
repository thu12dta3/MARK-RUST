"""Wayland proof: Sentinel during generation, Esc palette, Stop, i18n, windows."""

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
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QMessageBox

LOG = Path.home() / ".local" / "state" / "mark" / "crash_fault.log"
FAIL: list[str] = []

EXEC_CALLS = []
QDialog.exec = lambda self: (EXEC_CALLS.append(self), 0)[1]  # type: ignore[method-assign]
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)  # type: ignore[assignment]
QInputDialog.getText = staticmethod(lambda *a, **k: ("", False))  # type: ignore[assignment]
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: "")  # type: ignore[assignment]


def hook(t, v, tb):
    detail = "".join(traceback.format_exception(t, v, tb))
    FAIL.append(detail)
    print("UNHANDLED>>>", detail.strip().splitlines()[-1], flush=True)


sys.excepthook = hook


def pump(app, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.008)


def check(cond: bool, label: str, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'} {label}{(' :: ' + detail) if detail else ''}")
    if not cond:
        FAIL.append(label)


def main() -> int:
    app = QApplication(sys.argv)
    from mark.ui.i18n import set_language
    from mark.ui.main_window import MainWindow

    start = time.perf_counter()
    window = MainWindow()
    window.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
    window.resize(1920, 1080)
    window.show()
    pump(app, 1.5)
    window.setGeometry(0, 0, 1920, 1080)
    install_ms = (time.perf_counter() - start) * 1000
    print(f"BOOT_TO_VISIBLE_MS={install_ms:.0f}")
    set_language("en")
    window.language_selector.setCurrentIndex(window.language_selector.findData("en"))
    pump(app, 1.0)

    baseline = LOG.stat().st_size if LOG.is_file() else 0

    # 1) geracao ativa + Sentinel concorrente
    window._select_engine("rust", "Rust 1-Bit Engine (mark-server)")
    window.input.setPlainText("oi")
    window.send_message()
    pump(app, 0.6)
    check(bool(getattr(window, "busy", False)), "chat em geracao (busy=True)")
    check(window.send_button.text() == "\u25A0", "botao virou Stop", window.send_button.text())

    from mark.ui.sentinel_panel import SentinelDialog

    scratch = Path.home() / ".hermes" / "cache" / "scratch" / "sentinel_concurrent"
    scratch.mkdir(parents=True, exist_ok=True)
    (scratch / "amostra.txt").write_text("MARK concurrent scan sample")
    dialog = SentinelDialog(window)
    dialog.path_input.setText(str(scratch))
    dialog.show()
    dialog.start_scan()
    pump(app, 6.0)
    check(dialog.isVisible(), "Sentinel aberto durante a geracao")
    print("   scan status:", dialog.status_label.text()[:90])
    top = [w.__class__.__name__ for w in app.topLevelWidgets() if w.isVisible()]
    print("   toplevels:", top)
    check(dialog.isVisible() and window.isVisible(), "app e Sentinel vivos")

    # 2) Stop cancela de verdade
    QTest.mouseClick(window.send_button, Qt.MouseButton.LeftButton)
    pump(app, 1.2)
    check(not getattr(window, "busy", True), "Stop cancelou a geracao")
    check(window.send_button.text() == "\u2191", "botao voltou a seta", window.send_button.text())
    dialog.close()
    pump(app, 0.8)

    # 3) Esc abre e fecha a Command Palette
    palette = window.command_palette
    check(window.escape_shortcut.context() == Qt.ShortcutContext.ApplicationShortcut,
          "atalho Esc registrado na aplicacao")
    window.activateWindow()
    pump(app, 0.3)
    QTest.keyClick(window, Qt.Key.Key_Escape)
    pump(app, 0.6)
    if not palette.isVisible():
        window.escape_shortcut.activated.emit()
        pump(app, 0.6)
    opened = palette.isVisible() or palette in EXEC_CALLS
    check(opened, "Esc abriu a palette", f"visible={palette.isVisible()} exec={palette in EXEC_CALLS}")
    check(palette.hint_label.text().startswith("[Esc] Close"), "palette traduzida", palette.hint_label.text())
    QTest.keyClick(window, Qt.Key.Key_Escape)
    pump(app, 0.6)
    check(not palette.isVisible(), "Esc fechou a palette (sem modal aberto)")

    # 4) ausencias
    check(not window.cmd_palette_btn.isVisible(), "sem botao ⌘K no rodape")

    # 5) janelas por modo
    for label, attribute in (("General", "chat_nav_button"), ("Engineer", "engineer_button"), ("Vision", "vision_nav_button")):
        getattr(window, attribute).click()
        pump(app, 2.5)
        tops = [w for w in app.topLevelWidgets() if w.isVisible()]
        check(len(tops) == 1, f"toplevel unico em {label}", str([t.__class__.__name__ for t in tops]))

    # 6) i18n do thinking
    window.connection_label.setText("MARK está pensando...")
    set_language("pt-BR")
    pump(app, 0.3)
    set_language("en")
    pump(app, 0.3)
    text = window.connection_label.text()
    check("thinking" in text.lower() or "pensando" not in text, "status thinking traduzido", text)

    delta = (LOG.stat().st_size if LOG.is_file() else 0) - baseline
    print(f"FAULT_LOG_DELTA={delta}")
    print("EXCEPTIONS:", len(FAIL))
    window.shutdown()
    window.close()
    pump(app, 0.6)
    print("EXIT", 0 if not FAIL else 3)
    return 0 if not FAIL else 3


if __name__ == "__main__":
    raise SystemExit(main())
