"""Módulo de rede e sincronização multiplataforma do MARK.

Fornece protocolo resiliente de sincronização bidirecional, gerenciamento
de sessões, reconexão automática e pareamento criptográfico efêmero.
"""

from .sync import (
    SyncMessageType,
    SyncPacket,
    IdempotencyManager,
    PairingPayload,
    PairingSession,
    NetworkDeviceManager,
    ResilientSyncProtocol,
    get_best_local_endpoint,
)
from .interceptor import ExternalAPIInterceptor, AuthorizationEvent

__all__ = [
    "SyncMessageType",
    "SyncPacket",
    "IdempotencyManager",
    "PairingPayload",
    "PairingSession",
    "NetworkDeviceManager",
    "ResilientSyncProtocol",
    "get_best_local_endpoint",
    "ExternalAPIInterceptor",
    "AuthorizationEvent",
]
