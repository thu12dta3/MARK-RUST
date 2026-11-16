
"""Auditoria de sincronia real UI <-> backend (nenhum controle placebo)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PY_UI = Path(__file__).resolve().parent
sys.path.insert(0, str(PY_UI))
FAULT = Path.home() / ".local" / "state" / "mark" / "crash_fault.log"
SERVER_RS = Path(__file__).resolve().parent / "mark" / ".." / ".." / "crates" / "mark-engine" / "src" / "server.rs"


def fault_size() -> int:
    return FAULT.stat().st_size if FAULT.is_file() else 0


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "wayland")
    if not os.environ.get("WAYLAND_DISPLAY"):
        print("FAIL: WAYLAND_DISPLAY nao definido")
        return 2
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication

    from mark.config import get_local_inference_params, save_local_inference_params
    from mark.desktop_chat import _tuning_payload
    from mark.ui.main_window import MainWindow
    from mark.ui.model_scanner import format_ctx

    app = QApplication.instance() or QApplication(sys.argv)
    before = fault_size()
    failures: list[str] = []
    window = MainWindow()
    window.resize(1280, 850)
    window.show()
    QTest.qWait(2600)

    original = get_local_inference_params()

    # ------------------------------------------------- 1. sliders -> payload
    save_local_inference_params({"num_ctx": 4096, "temperature": 0.45})
    for level, loops in (("instant", 1), ("medium", 2), ("high", 3)):
        idx = window.reasoning_selector.findData(level)
        window.reasoning_selector.setCurrentIndex(idx)
        QTest.qWait(150)
        payload = _tuning_payload(str(window.reasoning_selector.currentData()))
        print(f"PAYLOAD level={level} {payload}")
        if payload["reasoning_loops"] != loops:
            failures.append(f"{level}: reasoning_loops={payload['reasoning_loops']} != {loops}")
        if abs(float(payload["temperature"]) - 0.45) > 1e-6:
            failures.append(f"{level}: temperatura nao veio do slider: {payload['temperature']}")
        if payload["context_length"] != 4096:
            failures.append(f"{level}: context_length={payload['context_length']} != 4096")

    server_src = (PY_UI.parent / "crates" / "mark-engine" / "src" / "server.rs").read_text(encoding="utf-8")
    for key in ("temperature", "max_tokens", "reasoning_loops", "context_length", "num_ctx", "mark_reasoning_level"):
        if key not in server_src:
            failures.append(f"server.rs nao le o campo {key!r} do JSON")
    print("SERVER_KEYS ok" if not failures else "SERVER_KEYS com falhas")

    # ------------------------------------------------------------ 2. CTX
    window._update_ctx_label()
    QTest.qWait(900)
    ctx_text = window.ctx_status_label.text()
    print(f"CTX_LABEL {ctx_text!r} esperado={format_ctx(4096)!r}")
    if format_ctx(4096) not in ctx_text:
        failures.append(f"CTX do rodape nao respeitou o slider: {ctx_text!r}")
    if "2M" in ctx_text and format_ctx(4096) != "2M":
        failures.append(f"CTX travado no teto do modelo: {ctx_text!r}")

    # --------------------------------------------------- 3. cancelamento real
    window.mark_mode_busy(True)
    QTest.qWait(300)
    window._cancel_generation()
    QTest.qWait(500)
    busy_after = bool(window.busy)
    icons = getattr(window, "_send_icon_pixels", None)
    print(f"CANCEL busy={busy_after} icon_pixels={icons}")
    if busy_after:
        failures.append("busy continuou True apos Stop")
    # nova mensagem logo depois nao pode estar bloqueada
    window.mark_mode_busy(True)
    QTest.qWait(200)
    if not window.busy:
        failures.append("nao foi possivel reenviar apos o Stop")
    window.mark_mode_busy(False)
    QTest.qWait(200)
    if window.busy:
        failures.append("busy nao voltou a False no segundo envio")

    # -------------------------------------- 4. tortura de navegacao + palette
    for target in ("general", "engineer", "general"):
        window.open_specialized_chat(target)
        QTest.qWait(300)
    for page in ("settings_page", "models_hub_page", "chat_page"):
        widget = getattr(window, page, None)
        if widget is not None:
            window.stacked_widget.setCurrentWidget(widget)
            QTest.qWait(250)
    window.open_command_palette()
    QTest.qWait(600)
    from PyQt6.QtWidgets import QListWidget

    lists = window.command_palette.findChildren(QListWidget) if getattr(window, "command_palette", None) else []
    entries = sum(lst.count() for lst in lists)
    print(f"PALETTE entries={entries}")
    if entries <= 0:
        failures.append("Command Palette sem entradas (placebo)")
    window._on_escape()
    QTest.qWait(400)
    if getattr(window, "command_palette", None) is not None and window.command_palette.isVisible():
        failures.append("Esc nao fechou a Command Palette")

    names = [w.objectName() or type(w).__name__ for w in app.topLevelWidgets() if w.isVisible()]
    delta = fault_size() - before
    print(f"TOPLEVELS {names}")
    print(f"FAULT_LOG_DELTA={delta}")
    if names != ["MainWindow"]:
        failures.append(f"topLevelWidgets inesperado: {names}")
    if delta != 0:
        failures.append(f"crash_fault.log cresceu {delta} bytes")

    save_local_inference_params({"num_ctx": original.get("num_ctx"), "temperature": original.get("temperature")})
    window.close()
    QTest.qWait(300)
    if failures:
        print(f"\nFAIL ({len(failures)} problemas)")
        for item in failures:
            print("  -", item)
        return 1
    print("\nUI<->BACKEND OK: sliders, reasoning, CTX, cancelamento, palette e navegacao")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
