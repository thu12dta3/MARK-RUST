"""Wayland UI audit: windows, timing, wheel, send icon, absence checks, i18n."""

from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

PY_UI = Path(__file__).resolve().parent
if str(PY_UI) not in sys.path:
    sys.path.insert(0, str(PY_UI))

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
)

QDialog.exec = lambda self: 0  # type: ignore[method-assign]
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)  # type: ignore[assignment]
QInputDialog.getText = staticmethod(lambda *a, **k: ("", False))  # type: ignore[assignment]
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: "")  # type: ignore[assignment]

FAIL: list[str] = []


def check(condition: bool, label: str, detail: str = "") -> None:
    print(f"{'PASS' if condition else 'FAIL'} {label}{(' :: ' + detail) if detail else ''}")
    if not condition:
        FAIL.append(label)


def pump(app: QApplication, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.008)


def visible_toplevels(app: QApplication) -> list[str]:
    return [
        f"{w.__class__.__name__}:{w.objectName()}:{w.geometry().width()}x{w.geometry().height()}"
        for w in app.topLevelWidgets()
        if w.isVisible()
    ]


def wheel(widget, delta: int = -120) -> None:
    pos = QPointF(widget.width() / 2, widget.height() / 2)
    event = QWheelEvent(
        pos,
        widget.mapToGlobal(QPoint(int(pos.x()), int(pos.y()))).toPointF(),
        QPoint(0, delta),
        QPoint(0, delta),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(widget, event)


def main() -> int:
    app = QApplication(sys.argv)
    from mark.ui.i18n import set_language
    from mark.ui.main_window import MainWindow

    window = MainWindow()
    window.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
    window.resize(1920, 1080)
    window.show()
    pump(app, 1.2)
    window.setGeometry(0, 0, 1920, 1080)
    set_language("en")
    window.language_selector.setCurrentIndex(window.language_selector.findData("en"))
    pump(app, 2.0)

    # 1) janelas top-level por modo
    for label, attribute in (
        ("General", "chat_nav_button"),
        ("Engineer", "engineer_button"),
        ("Vision", "vision_nav_button"),
        ("Library", "library_nav_button"),
        ("Devices", "devices_nav_button"),
        ("Settings", "settings_nav_button"),
        ("General", "chat_nav_button"),
    ):
        widget = getattr(window, attribute, None)
        if widget is None:
            check(False, f"botao {label} ausente")
            continue
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
        pump(app, 2.5)
        tops = visible_toplevels(app)
        check(len(tops) == 1, f"toplevel unico em {label}", str(tops))

    # 2) tempo de troca General <-> Engineer
    for _ in range(3):
        window.open_specialized_chat("general")
        pump(app, 0.2)
    start = time.perf_counter()
    window.open_specialized_chat("engineer")
    forward = (time.perf_counter() - start) * 1000
    start = time.perf_counter()
    window.open_specialized_chat("general")
    backward = (time.perf_counter() - start) * 1000
    check(forward < 30 and backward < 30, "troca General<->Engineer < 30 ms", f"{forward:.1f} ms / {backward:.1f} ms")

    # 3) roda do mouse nao altera selecao
    for label, widget in (
        ("model", window.model_selector),
        ("reasoning", window.reasoning_selector),
        ("language", window.language_selector),
    ):
        before = widget.currentIndex()
        wheel(widget)
        wheel(widget, 120)
        pump(app, 0.2)
        check(widget.currentIndex() == before, f"wheel nao altera {label}", str((before, widget.currentIndex())))

    # 4) icone do enviar tem pixels contrastantes
    image = window.send_button.grab().toImage()
    cx, cy = image.width() // 2, image.height() // 2
    colors = set()
    for dx in range(-9, 10):
        for dy in range(-9, 10):
            colors.add(image.pixelColor(cx + dx, cy + dy).name())
    check(len(colors) >= 3, "send button tem desenho interno", f"{len(colors)} cores na area central")

    # 5) ausencias
    texts = []
    for widget in window.findChildren(QLabel) + window.findChildren(QPushButton):
        try:
            if widget.isVisible():
                texts.append(widget.text())
        except RuntimeError:
            continue
    joined = " | ".join(texts)
    check("Call" not in texts, "header sem botao Call")
    check("Evolution" not in joined, "sidebar sem Evolution")
    check("Professor" not in joined, "sidebar sem Professor")
    check("Evolução" not in joined, "sidebar sem Evolução")
    check(getattr(window, "settings_button", None) is None or not window.settings_button.isVisible(), "header sem Settings")

    # 6) Tools com uma seta
    check("▾" not in window.tools_button.text(), "Tools com uma unica seta", window.tools_button.text())

    # 7) EngineerBar sem Suggest e visivel apenas com conversa vazia
    window.open_specialized_chat("engineer")
    pump(app, 0.6)
    labels = [w.text() for w in window.engineer_bar.findChildren(QPushButton) if w.isVisible()]
    visible_combo = [c.currentText() for c in window.engineer_bar.findChildren(QComboBox) if c.isVisible()]
    check("Suggest" not in visible_combo, "EngineerBar sem seletor de permissao", str(visible_combo))
    check(not any("Re-scan" in text or "Web Access" in text for text in labels), "EngineerBar sem Re-scan/Web", str(labels))
    check(window.engineer_bar.isVisible(), "EngineerBar visivel com conversa vazia")
    window._append_bubble("teste de mensagem", "user", None, auto_scroll=True)
    pump(app, 0.3)
    window.open_specialized_chat("engineer")
    pump(app, 0.4)
    check(not window.engineer_bar.isVisible(), "EngineerBar oculta apos mensagens")

    # 8) i18n sem vazamento em EN
    set_language("en")
    pump(app, 0.4)
    header = window.page_heading.text()
    check(header in {"General", "Engineer", "Vision"}, "header traduzido", header)
    pt_tokens = ("Falha no Processamento", "Tentar Novamente", "Alternar Modelo", "Não foi possível")
    leaks = [token for token in pt_tokens if token in joined]
    check(not leaks, "zero strings PT nos cards", str(leaks))

    print("FAILURES:", FAIL)
    window.shutdown()
    window.close()
    pump(app, 0.5)
    return 0 if not FAIL else 3


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        raise SystemExit(2)
