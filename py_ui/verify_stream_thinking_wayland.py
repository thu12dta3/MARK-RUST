
"""Wayland + SSE real: pintura incremental, think box ao vivo e Stop."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PY_UI = Path(__file__).resolve().parent
sys.path.insert(0, str(PY_UI))
FAULT = Path.home() / ".local" / "state" / "mark" / "crash_fault.log"

SCENARIOS = {
    "/think": [
        "<" + "think" + ">",
        "passo 1: ",
        "passo 2: somar",
        "</" + "think" + ">",
        "Resposta ",
        "final ",
        "limpa",
    ],
    "/plain": ["Apenas ", "conteudo ", "sem raciocinio."],
}
DELAY = 0.05


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("content-length") or 0)
        self.rfile.read(length)
        chunks = SCENARIOS.get(self.path, [])
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        for piece in chunks:
            payload = json.dumps({"choices": [{"delta": {"content": piece}}]})
            self.wfile.write(f"data: {payload}\n\n".encode())
            self.wfile.flush()
            time.sleep(DELAY)
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def log_message(self, *args):
        return


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "wayland")
    if not os.environ.get("WAYLAND_DISPLAY"):
        print("FAIL: WAYLAND_DISPLAY nao definido")
        return 2
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication

    from mark.sse_client import StreamCancelled, stream_chat
    from mark.think_stream import ThinkStreamParser
    from mark.ui.main_window import MainWindow
    from mark.ui.widgets import CollapsibleThinkingBox, MessageBubbleWidget

    app = QApplication.instance() or QApplication(sys.argv)
    before = FAULT.stat().st_size if FAULT.is_file() else 0
    failures: list[str] = []
    window = MainWindow()
    window.resize(1280, 850)
    window.show()
    QTest.qWait(2400)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    # ------------------------------------------- 1. streaming + think box ao vivo
    bubble = MessageBubbleWidget(text="", role="assistant", parent=window)
    thinking = CollapsibleThinkingBox(window)
    parser = ThinkStreamParser()
    snapshots: list[str] = []
    reasoning_steps: list[str] = []

    def on_content(chunk: str) -> None:
        for kind, piece in parser.feed(chunk):
            if kind == "reasoning":
                reasoning_steps.append(piece)
                thinking.append_reasoning(piece)
            else:
                bubble.set_text((bubble.text or "") + piece)
                snapshots.append(bubble.text)
        QTest.qWait(10)

    stream_chat(f"http://127.0.0.1:{port}/think", {}, on_content)
    for kind, piece in parser.finalize():
        if kind == "content":
            bubble.set_text((bubble.text or "") + piece)
            snapshots.append(bubble.text)
    thinking.finish()
    print(f"STREAM chunks={len(snapshots)} snapshots={snapshots[:3]}...{snapshots[-1:]}")
    print(f"THINK visible={thinking.isVisible()} header={thinking.header_button.text()!r} reasoning={thinking.reasoning_text()!r}")
    print(f"BUBBLE text={bubble.text!r}")
    if len(set(snapshots)) < 3:
        failures.append(f"bolha nao pintou incrementalmente: {snapshots}")
    if "Resposta final limpa" not in (bubble.text or ""):
        failures.append("resposta final ausente no corpo da bolha")
    if "<" + "think" in (bubble.text or ""):
        failures.append("tags de raciocinio vazaram para o corpo da bolha")
    if not thinking.isVisible():
        failures.append("caixa de pensamento nao apareceu com think real")
    if "passo 2" not in thinking.reasoning_text():
        failures.append("caixa de pensamento nao recebeu o raciocinio ao vivo")
    if not thinking.header_button.text().startswith("Thought for"):
        failures.append(f"cabecalho nao virou 'Thought for Ns': {thinking.header_button.text()!r}")

    # ------------------------------------------ 2. sem think: caixa permanece oculta
    bubble2 = MessageBubbleWidget(text="", role="assistant", parent=window)
    thinking2 = CollapsibleThinkingBox(window)
    parser2 = ThinkStreamParser()
    plain_snaps: list[str] = []

    def on_content2(chunk: str) -> None:
        for kind, piece in parser2.feed(chunk):
            if kind == "reasoning":
                thinking2.append_reasoning(piece)
            else:
                bubble2.set_text((bubble2.text or "") + piece)
                plain_snaps.append(bubble2.text)

    stream_chat(f"http://127.0.0.1:{port}/plain", {}, on_content2)
    thinking2.finish()
    print(f"PLAIN chunks={len(plain_snaps)} visible={thinking2.isVisible()} text={bubble2.text!r}")
    if thinking2.isVisible():
        failures.append("caixa de pensamento visivel sem raciocinio (pensamento inventado)")
    if "sem raciocinio" not in (bubble2.text or ""):
        failures.append("conteudo simples nao chegou na bolha")

    # --------------------------------------------------- 3. Stop cancela o stream
    cancel_flag = {"v": False}
    partial: list[str] = []

    def on_content3(chunk: str) -> None:
        partial.append(chunk)
        bubble2.set_text((bubble2.text or "") + chunk)
        if len(partial) >= 2:
            cancel_flag["v"] = True

    cancelled = False
    try:
        stream_chat(
            f"http://127.0.0.1:{port}/think",
            {},
            on_content3,
            cancelled=lambda: cancel_flag["v"],
        )
    except StreamCancelled:
        cancelled = True
    print(f"STOP cancelled={cancelled} chunks_received={len(partial)}")
    if not cancelled:
        failures.append("botao Stop nao interrompeu o stream SSE")
    if len(partial) > 3:
        failures.append(f"stream continuou apos o Stop: {len(partial)} chunks")

    server.shutdown()
    names = [w.objectName() or type(w).__name__ for w in app.topLevelWidgets() if w.isVisible()]
    delta = (FAULT.stat().st_size if FAULT.is_file() else 0) - before
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
    print("\nSSE+THINK OK: pintura incremental, raciocinio ao vivo, sem fake e Stop real")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
