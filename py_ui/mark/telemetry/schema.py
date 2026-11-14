"""Schema Universal de Telemetria e Leitura Biométrica (HealthReading).

Padroniza dados de frequência cardíaca, movimentação e confiança provenientes
de diferentes plataformas de smartwatch e sensores corporais:
- Wear OS / Google Health Connect
- Zepp OS / Amazfit / Zepp Life
- MARK Wear (nativo via Bluetooth / Mark Link)
- Apple Health / Garmin / Sensores genéricos BLE PPG
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import time
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class HealthReading:
    """Leitura biométrica universal de smartwatch e sensores de saúde."""

    timestamp: int
    source: str
    heart_rate_bpm: int
    is_active: bool
    confidence: float
    device_id: str | None = None
    hrv_ms: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """Validações fisiológicas e integridade estrutural."""
        if not isinstance(self.timestamp, (int, float)) or self.timestamp <= 0:
            raise ValueError(f"Timestamp inválido: {self.timestamp}")

        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("Fonte (source) da telemetria biométrica não pode ser vazia")

        if not isinstance(self.heart_rate_bpm, (int, float)) or isinstance(self.heart_rate_bpm, bool):
            raise TypeError("heart_rate_bpm precisa ser um número inteiro")

        bpm = int(self.heart_rate_bpm)
        if not (20 <= bpm <= 300):
            raise ValueError(f"Frequência cardíaca fora da faixa fisiológica humana plausível: {bpm} BPM")

        if not isinstance(self.is_active, bool):
            raise TypeError("is_active precisa ser booleano")

        if not isinstance(self.confidence, (int, float)) or isinstance(self.confidence, bool):
            raise TypeError("confidence precisa ser float")

        conf = float(self.confidence)
        if not math.isfinite(conf) or not (0.0 <= conf <= 1.0):
            raise ValueError(f"Confiança do sensor deve estar entre 0.0 e 1.0 (recebido: {conf})")

        if self.hrv_ms is not None:
            if not isinstance(self.hrv_ms, (int, float)) or self.hrv_ms < 0:
                raise ValueError(f"HRV inválido: {self.hrv_ms}")

    def to_dict(self) -> dict[str, Any]:
        """Converte a leitura em dicionário serializável."""
        data: dict[str, Any] = {
            "timestamp": int(self.timestamp),
            "source": self.source.strip().lower(),
            "heart_rate_bpm": int(self.heart_rate_bpm),
            "is_active": self.is_active,
            "confidence": round(float(self.confidence), 4),
        }
        if self.device_id:
            data["device_id"] = self.device_id
        if self.hrv_ms is not None:
            data["hrv_ms"] = round(float(self.hrv_ms), 2)
        if self.metadata:
            data["metadata"] = dict(self.metadata)
        return data

    def to_json(self) -> str:
        """Serializa em JSON canônico sem espaços redundantes."""
        return json.dumps(self.to_dict(), separators=(",", ":"), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> HealthReading:
        """Constrói uma instância a partir de um dicionário, validando todos os campos."""
        if not isinstance(data, Mapping):
            raise TypeError("Os dados da leitura biométrica devem ser um dicionário/mapeamento")

        # Mapeia chaves com fallback para flexibilidade com múltiplos sensores
        ts = data.get("timestamp") or data.get("at") or data.get("time") or int(time.time())
        source = str(data.get("source") or data.get("origin") or data.get("provider") or "smartwatch").strip().lower()

        raw_bpm = data.get("heart_rate_bpm")
        if raw_bpm is None:
            raw_bpm = data.get("heart_rate") or data.get("bpm") or data.get("rate")
        if raw_bpm is None:
            raise ValueError("Campo de frequência cardíaca (heart_rate_bpm/heart_rate/bpm) obrigatório")

        # Indicador de atividade / exercício
        raw_active = data.get("is_active")
        if raw_active is None:
            raw_active = data.get("active")
        if raw_active is None:
            raw_active = data.get("in_exercise") or data.get("exercising")
        if raw_active is None:
            raw_active = False

        # Confiança do sinal PPG do sensor óptico
        raw_conf = data.get("confidence")
        if raw_conf is None:
            raw_conf = data.get("accuracy")
        if raw_conf is None:
            raw_conf = 1.0  # Confiança padrão caso sensor não reporte índice de erro

        device_id = data.get("device_id") or data.get("device")
        hrv_ms = data.get("hrv_ms") or data.get("hrv")

        meta = data.get("metadata") or {}

        return cls(
            timestamp=int(ts),
            source=source,
            heart_rate_bpm=int(raw_bpm),
            is_active=bool(raw_active),
            confidence=float(raw_conf),
            device_id=str(device_id) if device_id else None,
            hrv_ms=float(hrv_ms) if hrv_ms is not None else None,
            metadata=meta if isinstance(meta, Mapping) else {},
        )

    @classmethod
    def from_json(cls, raw_json: str | bytes) -> HealthReading:
        """Desserializa uma leitura a partir de string ou bytes JSON."""
        data = json.loads(raw_json)
        return cls.from_dict(data)


def normalize_smartwatch_reading(raw: Mapping[str, Any] | HealthReading, default_source: str = "smartwatch") -> HealthReading:
    """Normaliza leituras provenientes de Zepp, Wear OS, Mark-Wear, Health Connect ou Garmin."""
    if isinstance(raw, HealthReading):
        return raw

    if not isinstance(raw, Mapping):
        raise TypeError(f"Payload inválido para leitura biométrica: {type(raw)}")

    data = dict(raw)
    if "source" not in data or not data["source"]:
        data["source"] = default_source

    return HealthReading.from_dict(data)


def parse_health_batch(payload: Any, default_source: str = "smartwatch") -> list[HealthReading]:
    """Interpreta um batch de leituras recebidas via HTTP/Mark Link.
    
    Aceita:
    - Um dicionário único com uma leitura.
    - Uma lista de dicionários.
    - Um dicionário com chave "readings" ou "events".
    """
    if isinstance(payload, str):
        payload = json.loads(payload)

    readings: list[HealthReading] = []

    if isinstance(payload, Mapping):
        if "readings" in payload and isinstance(payload["readings"], list):
            items = payload["readings"]
        elif "events" in payload and isinstance(payload["events"], list):
            items = payload["events"]
        else:
            items = [payload]
    elif isinstance(payload, list):
        items = payload
    else:
        raise ValueError("Formato de batch biométrico não suportado")

    for item in items:
        if isinstance(item, (Mapping, HealthReading)):
            readings.append(normalize_smartwatch_reading(item, default_source=default_source))

    return readings
