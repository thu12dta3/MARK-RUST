
"""Wayland: medidor de CTX, caixa de pensamento, plugins, descoberta e HF split view."""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PY_UI = Path(__file__).resolve().parent
sys.path.insert(0, str(PY_UI))
FAULT = Path.home() / ".local" / "state" / "mark" / "crash_fault.log"
MODELS = [{"id": "gpt-4o-mock"}, {"id": "deepseek-chat-mock"}, {"id": "claude-3-mock"}]


def fault_size() -> int:
    return FAULT.stat().st_size if FAULT.is_file() else 0


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (API http.server)
        body = json.dumps({"object": "list", "data": MODELS}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silencia o log do servidor de teste
        return


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "wayland")
    if not os.environ.get("WAYLAND_DISPLAY"):
        print("FAIL: WAYLAND_DISPLAY nao definido")
        return 2
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication, QLabel

    from mark.desktop_plugins import PluginsDialog
    from mark.engine_router import resolve_engine
    from mark.model_discovery import discover_models
    from mark.ui.hf_splitview import _chips_html, _strip_frontmatter
    from mark.ui.main_window import MainWindow
    from mark.ui.widgets import CollapsibleThinkingBox, CtxMeterWidget

    app = QApplication.instance() or QApplication(sys.argv)
    before = fault_size()
    failures: list[str] = []
    window = MainWindow()
    window.resize(1280, 850)
    window.show()
    QTest.qWait(2600)

    # ------------------------------------------------------- 1. medidor de CTX
    meter = CtxMeterWidget(window)  # unidade isolada: sem timers da janela
    for used, limit, expected in (
        (1000, 4096, CtxMeterWidget.CYAN),
        (3300, 4096, CtxMeterWidget.AMBER),
        (3900, 4096, CtxMeterWidget.RED),
    ):
        meter.set_usage(used, limit)
        QTest.qWait(120)
        got_used, got_limit, color = meter.usage()
        text = meter.text_label.text()
        print(f"CTX_METER used={got_used} limit={got_limit} color={color} text={text!r}")
        if color != expected:
            failures.append(f"cor do medidor {color} != {expected} para {used}/{limit}")
        if "%" not in text or "/" not in text:
            failures.append(f"texto do medidor sem porcentagem: {text!r}")
    window._update_ctx_label()
    QTest.qWait(400)
    footer = window._ctx_meter()
    footer.set_usage(3900, 4096)
    print(f"CTX_FOOTER text={footer.text_label.text()!r} color={footer.usage()[2]}")

    # ------------------------------------------- 2. caixa de pensamento real
    empty = CollapsibleThinkingBox(window)
    empty.finish()
    hidden_ok = not empty.isVisible()
    empty.append_reasoning("")
    hidden_empty_ok = not empty.isVisible()
    print(f"THINK_EMPTY hidden={hidden_ok} hidden_after_empty_chunk={hidden_empty_ok}")
    if not hidden_ok or not hidden_empty_ok:
        failures.append("caixa de pensamento apareceu sem conteudo real (fake)")
    box = CollapsibleThinkingBox(window)
    box.append_reasoning("primeiro passo do raciocinio")
    box.append_reasoning(" e o segundo")
    QTest.qWait(150)
    visible_ok = box.isVisible()
    collapsed = box.is_expanded()
    box.toggle()
    QTest.qWait(150)
    expanded = box.is_expanded()
    body_visible = box.body.isVisible()
    box.finish()
    header = box.header_button.text()
    print(f"THINK_BOX visible={visible_ok} collapsed={collapsed} expanded={expanded} "
          f"body_visible={body_visible} header={header!r} text={box.reasoning_text()!r}")
    if not visible_ok or collapsed or not expanded or not body_visible:
        failures.append("caixa de pensamento nao abriu/fechou corretamente")
    if "passo" not in box.reasoning_text():
        failures.append("caixa de pensamento nao acumulou o stream real")

    # ------------------------------------------------- 3. modal Plugins real
    dialog = PluginsDialog(window)
    texts = [label.text() for label in dialog.findChildren(QLabel) if label.text()]
    joined = " | ".join(texts)
    print(f"PLUGINS labels={len(texts)} mcp_switches={len(dialog.mcp_switches)}")
    if "não são executados" in joined or "nao sao executados" in joined:
        failures.append("modal Plugins ainda anuncia bloqueio fake")
    if len(dialog.switches) == 0:
        failures.append("modal Plugins sem toggles reais")
    dialog.close()

    # --------------------------------------- 4. descoberta de modelos por API
    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    canary = "sk-CANARY-LOOKUP-77"
    result = discover_models(f"http://127.0.0.1:{port}/v1", canary, "mock")
    server.shutdown()
    print(f"DISCOVERY ok={result['ok']} models={result['models']}")
    if result["models"] != sorted(m["id"] for m in MODELS):
        failures.append(f"descoberta retornou {result['models']}")
    for model in result["models"]:
        engine = resolve_engine(model)
        if engine != "api":
            failures.append(f"engine_router({model}) = {engine} != api")
    leaked = []
    for root in (Path.home() / ".local" / "state" / "mark", Path.home() / ".config" / "mark"):
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.stat().st_size < 4 * 1024 * 1024:
                try:
                    if canary.encode() in path.read_bytes():
                        leaked.append(str(path))
                except OSError:
                    continue
    if leaked:
        failures.append(f"api key de teste vazou em: {leaked[:3]}")
    print(f"DISCOVERY_LEAK files={leaked}")

    # --------------------------------------------------- 5. HF split view limpo
    raw = "---\ntags:\n- text-generation\n---\n# BertModel\nConteudo real"
    stripped = _strip_frontmatter(raw)
    chips = _chips_html(["ARCH: BertModel", "FORMAT: Safetensors"])
    print(f"HF frontmatter={stripped.splitlines()[0]!r} chips_has_arch={'BertModel' in chips}")
    if stripped.startswith("---") or "tags:" in stripped:
        failures.append("frontmatter YAML nao foi removido do README")
    if "BertModel" not in chips or "background:#121417" not in chips:
        failures.append("chips de arquitetura nao renderizaram no tema dark")

    names = [w.objectName() or type(w).__name__ for w in app.topLevelWidgets() if w.isVisible()]
    delta = fault_size() - before
    print(f"TOPLEVELS {names}")
    print(f"FAULT_LOG_DELTA={delta}")
    if names != ["MainWindow"]:
        failures.append(f"topLevelWidgets inesperado: {names}")
    if delta != 0:
        failures.append(f"crash_fault.log cresceu {delta} bytes")

    window.close()
    QTest.qWait(300)
    if failures:
        print(f"\nFAIL ({len(failures)} problemas)")
        for item in failures:
            print("  -", item)
        return 1
    print("\nUI FEATURES OK: CTX, thinking box, plugins, descoberta e HF split view")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
