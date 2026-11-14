"""Verification harness: persistence, engine dispatch and reasoning payloads."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

PY_UI = Path(__file__).resolve().parent
if str(PY_UI) not in sys.path:
    sys.path.insert(0, str(PY_UI))

CONFIG = Path.home() / ".config" / "mark" / "config.json"
TRACE = Path.home() / ".local" / "state" / "mark" / "http_trace.log"


def config_snapshot() -> dict:
    return json.loads(CONFIG.read_text()) if CONFIG.is_file() else {}


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "audit"

    if mode == "write":
        from PyQt6.QtWidgets import QApplication

        app = QApplication([])
        from mark.config import set_reasoning_level
        from mark.ui.main_window import MainWindow

        window = MainWindow()
        window.show()
        app.processEvents()
        window._select_engine("ollama", "Local Ollama")
        app.processEvents()
        set_reasoning_level("instant")
        index = next(
            (i for i in range(window.model_selector.count()) if "Deepseek R1" in window.model_selector.itemText(i)),
            0,
        )
        window.model_selector.setCurrentIndex(index)
        app.processEvents()
        saved = config_snapshot()
        print("WROTE engine:", saved.get("engine"), "| reasoning:", saved.get("reasoning_level"))
        print("WROTE qsettings model:", window.model_selector._settings.value("chat/selected_model"))
        window.shutdown()
        window.close()
        app.processEvents()
        return 0

    if mode == "read":
        from PyQt6.QtWidgets import QApplication

        app = QApplication([])
        from mark.ui.main_window import MainWindow

        window = MainWindow()
        window.show()
        app.processEvents()
        engine = getattr(window, "active_engine", "?")
        model = window.model_selector.currentText()
        reasoning = window.reasoning_selector.currentText()
        print("READ engine:", engine, "| engine_button:", window.engine_button.text())
        print("READ model:", model)
        print("READ reasoning:", reasoning)
        ok = engine == "ollama" and "Deepseek R1" in model and "Instant" in reasoning
        print("RESTORED_OK:", ok)
        window.shutdown()
        window.close()
        app.processEvents()
        return 0 if ok else 4

    # audit: despacho real por engine + payloads de raciocinio
    from mark.config import set_reasoning_level
    from mark.desktop_helpers import _request, set_active_engine
    from mark.rust_bridge import rust

    print("=== OLLAMA real ===")
    set_active_engine("ollama")
    payload = {"model": "deepseek-r1:8b-q3_k_l", "messages": [{"role": "user", "content": "oi"}], "stream": False}
    try:
        status, body = _request("/v1/chat/completions", payload, timeout=180)
        parsed = json.loads(body.decode("utf-8", "replace"))
        print("OLLAMA status:", status, "| content:", str(parsed.get("choices", [{}])[0].get("message", {}).get("content", ""))[:120].replace("\n", " "))
    except RuntimeError as exc:
        print("OLLAMA ERROR:", str(exc)[:300])

    print()
    print("=== RUST mark-server ===")
    set_active_engine("rust", 8931)
    started = rust.server_start(8931)
    print("server:", started)
    for proto in ("mark", "Mark-Bin-32B (1-Bit W1A4, 2M context)"):
        payload = {"model": proto, "messages": [{"role": "user", "content": "oi"}], "stream": False}
        try:
            status, body = _request("/v1/chat/completions", payload, timeout=60)
            print(f"RUST model={proto!r} ->", status, body[:200].decode("utf-8", "replace"))
        except RuntimeError as exc:
            print(f"RUST model={proto!r} ->", str(exc)[:260])

    print()
    print("=== LLAMA.CPP (binario ausente) ===")
    set_active_engine("llamacpp")
    try:
        _request("/v1/chat/completions", {"model": "x.gguf", "messages": [{"role": "user", "content": "oi"}]}, timeout=10)
        print("LLAMACPP: inesperado, respondeu")
    except RuntimeError as exc:
        print("LLAMACPP clear error:", str(exc)[:220])

    print()
    print("=== PAYLOADS DE RACIOCINIO (mark-server) ===")
    set_active_engine("rust", 8931)
    for level in ("instant", "balanced", "deep"):
        set_reasoning_level(level)
        before = TRACE.stat().st_size if TRACE.is_file() else 0
        try:
            _request(
                "/v1/chat/completions",
                {"model": "mark", "messages": [{"role": "user", "content": "oi"}], "stream": False},
                timeout=45,
            )
        except RuntimeError as exc:
            pass
        chunk = ""
        if TRACE.is_file():
            with TRACE.open("r", encoding="utf-8") as handle:
                handle.seek(before)
                chunk = handle.read()
        payload_line = ""
        for line in chunk.splitlines():
            if "reasoning_level" in line:
                payload_line = line
                break
        try:
            data = json.loads(payload_line)
        except Exception:
            data = {}
        print(
            f"{level}: reasoning_level={data.get('reasoning_level')} loops={data.get('reasoning_loops')} "
            f"max_tokens={data.get('max_tokens')} temperature={data.get('temperature')} model={data.get('model')}"
        )
    set_reasoning_level("balanced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
