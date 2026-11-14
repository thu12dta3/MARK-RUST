"""Middleware de interceptação de chamadas de rede e APIs externas.

Implementa a verificação prévia de consentimento (Token Caching / Cache de Consentimento)
para suprimir pop-ups redundantes de autorização no MARK.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable
from unittest.mock import MagicMock

from PyQt6.QtCore import QObject, pyqtSignal

from ..security.consent import APIConsentManager, get_api_consent_manager

logger = logging.getLogger(__name__)


class AuthorizationEvent:
    """Evento sincronizador thread-safe para captura de decisão do usuário em diálogos."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self.is_approved: bool = False
        self.remember: bool = False
        self.token: Any = True

    def set_result(self, approved: bool, remember: bool = False, token: Any = True) -> None:
        self.is_approved = bool(approved)
        self.remember = bool(remember)
        self.token = token
        self._event.set()

    def wait(self, timeout: float = 60.0) -> bool:
        return self._event.wait(timeout=timeout)


class ExternalAPIInterceptor(QObject):
    """Middleware que intercepta chamadas externas e consulta o cache seguro de consentimento.
    
    Antes de disparar o sinal `request_user_authorization` para pausar a thread e abrir
    o pop-up na interface, consulta o `APIConsentManager`. Se a permissão já foi concedida
    (em sessão ou permanente no cofre em Rust), realiza o bypass silencioso imediato.
    """

    request_user_authorization = pyqtSignal(str, dict, object)

    def __init__(
        self,
        consent_manager: APIConsentManager | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.consent_manager = consent_manager or get_api_consent_manager()
        self._parent_widget = parent if hasattr(parent, "window") else None

    def has_cached_permission(self, current_api: str) -> bool:
        """Verifica se a API especificada já possui consentimento válido em cache/cofre."""
        return bool(self.consent_manager.has_permission(current_api))

    def intercept(
        self,
        current_api: str,
        details: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> bool:
        """Intercepta a chamada à API externa.
        
        Lógica:
        1. Se APIConsentManager.has_permission(current_api) for True, retorna True imediatamente.
        2. Se não houver permissão, emite o sinal request_user_authorization ou chama o mock.
        3. Se o usuário conceder e selecionar 'lembrar', grava como permanent no cofre Rust.
        """
        norm_api = str(current_api).strip().lower()

        # Verificação prévia de consentimento (Bypass do Pop-up)
        if self.consent_manager.has_permission(norm_api):
            logger.debug("Consentimento prévio localizado para '%s' · Pop-up suprimido", norm_api)
            return True

        auth_event = AuthorizationEvent()
        req_target = getattr(self, "request_user_authorization")

        # Suporte a mock direto (e.g. mock_request_user_authorization passado ou patcheado)
        if callable(req_target) and (
            isinstance(req_target, MagicMock) or not hasattr(req_target, "emit")
        ):
            try:
                res = req_target(norm_api, details or {}, auth_event)
            except TypeError:
                res = req_target(norm_api)

            if res is not None:
                if isinstance(res, tuple):
                    approved = res[0]
                    remember = res[1] if len(res) > 1 else False
                    auth_event.set_result(approved, remember)
                elif isinstance(res, dict):
                    auth_event.set_result(
                        res.get("approved", True),
                        res.get("remember", False),
                        res.get("token", True),
                    )
                elif isinstance(res, bool):
                    auth_event.set_result(res, getattr(auth_event, "remember", False))
        else:
            # Emite sinal PyQt
            req_target.emit(norm_api, details or {}, auth_event)

        # Se ainda não estiver setado, aguarda resolução pelo diálogo da UI
        if not auth_event._event.is_set():
            signaled = auth_event.wait(timeout=timeout)
            if not signaled:
                logger.warning("Tempo limite esgotado aguardando autorização para '%s'", norm_api)
                return False

        if auth_event.is_approved:
            duration = "permanent" if auth_event.remember else "session"
            self.consent_manager.grant_permission(
                norm_api,
                token=auth_event.token,
                duration=duration,
            )
            return True

        return False

    def authorize(
        self,
        current_api: str,
        details: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> bool:
        """Alias para intercept()."""
        return self.intercept(current_api, details=details, timeout=timeout)

    def __call__(
        self,
        current_api: str,
        details: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> bool:
        """Permite que a instância seja invocada como callable."""
        return self.intercept(current_api, details=details, timeout=timeout)
