"""Módulo de segurança, controle de acesso e cofre de consentimento do MARK."""

from .consent import APIConsentManager, get_api_consent_manager

__all__ = ["APIConsentManager", "get_api_consent_manager"]
