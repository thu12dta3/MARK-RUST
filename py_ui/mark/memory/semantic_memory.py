"""Módulo de Memória Semântica (Fact Memory) do MARK.

Armazena de forma persistente fatos, preferências e configurações do usuário
extraídos em segundo plano das conversas ou adicionados explicitamente.
"""

from __future__ import annotations

from contextlib import contextmanager
import logging
import os
from pathlib import Path
import re
import sqlite3
import stat
import time

logger = logging.getLogger("mark.memory.semantic")

DEFAULT_SEMANTIC_DB = Path.home() / ".mark/memory/semantic.sqlite3"


def get_default_semantic_db_path() -> Path:
    from ..config import load_config
    try:
        cfg = load_config()
        path_str = cfg.get("memory", {}).get("storage_path") or cfg.get("memory_storage_path")
        if path_str:
            return Path(path_str).expanduser() / "semantic.sqlite3"
    except Exception:
        pass
    return DEFAULT_SEMANTIC_DB


class SemanticMemoryStore:
    """Gerenciador de armazenamento persistente SQLite para fatos semânticos."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.path = Path(db_path).expanduser() if db_path else get_default_semantic_db_path()
        self._ensure_secure_storage()
        self._init_db()

    def _ensure_secure_storage(self) -> None:
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
    def _db(self):
        conn = sqlite3.connect(self.path, timeout=10)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._db() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS semantic_facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fact TEXT NOT NULL UNIQUE,
                    category TEXT NOT NULL DEFAULT 'preference',
                    provenance TEXT NOT NULL DEFAULT 'extracted',
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_semantic_facts_cat ON semantic_facts(category, updated_at DESC)")

    def save_fact(self, fact: str, category: str = "preference", provenance: str = "extracted") -> bool:
        clean = " ".join(fact.strip().split())
        if not clean or len(clean) > 2000:
            return False
        now = int(time.time())
        try:
            with self._db() as db:
                db.execute(
                    "INSERT INTO semantic_facts (fact, category, provenance, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(fact) DO UPDATE SET updated_at = excluded.updated_at, provenance = excluded.provenance",
                    (clean, category, provenance, now, now),
                )
                return True
        except sqlite3.Error as exc:
            logger.error("Erro ao salvar fato semântico: %s", exc)
            return False

    def list_facts(self, category: str | None = None, limit: int = 100) -> list[dict]:
        with self._db() as db:
            if category:
                rows = db.execute(
                    "SELECT id, fact, category, provenance, created_at, updated_at "
                    "FROM semantic_facts WHERE category = ? ORDER BY updated_at DESC LIMIT ?",
                    (category, max(1, limit)),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT id, fact, category, provenance, created_at, updated_at "
                    "FROM semantic_facts ORDER BY updated_at DESC LIMIT ?",
                    (max(1, limit),),
                ).fetchall()
        return [
            {
                "id": r[0],
                "fact": r[1],
                "category": r[2],
                "provenance": r[3],
                "created_at": r[4],
                "updated_at": r[5],
            }
            for r in rows
        ]

    def delete_fact(self, fact_id: int) -> bool:
        with self._db() as db:
            cur = db.execute("DELETE FROM semantic_facts WHERE id = ?", (fact_id,))
            return cur.rowcount > 0

    def clear(self) -> None:
        with self._db() as db:
            db.execute("DELETE FROM semantic_facts")


_EXTRACTION_PATTERNS = [
    # Linguagens e Tecnologias
    (
        re.compile(r"\b(?:eu\s+)?(?:programo|desenvolvo|trabalho|codifico)\s+(?:principalmente\s+)?em\s+([A-Za-z0-9#+.]+)", re.IGNORECASE),
        lambda m: f"O usuário programa em {m.group(1)}",
    ),
    # Portas de rede
    (
        re.compile(r"\b(?:eu\s+)?(?:uso|utilizo|rodo|subo|configuro)\s+(?:a|na)?\s*porta\s+(\d+)", re.IGNORECASE),
        lambda m: f"O usuário utiliza a porta {m.group(1)}",
    ),
    (
        re.compile(r"\b(?:minha\s+)?porta\s+(?:padrão|padrao|local)\s+(?:é|e|foi)\s+(?:a\s+)?(\d+)", re.IGNORECASE),
        lambda m: f"O usuário utiliza a porta {m.group(1)}",
    ),
    # Preferências explícitas
    (
        re.compile(r"\b(?:eu\s+)?(?:prefiro|gosto\s+de)\s+([^.,;!?\n]{3,60})", re.IGNORECASE),
        lambda m: f"Preferência do usuário: {m.group(1).strip()}",
    ),
    # Nome do usuário
    (
        re.compile(r"\bmeu\s+nome\s+[eé]\s+([A-Za-zÀ-ÿ]+)", re.IGNORECASE),
        lambda m: f"O nome do usuário é {m.group(1).capitalize()}",
    ),
    # Sistema Operacional / Ambiente
    (
        re.compile(r"\b(?:eu\s+)?(?:uso|utilizo)\s+(?:o\s+)?(linux|arch\s*linux|ubuntu|debian|fedora|windows\s*11|macos)", re.IGNORECASE),
        lambda m: f"O usuário utiliza o sistema operacional {m.group(1)}",
    ),
]


def extract_semantic_facts(text: str) -> list[str]:
    """Extrai deterministicamente fatos e preferências do usuário a partir do texto."""
    if not isinstance(text, str) or not text.strip():
        return []

    facts: list[str] = []
    # Testar cada sentença ou a frase completa
    sentences = [s.strip() for s in re.split(r"[.\n]+", text) if s.strip()]
    if not sentences:
        sentences = [text.strip()]

    for sentence in sentences:
        for pattern, formatter in _EXTRACTION_PATTERNS:
            match = pattern.search(sentence)
            if match:
                try:
                    fact = formatter(match).strip()
                    if fact and fact not in facts:
                        facts.append(fact)
                except Exception:
                    pass

    return facts
