"""Armazenamento Local e Cifrado/Restrito de Telemetria de Saúde (health.db).

Em conformidade estrita com as REGRAS ANTI-MERDA de Privacidade Absoluta (Local-First):
- Dados de saúde (BPM, HRV, atividade) são tratados como PII/PHI críticos.
- Armazenamento em SQLite local com permissões estritas de arquivo (0o600) e pasta (0o700).
- Proibição absoluta de envio de métricas biométricas puras para APIs de LLM na nuvem.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import logging
import os
from pathlib import Path
import sqlite3
import stat
import time
from typing import Any, Generator

from .schema import HealthReading

logger = logging.getLogger("mark.telemetry.storage")

DEFAULT_HEALTH_DB = Path.home() / ".local/state/mark/health.db"


def get_default_health_db_path() -> Path:
    """Recupera o caminho padrão configurado para o banco de dados de saúde."""
    try:
        from ..config import load_config
        cfg = load_config()
        path_str = cfg.get("telemetry", {}).get("health_db_path") or cfg.get("health_db_path")
        if path_str:
            return Path(path_str).expanduser()
    except Exception:
        pass
    return DEFAULT_HEALTH_DB


class HealthTelemetryStore:
    """Gerenciador SQLite seguro e otimizado para séries temporais biométricas."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.path = Path(db_path).expanduser() if db_path else get_default_health_db_path()
        self._ensure_secure_storage()
        self._init_db()

    def _ensure_secure_storage(self) -> None:
        """Garante permissões 0700 no diretório e 0600 no arquivo de banco de dados."""
        parent = self.path.parent
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            if parent.stat().st_uid == os.getuid():
                parent.chmod(0o700)
        except OSError:
            pass

        if not self.path.exists():
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            try:
                fd = os.open(self.path, flags, 0o600)
                os.close(fd)
            except FileExistsError:
                pass

        try:
            if self.path.exists() and self.path.stat().st_uid == os.getuid():
                self.path.chmod(0o600)
        except OSError:
            pass

    @contextmanager
    def _db(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._db() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS health_readings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    heart_rate_bpm INTEGER NOT NULL,
                    is_active INTEGER NOT NULL,
                    confidence REAL NOT NULL,
                    device_id TEXT,
                    hrv_ms REAL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at INTEGER NOT NULL
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_health_ts ON health_readings(timestamp DESC)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_health_source ON health_readings(source)")

            db.execute("""
                CREATE TABLE IF NOT EXISTS health_anomalies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp INTEGER NOT NULL,
                    anomaly_type TEXT NOT NULL,
                    heart_rate_bpm INTEGER NOT NULL,
                    consecutive_count INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_anomalies_ts ON health_anomalies(timestamp DESC)")

    def save_reading(self, reading: HealthReading) -> int:
        """Persiste uma leitura biométrica no banco de dados local."""
        now = int(time.time())
        meta_json = json.dumps(dict(reading.metadata), ensure_ascii=False)
        with self._db() as db:
            cursor = db.execute(
                """
                INSERT INTO health_readings (
                    timestamp, source, heart_rate_bpm, is_active,
                    confidence, device_id, hrv_ms, metadata, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(reading.timestamp),
                    reading.source,
                    int(reading.heart_rate_bpm),
                    1 if reading.is_active else 0,
                    float(reading.confidence),
                    reading.device_id,
                    float(reading.hrv_ms) if reading.hrv_ms is not None else None,
                    meta_json,
                    now,
                ),
            )
            return cursor.lastrowid

    def save_readings(self, readings: list[HealthReading]) -> int:
        """Persiste um lote de leituras atomicamente."""
        if not readings:
            return 0
        now = int(time.time())
        rows = [
            (
                int(r.timestamp),
                r.source,
                int(r.heart_rate_bpm),
                1 if r.is_active else 0,
                float(r.confidence),
                r.device_id,
                float(r.hrv_ms) if r.hrv_ms is not None else None,
                json.dumps(dict(r.metadata), ensure_ascii=False),
                now,
            )
            for r in readings
        ]
        with self._db() as db:
            db.executemany(
                """
                INSERT INTO health_readings (
                    timestamp, source, heart_rate_bpm, is_active,
                    confidence, device_id, hrv_ms, metadata, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            return len(rows)

    def save_anomaly(
        self,
        anomaly_type: str,
        heart_rate_bpm: int,
        consecutive_count: int,
        source: str,
        summary: str,
        timestamp: int | None = None,
    ) -> int:
        """Persiste o registro de anomalia cardíaca detectada."""
        ts = int(time.time()) if timestamp is None else int(timestamp)
        now = int(time.time())
        with self._db() as db:
            cursor = db.execute(
                """
                INSERT INTO health_anomalies (
                    timestamp, anomaly_type, heart_rate_bpm,
                    consecutive_count, source, summary, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (ts, anomaly_type, int(heart_rate_bpm), int(consecutive_count), source, summary, now),
            )
            return cursor.lastrowid

    def get_readings_count(self) -> int:
        with self._db() as db:
            row = db.execute("SELECT COUNT(*) FROM health_readings").fetchone()
            return row[0] if row else 0

    def get_anomalies_count(self) -> int:
        with self._db() as db:
            row = db.execute("SELECT COUNT(*) FROM health_anomalies").fetchone()
            return row[0] if row else 0

    def get_recent_readings(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute(
                """
                SELECT id, timestamp, source, heart_rate_bpm, is_active,
                       confidence, device_id, hrv_ms, metadata, created_at
                FROM health_readings ORDER BY timestamp DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [
                {
                    "id": r[0],
                    "timestamp": r[1],
                    "source": r[2],
                    "heart_rate_bpm": r[3],
                    "is_active": bool(r[4]),
                    "confidence": r[5],
                    "device_id": r[6],
                    "hrv_ms": r[7],
                    "metadata": json.loads(r[8]),
                    "created_at": r[9],
                }
                for r in rows
            ]

    def get_recent_anomalies(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute(
                """
                SELECT id, timestamp, anomaly_type, heart_rate_bpm,
                       consecutive_count, source, summary, created_at
                FROM health_anomalies ORDER BY timestamp DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [
                {
                    "id": r[0],
                    "timestamp": r[1],
                    "anomaly_type": r[2],
                    "heart_rate_bpm": r[3],
                    "consecutive_count": r[4],
                    "source": r[5],
                    "summary": r[6],
                    "created_at": r[7],
                }
                for r in rows
            ]
