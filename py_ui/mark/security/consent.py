"""Cofre seguro e gerenciador de consentimento para APIs externas do MARK.

Implementa conformidade de segurança e controle de consentimento Human-in-the-Loop:
1. Zero Tokens em Plaintext: armazena permissões e tokens permanentemente
   utilizando criptografia autenticada AES-256-GCM via Rust Core (mark_core)
   e integração com Keyring do sistema operacional, com permissões POSIX estritas (0600).
2. Fricção Mínima, Segurança Máxima: mantém cache em memória durante a sessão
   e persistência segura para decisões permanentes, evitando pop-ups redundantes.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
import secrets
import stat
import threading
import time
from typing import Any, Callable

try:
    import mark_core
except ImportError:
    mark_core = None

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    AESGCM = None

try:
    import keyring
except ImportError:
    keyring = None

from ..cognition.storage import (
    StorageSecurityError,
    atomic_create_temp_file,
    ensure_private_dir,
    verify_private_path,
)

logger = logging.getLogger(__name__)

CONSENT_VAULT_AAD = b"MARK-API-CONSENT-V1"
DEFAULT_VAULT_DIR = Path.home() / ".local/state/mark/vault"
DEFAULT_CONSENT_VAULT_FILE = DEFAULT_VAULT_DIR / "api_consent.enc"
DEFAULT_CONSENT_KEY_FILE = DEFAULT_VAULT_DIR / ".consent_master.key"
KEYRING_SERVICE_NAME = "mark_api_consent"


class _HybridConsentMethod:
    """Permite que um método funcione transparentemente tanto chamado na classe
    quanto na instância de APIConsentManager.
    """

    def __init__(self, func: Callable) -> None:
        self.func = func

    def __get__(self, instance: Any, owner: type) -> Callable:
        if instance is None:
            def class_call(*args: Any, **kwargs: Any) -> Any:
                return self.func(owner.get_instance(), *args, **kwargs)
            return class_call

        def instance_call(*args: Any, **kwargs: Any) -> Any:
            return self.func(instance, *args, **kwargs)
        return instance_call


class APIConsentManager:
    """Gerenciador de autorização e cache seguro de consentimento para APIs externas."""

    _global_instance: APIConsentManager | None = None
    _global_lock = threading.Lock()

    def __init__(
        self,
        vault_file: Path | str | None = None,
        master_key_file: Path | str | None = None,
        master_key_bytes: bytes | None = None,
        use_keyring: bool = True,
    ) -> None:
        self.vault_file = (
            Path(vault_file)
            if vault_file is not None
            else Path(os.environ.get("MARK_API_CONSENT_VAULT", DEFAULT_CONSENT_VAULT_FILE))
        )
        self.master_key_file = (
            Path(master_key_file)
            if master_key_file is not None
            else Path(os.environ.get("MARK_API_CONSENT_MASTER_KEY", DEFAULT_CONSENT_KEY_FILE))
        )
        self._master_key_override = master_key_bytes
        self.use_keyring = use_keyring and (keyring is not None)
        self._lock = threading.RLock()
        self._session_permissions: dict[str, dict[str, Any]] = {}
        self._permanent_loaded = False

    @classmethod
    def get_instance(cls) -> APIConsentManager:
        with cls._global_lock:
            if cls._global_instance is None:
                cls._global_instance = cls()
            return cls._global_instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reinicia a instância global (útil para testes isolados)."""
        with cls._global_lock:
            cls._global_instance = None

    def _get_or_create_master_key(self) -> bytes:
        if self._master_key_override:
            return self._master_key_override

        env_key = os.environ.get("MARK_CONSENT_MASTER_KEY_HEX")
        if env_key:
            return bytes.fromhex(env_key.strip())

        ensure_private_dir(self.master_key_file.parent)
        if self.master_key_file.exists():
            verify_private_path(self.master_key_file, is_dir=False)
            raw = self.master_key_file.read_bytes()
            if len(raw) == 32:
                return raw

        new_key = secrets.token_bytes(32)
        tmp = atomic_create_temp_file(dir_path=self.master_key_file.parent, prefix=".consent_key_")
        tmp.write_bytes(new_key)
        tmp.chmod(0o600)
        os.replace(tmp, self.master_key_file)
        self.master_key_file.chmod(0o600)
        return new_key

    def _read_vault(self) -> dict[str, Any]:
        if not self.vault_file.exists():
            return {}

        verify_private_path(self.vault_file, is_dir=False)
        raw_payload = self.vault_file.read_bytes()
        if len(raw_payload) < 28:
            return {}

        master_key = self._get_or_create_master_key()
        payload_str = raw_payload.decode("utf-8", errors="replace").strip()

        if mark_core is not None:
            try:
                decrypted = mark_core.decrypt_aes_256_gcm(master_key, payload_str, CONSENT_VAULT_AAD)
                data = json.loads(decrypted.decode("utf-8"))
                if isinstance(data, dict):
                    return data
            except Exception as exc:
                logger.warning("Falha na decifragem do cofre via mark_core: %s", exc)

        if AESGCM is not None:
            try:
                payload_dict = json.loads(payload_str)
                nonce = base64.b64decode(payload_dict["nonce"])
                ciphertext = base64.b64decode(payload_dict["ciphertext"])
                aesgcm = AESGCM(master_key)
                decrypted = aesgcm.decrypt(nonce, ciphertext, CONSENT_VAULT_AAD)
                data = json.loads(decrypted.decode("utf-8"))
                if isinstance(data, dict):
                    return data
            except Exception as exc:
                logger.warning("Falha na decifragem do cofre via AESGCM: %s", exc)

        return {}

    def _write_vault(self, data: dict[str, Any]) -> None:
        ensure_private_dir(self.vault_file.parent)
        master_key = self._get_or_create_master_key()
        plaintext = json.dumps(data, ensure_ascii=False).encode("utf-8")

        if mark_core is not None:
            payload_str = mark_core.encrypt_aes_256_gcm(master_key, plaintext, CONSENT_VAULT_AAD)
            raw = payload_str.encode("utf-8")
        elif AESGCM is not None:
            nonce = os.urandom(12)
            aesgcm = AESGCM(master_key)
            ciphertext = aesgcm.encrypt(nonce, plaintext, CONSENT_VAULT_AAD)
            payload_dict = {
                "version": 1,
                "cipher": "AES-256-GCM",
                "nonce": base64.b64encode(nonce).decode("ascii"),
                "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
            }
            raw = json.dumps(payload_dict).encode("utf-8")
        else:
            raise StorageSecurityError("Nenhum backend de criptografia (mark_core ou AESGCM) disponível.")

        tmp = atomic_create_temp_file(dir_path=self.vault_file.parent, prefix=".consent_tmp_")
        tmp.write_bytes(raw)
        tmp.chmod(0o600)
        os.replace(tmp, self.vault_file)
        self.vault_file.chmod(0o600)
        verify_private_path(self.vault_file, is_dir=False)

    def _load_permanent_cache(self) -> None:
        if self._permanent_loaded:
            return
        vault_data = self._read_vault()
        permissions = vault_data.get("permissions", {})
        if isinstance(permissions, dict):
            for k, v in permissions.items():
                if isinstance(v, dict) and v.get("granted"):
                    self._session_permissions.setdefault(k.strip().lower(), v)
        self._permanent_loaded = True

    def _grant_permission(
        self,
        api_name: str,
        token: Any = True,
        duration: str = "session",
    ) -> None:
        norm_name = str(api_name).strip().lower()
        if not norm_name:
            raise ValueError("Nome da API não pode ser vazio.")

        is_permanent = "permanent" in str(duration).lower()
        record = {
            "api_name": norm_name,
            "token": token,
            "duration": "permanent" if is_permanent else "session",
            "granted": True,
            "timestamp": time.time(),
        }

        with self._lock:
            self._session_permissions[norm_name] = record

            if is_permanent:
                vault_data = self._read_vault()
                perms = vault_data.setdefault("permissions", {})
                perms[norm_name] = record
                self._write_vault(vault_data)

                if self.use_keyring and keyring is not None:
                    try:
                        keyring.set_password(KEYRING_SERVICE_NAME, norm_name, json.dumps(record))
                    except Exception as exc:
                        logger.debug("Keyring não disponível para persistência: %s", exc)

    def _has_permission(self, api_name: str) -> bool:
        norm_name = str(api_name).strip().lower()
        if not norm_name:
            return False

        with self._lock:
            # 1. Verifica cache de sessão
            if norm_name in self._session_permissions:
                entry = self._session_permissions[norm_name]
                if entry.get("granted") is True:
                    return True

            # 2. Carrega e verifica o cofre permanente
            vault_data = self._read_vault()
            perms = vault_data.get("permissions", {})
            if isinstance(perms, dict) and norm_name in perms:
                entry = perms[norm_name]
                if isinstance(entry, dict) and entry.get("granted") is True:
                    self._session_permissions[norm_name] = entry
                    return True

            # 3. Fallback no Keyring do SO se habilitado
            if self.use_keyring and keyring is not None:
                try:
                    stored = keyring.get_password(KEYRING_SERVICE_NAME, norm_name)
                    if stored:
                        entry = json.loads(stored)
                        if isinstance(entry, dict) and entry.get("granted") is True:
                            self._session_permissions[norm_name] = entry
                            return True
                except Exception as exc:
                    logger.debug("Consulta ao keyring falhou: %s", exc)

            return False

    def _get_permission(self, api_name: str) -> Any | None:
        norm_name = str(api_name).strip().lower()
        with self._lock:
            if self._has_permission(norm_name):
                return self._session_permissions.get(norm_name, {}).get("token")
            return None

    def _revoke_permission(self, api_name: str) -> bool:
        norm_name = str(api_name).strip().lower()
        if not norm_name:
            return False

        with self._lock:
            had_perm = False
            if norm_name in self._session_permissions:
                del self._session_permissions[norm_name]
                had_perm = True

            vault_data = self._read_vault()
            perms = vault_data.get("permissions", {})
            if isinstance(perms, dict) and norm_name in perms:
                del perms[norm_name]
                self._write_vault(vault_data)
                had_perm = True

            if self.use_keyring and keyring is not None:
                try:
                    keyring.delete_password(KEYRING_SERVICE_NAME, norm_name)
                except Exception:
                    pass

            return had_perm

    def _revoke_all_permissions(self) -> None:
        with self._lock:
            cached_keys = list(self._session_permissions.keys())
            self._session_permissions.clear()

            vault_data = self._read_vault()
            vault_perms = list(vault_data.get("permissions", {}).keys())
            vault_data["permissions"] = {}
            self._write_vault(vault_data)

            if self.use_keyring and keyring is not None:
                for k in set(cached_keys + vault_perms):
                    try:
                        keyring.delete_password(KEYRING_SERVICE_NAME, k)
                    except Exception:
                        pass

    def _list_permissions(self) -> list[dict[str, Any]]:
        with self._lock:
            self._load_permanent_cache()
            result: list[dict[str, Any]] = []
            for k, v in self._session_permissions.items():
                if v.get("granted"):
                    result.append({
                        "api_name": k,
                        "duration": v.get("duration", "session"),
                        "timestamp": v.get("timestamp", 0.0),
                    })
            return result

    # Métodos híbridos que funcionam tanto na classe APIConsentManager quanto em instâncias
    grant_permission = _HybridConsentMethod(_grant_permission)
    has_permission = _HybridConsentMethod(_has_permission)
    get_permission = _HybridConsentMethod(_get_permission)
    revoke_permission = _HybridConsentMethod(_revoke_permission)
    revoke_all_permissions = _HybridConsentMethod(_revoke_all_permissions)
    clear_all = _HybridConsentMethod(_revoke_all_permissions)
    list_permissions = _HybridConsentMethod(_list_permissions)


def get_api_consent_manager() -> APIConsentManager:
    """Retorna o gerenciador singleton de consentimento de APIs externas."""
    return APIConsentManager.get_instance()
