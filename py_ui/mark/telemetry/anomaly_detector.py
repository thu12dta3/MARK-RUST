"""Motor de Detecção de Anomalias Cardíacas em Repouso do MARK.

Executa como Worker em background (não bloqueante) com isolamento estrito de threads,
aplicando heurística cardiológica preventiva com filtro de ruído óptico PPG:
- Taquicardia em Repouso: is_active == False E heart_rate_bpm > 100 por >= 3 leituras consecutivas.
- Bradicardia em Repouso: is_active == False E heart_rate_bpm < 40 por >= 3 leituras consecutivas.
- Filtro de Ruído: Ignora leituras isoladas com confidence < 0.6.
- Proteção de Falso Positivo: Atividade física (is_active == True) reseta contadores imediatamente.
- Persistência Local-First: Salva séries temporais em health.db localmente restrito.
"""

from __future__ import annotations

import logging
from pathlib import Path
import queue
import threading
import time
from typing import Any, Callable

from .events import (
    CardiacAnomaly,
    TelemetryEventBus,
    dispatch_system_notification,
    inject_into_episodic_memory,
    telemetry_events,
)
from .schema import HealthReading
from .storage import HealthTelemetryStore

logger = logging.getLogger("mark.telemetry.detector")


class AnomalyDetector:
    """Motor de detecção de anomalias biométricas e worker assíncrono em background."""

    def __init__(
        self,
        store: HealthTelemetryStore | None = None,
        db_path: Path | str | None = None,
        event_bus: TelemetryEventBus | None = None,
        episodic_store: Any | None = None,
        resting_tachycardia_bpm: int = 100,
        bradycardia_bpm: int = 40,
        consecutive_threshold: int = 3,
        min_confidence: float = 0.6,
        auto_notify: bool = True,
        auto_record_episodic: bool = True,
        start_worker: bool = True,
    ) -> None:
        self.store = store or HealthTelemetryStore(db_path=db_path)
        self.event_bus = event_bus or telemetry_events
        self.episodic_store = episodic_store

        self.resting_tachycardia_bpm = resting_tachycardia_bpm
        self.bradycardia_bpm = bradycardia_bpm
        self.consecutive_threshold = consecutive_threshold
        self.min_confidence = min_confidence

        self.auto_notify = auto_notify
        self.auto_record_episodic = auto_record_episodic

        self._lock = threading.RLock()
        self._consecutive_tachycardia = 0
        self._consecutive_bradycardia = 0
        self._alerts_triggered: list[CardiacAnomaly] = []

        # Fila e Worker de isolamento em background
        self._queue: queue.Queue[HealthReading | None] = queue.Queue(maxsize=10000)
        self._worker_thread: threading.Thread | None = None
        self._running = False

        if start_worker:
            self.start()

    def start(self) -> None:
        """Inicia a thread do worker em background caso não esteja ativa."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._worker_thread = threading.Thread(
                target=self._worker_loop,
                name="mark-anomaly-detector",
                daemon=True,
            )
            self._worker_thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        """Para a thread do worker de forma graciosa."""
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._queue.put(None)
            if self._worker_thread and self._worker_thread.is_alive():
                self._worker_thread.join(timeout=timeout)
                self._worker_thread = None

    def submit(self, reading: HealthReading) -> None:
        """Envia leitura para o worker assíncrono em background sem bloquear."""
        try:
            self._queue.put_nowait(reading)
        except queue.Full:
            logger.warning("Fila de telemetria cheia; descartando leitura antiga para evitar OOM")
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            self._queue.put_nowait(reading)

    def flush(self, timeout: float = 2.0) -> None:
        """Aguarda o processamento de todas as leituras pendentes na fila."""
        start = time.time()
        while not self._queue.empty() and time.time() - start < timeout:
            time.sleep(0.01)

    def _worker_loop(self) -> None:
        """Loop de execução isolado em background."""
        while self._running:
            try:
                reading = self._queue.get(timeout=0.2)
                if reading is None:
                    break
                self.process_reading(reading)
                self._queue.task_done()
            except queue.Empty:
                continue
            except Exception as exc:
                logger.error("Erro no worker de telemetria biométrica: %s", exc)

    def process_reading(self, reading: HealthReading) -> CardiacAnomaly | None:
        """Executa a análise heurística de forma thread-safe."""
        # 1. Persistência local no banco time-series
        try:
            self.store.save_reading(reading)
        except Exception as exc:
            logger.warning("Falha ao salvar leitura biométrica no SQLite: %s", exc)

        with self._lock:
            # 2. Filtro de Ruído: ignora artefatos de contato óptico sem alterar estado
            if reading.confidence < self.min_confidence:
                logger.debug(
                    "Leitura biométrica ignorada pelo filtro de ruído (confiança %.2f < %.2f)",
                    reading.confidence,
                    self.min_confidence,
                )
                return None

            # 3. Exercício / Atividade Física: reseta contadores de repouso imediatamente
            if reading.is_active:
                self._consecutive_tachycardia = 0
                self._consecutive_bradycardia = 0
                logger.debug(
                    "Usuário em atividade física (%d BPM, %s). Contadores de repouso resetados.",
                    reading.heart_rate_bpm,
                    reading.source,
                )
                return None

            # 4. Estado de Repouso (is_active == False): Avaliação Heurística
            bpm = reading.heart_rate_bpm

            # Caso A: Taquicardia em Repouso (> 100 BPM)
            if bpm > self.resting_tachycardia_bpm:
                self._consecutive_tachycardia += 1
                self._consecutive_bradycardia = 0
                logger.info(
                    "Leitura elevada em repouso: %d BPM (consecutiva %d/%d)",
                    bpm,
                    self._consecutive_tachycardia,
                    self.consecutive_threshold,
                )

                if self._consecutive_tachycardia >= self.consecutive_threshold:
                    anomaly = CardiacAnomaly(
                        anomaly_type="resting_tachycardia",
                        heart_rate_bpm=bpm,
                        consecutive_count=self._consecutive_tachycardia,
                        source=reading.source,
                        timestamp=reading.timestamp,
                        is_active=False,
                    )
                    self._trigger_anomaly_actions(anomaly)
                    return anomaly

            # Caso B: Bradicardia em Repouso (< 40 BPM)
            elif bpm < self.bradycardia_bpm:
                self._consecutive_bradycardia += 1
                self._consecutive_tachycardia = 0
                logger.info(
                    "Leitura baixa em repouso: %d BPM (consecutiva %d/%d)",
                    bpm,
                    self._consecutive_bradycardia,
                    self.consecutive_threshold,
                )

                if self._consecutive_bradycardia >= self.consecutive_threshold:
                    anomaly = CardiacAnomaly(
                        anomaly_type="bradycardia",
                        heart_rate_bpm=bpm,
                        consecutive_count=self._consecutive_bradycardia,
                        source=reading.source,
                        timestamp=reading.timestamp,
                        is_active=False,
                    )
                    self._trigger_anomaly_actions(anomaly)
                    return anomaly

            # Caso C: Faixa Fisiológica Normal em Repouso
            else:
                self._consecutive_tachycardia = 0
                self._consecutive_bradycardia = 0

            return None

    def _trigger_anomaly_actions(self, anomaly: CardiacAnomaly) -> None:
        """Executa o roteamento de ações quando uma anomalia é confirmada."""
        self._alerts_triggered.append(anomaly)

        # 1. Salva anomalia no SQLite local
        try:
            self.store.save_anomaly(
                anomaly_type=anomaly.anomaly_type,
                heart_rate_bpm=anomaly.heart_rate_bpm,
                consecutive_count=anomaly.consecutive_count,
                source=anomaly.source,
                summary=anomaly.formatted_summary(),
                timestamp=anomaly.timestamp,
            )
        except Exception as exc:
            logger.warning("Falha ao salvar anomalia no banco local: %s", exc)

        # 2. Publica no EventBus
        try:
            self.event_bus.publish(anomaly)
        except Exception as exc:
            logger.warning("Falha ao publicar anomalia no EventBus: %s", exc)

        # 3. Ação 1 (Imediata): Notificação no Sistema Desktop/Mobile
        if self.auto_notify:
            dispatch_system_notification(
                title="MARK - Alerta de Saúde",
                message="MARK: Anomalia cardíaca detetada em repouso. Estás bem?",
            )

        # 4. Ação 2 (Cognitiva): Injeção na Memória Episódica
        if self.auto_record_episodic:
            inject_into_episodic_memory(anomaly, episodic_store=self.episodic_store)

    @property
    def alerts_triggered(self) -> list[CardiacAnomaly]:
        with self._lock:
            return list(self._alerts_triggered)

    def reset_state(self) -> None:
        """Reseta contadores de estado em memória (útil para testes isolados)."""
        with self._lock:
            self._consecutive_tachycardia = 0
            self._consecutive_bradycardia = 0
            self._alerts_triggered.clear()


_detector_instance: AnomalyDetector | None = None
_detector_lock = threading.Lock()


def get_anomaly_detector() -> AnomalyDetector:
    """Retorna o singleton global do detector de anomalias."""
    global _detector_instance
    with _detector_lock:
        if _detector_instance is None:
            _detector_instance = AnomalyDetector()
        return _detector_instance
