from __future__ import annotations

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .cognition.mark_local_provider import run_native_1bit_engine
from .cognition.provider_adapter import adapt_ollama_payload, get_local_inference_params
from .config.llm_config import get_role_models_config
from .hf_hub_manager import HuggingFaceHubManager

logger = logging.getLogger(__name__)

_SERVER_LOGS: list[str] = []
_SERVER_LOCK = threading.Lock()


def append_server_log(entry: str) -> None:
    ts = time.strftime("%H:%M:%S")
    with _SERVER_LOCK:
        _SERVER_LOGS.append(f"[{ts}] {entry}")
        if len(_SERVER_LOGS) > 200:
            _SERVER_LOGS.pop(0)


def get_server_logs() -> list[str]:
    with _SERVER_LOCK:
        return list(_SERVER_LOGS)


class OpenAICompatibleHandler(BaseHTTPRequestHandler):
    server_version = "MARKLocalServer/2.0"

    def log_message(self, format_str: str, *args: Any) -> None:
        logger.debug(format_str, *args)

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def do_OPTIONS(self) -> None:
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        if self.path.startswith("/v1/health") or self.path == "/health":
            lip = get_local_inference_params()
            payload = {"status": "ok", "engine": "MARK-1Bit-W1A4", "num_ctx": lip.get("num_ctx", 32768)}
            self._write_json(200, payload)
            append_server_log("GET /v1/health -> 200 OK")
            return

        if self.path.startswith("/v1/models"):
            hub = HuggingFaceHubManager()
            installed = hub.list_installed_models()
            roles = get_role_models_config()
            model_list = [
                {"id": "mark-bin-32b", "object": "model", "owned_by": "miceworks"},
                {"id": "mark-rust-4b", "object": "model", "owned_by": "miceworks"},
                {"id": "mark-slm-v3-150m", "object": "model", "owned_by": "miceworks"},
                {"id": "mark-engineer-1.5b", "object": "model", "owned_by": "miceworks"},
                {"id": "mark-general-1.5b", "object": "model", "owned_by": "miceworks"},
                {"id": "mark-vl-2.2b", "object": "model", "owned_by": "miceworks"},
            ]
            seen = {m["id"] for m in model_list}
            for role_name, r_cfg in roles.items():
                alias = f"mark-{role_name}"
                if alias not in seen:
                    model_list.append({"id": alias, "object": "model", "owned_by": "mark-role"})
                    seen.add(alias)
            for inst in installed:
                if inst["id"] not in seen:
                    model_list.append({"id": inst["id"], "object": "model", "owned_by": inst["source"]})
                    seen.add(inst["id"])
            self._write_json(200, {"object": "list", "data": model_list})
            append_server_log(f"GET /v1/models -> {len(model_list)} modelos listados")
            return

        self._write_json(404, {"error": "Endpoint nao encontrado"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw_body = self.rfile.read(length).decode("utf-8", errors="ignore") if length > 0 else "{}"
        try:
            body = json.loads(raw_body)
        except Exception:
            body = {}

        if self.path.startswith("/v1/chat/completions") or self.path.startswith("/v1/completions"):
            t0 = time.time()
            req_model = str(body.get("model") or "mark-bin-32b")
            stream = bool(body.get("stream", False))
            messages = body.get("messages", [])
            prompt = str(body.get("prompt") or "")
            system_prompt = ""
            has_image = False

            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if isinstance(content, list):
                    for part in content:
                        if part.get("type") == "image_url":
                            has_image = True
                        elif part.get("type") == "text":
                            prompt += part.get("text", "") + "\n"
                elif role == "system":
                    system_prompt += str(content) + "\n"
                else:
                    prompt += f"{content}\n"

            roles_cfg = get_role_models_config()
            if has_image:
                req_model = roles_cfg["vision"]["primary_model"]

            lip = get_local_inference_params()
            if "bin-32b" in req_model or "1bit" in req_model or req_model == "mark":
                res = run_native_1bit_engine(
                    prompt=prompt.strip(),
                    system_prompt=system_prompt.strip(),
                    max_tokens=int(body.get("max_tokens") or 512),
                    clan_id=0 if "engineer" in req_model else 2,
                    core_loops=2,
                    temperature=float(body.get("temperature") or 0.2),
                    num_ctx=int(lip.get("num_ctx", 2097152)),
                )
                reply_text = res.get("text", "")
            else:
                import urllib.request
                ollama_payload = adapt_ollama_payload(req_model, prompt.strip(), system=system_prompt.strip(), stream=False)
                try:
                    req = urllib.request.Request(
                        "http://127.0.0.1:11434/api/generate",
                        data=json.dumps(ollama_payload).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(req, timeout=60) as resp:  # nosec: B310
                        odata = json.loads(resp.read().decode("utf-8"))
                        reply_text = odata.get("response", "")
                except Exception:
                    res = run_native_1bit_engine(prompt=prompt.strip(), system_prompt=system_prompt.strip())
                    reply_text = res.get("text", "")

            elapsed = max(0.001, time.time() - t0)
            tok_count = max(1, len(reply_text.split()))
            tok_s = round(tok_count / elapsed, 1)
            append_server_log(f"POST {self.path} | model={req_model} | {tok_count} tok ({tok_s} tok/s)")

            if stream:
                self.send_response(200)
                self._send_cors_headers()
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                chunk_obj = {
                    "id": "chatcmpl-mark1bit",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": req_model,
                    "choices": [{"index": 0, "delta": {"role": "assistant", "content": reply_text}, "finish_reason": "stop"}],
                }
                self.wfile.write(f"data: {json.dumps(chunk_obj)}\n\ndata: [DONE]\n\n".encode("utf-8"))
                self.wfile.flush()
                return

            resp_obj = {
                "id": "chatcmpl-mark1bit",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": req_model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": reply_text},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": len(prompt.split()), "completion_tokens": tok_count, "total_tokens": len(prompt.split()) + tok_count},
            }
            self._write_json(200, resp_obj)
            return

        self._write_json(404, {"error": "Rota POST desconhecida"})

    def _write_json(self, status: int, data: dict[str, Any]) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class LocalOpenAIServer:
    """Controlador singleton do servidor HTTP OpenAI/LM Studio do MARK."""

    def __init__(self) -> None:
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.host: str = "127.0.0.1"
        self.port: int = 1234
        self.running: bool = False

    def start(self, host: str = "127.0.0.1", port: int = 1234) -> bool:
        if self.running:
            return True
        try:
            ThreadingHTTPServer.allow_reuse_address = True
            self._httpd = ThreadingHTTPServer((host, port), OpenAICompatibleHandler)
            self.host = host
            self.port = port
            self.running = True
            self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
            self._thread.start()
            append_server_log(f"Servidor OpenAI Local iniciado em http://{host}:{port}/v1")
            return True
        except Exception as exc:
            append_server_log(f"Erro ao iniciar servidor na porta {port}: {exc}")
            self.running = False
            return False

    def stop(self) -> None:
        if self._httpd and self.running:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
            self.running = False
            append_server_log("Servidor Local encerrado.")


GLOBAL_LOCAL_SERVER = LocalOpenAIServer()
