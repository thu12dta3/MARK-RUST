"""Interpretador Seguro e Especificação do Formato .mctx (Context Virtualizer).

Implementa parsing com esquema estrito, validação de tipos, sandbox contra path traversal,
computação canônica de hash de integridade e persistência atômica.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519

DEFAULT_MAX_MANIFEST_BYTES = 2 * 1024 * 1024  # 2 MiB
ALLOWED_FORMAT_VERSIONS = {"1.0"}
ALLOWED_SIGNATURE_ALGORITHMS = {"ed25519", "ecdsa-p256-sha256"}


class MCTXError(Exception):
    """Erro base para operações com manifesto MCTX."""


class MCTXSecurityError(MCTXError):
    """Violação de segurança, tentativa de traversal ou leitura fora de raiz confiável."""


class MCTXValidationError(MCTXError):
    """Falha de validação estrutural ou corrupção de dados no manifesto."""


def resolve_inside_root(target_path: str | Path, trusted_root: str | Path) -> Path:
    """Resolve um caminho garantindo que permaneça estritamente contido dentro da raiz confiável.

    Previne Directory Traversal, links simbólicos maliciosos e referências absolutas externas.
    """
    root = Path(trusted_root).resolve()
    target = Path(target_path)

    # Se for relativo, resolve em relação à raiz confiável
    if not target.is_absolute():
        resolved = (root / target).resolve()
    else:
        resolved = target.resolve()

    try:
        # Se resolved não estiver sob root, relative_to lançará ValueError
        resolved.relative_to(root)
    except ValueError:
        raise MCTXSecurityError(
            f"Tentativa de acesso fora da raiz autorizada: '{target_path}' não está contido em '{root}'"
        )

    return resolved


import math


def _escape_jcs_string(s: str) -> bytes:
    """Escapa strings estritamente de acordo com RFC 8785 §3.2.2.2."""
    out = ['"']
    for ch in s:
        cp = ord(ch)
        if cp == 0x22:  # "
            out.append(r'\"')
        elif cp == 0x5C:  # \
            out.append(r"\\")
        elif cp == 0x08:  # \b
            out.append(r"\b")
        elif cp == 0x0C:  # \f
            out.append(r"\f")
        elif cp == 0x0A:  # \n
            out.append(r"\n")
        elif cp == 0x0D:  # \r
            out.append(r"\r")
        elif cp == 0x09:  # \t
            out.append(r"\t")
        elif cp < 0x20:  # U+0000..U+001F
            out.append(fr"\u{cp:04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out).encode("utf-8")


def _format_jcs_number(val: int | float) -> bytes:
    """Formata números de acordo com as regras ECMAScript da RFC 8785 §3.2.2.3."""
    if isinstance(val, bool):
        raise TypeError("Booleanos não são permitidos em _format_jcs_number")
    if isinstance(val, int):
        return str(val).encode("utf-8")
    if math.isnan(val) or math.isinf(val):
        raise ValueError("NaN e Infinity são proibidos pela RFC 8785")
    if val == 0.0:
        return b"0"

    sign = "-" if math.copysign(1.0, val) < 0 else ""
    v = abs(val)
    r = repr(v)
    if "e" in r or "E" in r:
        mant_str, exp_str = r.split("e" if "e" in r else "E")
        exp = int(exp_str)
        if "." in mant_str:
            ip, fp = mant_str.split(".")
            fp = fp.rstrip("0")
            digits = ip + fp if fp else ip
        else:
            digits = mant_str
    elif "." in r:
        int_p, frac_p = r.split(".")
        frac_p = frac_p.rstrip("0")
        if int_p == "0":
            first_nz = 0
            while first_nz < len(frac_p) and frac_p[first_nz] == "0":
                first_nz += 1
            digits = frac_p[first_nz:]
            exp = -(first_nz + 1)
        else:
            digits = int_p + frac_p
            exp = len(int_p) - 1
    else:
        digits = r
        exp = len(r) - 1

    k = len(digits)
    n = exp + 1

    if k <= n <= 21:
        res = digits + ("0" * (n - k))
    elif 0 < n <= 21:
        res = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        res = "0." + ("0" * (-n)) + digits
    else:
        mant = digits[0] + ("." + digits[1:] if k > 1 else "")
        exp_val = n - 1
        exp_sign = "+" if exp_val >= 0 else "-"
        res = f"{mant}e{exp_sign}{abs(exp_val)}"

    return (sign + res).encode("utf-8")


def canonicalize_jcs(data: Any) -> bytes:
    """Serializa uma estrutura de dados de acordo com a RFC 8785 (JSON Canonicalization Scheme - JCS).

    Garante:
    - UTF-8 bruto para strings (sem escape \\uXXXX desnecessário)
    - Escape restrito a \", \\ e caracteres de controle U+0000..U+001F
    - Ordenação de chaves por unidades de código UTF-16
    - Formatação numérica ECMAScript (-0 -> 0, 1.0 -> 1)
    - Rejeição de NaN e Infinity
    - Proibição de espaços em branco arbitrários
    """
    if data is None:
        return b"null"
    if isinstance(data, bool):
        return b"true" if data else b"false"
    if isinstance(data, (int, float)):
        return _format_jcs_number(data)
    if isinstance(data, str):
        return _escape_jcs_string(data)
    if isinstance(data, list):
        return b"[" + b",".join(canonicalize_jcs(x) for x in data) + b"]"
    if isinstance(data, dict):
        for k in data.keys():
            if not isinstance(k, str):
                raise TypeError(f"Chave de dicionário RFC 8785 deve ser string, obtido: {type(k)}")
        sorted_keys = sorted(data.keys(), key=lambda k: k.encode("utf-16-be"))
        parts = [
            _escape_jcs_string(k) + b":" + canonicalize_jcs(data[k])
            for k in sorted_keys
        ]
        return b"{" + b",".join(parts) + b"}"
    raise TypeError(f"Tipo não serializável em RFC 8785: {type(data)}")


def compute_canonical_manifest_hash(data: dict[str, Any] | MCTXManifest) -> str:
    """Calcula o hash SHA-256 canônico do manifesto sem autorreferência segundo a RFC 8785 (JCS).

    Omite integrity.manifest_hash e integrity.signature durante o cálculo para evitar dependência cíclica.
    """
    if isinstance(data, MCTXManifest):
        d = asdict(data)
    else:
        d = json.loads(json.dumps(data))  # cópia profunda

    if "integrity" in d and isinstance(d["integrity"], dict):
        d["integrity"]["manifest_hash"] = ""
        d["integrity"].pop("signature", None)

    canonical_bytes = canonicalize_jcs(d)
    return hashlib.sha256(canonical_bytes).hexdigest()



@dataclass
class StorageConfig:
    adapter: str = "filesystem"
    root_id: str = "local-corpus-root"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SourceDescriptor:
    source_id: str
    logical_ref: str
    media_type: str
    content_hash: str
    version: str
    classification: str = "engineering"
    access_policy_ref: str = "policy:mark-dev"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class IndexDescriptor:
    index_id: str
    kind: str  # "lexical" | "vector"
    build_id: str
    embedding_model_id: str | None = None
    dimensions: int | None = None

    def to_dict(self) -> dict[str, Any]:
        res = asdict(self)
        if self.embedding_model_id is None:
            res.pop("embedding_model_id", None)
        if self.dimensions is None:
            res.pop("dimensions", None)
        return res


@dataclass
class RetrievalProfile:
    hybrid: bool = True
    lexical_candidates: int = 80
    vector_candidates: int = 80
    rerank_limit: int = 40
    max_expansion_depth: int = 2
    max_rounds: int = 4

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ChunkingProfile:
    profile_id: str = "semantic-adaptive-v1"
    target_tokens: int = 450
    overlap_tokens: int = 60
    preserve_source_offsets: bool = True
    method: str = "semantic_adaptive"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SignatureSection:
    signer_id: str
    algorithm: str  # "ed25519" | "ecdsa-p256-sha256"
    signature: str  # Hexadecimal encoded signature
    timestamp: int = field(default_factory=lambda: int(time.time()))
    sequence_number: int = 1
    protocol_version: str = "1.0"
    scope: str = "mctx:sync"
    session_nonce: str | None = None
    public_key_hex: str | None = None

    def to_dict(self) -> dict[str, Any]:
        res = asdict(self)
        if self.session_nonce is None:
            res.pop("session_nonce", None)
        if self.public_key_hex is None:
            res.pop("public_key_hex", None)
        return res


@dataclass
class IntegritySection:
    manifest_hash: str
    merkle_root: str
    tree: dict[str, Any] | None = None
    signature: SignatureSection | None = None

    def to_dict(self) -> dict[str, Any]:
        res = asdict(self)
        if self.tree is None:
            res.pop("tree", None)
        if self.signature is None:
            res.pop("signature", None)
        else:
            res["signature"] = self.signature.to_dict()
        return res


@dataclass
class MCTXManifest:
    format: str
    format_version: str
    corpus_id: str
    created_at: str
    updated_at: str
    storage: StorageConfig
    source_catalog: list[SourceDescriptor]
    index_catalog: list[IndexDescriptor]
    retrieval_profile: RetrievalProfile
    chunking_profile: ChunkingProfile
    integrity: IntegritySection
    extensions: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "format_version": self.format_version,
            "corpus_id": self.corpus_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "storage": self.storage.to_dict(),
            "source_catalog": [s.to_dict() for s in self.source_catalog],
            "index_catalog": [i.to_dict() for i in self.index_catalog],
            "retrieval_profile": self.retrieval_profile.to_dict(),
            "chunking_profile": self.chunking_profile.to_dict(),
            "integrity": self.integrity.to_dict(),
            "extensions": self.extensions,
        }


class MCTXParser:
    """Parser estrito e sanitizador para arquivos de manifesto .mctx."""

    @classmethod
    def load_manifest(
        cls,
        path: str | Path,
        trusted_root: str | Path,
        max_bytes: int = DEFAULT_MAX_MANIFEST_BYTES,
    ) -> MCTXManifest:
        resolved_path = resolve_inside_root(path, trusted_root)
        if not resolved_path.is_file():
            raise FileNotFoundError(f"Arquivo de manifesto não encontrado: {resolved_path}")

        file_size = resolved_path.stat().st_size
        if file_size > max_bytes:
            raise MCTXSecurityError(
                f"Tamanho do manifesto ({file_size} bytes) excede o limite seguro permitido ({max_bytes} bytes)"
            )

        try:
            raw_content = resolved_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise MCTXValidationError(f"Manifesto não está em codificação UTF-8 válida: {exc}")

        return cls.parse_json(raw_content, trusted_root=trusted_root)

    parse_file = load_manifest

    @classmethod
    def parse_json(cls, raw_json: str, trusted_root: str | Path) -> MCTXManifest:
        def _reject_duplicate_keys(ordered_pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            d: dict[str, Any] = {}
            for key, val in ordered_pairs:
                if key in d:
                    raise MCTXValidationError(f"Chave duplicada detectada no payload JSON do manifesto: '{key}'")
                d[key] = val
            return d

        try:
            data = json.loads(raw_json, object_pairs_hook=_reject_duplicate_keys)
        except json.JSONDecodeError as exc:
            raise MCTXValidationError(f"JSON de manifesto malformado ou truncado: {exc}")

        if not isinstance(data, dict):
            raise MCTXValidationError("Manifesto raiz deve ser um objeto JSON.")

        # Validação de formato e versão
        fmt = data.get("format")
        if fmt != "mctx":
            raise MCTXValidationError(f"Formato inválido: esperado 'mctx', obtido '{fmt}'")

        version = data.get("format_version")
        if version not in ALLOWED_FORMAT_VERSIONS:
            raise MCTXValidationError(
                f"Versão de esquema '{version}' incompatível. Versões suportadas: {sorted(ALLOWED_FORMAT_VERSIONS)}"
            )

        corpus_id = data.get("corpus_id")
        if not corpus_id or not isinstance(corpus_id, str):
            raise MCTXValidationError("Campo obrigatório 'corpus_id' ausente ou inválido.")

        # Validação de integridade de hash
        integrity_data = data.get("integrity", {})
        if not isinstance(integrity_data, dict):
            raise MCTXValidationError("Seção 'integrity' deve ser um objeto.")

        given_hash = integrity_data.get("manifest_hash", "")
        if not given_hash.startswith("sha256:"):
            raise MCTXValidationError("Campo 'integrity.manifest_hash' deve iniciar com 'sha256:'")

        expected_hash = compute_canonical_manifest_hash(data)
        extracted_hash = given_hash.replace("sha256:", "")
        if extracted_hash != expected_hash:
            raise MCTXValidationError(
                f"Hash do manifesto adulterado ou corrompido! Fornecido: {extracted_hash}, Calculado: {expected_hash}"
            )

        # Validação de catálogo de fontes e contenção no sandbox
        source_catalog_raw = data.get("source_catalog", [])
        if not isinstance(source_catalog_raw, list):
            raise MCTXValidationError("Campo 'source_catalog' deve ser uma lista.")

        sources: list[SourceDescriptor] = []
        for s in source_catalog_raw:
            if not isinstance(s, dict):
                raise MCTXValidationError("Entrada em source_catalog deve ser objeto.")
            log_ref = s.get("logical_ref", "")
            # Assegura que o caminho lógico está estritamente contido no root
            resolve_inside_root(log_ref, trusted_root)
            sources.append(
                SourceDescriptor(
                    source_id=s.get("source_id", ""),
                    logical_ref=log_ref,
                    media_type=s.get("media_type", "text/plain"),
                    content_hash=s.get("content_hash", ""),
                    version=s.get("version", "1.0"),
                    classification=s.get("classification", "engineering"),
                    access_policy_ref=s.get("access_policy_ref", "policy:mark-dev"),
                )
            )

        storage_raw = data.get("storage", {})
        storage = StorageConfig(
            adapter=storage_raw.get("adapter", "filesystem"),
            root_id=storage_raw.get("root_id", "local-corpus-root"),
        )

        index_catalog_raw = data.get("index_catalog", [])
        indexes = [
            IndexDescriptor(
                index_id=i.get("index_id", ""),
                kind=i.get("kind", "lexical"),
                build_id=i.get("build_id", ""),
                embedding_model_id=i.get("embedding_model_id"),
                dimensions=i.get("dimensions"),
            )
            for i in index_catalog_raw
        ]

        retrieval_raw = data.get("retrieval_profile", {})
        retrieval_profile = RetrievalProfile(
            hybrid=retrieval_raw.get("hybrid", True),
            lexical_candidates=retrieval_raw.get("lexical_candidates", 80),
            vector_candidates=retrieval_raw.get("vector_candidates", 80),
            rerank_limit=retrieval_raw.get("rerank_limit", 40),
            max_expansion_depth=retrieval_raw.get("max_expansion_depth", 2),
            max_rounds=retrieval_raw.get("max_rounds", 4),
        )

        chunking_raw = data.get("chunking_profile", {})
        chunking_profile = ChunkingProfile(
            profile_id=chunking_raw.get("profile_id", "semantic-adaptive-v1"),
            target_tokens=chunking_raw.get("target_tokens", 450),
            overlap_tokens=chunking_raw.get("overlap_tokens", 60),
            preserve_source_offsets=chunking_raw.get("preserve_source_offsets", True),
            method=chunking_raw.get("method", "semantic_adaptive"),
        )

        sig_raw = integrity_data.get("signature")
        sig = None
        if isinstance(sig_raw, dict):
            sig = SignatureSection(
                signer_id=sig_raw.get("signer_id", ""),
                algorithm=sig_raw.get("algorithm", ""),
                signature=sig_raw.get("signature", ""),
                timestamp=sig_raw.get("timestamp", 0),
                sequence_number=sig_raw.get("sequence_number", 1),
                protocol_version=sig_raw.get("protocol_version", "1.0"),
                scope=sig_raw.get("scope", "mctx:sync"),
                session_nonce=sig_raw.get("session_nonce"),
                public_key_hex=sig_raw.get("public_key_hex"),
            )

        integrity = IntegritySection(
            manifest_hash=given_hash,
            merkle_root=integrity_data.get("merkle_root", ""),
            tree=integrity_data.get("tree"),
            signature=sig,
        )

        return MCTXManifest(
            format=fmt,
            format_version=version,
            corpus_id=corpus_id,
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            storage=storage,
            source_catalog=sources,
            index_catalog=indexes,
            retrieval_profile=retrieval_profile,
            chunking_profile=chunking_profile,
            integrity=integrity,
            extensions=data.get("extensions", {}),
        )

    @classmethod
    def save_manifest(
        cls,
        manifest: MCTXManifest,
        target_path: str | Path,
        trusted_root: str | Path,
    ) -> Path:
        """Salva o manifesto em disco de forma atômica (gravação em tempfile seguida de rename)."""
        resolved_path = resolve_inside_root(target_path, trusted_root)
        manifest_dict = manifest.to_dict()

        # Recalcula hash canônico antes de salvar
        h = compute_canonical_manifest_hash(manifest_dict)
        manifest_dict["integrity"]["manifest_hash"] = f"sha256:{h}"
        manifest.integrity.manifest_hash = f"sha256:{h}"

        payload = json.dumps(manifest_dict, indent=2, ensure_ascii=False)

        parent = resolved_path.parent
        parent.mkdir(parents=True, exist_ok=True)

        fd, temp_file_path = tempfile.mkstemp(dir=str(parent), prefix="mctx_tmp_")
        try:
            with open(fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_file_path, str(resolved_path))

            # Fsync no diretório pai para persistência atômica da entrada de diretório no POSIX
            try:
                dir_fd = os.open(str(parent), os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except OSError:
                pass  # Alguns sistemas de arquivos virtuais em memória não suportam fsync de diretório
        except Exception:
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
            raise

        return resolved_path


def sign_manifest(
    manifest: MCTXManifest,
    signer_id: str,
    private_key: Any,
    algorithm: str = "ed25519",
    sequence_number: int = 1,
    protocol_version: str = "1.0",
    scope: str = "mctx:sync",
    session_nonce: str | None = None,
) -> SignatureSection:
    """Assina digitalmente um manifesto MCTX com chave assimétrica (Ed25519 ou ECDSA P-256).

    Vincula a assinatura ao hash canônico, ID do dispositivo, versão do protocolo,
    escopo autorizado, número de sequência monotônico e timestamp.
    Rejeita categoricamente HMAC-SHA256 e outros esquemas de chave compartilhada simétrica.
    """
    if algorithm == "hmac-sha256":
        raise MCTXSecurityError(
            "Algoritmo simétrico 'hmac-sha256' descontinuado e inseguro: "
            "o MCTX exige assinaturas assimétricas exclusivas por dispositivo (Ed25519 ou ECDSA P-256)."
        )

    if algorithm not in ALLOWED_SIGNATURE_ALGORITHMS:
        raise MCTXSecurityError(f"Algoritmo de assinatura não suportado ou inseguro: '{algorithm}'")

    # Atualiza o hash canônico antes da assinatura
    h = compute_canonical_manifest_hash(manifest)
    manifest.integrity.manifest_hash = f"sha256:{h}"
    now_ts = int(time.time())

    payload_parts = [h, signer_id, protocol_version, scope, str(sequence_number), str(now_ts)]
    if session_nonce is not None:
        payload_parts.append(str(session_nonce))
    payload_to_sign = ":".join(payload_parts).encode("utf-8")

    pub_hex = None
    if algorithm == "ed25519":
        if isinstance(private_key, ed25519.Ed25519PrivateKey):
            priv = private_key
        elif isinstance(private_key, (bytes, bytearray)) and len(private_key) == 32:
            priv = ed25519.Ed25519PrivateKey.from_private_bytes(bytes(private_key))
        else:
            raise MCTXSecurityError(f"Chave privada inválida para Ed25519: {type(private_key)}")

        sig_bytes = priv.sign(payload_to_sign)
        sig_hex = sig_bytes.hex()
        pub_raw = priv.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        pub_hex = pub_raw.hex()
    elif algorithm == "ecdsa-p256-sha256":
        if isinstance(private_key, ec.EllipticCurvePrivateKey):
            priv = private_key
        else:
            raise MCTXSecurityError(f"Chave privada inválida para ECDSA P-256: {type(private_key)}")

        sig_bytes = priv.sign(payload_to_sign, ec.ECDSA(hashes.SHA256()))
        sig_hex = sig_bytes.hex()
        pub_raw = priv.public_key().public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.CompressedPoint,
        )
        pub_hex = pub_raw.hex()
    else:
        raise MCTXSecurityError(f"Algoritmo não suportado: {algorithm}")

    sig = SignatureSection(
        signer_id=signer_id,
        algorithm=algorithm,
        signature=sig_hex,
        timestamp=now_ts,
        sequence_number=sequence_number,
        protocol_version=protocol_version,
        scope=scope,
        session_nonce=session_nonce,
        public_key_hex=pub_hex,
    )
    manifest.integrity.signature = sig
    return sig


def verify_manifest_crypto(
    manifest: MCTXManifest,
    authorized_keys: dict[str, Any],
) -> bool:
    """Valida estritamente a autenticidade criptográfica e integridade da assinatura do manifesto.

    Verifica se a assinatura assimétrica é matematicamente válida contra a chave pública autorizada,
    e se todos os campos vinculados (hash canônico, escopo, versão, sequência) estão íntegros.
    Lança MCTXSecurityError em caso de violação.
    """
    sig = manifest.integrity.signature
    if sig is None:
        raise MCTXSecurityError("Manifesto não possui assinatura digital para validação.")

    if sig.algorithm == "hmac-sha256":
        raise MCTXSecurityError(
            "Algoritmo simétrico 'hmac-sha256' descontinuado e rejeitado para verificação."
        )

    if sig.algorithm not in ALLOWED_SIGNATURE_ALGORITHMS:
        raise MCTXSecurityError(
            f"Tentativa de uso de algoritmo não suportado ou inseguro: '{sig.algorithm}' (rejeitado)"
        )

    if sig.signer_id not in authorized_keys:
        raise MCTXSecurityError(
            f"Signatário '{sig.signer_id}' não autorizado ou desconhecido no keyring."
        )

    # Verifica integridade do hash canônico do manifesto
    computed_h = compute_canonical_manifest_hash(manifest)
    expected_manifest_hash = f"sha256:{computed_h}"
    if manifest.integrity.manifest_hash != expected_manifest_hash:
        raise MCTXSecurityError(
            f"Hash do manifesto corrompido ou adulterado antes da verificação da assinatura. "
            f"Esperado: {expected_manifest_hash}, Atual: {manifest.integrity.manifest_hash}"
        )

    # Reconstrói payload vinculado
    payload_parts = [
        computed_h,
        sig.signer_id,
        sig.protocol_version,
        sig.scope,
        str(sig.sequence_number),
        str(sig.timestamp),
    ]
    if getattr(sig, "session_nonce", None) is not None:
        payload_parts.append(str(sig.session_nonce))
    payload_to_verify = ":".join(payload_parts).encode("utf-8")

    key_entry = authorized_keys[sig.signer_id]
    try:
        sig_bytes = bytes.fromhex(sig.signature)
    except ValueError:
        raise MCTXSecurityError("Formato de assinatura digital hexadecimal inválido.")

    try:
        if sig.algorithm == "ed25519":
            if isinstance(key_entry, ed25519.Ed25519PublicKey):
                pub = key_entry
            elif isinstance(key_entry, (bytes, bytearray)) and len(key_entry) == 32:
                pub = ed25519.Ed25519PublicKey.from_public_bytes(bytes(key_entry))
            elif isinstance(key_entry, str) and len(key_entry) == 64:
                pub = ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(key_entry))
            else:
                raise MCTXSecurityError(f"Formato de chave pública inválido para Ed25519: {type(key_entry)}")

            pub.verify(sig_bytes, payload_to_verify)

        elif sig.algorithm == "ecdsa-p256-sha256":
            if isinstance(key_entry, ec.EllipticCurvePublicKey):
                pub = key_entry
            elif isinstance(key_entry, (bytes, bytearray)):
                pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), bytes(key_entry))
            elif isinstance(key_entry, str):
                pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), bytes.fromhex(key_entry))
            else:
                raise MCTXSecurityError(f"Formato de chave pública inválido para ECDSA P-256: {type(key_entry)}")

            pub.verify(sig_bytes, payload_to_verify, ec.ECDSA(hashes.SHA256()))

        else:
            raise MCTXSecurityError(f"Algoritmo não suportado: {sig.algorithm}")

    except InvalidSignature:
        raise MCTXSecurityError(
            f"Assinatura digital inválida para o signatário '{sig.signer_id}'. "
            f"Conteúdo ou parâmetros vinculados adulterados."
        )

    return True


def verify_manifest_signature(
    manifest: MCTXManifest,
    authorized_keys: dict[str, Any],
) -> bool:
    """Alias para verify_manifest_crypto."""
    return verify_manifest_crypto(manifest, authorized_keys)
