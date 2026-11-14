"""EventBus, Sinais e Roteamento de Alertas Biométricos do MARK.

Gerencia o disparo assíncrono de eventos quando anomalias cardíacas são detectadas:
- Ação 1 (Imediata): Notificação no Sistema Desktop / Mobile ("MARK: Anomalia cardíaca detetada em repouso. Estás bem?").
- Ação 2 (Cognitiva): Injeção silenciosa na Memória Episódica (EpisodicMemoryStore) para recuperação futura via RAG.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
import os
import subprocess
import threading
from typing import Callable

logger = logging.getLogger("mark.telemetry.events")


@dataclass(frozen=True, slots=True)
class CardiacAnomaly:
    """Representa um evento detectado de anomalia na frequência cardíaca."""

    anomaly_type: str  # "resting_tachycardia" ou "bradycardia"
    heart_rate_bpm: int
    consecutive_count: int
    source: str
    timestamp: int
    is_active: bool = False
    summary: str = ""

    def formatted_summary(self) -> str:
        """Gera o sumário textual canônico para a memória episódica."""
        if self.summary:
            return self.summary
        try:
            dt = datetime.fromtimestamp(self.timestamp)
            dt_str = dt.strftime("%d/%m/%Y às %H:%M:%S")
        except Exception:
            dt_str = str(self.timestamp)

        tipo = "taquicardia" if self.anomaly_type == "resting_tachycardia" else "bradicardia"
        return (
            f"Em {dt_str}, o sistema detetou um batimento cardíaco anormal de "
            f"{self.heart_rate_bpm} BPM ({tipo}) enquanto o utilizador estava em repouso. "
            f"Alerta de saúde e bem-estar (o utilizador pode não se sentir bem hoje)."
        )


class TelemetryEventBus:
    """Barramento de eventos internos para telemetria de saúde e anomalias."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._listeners: list[Callable[[CardiacAnomaly], None]] = []

    def subscribe(self, listener: Callable[[CardiacAnomaly], None]) -> Callable[[], None]:
        """Inscreve um ouvinte para receber anomalias cardíacas."""
        if not callable(listener):
            raise TypeError("Ouvinte precisa ser chamável")
        with self._lock:
            self._listeners.append(listener)

        def unsubscribe() -> None:
            with self._lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)

        return unsubscribe

    def publish(self, anomaly: CardiacAnomaly) -> None:
        """Dispara a anomalia para todos os ouvintes registrados."""
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(anomaly)
            except Exception as exc:
                logger.warning("Falha em ouvinte de telemetria (%s): %s", type(exc).__name__, exc)


# Instância global do barramento
telemetry_events = TelemetryEventBus()


def dispatch_system_notification(
    title: str = "MARK",
    message: str = "MARK: Anomalia cardíaca detetada em repouso. Estás bem?",
) -> bool:
    """Dispara notificação de sistema no desktop (Linux/notify-send) sem bloquear."""
    try:
        # Se notify-send estiver disponível no PATH
        result = subprocess.run(
            ["notify-send", "--app-name=MARK", "--urgency=critical", title, message],
            capture_output=True,
            timeout=5,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        # Ambiente headless, sem servidor X11/Wayland ou sem notify-send
        logger.info("Notificação de sistema desktop (simulada/headless): %s", message)
        return False


def inject_into_episodic_memory(
    anomaly: CardiacAnomaly,
    episodic_store: Any | None = None,
) -> int:
    """Injeta silenciosamente o resumo da anomalia na Memória Episódica (Vector Store)."""
    try:
        if episodic_store is None:
            from ..memory.episodic_memory import EpisodicMemoryStore
            store = EpisodicMemoryStore()
        else:
            store = episodic_store

        summary_text = anomaly.formatted_summary()
        metadata = {
            "type": "cardiac_anomaly",
            "anomaly_type": anomaly.anomaly_type,
            "heart_rate_bpm": anomaly.heart_rate_bpm,
            "source": anomaly.source,
            "timestamp": anomaly.timestamp,
            "consecutive_count": anomaly.consecutive_count,
        }
        if hasattr(store, "record_biometric_event"):
            row_id = store.record_biometric_event(summary=summary_text, metadata=metadata)
        else:
            row_id = store.store_summary(
                summary=summary_text,
                session_id="health_biometrics",
                metadata=metadata,
            )
        logger.info(
            "Anomalia cardíaca injetada na Memória Episódica (id=%d): %s",
            row_id,
            summary_text,
        )
        return row_id
    except Exception as exc:
        logger.error("Falha ao registrar anomalia na memória episódica: %s", exc)
        return -1
