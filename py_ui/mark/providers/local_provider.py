"""Adaptador e Gerenciador de Inferência Local com Guardrails Anti-OOM e Fallback Seguro.

Implementa a injeção dinâmica de parâmetros da API do Ollama/llama.cpp e o mecanismo
de segurança que reverte imediatamente para as configurações seguras em caso de falha de
alocação de memória (VRAM/RAM), emitindo alertas nativos e mantendo o sistema ativo.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Callable
import urllib.error
import urllib.request

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QMessageBox, QWidget

from ..config import (
    LOCAL_INFERENCE_DEFAULTS,
    get_local_inference_params,
    load_config,
    save_local_inference_params,
    validate_and_clamp_inference_params,
)

logger = logging.getLogger("mark.providers.local")


class LocalProviderError(RuntimeError):
    """Exceção base para erros em provedores locais."""


class MemoryAllocationError(LocalProviderError):
    """Erro de alocação de memória VRAM/RAM durante inicialização ou inferência do motor."""


class LocalInferenceManager(QObject):
    """Gerenciador central do ciclo de vida e recarga a quente do motor local.
    
    Escuta solicitações de alteração de parâmetros e executa a recarga protegida por
    mecanismo de fallback anti-crash.
    """

    reload_completed = pyqtSignal(dict)
    fallback_triggered = pyqtSignal(dict)

    FALLBACK_ALERT_MESSAGE = "Erro ao alocar memória. A reverter para as definições anteriores."

    def __init__(self, cfg: dict | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg or {}
        try:
            self.current_params = get_local_inference_params(self.cfg)
        except Exception:
            self.current_params = dict(LOCAL_INFERENCE_DEFAULTS)
        self.previous_safe_params = dict(self.current_params)
        self._attached_widget: Any = None
        self._alert_fn: Callable[[str, Any], None] | None = None

    def _show_native_alert(self, message: str, parent: QWidget | None = None) -> None:
        """Exibe um diálogo nativo de aviso na interface gráfica sem travar o motor."""
        if self._alert_fn:
            self._alert_fn(message, parent)
            return

        try:
            target_parent = parent or (self._attached_widget if isinstance(self._attached_widget, QWidget) else None)
            QMessageBox.warning(
                target_parent,
                "MARK · Alerta de Memória",
                message,
                QMessageBox.StandardButton.Ok,
            )
        except Exception as exc:
            logger.warning(f"Não foi possível abrir diálogo gráfico nativo ({exc}): {message}")

    def _test_engine_allocation(self, params: dict[str, Any]) -> None:
        """Testa ou valida se o motor local aceita as novas configurações sem falta de VRAM."""
        base_url = (
            os.environ.get("MARK_OLLAMA_URL")
            or os.environ.get("OLLAMA_HOST")
            or self.cfg.get("ollama", {}).get("url", "http://127.0.0.1:11434")
        ).rstrip("/")

        model_name = self.cfg.get("ollama", {}).get("model", "haervwe/qwen3-vl-4b-heretic:latest")

        try:
            url = f"{base_url}/api/show"
            req = urllib.request.Request(
                url,
                data=json.dumps({"model": model_name}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                if resp.status != 200:
                    pass
        except urllib.error.HTTPError as http_err:
            body = ""
            try:
                body = http_err.read().decode("utf-8", errors="ignore")
            except Exception:
                pass
            lower_body = (body + " " + str(http_err)).lower()
            if any(k in lower_body for k in ("out of memory", "not enough memory", "vram", "allocation failed", "cuda error: out of memory")):
                raise MemoryAllocationError(f"Ollama/llama.cpp OOM: {body}") from http_err
        except (urllib.error.URLError, ConnectionError, OSError):
            pass

    def reload_inference_engine(
        self,
        new_params: dict[str, Any],
        show_alert: bool = True,
        alert_callback: Callable[[str, Any], None] | None = None,
    ) -> tuple[bool, dict[str, Any]]:
        """Recarrega o motor com os novos parâmetros sob sistema de fallback estrito anti-crash."""
        clamped_params = validate_and_clamp_inference_params(new_params)

        try:
            logger.info("Tentando recarregar motor local com parâmetros: %s", clamped_params)
            self._test_engine_allocation(clamped_params)

            # Recarga bem-sucedida: atualiza histórico seguro e persiste
            self.previous_safe_params = dict(clamped_params)
            self.current_params = dict(clamped_params)
            save_local_inference_params(clamped_params)

            self.reload_completed.emit(clamped_params)
            return True, clamped_params

        except (MemoryAllocationError, MemoryError, Exception) as exc:
            logger.error("Falha ao recarregar motor de inferência local (%s): %s", type(exc).__name__, exc)

            # Reverte imediatamente para as configurações seguras
            safe_fallback = dict(self.previous_safe_params)
            self.current_params = dict(safe_fallback)
            save_local_inference_params(safe_fallback)

            # Emite alerta nativo
            if show_alert:
                alert_fn = alert_callback or self._alert_fn or self._show_native_alert
                alert_fn(self.FALLBACK_ALERT_MESSAGE, self._attached_widget)

            self.fallback_triggered.emit(safe_fallback)
            return False, safe_fallback

    def attach_settings_widget(self, settings_widget: Any) -> None:
        """Conecta o sinal reload_inference_engine_requested do SettingsWidget ao gerenciador."""
        self._attached_widget = settings_widget
        if hasattr(settings_widget, "reload_inference_engine_requested"):
            settings_widget.reload_inference_engine_requested.connect(self._handle_ui_reload_request)

    def _handle_ui_reload_request(self, params: dict[str, Any]) -> None:
        """Manipulador chamado quando o usuário clica no botão de recarregar na interface."""
        try:
            success, active_params = self.reload_inference_engine(params, show_alert=True)
            if not success and self._attached_widget:
                safe = dict(LOCAL_INFERENCE_DEFAULTS)
                safe.update(active_params)
                if hasattr(self._attached_widget, "slider_ctx"):
                    self._attached_widget.slider_ctx.setValue(safe.get("num_ctx", 4096))
                if hasattr(self._attached_widget, "slider_gpu"):
                    self._attached_widget.slider_gpu.setValue(safe.get("num_gpu", 16))
                if hasattr(self._attached_widget, "slider_threads"):
                    self._attached_widget.slider_threads.setValue(safe.get("num_thread", 3))
                if hasattr(self._attached_widget, "input_num_batch"):
                    self._attached_widget.input_num_batch.setValue(safe.get("num_batch", 2048))
                if hasattr(self._attached_widget, "input_physical_batch"):
                    self._attached_widget.input_physical_batch.setValue(safe.get("physical_batch_size", 512))
                if hasattr(self._attached_widget, "input_max_concurrent"):
                    self._attached_widget.input_max_concurrent.setValue(safe.get("max_concurrent_predictions", 4))
                if hasattr(self._attached_widget, "toggle_unified_kv"):
                    self._attached_widget.toggle_unified_kv.setChecked(bool(safe.get("unified_kv_cache", True)))
                if hasattr(self._attached_widget, "input_context_checkpoints"):
                    self._attached_widget.input_context_checkpoints.setValue(safe.get("context_checkpoints", 32))
                if hasattr(self._attached_widget, "toggle_flash_attn"):
                    self._attached_widget.toggle_flash_attn.setChecked(bool(safe.get("flash_attn", True)))
                if hasattr(self._attached_widget, "toggle_mmap"):
                    self._attached_widget.toggle_mmap.setChecked(bool(safe.get("use_mmap", True)))
                if hasattr(self._attached_widget, "inference_status_label"):
                    self._attached_widget.inference_status_label.setStyleSheet("color: #F85149;")
                    self._attached_widget.inference_status_label.setText("Falta de memória VRAM detectada. Revertido com segurança.")
        except Exception as exc:
            logger.error("Erro ao processar reload da UI: %s", exc)


class LocalProvider:
    """Interface de alto nível do provedor local integrada ao LocalInferenceManager."""

    def __init__(self, cfg: dict | None = None) -> None:
        self.cfg = cfg or {}
        self.manager = LocalInferenceManager(self.cfg)

    def reload(self, params: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        return self.manager.reload_inference_engine(params)
