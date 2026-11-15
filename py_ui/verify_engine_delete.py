"""Prova headless (Wayland) dos tres consertos desta rodada."""

from __future__ import annotations

import sqlite3
import sys
import time
import uuid
from pathlib import Path

PY_UI = Path("/home/thu12/MARK-RUST/py_ui")
if str(PY_UI) not in sys.path:
    sys.path.insert(0, str(PY_UI))

from PyQt6.QtWidgets import QApplication  # noqa: E402


def main() -> int:
    app = QApplication(sys.argv)
    from mark.ui.main_window import MainWindow

    window = MainWindow()
    window.resize(1400, 900)
    window.show()
    for _ in range(3):
        app.processEvents()

    ok = True

    engine_hidden = not window.engine_button.isVisible()
    print(f"ENGINE_DROPDOWN_VISIVEL={not engine_hidden}  -> {'PASS' if engine_hidden else 'FAIL'}")
    ok = ok and engine_hidden

    cases = {
        "Mark-Bin-32B": "rust",
        "miceworks/mark-bin-32b.mkbin": "rust",
        "qwen3:8b": "ollama",
        "model.gguf": "llamacpp",
        "gpt-4o-mini": "api",
    }
    for model_id, expected in cases.items():
        got = window.resolve_engine_for_model(model_id)
        status = "PASS" if got == expected else "FAIL"
        print(f"ROUTE {model_id!r} -> {got} (esperado {expected}) {status}")
        ok = ok and got == expected

    before = len(QApplication.topLevelWidgets())
    window.run_autonomous_engineering()
    for _ in range(3):
        app.processEvents()
    after = len(QApplication.topLevelWidgets())
    spec = window.current_specialization
    modal_ok = after == before and spec == "engineer"
    print(f"SANDBOX_MODAL topLevel antes={before} depois={after} modo={spec} -> {'PASS' if modal_ok else 'FAIL'}")
    ok = ok and modal_ok

    # Exclusao da conversa ativa: precisa sobrar uma conversa valida e enviar.
    spec_general = "general"
    conv_id = uuid.uuid4().hex
    now = int(time.time())
    db = window._conversation_db()
    db.execute(
        "INSERT INTO conversations VALUES(?,?,?,?,?)",
        (conv_id, spec_general, "Teste delete", now, now),
    )
    db.execute(
        "INSERT INTO conversation_messages(conversation_id,role,content,created_at) VALUES(?,?,?,?)",
        (conv_id, "user", "mensagem antiga", now),
    )
    db.commit()
    db.close()

    window.current_specialization = spec_general
    window.current_conversation_id = conv_id
    window.specialization_conversations[spec_general] = conv_id
    window._delete_conversation(conv_id, spec_general)
    for _ in range(3):
        app.processEvents()

    active = window.current_conversation_id
    db = window._conversation_db()
    row = db.execute("SELECT id FROM conversations WHERE id=?", (active,)).fetchone()
    msgs = db.execute(
        "SELECT COUNT(*) FROM conversation_messages WHERE conversation_id=?", (active,)
    ).fetchone()[0]
    db.close()
    delete_ok = (active != conv_id) and row is not None and window.busy is False
    print(f"DELETE_ATIVO novo_id={active} existe_no_store={row is not None} "
          f"msgs={msgs} busy={window.busy} -> {'PASS' if delete_ok else 'FAIL'}")
    ok = ok and delete_ok

    window.shutdown()
    window.close()
    app.processEvents()
    print("RESULTADO_GERAL=" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
