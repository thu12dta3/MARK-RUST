"""Módulo de ferramentas do MARK e integração com interceptor de APIs externas."""

from ..network.interceptor import ExternalAPIInterceptor, AuthorizationEvent
from ..security.consent import APIConsentManager, get_api_consent_manager

__all__ = [
    "ExternalAPIInterceptor",
    "AuthorizationEvent",
    "APIConsentManager",
    "get_api_consent_manager",
]
