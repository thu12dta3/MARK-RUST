"""Máquina de Estados de Sincronização, Anti-Replay e Autorização do MCTX.

Garante a separação estrita entre validação criptográfica (autenticidade)
e autorização (permissão ativa), previne ataques de replay/rollback através
de números de sequência monotônicos e tombstones indeléveis de revogação.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import json
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519

from .manifest import MCTXError, MCTXManifest, MCTXSecurityError, SignatureSection


class MCTXSyncError(MCTXError):
    """Erro base para operações de sincronização do MCTX."""


class MCTXAuthorizationError(MCTXSyncError):
    """Falha de autorização: dispositivo não autorizado, pendente ou revogado."""


class MCTXReplayAttackError(MCTXSyncError):
    """Ataque de replay, reutilização de nonce ou detecção de rollback de sequência."""


class DeviceStatus(str, Enum):
    PENDING = "pending"
    AUTHORIZED = "authorized"
    ACTIVE = "authorized"
    RESTRICTED = "restricted"
    REVOKED = "revoked"


@dataclass
class DeviceSyncRecord:
    device_id: str
    public_key_hex: str
    algorithm: str
    status: DeviceStatus
    last_sequence: int
    authorized_scopes: set[str]
    enrolled_at: int
    revoked_at: int | None = None
    revocation_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "public_key_hex": self.public_key_hex,
            "algorithm": self.algorithm,
            "status": self.status.value,
            "last_sequence": self.last_sequence,
            "authorized_scopes": sorted(list(self.authorized_scopes)),
            "enrolled_at": self.enrolled_at,
            "revoked_at": self.revoked_at,
            "revocation_reason": self.revocation_reason,
        }


def _serialize_public_key_to_hex(public_key: Any) -> tuple[str, str]:
    """Serializa uma chave pública Ed25519 ou ECDSA P-256 para formato hexadecimal determinístico."""
    if isinstance(public_key, ed25519.Ed25519PublicKey):
        raw_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return raw_bytes.hex(), "ed25519"
    elif isinstance(public_key, ec.EllipticCurvePublicKey):
        raw_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.CompressedPoint,
        )
        return raw_bytes.hex(), "ecdsa-p256-sha256"
    elif isinstance(public_key, bytes):
        if len(public_key) == 32:
            return public_key.hex(), "ed25519"
        return public_key.hex(), "raw-bytes"
    elif isinstance(public_key, str):
        return public_key.strip().lower(), "ed25519"
    else:
        raise ValueError(f"Tipo de chave pública não suportado: {type(public_key)}")


class DeviceSyncRegistry:
    """Registro e Máquina de Estados de Dispositivos e Sincronização do MCTX."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = str(db_path) if db_path else ":memory:"
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout = 30000;")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS devices (
                    device_id TEXT PRIMARY KEY,
                    public_key_hex TEXT NOT NULL,
                    algorithm TEXT NOT NULL,
                    status TEXT NOT NULL,
                    last_sequence INTEGER NOT NULL DEFAULT 0,
                    authorized_scopes TEXT NOT NULL,
                    enrolled_at INTEGER NOT NULL,
                    revoked_at INTEGER,
                    revocation_reason TEXT
                );
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS revocation_tombstones (
                    device_id TEXT PRIMARY KEY,
                    revoked_at INTEGER NOT NULL,
                    revocation_reason TEXT NOT NULL
                );
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS session_challenges (
                    nonce TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    issued_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    used INTEGER NOT NULL DEFAULT 0
                );
                """
            )

    def register_device(
        self,
        device_id: str,
        public_key: Any,
        status: DeviceStatus = DeviceStatus.AUTHORIZED,
        authorized_scopes: set[str] | list[str] | None = None,
        algorithm: str | None = None,
    ) -> DeviceSyncRecord:
        """Registra um dispositivo no registro. Falha se o dispositivo possuir tombstone de revogação."""
        with self._lock:
            if self.is_revoked(device_id):
                raise MCTXAuthorizationError(
                    f"Dispositivo '{device_id}' possui tombstone de revogação indelével e não pode ser reativado."
                )

            pk_hex, detected_algo = _serialize_public_key_to_hex(public_key)
            algo = algorithm or detected_algo
            scopes = set(authorized_scopes) if authorized_scopes else {"mctx:sync"}
            now = int(time.time())

            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO devices (
                        device_id, public_key_hex, algorithm, status,
                        last_sequence, authorized_scopes, enrolled_at
                    ) VALUES (?, ?, ?, ?, 0, ?, ?)
                    ON CONFLICT(device_id) DO UPDATE SET
                        public_key_hex=excluded.public_key_hex,
                        algorithm=excluded.algorithm,
                        status=excluded.status,
                        authorized_scopes=excluded.authorized_scopes
                    WHERE device_id NOT IN (SELECT device_id FROM revocation_tombstones);
                    """,
                    (device_id, pk_hex, algo, status.value, json.dumps(sorted(list(scopes))), now),
                )

            rec = self.get_device(device_id)
            if rec is None:
                raise MCTXAuthorizationError(f"Falha ao registrar dispositivo '{device_id}'.")
            return rec

    def revoke_device(self, device_id: str, reason: str = "Revogação de segurança") -> None:
        """Revoga imutavelmente um dispositivo gravando um tombstone irreversível."""
        now = int(time.time())
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO revocation_tombstones (device_id, revoked_at, revocation_reason)
                    VALUES (?, ?, ?)
                    ON CONFLICT(device_id) DO NOTHING;
                    """,
                    (device_id, now, reason),
                )
                self._conn.execute(
                    """
                    UPDATE devices
                    SET status = ?, revoked_at = ?, revocation_reason = ?
                    WHERE device_id = ?;
                    """,
                    (DeviceStatus.REVOKED.value, now, reason, device_id),
                )

    def is_revoked(self, device_id: str) -> bool:
        """Verifica se o dispositivo possui registro na tabela de tombstones indeléveis."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT 1 FROM revocation_tombstones WHERE device_id = ?;", (device_id,)
            )
            return cur.fetchone() is not None

    def get_device(self, device_id: str) -> DeviceSyncRecord | None:
        """Retorna o registro do dispositivo ou None caso não exista."""
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT device_id, public_key_hex, algorithm, status, last_sequence,
                       authorized_scopes, enrolled_at, revoked_at, revocation_reason
                FROM devices WHERE device_id = ?;
                """,
                (device_id,),
            )
            row = cur.fetchone()
            if not row:
                return None

            tombstone_cur = self._conn.execute(
                "SELECT revoked_at, revocation_reason FROM revocation_tombstones WHERE device_id = ?;",
                (device_id,),
            )
            t_row = tombstone_cur.fetchone()
            if t_row:
                return DeviceSyncRecord(
                    device_id=row["device_id"],
                    public_key_hex=row["public_key_hex"],
                    algorithm=row["algorithm"],
                    status=DeviceStatus.REVOKED,
                    last_sequence=row["last_sequence"],
                    authorized_scopes=set(json.loads(row["authorized_scopes"])),
                    enrolled_at=row["enrolled_at"],
                    revoked_at=t_row["revoked_at"],
                    revocation_reason=t_row["revocation_reason"],
                )

            return DeviceSyncRecord(
                device_id=row["device_id"],
                public_key_hex=row["public_key_hex"],
                algorithm=row["algorithm"],
                status=DeviceStatus(row["status"]),
                last_sequence=row["last_sequence"],
                authorized_scopes=set(json.loads(row["authorized_scopes"])),
                enrolled_at=row["enrolled_at"],
                revoked_at=row["revoked_at"],
                revocation_reason=row["revocation_reason"],
            )

    def list_devices(self) -> list[DeviceSyncRecord]:
        """Lista todos os dispositivos registrados."""
        with self._lock:
            cur = self._conn.execute("SELECT device_id FROM devices;")
            records = []
            for r in cur.fetchall():
                rec = self.get_device(r["device_id"])
                if rec:
                    records.append(rec)
            return records

    def get_last_sequence(self, device_id: str) -> int:
        with self._lock:
            rec = self.get_device(device_id)
            return rec.last_sequence if rec else 0

    def update_sequence(self, device_id: str, new_sequence: int) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute(
                    "UPDATE devices SET last_sequence = ? WHERE device_id = ?;",
                    (new_sequence, device_id),
                )

    def check_and_advance_sequence(self, device_id: str, new_sequence: int) -> bool:
        """Valida e atualiza atomicamente a sequência se new_sequence for estritamente crescente.
        Retorna True em caso de sucesso; False se houver replay, rollback ou dispositivo não autorizado.
        """
        with self._lock:
            with self._conn:
                cur = self._conn.execute(
                    """
                    UPDATE devices
                    SET last_sequence = ?
                    WHERE device_id = ?
                      AND ? > last_sequence
                      AND status = ?
                      AND device_id NOT IN (SELECT device_id FROM revocation_tombstones);
                    """,
                    (new_sequence, device_id, new_sequence, DeviceStatus.AUTHORIZED.value),
                )
                return cur.rowcount > 0

    def issue_session_challenge(self, device_id: str, lifetime_sec: int | float = 120) -> str:
        """Gera um desafio nonce de sessão de uso único com janela de expiração estrita."""
        import secrets

        nonce = f"nonce-{secrets.token_hex(16)}"
        now = time.time()
        exp = now + float(lifetime_sec)
        with self._lock:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO session_challenges (nonce, device_id, issued_at, expires_at, used) VALUES (?, ?, ?, ?, 0);",
                    (nonce, device_id, now, exp),
                )
        return nonce

    def verify_session_challenge(self, nonce: str, device_id: str) -> bool:
        """Valida o nonce de sessão, garantindo que não esteja expirado e marcando como usado (single-use) atomicamente."""
        now = time.time()
        with self._lock:
            with self._conn:
                cur = self._conn.execute(
                    """
                    UPDATE session_challenges
                    SET used = 1
                    WHERE nonce = ? AND device_id = ? AND used = 0 AND ? < expires_at;
                    """,
                    (nonce, device_id, now),
                )
                return cur.rowcount > 0

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def authorize_manifest_sync(
    manifest: MCTXManifest,
    registry: DeviceSyncRegistry,
    session_nonce: str | None = None,
) -> bool:
    """Gate de autorização do MCTX.
    
    Verifica se o signatário possui status AUTHORIZED, escopo permitido e se o
    número de sequência é estritamente monotônico crescente (defesa contra replay/rollback).
    Garante serialização atômica contra requisições concorrentes.
    """
    sig = manifest.integrity.signature
    if sig is None:
        raise MCTXAuthorizationError("Manifesto não assinado: ausência de assinatura de dispositivo.")

    with registry._lock:
        rec = registry.get_device(sig.signer_id)
        if rec is None:
            raise MCTXAuthorizationError(f"Signatário '{sig.signer_id}' não cadastrado no registro de dispositivos.")

        if rec.status == DeviceStatus.REVOKED:
            raise MCTXAuthorizationError(
                f"Dispositivo '{sig.signer_id}' está REVOGADO (Motivo: {rec.revocation_reason})."
            )
        if rec.status == DeviceStatus.PENDING:
            raise MCTXAuthorizationError(f"Dispositivo '{sig.signer_id}' está PENDENTE de aprovação do proprietário.")
        if rec.status == DeviceStatus.RESTRICTED:
            raise MCTXAuthorizationError(f"Dispositivo '{sig.signer_id}' está RESTRITO para operações de sincronização.")
        if rec.status != DeviceStatus.AUTHORIZED and rec.status != DeviceStatus.ACTIVE:
            raise MCTXAuthorizationError(f"Status '{rec.status}' não permite sincronização do MCTX.")

        # Validação de escopo
        if sig.scope not in rec.authorized_scopes:
            raise MCTXAuthorizationError(
                f"Escopo solicitado '{sig.scope}' não está autorizado para o dispositivo '{sig.signer_id}'."
            )

        # Validação de desafio de sessão
        nonce_to_check = session_nonce or getattr(sig, "session_nonce", None)
        if nonce_to_check is not None:
            if not registry.verify_session_challenge(nonce_to_check, sig.signer_id):
                raise MCTXReplayAttackError(
                    f"Desafio de sessão (nonce '{nonce_to_check}') inválido, expirado ou reutilizado."
                )

        # Validação atômica de Anti-Replay e Monotonicidade de Sequência
        if not registry.check_and_advance_sequence(sig.signer_id, sig.sequence_number):
            if registry.is_revoked(sig.signer_id):
                raise MCTXAuthorizationError(f"Dispositivo '{sig.signer_id}' está REVOGADO.")
            rec_cur = registry.get_device(sig.signer_id)
            current_seq = rec_cur.last_sequence if rec_cur else rec.last_sequence
            raise MCTXReplayAttackError(
                f"Ataque de Replay ou Rollback detectado para '{sig.signer_id}': "
                f"sequência recebida {sig.sequence_number} <= última sequência confirmada {current_seq}."
            )

        return True



def verify_mctx_sync_gate(
    manifest: MCTXManifest,
    registry: DeviceSyncRegistry,
    trusted_root: str | Path,
    expected_scope: str = "sync:knowledge",
    session_nonce: str | None = None,
) -> bool:
    """Gate de liberação de sincronização do MARK Link MCTX.

    Valida as 4 camadas de alta garantia:
    1. Validação Criptográfica: Assinatura assimétrica válida contra chave pública do keyring.
    2. Autorização e Estado do Dispositivo: Status AUTHORIZED, escopo permitido, sem tombstones de revogação.
    3. Anti-Replay e Anti-Rollback: Sequência estritamente monotônica e validação de nonce de sessão.
    4. Integridade Canônica: Verificação do hash canônico do manifesto e estrutura das fontes.
    """
    from .manifest import compute_canonical_manifest_hash, verify_manifest_crypto

    # 1. Validação Criptográfica e Integridade do Manifesto
    expected_hash = compute_canonical_manifest_hash(manifest)
    if manifest.integrity.manifest_hash != f"sha256:{expected_hash}":
        raise MCTXSecurityError("Corrupção ou adulteração do hash canônico do manifesto detectada.")

    keyring: dict[str, str] = {}
    for dev in registry.list_devices():
        if dev.public_key_hex:
            keyring[dev.device_id] = dev.public_key_hex

    is_crypto_valid = verify_manifest_crypto(manifest, authorized_keys=keyring)
    if not is_crypto_valid:
        raise MCTXSecurityError("Falha na validação criptográfica da assinatura assimétrica.")

    # 2 & 3. Autorização de Estado e Monotonicidade Anti-Replay
    sig = manifest.integrity.signature
    if sig is None:
        raise MCTXAuthorizationError("Manifesto não assinado.")

    if sig.scope != expected_scope:
        raise MCTXAuthorizationError(f"Escopo do manifesto '{sig.scope}' diverge do esperado '{expected_scope}'.")

    return authorize_manifest_sync(manifest, registry, session_nonce=session_nonce)

