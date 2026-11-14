"""Módulo de Memória Episódica (Long-term Archival & Vector Store) do MARK.

Sumariza turnos de conversa arquivados/descartados do contexto imediato,
gera embeddings vetoriais locais (via HashEmbeddingProvider) e armazena
persistentemente em SQLite para recuperação semântica de longo prazo via RAG.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Callable

from ..cognition.embeddings import HashEmbeddingProvider, cosine

logger = logging.getLogger("mark.memory.episodic")

DEFAULT_EPISODIC_DB = Path.home() / ".mark/memory/episodic.sqlite3"


def get_default_episodic_db_path() -> Path:
    from ..config import load_config
    try:
        cfg = load_config()
        path_str = cfg.get("memory", {}).get("storage_path") or cfg.get("memory_storage_path")
        if path_str:
            return Path(path_str).expanduser() / "episodic.sqlite3"
    except Exception:
        pass
    return DEFAULT_EPISODIC_DB


class EpisodicMemoryStore:
    """Vector Store em SQLite para armazenamento e busca de resumos episódicos."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.path = Path(db_path).expanduser() if db_path else get_default_episodic_db_path()
        self.embedder = HashEmbeddingProvider()
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
                CREATE TABLE IF NOT EXISTS episodic_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    embedding TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at INTEGER NOT NULL
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_episodic_session ON episodic_memories(session_id)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_episodic_created ON episodic_memories(created_at DESC)")

    def store_summary(
        self,
        summary: str,
        session_id: str = "default",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        clean = summary.strip()
        if not clean:
            return -1

        emb = self.embedder.embed(clean)
        emb_json = json.dumps(emb)
        meta_json = json.dumps(metadata or {})
        now = int(time.time())

        with self._db() as db:
            cursor = db.execute(
                "INSERT INTO episodic_memories (session_id, summary, embedding, metadata, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, clean, emb_json, meta_json, now),
            )
            return cursor.lastrowid

    def record_biometric_event(
        self,
        summary: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Injeta silenciosamente um evento ou alerta biométrico na memória episódica."""
        meta = {"category": "biometrics", **(metadata or {})}
        return self.store_summary(summary=summary, session_id="health_biometrics", metadata=meta)

    def search(
        self,
        query: str,
        top_k: int = 3,
        min_similarity: float = 0.1,
    ) -> list[dict]:
        clean_query = query.strip()
        if not clean_query:
            return []

        query_emb = self.embedder.embed(clean_query)
        q_terms = set(re.findall(r"\w{3,}", clean_query.casefold()))

        with self._db() as db:
            rows = db.execute(
                "SELECT id, session_id, summary, embedding, metadata, created_at "
                "FROM episodic_memories ORDER BY created_at DESC LIMIT 500"
            ).fetchall()

        scored = []
        for row in rows:
            rec_id, s_id, summary_text, emb_str, meta_str, created_at = row
            try:
                emb = json.loads(emb_str)
                sim = cosine(query_emb, emb)
            except Exception:
                sim = 0.0

            s_terms = set(re.findall(r"\w{3,}", summary_text.casefold()))
            overlap = len(q_terms & s_terms)
            lexical_bonus = min(0.3, overlap * 0.05)
            final_sim = sim + lexical_bonus

            if final_sim >= min_similarity:
                try:
                    meta = json.loads(meta_str)
                except Exception:
                    meta = {}
                scored.append({
                    "id": rec_id,
                    "session_id": s_id,
                    "summary": summary_text,
                    "similarity": final_sim,
                    "metadata": meta,
                    "created_at": created_at,
                })

        scored.sort(key=lambda x: x["similarity"], reverse=True)
        return scored[:max(1, top_k)]


    def list_episodes(self, limit: int = 50) -> list[dict]:
        with self._db() as db:
            rows = db.execute(
                "SELECT id, session_id, summary, metadata, created_at "
                "FROM episodic_memories ORDER BY created_at DESC LIMIT ?",
                (max(1, limit),),
            ).fetchall()
        return [
            {
                "id": r[0],
                "session_id": r[1],
                "summary": r[2],
                "metadata": json.loads(r[3]) if r[3] else {},
                "created_at": r[4],
            }
            for r in rows
        ]

    def clear(self) -> None:
        with self._db() as db:
            db.execute("DELETE FROM episodic_memories")


def summarize_conversation_turns(
    turns: list[dict],
    model_caller: Callable[..., str] | None = None,
    cfg: dict | None = None,
) -> str:
    """Sumariza uma sequência de turnos descartados da conversa em um sumário estruturado."""
    if not turns:
        return ""

    formatted_turns: list[str] = []
    topics_detected: list[str] = []
    facts_detected: list[str] = []

    for t in turns:
        u = str(t.get("user", "")).strip()
        a = str(t.get("assistant", "")).strip()
        if u:
            formatted_turns.append(f"Usuário: {u}")
        if a:
            formatted_turns.append(f"MARK: {a}")

        # Extração de tópicos e decisões chave
        full_turn = f"{u} {a}"
        # Portas / configurações técnicas
        ports = re.findall(r"\bporta\s+(\d+)\b", full_turn, re.IGNORECASE)
        for p in ports:
            facts_detected.append(f"porta {p}")
        # Decisões explícitas
        decisions = re.findall(r"(?:decidimos|combinamos|vamos\s+migrar|adotar|usar)\s+([^.,;!?\n]+)", full_turn, re.IGNORECASE)
        for d in decisions:
            facts_detected.append(d.strip())

    conversation_text = "\n".join(formatted_turns)

    # Tenta sumarização via modelo local se fornecido
    if model_caller is not None and callable(model_caller):
        prompt = (
            "Gere um sumário estruturado e conciso dos pontos principais, decisões e configurações "
            "acordadas na conversa a seguir. Não invente nada além do texto:\n\n"
            f"{conversation_text}\n\nSumário estruturado:"
        )
        try:
            summary = model_caller(prompt, cfg or {}, "Você é um sumarizador conciso de conversas passadas.")
            if summary and len(summary.strip()) > 10:
                return summary.strip()
        except Exception as exc:
            logger.debug("Sumarização via modelo indisponível (%s), usando fallback estruturado.", exc)

    # Fallback estruturado determinístico (alta fidelidade e sem rede)
    summary_lines = [
        "Sumário da sessão anterior:",
    ]
    if facts_detected:
        summary_lines.append(f"- Decisões e configurações: {'; '.join(set(facts_detected))}")

    # Principais afirmações e diálogos
    dialogue_summary = []
    for t in turns:
        u = str(t.get("user", "")).strip()
        a = str(t.get("assistant", "")).strip()
        if u:
            dialogue_summary.append(f"Usuário pontuou: {u}")
        if a and len(a) < 120:
            dialogue_summary.append(f"MARK respondeu: {a}")

    summary_lines.append("- Registros: " + " | ".join(dialogue_summary[:6]))
    return "\n".join(summary_lines)


def trigger_episodic_summarization(
    discarded_turns: list[dict],
    session_id: str = "default",
    episodic_store: EpisodicMemoryStore | None = None,
    model_caller: Callable[..., str] | None = None,
    cfg: dict | None = None,
) -> str | None:
    """Gatilho para sumarizar turnos descartados e indexar na memória episódica."""
    if not discarded_turns:
        return None

    summary = summarize_conversation_turns(discarded_turns, model_caller=model_caller, cfg=cfg)
    if not summary:
        return None

    store = episodic_store or EpisodicMemoryStore()
    store.store_summary(summary, session_id=session_id, metadata={"turn_count": len(discarded_turns)})
    return summary
