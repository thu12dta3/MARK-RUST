"""Motor Unificado do Context Virtualizer (MCTXEngine).

Integra Manifesto .mctx, Ingestão Estruturada, Árvore de Merkle para Invalidação Atômica,
Fusão Híbrida Dinâmica (Intent-Aware RRF) e Orquestração Self-RAG sob Orçamento Estrito de Tokens.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import time
from typing import Any

from ...cognition.embeddings import EmbeddingProvider, HashEmbeddingProvider, cosine, tokens
from .chunking import AdaptiveSemanticChunker, RepresentationLevel, SemanticChunk, estimate_tokens
from .fusion import DynamicIntentRRF, IntentAwareHit, QueryIntent, classify_query_intent
from .manifest import (
    ChunkingProfile,
    IndexDescriptor,
    IntegritySection,
    MCTXManifest,
    MCTXParser,
    MCTXSecurityError,
    RetrievalProfile,
    SourceDescriptor,
    StorageConfig,
    compute_canonical_manifest_hash,
    resolve_inside_root,
)
from .merkle import MerkleDiff, MerkleTree, build_merkle_tree, diff_merkle_trees
from .self_rag import (
    EvidencePackage,
    SelfRAGOrchestrator,
    TokenBudget,
    build_contained_context,
    default_mctx_system_instruction,
)


class MCTXEngine:
    """Motor central do ecossistema MCTX para gerenciar manifestos, índices e recuperação."""

    def __init__(
        self,
        trusted_root: str | Path,
        db_path: str | Path | None = None,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self.trusted_root = Path(trusted_root).resolve()
        self.db_path = Path(db_path).resolve() if db_path else self.trusted_root / "mctx_index.sqlite3"
        self.embedding = embedding_provider or HashEmbeddingProvider()
        self.chunker = AdaptiveSemanticChunker()
        self.rrf = DynamicIntentRRF()
        self.trees: dict[str, MerkleTree] = {}

        self.conn = sqlite3.connect(str(self.db_path), timeout=15)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def _init_schema(self) -> None:
        with self.conn:
            self.conn.execute(
                """CREATE TABLE IF NOT EXISTS mctx_sources (
                    source_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    logical_ref TEXT NOT NULL,
                    format TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    merkle_root TEXT NOT NULL,
                    classification TEXT NOT NULL,
                    access_policy_ref TEXT NOT NULL DEFAULT 'policy:mark-dev',
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )"""
            )
            try:
                self.conn.execute(
                    "ALTER TABLE mctx_sources ADD COLUMN access_policy_ref TEXT NOT NULL DEFAULT 'policy:mark-dev'"
                )
            except sqlite3.OperationalError:
                pass

            self.conn.execute(
                """CREATE TABLE IF NOT EXISTS mctx_embedding_cache (
                    content_hash TEXT PRIMARY KEY,
                    vector TEXT NOT NULL,
                    dimensions INTEGER NOT NULL,
                    created_at INTEGER NOT NULL
                )"""
            )
            self.conn.execute(
                """CREATE TABLE IF NOT EXISTS mctx_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    section TEXT NOT NULL,
                    level_l0 TEXT NOT NULL,
                    level_l1 TEXT NOT NULL,
                    level_l2 TEXT NOT NULL,
                    level_l3 TEXT NOT NULL,
                    level_l4 TEXT NOT NULL,
                    vector TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    span_start INTEGER NOT NULL,
                    span_end INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    FOREIGN KEY(source_id) REFERENCES mctx_sources(source_id) ON DELETE CASCADE
                )"""
            )
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_mctx_chunks_source ON mctx_chunks(source_id)")
            self.conn.execute(
                """CREATE VIRTUAL TABLE IF NOT EXISTS mctx_chunks_fts USING fts5(
                    chunk_id UNINDEXED,
                    source_id UNINDEXED,
                    content
                )"""
            )

    def _get_or_compute_embedding(self, text: str) -> list[float]:
        """Recupera vetor do cache por hash de conteúdo ou calcula sob demanda."""
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        c_key = f"sha256:{content_hash}"
        row = self.conn.execute(
            "SELECT vector FROM mctx_embedding_cache WHERE content_hash = ?",
            (c_key,),
        ).fetchone()
        if row:
            return json.loads(row[0])

        vec = self.embedding.embed(text)
        now = int(time.time())
        self.conn.execute(
            """INSERT OR REPLACE INTO mctx_embedding_cache
               (content_hash, vector, dimensions, created_at)
               VALUES (?, ?, ?, ?)""",
            (c_key, json.dumps(vec), len(vec), now),
        )
        return vec

    def ingest_source(
        self,
        file_path: str | Path,
        source_id: str,
        title: str | None = None,
        classification: str = "engineering",
        access_policy_ref: str = "policy:mark-dev",
    ) -> MCTXManifest:
        """Ingesta uma fonte aplicando chunking semântico adaptativo e árvore de Merkle."""
        resolved = resolve_inside_root(file_path, self.trusted_root)
        if not resolved.is_file():
            raise FileNotFoundError(f"Fonte não encontrada: {resolved}")

        text = resolved.read_text(encoding="utf-8", errors="replace")
        checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()
        doc_title = title or resolved.stem.replace("_", " ").title()

        # 1. Chunking semântico adaptativo gerando níveis L0 a L4
        chunks = self.chunker.chunk_document(doc_id=source_id, text=text, title=doc_title)

        # 2. Construção da Árvore de Merkle
        tree = build_merkle_tree([(c.chunk_id, c.levels[RepresentationLevel.L3]) for c in chunks])
        self.trees[source_id] = tree

        # 3. Persistência no SQLite e índice BM25/FTS5
        now = int(time.time())
        logical_ref = str(resolved.relative_to(self.trusted_root))

        with self.conn:
            self.conn.execute(
                """INSERT OR REPLACE INTO mctx_sources
                   (source_id, title, logical_ref, format, checksum, merkle_root, classification, access_policy_ref, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    source_id,
                    doc_title,
                    logical_ref,
                    resolved.suffix.lstrip("."),
                    f"sha256:{checksum}",
                    tree.root_hash,
                    classification,
                    access_policy_ref,
                    now,
                    now,
                ),
            )
            # Limpa chunks antigos se houver
            self.conn.execute("DELETE FROM mctx_chunks WHERE source_id = ?", (source_id,))
            self.conn.execute("DELETE FROM mctx_chunks_fts WHERE source_id = ?", (source_id,))

            for c in chunks:
                vec = self._get_or_compute_embedding(c.levels[RepresentationLevel.L2])
                c_hash = hashlib.sha256(c.levels[RepresentationLevel.L3].encode("utf-8")).hexdigest()
                self.conn.execute(
                    """INSERT INTO mctx_chunks
                       (chunk_id, source_id, chunk_index, section, level_l0, level_l1, level_l2, level_l3, level_l4,
                        vector, content_hash, span_start, span_end, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        c.chunk_id,
                        source_id,
                        c.chunk_index,
                        c.section,
                        c.levels[RepresentationLevel.L0],
                        c.levels[RepresentationLevel.L1],
                        c.levels[RepresentationLevel.L2],
                        c.levels[RepresentationLevel.L3],
                        c.levels[RepresentationLevel.L4],
                        json.dumps(vec),
                        f"sha256:{c_hash}",
                        c.span_start,
                        c.span_end,
                        now,
                    ),
                )
                self.conn.execute(
                    "INSERT INTO mctx_chunks_fts (chunk_id, source_id, content) VALUES (?, ?, ?)",
                    (c.chunk_id, source_id, c.levels[RepresentationLevel.L3]),
                )

        # 4. Geração do manifesto .mctx
        manifest = self._build_manifest(
            source_id=source_id,
            logical_ref=logical_ref,
            checksum=f"sha256:{checksum}",
            merkle_root=tree.root_hash,
            classification=classification,
            access_policy_ref=access_policy_ref,
        )

        manifest_path = self.trusted_root / f"{source_id}.mctx"
        MCTXParser.save_manifest(manifest, manifest_path, trusted_root=self.trusted_root)
        return manifest

    def update_source_incremental(
        self,
        file_path: str | Path,
        source_id: str,
    ) -> tuple[MCTXManifest, MerkleDiff]:
        """Atualização incremental atômica: compara árvores de Merkle e invalida cirurgicamente o índice."""
        resolved = resolve_inside_root(file_path, self.trusted_root)
        text = resolved.read_text(encoding="utf-8", errors="replace")
        new_checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()

        # Chunks novos
        new_chunks = self.chunker.chunk_document(doc_id=source_id, text=text)
        new_tree = build_merkle_tree([(c.chunk_id, c.levels[RepresentationLevel.L3]) for c in new_chunks])

        # Recupera árvore antiga
        old_tree = self.trees.get(source_id)
        if not old_tree:
            # Reconstrói a partir do banco
            rows = self.conn.execute(
                "SELECT chunk_id, level_l3 FROM mctx_chunks WHERE source_id = ? ORDER BY chunk_index ASC",
                (source_id,),
            ).fetchall()
            old_tree = build_merkle_tree([(r[0], r[1]) for r in rows])

        # Diff O(log n)
        diff, _ = diff_merkle_trees(old_tree, new_tree)
        self.trees[source_id] = new_tree

        now = int(time.time())
        new_chunks_map = {c.chunk_id: c for c in new_chunks}

        with self.conn:
            # 1. Purga chunks deletados
            for cid in diff.deleted_chunk_ids:
                self.conn.execute("DELETE FROM mctx_chunks WHERE chunk_id = ?", (cid,))
                self.conn.execute("DELETE FROM mctx_chunks_fts WHERE chunk_id = ?", (cid,))

            # 2. Atualiza chunks modificados
            for cid in diff.modified_chunk_ids:
                if cid in new_chunks_map:
                    c = new_chunks_map[cid]
                    vec = self._get_or_compute_embedding(c.levels[RepresentationLevel.L2])
                    c_hash = hashlib.sha256(c.levels[RepresentationLevel.L3].encode("utf-8")).hexdigest()
                    self.conn.execute("DELETE FROM mctx_chunks WHERE chunk_id = ?", (cid,))
                    self.conn.execute("DELETE FROM mctx_chunks_fts WHERE chunk_id = ?", (cid,))
                    self.conn.execute(
                        """INSERT INTO mctx_chunks
                           (chunk_id, source_id, chunk_index, section, level_l0, level_l1, level_l2, level_l3, level_l4,
                            vector, content_hash, span_start, span_end, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            c.chunk_id,
                            source_id,
                            c.chunk_index,
                            c.section,
                            c.levels[RepresentationLevel.L0],
                            c.levels[RepresentationLevel.L1],
                            c.levels[RepresentationLevel.L2],
                            c.levels[RepresentationLevel.L3],
                            c.levels[RepresentationLevel.L4],
                            json.dumps(vec),
                            f"sha256:{c_hash}",
                            c.span_start,
                            c.span_end,
                            now,
                        ),
                    )
                    self.conn.execute(
                        "INSERT INTO mctx_chunks_fts (chunk_id, source_id, content) VALUES (?, ?, ?)",
                        (c.chunk_id, source_id, c.levels[RepresentationLevel.L3]),
                    )

            # 3. Adiciona chunks novos
            for cid in diff.added_chunk_ids:
                if cid in new_chunks_map:
                    c = new_chunks_map[cid]
                    vec = self._get_or_compute_embedding(c.levels[RepresentationLevel.L2])
                    c_hash = hashlib.sha256(c.levels[RepresentationLevel.L3].encode("utf-8")).hexdigest()
                    self.conn.execute(
                        """INSERT INTO mctx_chunks
                           (chunk_id, source_id, chunk_index, section, level_l0, level_l1, level_l2, level_l3, level_l4,
                            vector, content_hash, span_start, span_end, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            c.chunk_id,
                            source_id,
                            c.chunk_index,
                            c.section,
                            c.levels[RepresentationLevel.L0],
                            c.levels[RepresentationLevel.L1],
                            c.levels[RepresentationLevel.L2],
                            c.levels[RepresentationLevel.L3],
                            c.levels[RepresentationLevel.L4],
                            json.dumps(vec),
                            f"sha256:{c_hash}",
                            c.span_start,
                            c.span_end,
                            now,
                        ),
                    )
                    self.conn.execute(
                        "INSERT INTO mctx_chunks_fts (chunk_id, source_id, content) VALUES (?, ?, ?)",
                        (c.chunk_id, source_id, c.levels[RepresentationLevel.L3]),
                    )

            # 4. Atualiza registro da fonte com nova raiz da Árvore de Merkle
            self.conn.execute(
                """UPDATE mctx_sources
                   SET checksum = ?, merkle_root = ?, updated_at = ?
                   WHERE source_id = ?""",
                (f"sha256:{new_checksum}", new_tree.root_hash, now, source_id),
            )

        logical_ref = str(resolved.relative_to(self.trusted_root))
        source_meta = self.conn.execute(
            "SELECT classification, access_policy_ref FROM mctx_sources WHERE source_id = ?",
            (source_id,),
        ).fetchone()
        classification = source_meta[0] if source_meta else "engineering"
        access_policy = source_meta[1] if source_meta else "policy:mark-dev"

        manifest = self._build_manifest(
            source_id=source_id,
            logical_ref=logical_ref,
            checksum=f"sha256:{new_checksum}",
            merkle_root=new_tree.root_hash,
            classification=classification,
            access_policy_ref=access_policy,
        )
        manifest_path = self.trusted_root / f"{source_id}.mctx"
        MCTXParser.save_manifest(manifest, manifest_path, trusted_root=self.trusted_root)

        return manifest, diff

    def get_chunks(self, source_id: str) -> list[SemanticChunk]:
        """Recupera todos os SemanticChunks persistidos para a fonte."""
        rows = self.conn.execute(
            """SELECT chunk_id, source_id, chunk_index, section,
                      level_l0, level_l1, level_l2, level_l3, level_l4,
                      span_start, span_end
               FROM mctx_chunks
               WHERE source_id = ?
               ORDER BY chunk_index ASC""",
            (source_id,),
        ).fetchall()

        chunks: list[SemanticChunk] = []
        for r in rows:
            levels = {
                RepresentationLevel.L0: r[4],
                RepresentationLevel.L1: r[5],
                RepresentationLevel.L2: r[6],
                RepresentationLevel.L3: r[7],
                RepresentationLevel.L4: r[8],
            }
            toks = {k: estimate_tokens(v) for k, v in levels.items()}
            chunks.append(
                SemanticChunk(
                    chunk_id=r[0],
                    doc_id=r[1],
                    chunk_index=r[2],
                    section=r[3],
                    levels=levels,
                    token_counts=toks,
                    span_start=r[9],
                    span_end=r[10],
                )
            )
        return chunks

    def retrieve(
        self,
        query: str,
        limit: int = 10,
        caller_policy: str | None = None,
        allowed_classifications: list[str] | set[str] | None = None,
    ) -> list[IntentAwareHit]:
        """Recuperação híbrida com classificação de intenção, isolamento de proveniência e fusão dinâmica RRF."""
        if not query or not query.strip():
            return []

        # 0. Verificação e Filtragem Estrita de Autorização / Políticas de Acesso
        allowed_sources: set[str] | None = None
        if caller_policy is not None or allowed_classifications is not None:
            clauses = []
            params: list[Any] = []
            if caller_policy is not None:
                clauses.append("access_policy_ref = ?")
                params.append(caller_policy)
            if allowed_classifications is not None:
                ph = ",".join("?" for _ in allowed_classifications)
                clauses.append(f"classification IN ({ph})")
                params.extend(list(allowed_classifications))
            query_sql = f"SELECT source_id FROM mctx_sources WHERE {' AND '.join(clauses)}"
            rows = self.conn.execute(query_sql, params).fetchall()
            allowed_sources = {r[0] for r in rows}
            if not allowed_sources:
                return []

        # 1. Busca Léxica BM25 (FTS5)
        raw_fts_tokens = tokens(query)
        clean = [t for t in raw_fts_tokens if len(t) >= 2]
        lexical_ranks: dict[str, int] = {}
        lexical_raw_scores: dict[str, float] = {}

        if clean:
            fts_query = " OR ".join(f'"{t}"' for t in clean[:32])
            try:
                rows = self.conn.execute(
                    """SELECT chunk_id, source_id, bm25(mctx_chunks_fts) as score
                       FROM mctx_chunks_fts
                       WHERE mctx_chunks_fts MATCH ?
                       ORDER BY bm25(mctx_chunks_fts)
                       LIMIT ?""",
                    (fts_query, limit * 6),
                ).fetchall()
                rank_counter = 1
                for cid, sid, score in rows:
                    if allowed_sources is not None and sid not in allowed_sources:
                        continue
                    lexical_ranks[cid] = rank_counter
                    lexical_raw_scores[cid] = abs(float(score))
                    rank_counter += 1
            except Exception:
                pass

        # 2. Busca Semântica Densa (Vectors)
        query_vec = self.embedding.embed(query)
        if allowed_sources is not None:
            ph = ",".join("?" for _ in allowed_sources)
            rows = self.conn.execute(
                f"SELECT chunk_id, vector FROM mctx_chunks WHERE source_id IN ({ph})",
                list(allowed_sources),
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT chunk_id, vector FROM mctx_chunks").fetchall()

        sem_candidates: list[tuple[str, float]] = []
        for cid, vec_json in rows:
            vec = json.loads(vec_json)
            sim = cosine(query_vec, vec)
            sem_candidates.append((cid, float(sim)))

        sem_candidates.sort(key=lambda x: x[1], reverse=True)
        semantic_ranks: dict[str, int] = {}
        semantic_raw_scores: dict[str, float] = {}
        for rank, (cid, sim) in enumerate(sem_candidates[: limit * 4], start=1):
            semantic_ranks[cid] = rank
            semantic_raw_scores[cid] = max(0.0, sim)

        # 3. Metadados dos chunks
        all_cids = set(lexical_ranks.keys()) | set(semantic_ranks.keys())
        chunk_meta: dict[str, dict[str, Any]] = {}
        if all_cids:
            placeholders = ",".join("?" for _ in all_cids)
            meta_rows = self.conn.execute(
                f"""SELECT chunk_id, source_id, section, level_l2, level_l3
                    FROM mctx_chunks WHERE chunk_id IN ({placeholders})""",
                list(all_cids),
            ).fetchall()
            for r in meta_rows:
                chunk_meta[r[0]] = {
                    "source_id": r[1],
                    "section": r[2],
                    "text": r[4],  # Texto completo L3
                }

        # 4. Dynamic Intent-Aware RRF
        hits = self.rrf.fuse(
            query=query,
            lexical_ranks=lexical_ranks,
            semantic_ranks=semantic_ranks,
            chunk_metadata=chunk_meta,
            lexical_raw_scores=lexical_raw_scores,
            semantic_raw_scores=semantic_raw_scores,
        )

        return hits[:limit]

    def retrieve_with_self_rag(
        self,
        query: str,
        budget: TokenBudget | None = None,
        limit: int = 10,
        caller_policy: str | None = None,
        allowed_classifications: list[str] | set[str] | None = None,
    ) -> EvidencePackage:
        """Executa recuperação híbrida seguida de auto-reflexão e escalonamento Self-RAG sob orçamento."""
        hits = self.retrieve(
            query,
            limit=limit,
            caller_policy=caller_policy,
            allowed_classifications=allowed_classifications,
        )
        if not hits:
            orchestrator = SelfRAGOrchestrator(budget=budget)
            _, package = orchestrator.evaluate_and_escalate(query, [], [])
            return package

        # Busca os SemanticChunks correspondentes aos hits
        chunks: list[SemanticChunk] = []
        cids = [h.chunk_id for h in hits]
        placeholders = ",".join("?" for _ in cids)
        rows = self.conn.execute(
            f"""SELECT chunk_id, source_id, chunk_index, section,
                       level_l0, level_l1, level_l2, level_l3, level_l4,
                       span_start, span_end
                FROM mctx_chunks WHERE chunk_id IN ({placeholders})""",
            cids,
        ).fetchall()

        rows_map = {r[0]: r for r in rows}
        for cid in cids:
            if cid in rows_map:
                r = rows_map[cid]
                levels = {
                    RepresentationLevel.L0: r[4],
                    RepresentationLevel.L1: r[5],
                    RepresentationLevel.L2: r[6],
                    RepresentationLevel.L3: r[7],
                    RepresentationLevel.L4: r[8],
                }
                toks = {k: estimate_tokens(v) for k, v in levels.items()}
                chunks.append(
                    SemanticChunk(
                        chunk_id=r[0],
                        doc_id=r[1],
                        chunk_index=r[2],
                        section=r[3],
                        levels=levels,
                        token_counts=toks,
                        span_start=r[9],
                        span_end=r[10],
                    )
                )

        orchestrator = SelfRAGOrchestrator(budget=budget)
        initial_candidates = [(c, RepresentationLevel.L1) for c in chunks]
        _, package = orchestrator.evaluate_and_escalate(query, initial_candidates, chunks)
        return package

    def build_context_package(
        self,
        hits: list[IntentAwareHit],
        budget: TokenBudget | None = None,
    ) -> EvidencePackage:
        """Constrói um pacote de contexto protegido com contenção de prompt injection."""
        b = budget or TokenBudget()
        raw_items: list[tuple[str, str, str]] = [(h.source_id, h.chunk_id, h.text) for h in hits]
        formatted_context, total_tokens = build_contained_context(raw_items, budget=b)

        return EvidencePackage(
            query="",
            evidence_items=[],
            active_levels={},
            total_tokens=total_tokens,
            formatted_context=formatted_context,
            system_instruction=default_mctx_system_instruction(),
            budget=b,
        )

    def _build_manifest(
        self,
        source_id: str,
        logical_ref: str,
        checksum: str,
        merkle_root: str,
        classification: str = "engineering",
        access_policy_ref: str = "policy:mark-dev",
    ) -> MCTXManifest:
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        m = MCTXManifest(
            format="mctx",
            format_version="1.0",
            corpus_id="mark-engineering",
            created_at=now_iso,
            updated_at=now_iso,
            storage=StorageConfig(adapter="filesystem", root_id="local-corpus-root"),
            source_catalog=[
                SourceDescriptor(
                    source_id=source_id,
                    logical_ref=logical_ref,
                    media_type="text/plain",
                    content_hash=checksum,
                    version="1.0",
                    classification=classification,
                    access_policy_ref=access_policy_ref,
                )
            ],
            index_catalog=[
                IndexDescriptor(index_id="idx-lex-v1", kind="lexical", build_id="build-mctx"),
                IndexDescriptor(
                    index_id="idx-vec-v1",
                    kind="vector",
                    embedding_model_id="hash-embedding",
                    dimensions=64,
                    build_id="build-mctx",
                ),
            ],
            retrieval_profile=RetrievalProfile(
                hybrid=True,
                lexical_candidates=80,
                vector_candidates=80,
                rerank_limit=40,
                max_expansion_depth=2,
                max_rounds=4,
            ),
            chunking_profile=ChunkingProfile(
                profile_id="semantic-adaptive-v1",
                target_tokens=450,
                overlap_tokens=60,
                preserve_source_offsets=True,
                method="semantic_adaptive",
            ),
            integrity=IntegritySection(
                manifest_hash="",
                merkle_root=merkle_root,
            ),
            extensions={},
        )
        h = compute_canonical_manifest_hash(m)
        m.integrity.manifest_hash = f"sha256:{h}"
        return m

    def apply_remote_sync_package(
        self,
        source_id: str,
        chunks: list[dict[str, Any]],
        fail_at_chunk_index: int | None = None,
    ) -> bool:
        """Aplica pacote de sincronização remota sob transação SQLite atômica com savepoint.

        Se ocorrer falha (queda de rede, I/O ou erro de validação), restaura
        integralmente o estado anterior (rollback total), sem chunks parciais nem
        dessincronização com o índice FTS5.
        """
        from .sync_state import MCTXSyncError

        savepoint_name = f"sp_sync_{int(time.time() * 1000)}"
        self.conn.execute(f"SAVEPOINT {savepoint_name}")

        try:
            now = int(time.time())
            # Limpa chunks antigos da fonte sob o savepoint
            self.conn.execute("DELETE FROM mctx_chunks WHERE source_id = ?", (source_id,))
            self.conn.execute("DELETE FROM mctx_chunks_fts WHERE source_id = ?", (source_id,))

            for i, c in enumerate(chunks):
                if fail_at_chunk_index is not None and i >= fail_at_chunk_index:
                    raise ConnectionResetError(f"Simulated network drop at chunk {i}")

                cid = c["chunk_id"]
                c_idx = c.get("chunk_index", i)
                section = c.get("section", "Geral")
                l0 = c.get("level_l0", "")
                l1 = c.get("level_l1", "")
                l2 = c.get("level_l2", "")
                l3 = c.get("level_l3", c.get("text", ""))
                l4 = c.get("level_l4", "")

                vec = self._get_or_compute_embedding(l2 or l3)
                c_hash = hashlib.sha256(l3.encode("utf-8")).hexdigest()

                self.conn.execute(
                    """INSERT INTO mctx_chunks
                       (chunk_id, source_id, chunk_index, section, level_l0, level_l1, level_l2, level_l3, level_l4,
                        vector, content_hash, span_start, span_end, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        cid,
                        source_id,
                        c_idx,
                        section,
                        l0,
                        l1,
                        l2,
                        l3,
                        l4,
                        json.dumps(vec),
                        f"sha256:{c_hash}",
                        c.get("span_start", 0),
                        c.get("span_end", len(l3)),
                        now,
                    ),
                )
                self.conn.execute(
                    "INSERT INTO mctx_chunks_fts (chunk_id, source_id, content) VALUES (?, ?, ?)",
                    (cid, source_id, l3),
                )

            self.conn.execute(f"RELEASE SAVEPOINT {savepoint_name}")
            return True

        except Exception as e:
            self.conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
            self.conn.execute(f"RELEASE SAVEPOINT {savepoint_name}")
            if isinstance(e, (ConnectionResetError, TimeoutError)):
                raise e
            raise MCTXSyncError(f"Erro na sincronização de chunks para '{source_id}': {e}") from e

    def close(self) -> None:
        if hasattr(self, "conn"):
            self.conn.close()
