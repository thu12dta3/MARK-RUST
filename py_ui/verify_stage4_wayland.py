"""Harness Wayland da Etapa 4: sandbox, servidor, conversas, busy e indicador.

Roda em dois estagios (processos separados) para provar que `Clear conversation`
persiste: o estagio 1 limpa e salva o id da conversa, o estagio 2 reabre o
aplicativo e conta as bolhas.

Uso:
  WAYLAND_DISPLAY=wayland-1 QT_QPA_PLATFORM=wayland .venv/bin/python \
      py_ui/verify_stage4_wayland.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PY_UI = Path(__file__).resolve().parent
sys.path.insert(0, str(PY_UI))

FAULT_LOG = Path.home() / ".local" / "state" / "mark" / "crash_fault.log"
STATE_FILE = Path(
    os.environ.get("MARK_STATE_FILE", "")
    or (Path.home() / ".hermes" / "cache" / "scratch" / "stage4_conv.txt")
)


def fault_size() -> int:
    return FAULT_LOG.stat().st_size if FAULT_LOG.is_file() else 0


def bubbles(window) -> int:
    from PyQt6.QtWidgets import QWidget

    return len(window.findChildren(QWidget, "bubbleWrapper"))


def top_levels(app) -> list[str]:
    names = []
    for widget in app.topLevelWidgets():
        if not widget.isVisible():
            continue
        names.append(widget.objectName() or type(widget).__name__)
    return names


def build_window(app):
    from mark.ui.main_window import MainWindow

    window = MainWindow()
    window.resize(1280, 850)
    window.show()
    from PyQt6.QtTest import QTest

    QTest.qWait(2600)
    return window


def conversation_spec(window, conv_id: str) -> str:
    db = window._conversation_db()
    try:
        row = db.execute("SELECT specialization FROM conversations WHERE id=?", (conv_id,)).fetchone()
        return str(row[0]) if row else ""
    finally:
        db.close()


def phase2(app) -> int:
    """Reabre o aplicativo e prova que a conversa limpa continua com 0 bolhas."""
    from PyQt6.QtTest import QTest

    conv_id = STATE_FILE.read_text(encoding="utf-8").strip() if STATE_FILE.is_file() else ""
    window = build_window(app)
    failures: list[str] = []
    if conv_id:
        window.specialization_conversations["general"] = conv_id
        window.current_conversation_id = conv_id
        window._load_active_conversation()
        QTest.qWait(600)
    count = bubbles(window)
    print(f"PHASE2 conversation={conv_id or '-'} bubbles_after_reopen={count}")
    if conv_id and count != 0:
        failures.append(f"bolhas sobreviveram ao reinicio: {count}")
    names = top_levels(app)
    print(f"PHASE2 topLevelWidgets={names}")
    if names != ["MainWindow"]:
        failures.append(f"topLevelWidgets inesperado: {names}")
    if conv_id:
        window._delete_conversation(conv_id, "general")
    for item in failures:
        print("FAIL:", item)
    return 1 if failures else 0


def phase1(app) -> int:
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QInputDialog

    from mark.rust_bridge import rust

    before_fault = fault_size()
    window = build_window(app)
    early_levels = top_levels(app)
    print(f"TOPLEVELS_INICIAL {early_levels}")
    failures: list[str] = []
    if early_levels != ["MainWindow"]:
        failures.append(f"topLevelWidgets inesperado na abertura: {early_levels}")

    # ---------------------------------------------------------------- servidor
    calls = {"start": 0, "stop": 0}
    real_start = rust.server_start
    real_stop = rust.server_stop

    def fake_start(port: int = 8765, model: str | None = None):
        calls["start"] += 1
        return {"running": True, "port": port}

    def fake_stop():
        calls["stop"] += 1
        return {"running": False}

    rust.server_start = fake_start
    rust.server_stop = fake_stop
    window._prewarm_local_server()
    QTest.qWait(400)
    window._prewarm_local_server()
    QTest.qWait(200)
    if calls["start"] != 1:
        failures.append(f"pre-aquecimento nao foi idempotente: {calls['start']} starts")

    # ------------------------------------------------------- busy por modo
    window.open_specialized_chat("general")
    QTest.qWait(300)
    window.mark_mode_busy(True)
    QTest.qWait(200)
    general_busy = bool(window.busy)
    window.open_specialized_chat("engineer")
    QTest.qWait(2600)
    engineer_busy = bool(window.busy)
    send_enabled = window.send_button.isEnabled()
    print(
        f"BUSY general_busy={general_busy} engineer_busy={engineer_busy} "
        f"send_enabled={send_enabled}"
    )
    if not general_busy:
        failures.append("busy do General nao foi marcado")
    if engineer_busy:
        failures.append("Engineer herdou o busy do General")
    if not send_enabled:
        failures.append("campo de envio do Engineer ficou travado")
    window.mark_mode_busy(False)

    # --------------------------------------------------- sandbox sem QInputDialog
    window.open_specialized_chat("general")
    QTest.qWait(300)
    window.run_autonomous_engineering()
    QTest.qWait(2600)
    spec_after = getattr(window, "current_specialization", "")
    modal = app.activeModalWidget()
    modal_kind = type(modal).__name__ if modal is not None else ""
    print(f"SANDBOX specialization={spec_after} modal={modal_kind or 'nenhum'}")
    if spec_after != "engineer":
        failures.append(f"sandbox nao consolidou engineer: {spec_after!r}")
    if isinstance(modal, QInputDialog) or modal_kind == "QInputDialog":
        failures.append("sandbox abriu QInputDialog")

    # ---------------------------------------------- + New chat no modo General
    window.open_specialized_chat("general")
    QTest.qWait(300)
    window._create_new_conversation_from_sidebar()
    QTest.qWait(600)
    new_id = str(getattr(window, "current_conversation_id", ""))
    new_spec = conversation_spec(window, new_id)
    visible = window.sidebar_new_chat_btn.isVisible()
    print(f"NEWCHAT id={new_id[:8]} spec={new_spec!r} botao_visivel={visible}")
    if new_spec != "general":
        failures.append(f"+ New chat no General criou conversa de {new_spec!r}")
    if not visible:
        failures.append("+ New chat escondido no modo General")

    # -------------------------------------------------- icones em RECENT CHATS
    window._refresh_sidebar_conversations()
    QTest.qWait(300)
    icons = {}
    for index in range(window.sidebar_conv_list.count()):
        item = window.sidebar_conv_list.item(index)
        data = item.data(0x0100)
        if isinstance(data, tuple) and len(data) == 2:
            icons.setdefault(data[1], item.icon().isNull())
        icons[data[1]] = icons.get(data[1], item.icon().isNull())
    print(f"ICONS null_por_modo={icons}")
    if not icons:
        failures.append("lista de conversas vazia ao checar icones")
    for spec, is_null in icons.items():
        if is_null:
            failures.append(f"item de {spec!r} sem icone vetorial")

    # ------------------------------------- Clear conversation: 0 bolhas na hora
    window._append_bubble("teste usuario", "user")
    window._append_bubble("teste assistente", "assistant")
    QTest.qWait(400)
    before_clear = bubbles(window)
    window.clear_memory()
    QTest.qWait(700)
    after_clear = bubbles(window)
    print(f"CLEAR before={before_clear} after={after_clear}")
    if before_clear < 2:
        failures.append(f"bolhas de teste nao foram criadas: {before_clear}")
    if after_clear != 0:
        failures.append(f"Clear conversation deixou {after_clear} bolhas")

    # ------------------------------------------------- indicador com 3 pontos
    indicator = window.thinking_indicator
    indicator.set_phrase("Synthesizing tokens...")
    indicator._animate_dots()
    rendered = indicator.text_label.text()
    print(f"INDICATOR {rendered!r}")
    if not rendered.endswith("...") or rendered.endswith("...."):
        failures.append(f"indicador com pontos errados: {rendered!r}")
    if rendered != "Synthesizing tokens...":
        failures.append(f"indicador acumulou pontos: {rendered!r}")

    # ------------------------------------------- servidor nao reinicia no clear
    window.open_specialized_chat("engineer")
    QTest.qWait(300)
    window.open_specialized_chat("general")
    QTest.qWait(300)
    window.clear_memory()
    QTest.qWait(400)
    if calls["start"] != 1 or calls["stop"] != 0:
        failures.append(f"servidor reiniciado em troca de modo/clear: {calls}")
    rust.server_start = real_start
    rust.server_stop = real_stop

    # ------------------------------------------------------- janelas orfas/topo
    window.show()
    QTest.qWait(600)
    names = top_levels(app)
    print(f"TOPLEVELS {names}")
    if names != ["MainWindow"]:
        failures.append(f"topLevelWidgets inesperado: {names}")

    # ------------------------------------------------------- fault log delta
    after_fault = fault_size()
    delta = after_fault - before_fault
    print(f"FAULT_LOG_DELTA={delta}")
    if delta != 0:
        failures.append(f"crash_fault.log cresceu {delta} bytes")

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(new_id, encoding="utf-8")
    window.close()
    QTest.qWait(300)

    # ------------------------------------------------- reabertura em processo novo
    env = dict(os.environ)
    env["MARK_PHASE"] = "2"
    env["MARK_STATE_FILE"] = str(STATE_FILE)
    result = subprocess.run([sys.executable, str(Path(__file__).resolve())], env=env)
    if result.returncode != 0:
        failures.append(f"estagio de reabertura falhou (exit {result.returncode})")

    if failures:
        print(f"\nFAIL ({len(failures)} problemas)")
        for item in failures:
            print("  -", item)
        return 1
    print("\nSTAGE4 OK: sandbox, servidor, conversas, icones, clear, busy e indicador")
    return 0


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "wayland")
    if not os.environ.get("WAYLAND_DISPLAY"):
        print("FAIL: WAYLAND_DISPLAY nao definido (teste exige Wayland real)")
        return 2
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("MARK")
    app.setOrganizationName("miceworks")
    if os.environ.get("MARK_PHASE") == "2":
        return phase2(app)
    return phase1(app)


if __name__ == "__main__":
    raise SystemExit(main())
