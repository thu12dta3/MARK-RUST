"""Bridge between the PyQt6 interface and the compiled MARK-RUST engine.

Every call in this module talks to a real artifact: a compiled binary under
``target/release``, the OpenAI-compatible HTTP server exported by
``mark-engine::server``, or the on-disk vault produced by ``mark-core::vault``.
When a binary is missing the method reports that honestly instead of inventing
a result.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BIN_DIR = Path(os.environ.get("MARK_RUST_BIN_DIR", ROOT / "target" / "release"))
SERVER_BIN = "mark-server"
VAULT_BIN = "mark-vault"
ENGINEER_BIN = "mark-engineer"


def data_home() -> Path:
    """XDG data root for MARK, honouring MARK_DATA_HOME when set."""
    override = os.environ.get("MARK_DATA_HOME")
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return base / "mark"


class RustBridge:
    """Thin, synchronous facade over the Rust workspace binaries."""

    def __init__(self) -> None:
        self._server: subprocess.Popen[bytes] | None = None
        self._server_port = 0
        self._server_log: Path | None = None
        self._master_password = ""

    # ---------------------------------------------------------------- helpers
    def binary(self, name: str) -> Path | None:
        candidate = BIN_DIR / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
        found = shutil.which(name)
        return Path(found) if found else None

    def available(self) -> bool:
        return any(self.binary(name) is not None for name in (SERVER_BIN, VAULT_BIN, ENGINEER_BIN))

    def binaries(self) -> dict[str, str | None]:
        return {name: (str(self.binary(name)) if self.binary(name) else None) for name in (SERVER_BIN, VAULT_BIN, ENGINEER_BIN)}

    def _run(self, name: str, args: list[str], stdin: str | None = None, timeout: int = 120) -> dict[str, Any]:
        exe = self.binary(name)
        if exe is None:
            return {"ok": False, "stdout": "", "stderr": f"{name} not compiled in {BIN_DIR}", "code": -1}
        try:
            proc = subprocess.run(
                [str(exe), *args],
                input=(stdin or "").encode(),
                capture_output=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "stdout": "", "stderr": f"{name} timed out after {timeout}s", "code": -2}
        except OSError as exc:
            return {"ok": False, "stdout": "", "stderr": f"{name} failed to start: {exc}", "code": -3}
        return {
            "ok": proc.returncode == 0,
            "stdout": proc.stdout.decode(errors="replace"),
            "stderr": proc.stderr.decode(errors="replace"),
            "code": proc.returncode,
        }

    @staticmethod
    def _json(result: dict[str, Any]) -> dict[str, Any]:
        text = (result.get("stdout") or "").strip()
        if not text:
            return {"ok": bool(result.get("ok")), "message": (result.get("stderr") or "").strip()}
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return {"ok": bool(result.get("ok")), "message": text}
        if isinstance(payload, dict):
            payload.setdefault("ok", bool(result.get("ok")))
            return payload
        return {"ok": bool(result.get("ok")), "value": payload}

    # ------------------------------------------------------------------ vault
    def vault_status(self) -> dict[str, Any]:
        result = self._run(VAULT_BIN, ["status", "--json"], timeout=30)
        payload = self._json(result)
        payload.setdefault("exists", False)
        payload.setdefault("sealed", False)
        payload.setdefault("path", str(Path.home() / ".config" / "mark" / "vault.bin"))
        payload.setdefault("entries", 0)
        payload["backend"] = "rust" if result.get("code") == 0 else "python"
        return payload

    def vault_init(self, password: str) -> dict[str, Any]:
        result = self._json(self._run(VAULT_BIN, ["init", "--json"], stdin=password, timeout=180))
        if result.get("ok"):
            self._master_password = password
        return result

    def vault_unlock(self, password: str) -> dict[str, Any]:
        """Valida a senha mestra no cofre Rust e abre a sessao local."""
        result = self._json(self._run(VAULT_BIN, ["unlock", "--json"], stdin=password, timeout=180))
        self._master_password = password if result.get("ok") else ""
        return result

    def vault_lock(self) -> dict[str, Any]:
        """Encerra a sessao local sem tocar no cofre em disco."""
        self._master_password = ""
        return {"ok": True, "message": "vault session closed"}

    def vault_list(self) -> dict[str, Any]:
        """Lista as chaves guardadas dentro do cofre Rust."""
        if not self._master_password:
            return {"ok": False, "error": "vault-locked", "keys": []}
        return self._json(self._run(VAULT_BIN, ["list", "--json"], stdin=self._master_password, timeout=180))

    def vault_set(self, name: str, value: str) -> dict[str, Any]:
        """Grava um segredo cifrado dentro do cofre Rust."""
        if not self._master_password:
            return {"ok": False, "error": "vault-locked"}
        payload = "\n".join([self._master_password, name, value])
        return self._json(self._run(VAULT_BIN, ["set", "--json"], stdin=payload, timeout=180))

    def vault_get(self, name: str) -> dict[str, Any]:
        """Le um segredo do cofre Rust."""
        if not self._master_password:
            return {"ok": False, "error": "vault-locked"}
        payload = "\n".join([self._master_password, name])
        return self._json(self._run(VAULT_BIN, ["get", "--json"], stdin=payload, timeout=180))

    def vault_delete(self, name: str) -> dict[str, Any]:
        """Remove um segredo do cofre Rust."""
        if not self._master_password:
            return {"ok": False, "error": "vault-locked"}
        payload = "\n".join([self._master_password, name])
        return self._json(self._run(VAULT_BIN, ["delete", "--json"], stdin=payload, timeout=180))

    def vault_rekey(self, current: str, new: str) -> dict[str, Any]:
        result = self._json(self._run(VAULT_BIN, ["rekey", "--json"], stdin=f"{current}\n{new}", timeout=300))
        if result.get("ok"):
            self._master_password = new
        return result

    def vault_factory_reset(self, password: str) -> dict[str, Any]:
        result = self._json(self._run(VAULT_BIN, ["factory-reset", "--json"], stdin=password, timeout=300))
        if result.get("ok"):
            self._master_password = password
        return result

    # ----------------------------------------------------------- local server
    def _port_free(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                return False
        return True

    def _probe_http(self, port: int) -> bool:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=2) as response:
                return response.status == 200
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def server_start(self, port: int = 8765, model: str | None = None) -> dict[str, Any]:
        status = self.server_status()
        if status["running"]:
            return {"ok": True, "port": status["port"], "message": "server already running"}
        exe = self.binary(SERVER_BIN)
        if exe is None:
            return {"ok": False, "port": port, "message": f"{SERVER_BIN} not compiled in {BIN_DIR}"}
        if not self._port_free(port):
            return {"ok": False, "port": port, "message": f"port {port} is already in use"}
        log_path = data_home() / "logs" / "mark-server.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        args = [str(exe), "--port", str(port)]
        if model:
            args.extend(["--model", model])
        handle = open(log_path, "ab")
        try:
            self._server = subprocess.Popen(args, stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as exc:
            handle.close()
            return {"ok": False, "port": port, "message": f"failed to spawn {SERVER_BIN}: {exc}"}
        self._server_port = port
        self._server_log = log_path
        deadline = time.time() + 180
        while time.time() < deadline:
            if self._server.poll() is not None:
                tail = log_path.read_text(errors="replace")[-1500:]
                self._server = None
                return {"ok": False, "port": port, "message": f"server exited during startup: {tail.strip()}"}
            if self._probe_http(port):
                return {"ok": True, "port": port, "message": f"listening on 127.0.0.1:{port}"}
            time.sleep(0.4)
        return {"ok": False, "port": port, "message": f"server did not answer /v1/models within 180s (log: {log_path})"}

    def server_stop(self) -> dict[str, Any]:
        if self._server is None:
            return {"ok": True, "message": "no server started by this session"}
        self._server.terminate()
        try:
            self._server.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self._server.kill()
            self._server.wait(timeout=5)
        self._server = None
        return {"ok": True, "message": "server stopped"}

    def server_status(self) -> dict[str, Any]:
        running = self._server is not None and self._server.poll() is None
        port = self._server_port
        models: list[str] = []
        if running and port:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=2) as response:
                    payload = json.loads(response.read().decode())
                models = [item.get("id", "") for item in payload.get("data", []) if item.get("id")]
            except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
                running = self._probe_http(port)
        return {
            "running": running,
            "port": port,
            "pid": self._server.pid if self._server is not None else None,
            "models": models,
            "log": str(self._server_log) if self._server_log else "",
        }

    def chat(self, messages: list[dict[str, str]], model: str | None = None, max_tokens: int = 512, timeout: int = 180) -> str:
        status = self.server_status()
        if not status["running"]:
            raise RuntimeError("MARK Rust local server is not running (start it in Settings > Local OpenAI API Server)")
        payload = {
            "model": model or (status["models"][0] if status["models"] else "mark"),
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": False,
        }
        request = urllib.request.Request(
            f"http://127.0.0.1:{status['port']}/v1/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode())
        choices = body.get("choices") or []
        if not choices:
            raise RuntimeError(f"empty completion payload: {body}")
        return str(choices[0].get("message", {}).get("content", ""))

    # --------------------------------------------------------------- engineer
    def engine_status(self) -> dict[str, Any]:
        result = self._run(SERVER_BIN, ["--probe"], timeout=60)
        payload = self._json(result)
        payload.setdefault("gpu", False)
        payload.setdefault("backend", "unavailable")
        payload.setdefault("checkpoint", None)
        return payload

    def engineer_action(self, action: dict[str, Any], workspace: str | None = None, approval: str = "suggest") -> dict[str, Any]:
        args = ["--json", "--approval", approval]
        if workspace:
            args.extend(["--workspace", workspace])
        return self._json(self._run(ENGINEER_BIN, args, stdin=json.dumps(action), timeout=600))

    def engineer_skills(self) -> dict[str, Any]:
        result = self._run(ENGINEER_BIN, ["--list-skills", "--json"], timeout=60)
        return self._json(result)

    def web_search(self, query: str, limit: int = 5) -> dict[str, Any]:
        return self._json(self._run(ENGINEER_BIN, ["--web-search", query, "--limit", str(limit), "--json"], timeout=90))

    def temp_workspace(self) -> Path:
        target = data_home() / "sandbox"
        target.mkdir(parents=True, exist_ok=True)
        return target


rust = RustBridge()
