"""Fusão Híbrida Dinâmica Sensível à Intenção (Intent-Aware Dynamic RRF).

Substitui o baseline estático de RRF (k=60 fixo) por um classificador de intenção
e multiplicadores dinâmicos de rank/peso para elevar recall de símbolos exatos de código
sem inflar a latência do sistema.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import re
from typing import Any


class QueryIntent(str, Enum):
    CODE_EXACT = "code_exact"
    CONCEPTUAL = "conceptual"
    HYBRID = "hybrid"


_CODE_SYMBOLS_RE = re.compile(
    r"(?:::|->|=>|\b(?:def|class|fn|pub|impl|struct|enum|import|from|return|assert|let|const|var)\b|[{}()\[\];`'\"]|0x[0-9a-fA-F]+|\bsha256:[0-9a-fA-F]+|\.(?:py|rs|json|mctx|sqlite3|md|env|toml|yaml|txt)\b)"
)
_IDENTIFIER_RE = re.compile(
    r"\b[a-zA-Z_][a-zA-Z0-9_]*[._][a-zA-Z0-9_]+\b|\b(?:[a-z]+[A-Z]|[A-Z]+[a-z0-9]+[A-Z]|[A-Z][a-z0-9]+[A-Z])[a-zA-Z0-9]*\b|\b[A-Z][a-zA-Z0-9]*(?:Error|Exception|Panic|Traceback)\b"
)
_CONCEPTUAL_PREFIX_RE = re.compile(
    r"(?i)^(?:como|por que|porque|quais|qual|explique|descreva|resuma|vis[aã]o geral|o que [eé]|how|why|what|explain|describe|overview|summarize)\b"
)


def classify_query_intent(query: str) -> QueryIntent:
    """Classifica a consulta em menos de 0.1ms com heurística lexical compilada."""
    q = query.strip()
    if not q:
        return QueryIntent.HYBRID

    has_code_syntax = bool(_CODE_SYMBOLS_RE.search(q))
    has_identifier = bool(_IDENTIFIER_RE.search(q))
    has_conceptual = bool(_CONCEPTUAL_PREFIX_RE.search(q))

    if (has_code_syntax or has_identifier) and not has_conceptual:
        return QueryIntent.CODE_EXACT

    if has_conceptual and not (has_code_syntax or has_identifier):
        return QueryIntent.CONCEPTUAL

    # Se tiver ambos (ex: "como funciona a função McpBridge::execute_tool()")
    if has_code_syntax or has_identifier:
        # Quando há um identificador explícito de código, a precisão lexical é crítica
        return QueryIntent.CODE_EXACT

    return QueryIntent.HYBRID


@dataclass
class IntentAwareHit:
    chunk_id: str
    combined_score: float
    rank: int = 0
    intent: QueryIntent = QueryIntent.HYBRID
    lexical_rank: int | None = None
    semantic_rank: int | None = None
    lexical_score: float = 0.0
    semantic_score: float = 0.0
    text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    source_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "combined_score": round(self.combined_score, 6),
            "rank": self.rank,
            "intent": self.intent.value,
            "lexical_rank": self.lexical_rank,
            "semantic_rank": self.semantic_rank,
            "lexical_score": round(self.lexical_score, 4),
            "semantic_score": round(self.semantic_score, 4),
            "text": self.text,
            "metadata": self.metadata,
            "source_id": self.source_id,
        }


class DynamicIntentRRF:
    """Motor de fusão RRF ponderado sensível à intenção detectada na consulta."""

    def __init__(
        self,
        code_lexical_weight: float = 0.85,
        code_semantic_weight: float = 0.15,
        code_k_lex: int = 20,
        code_k_sem: int = 100,
        conceptual_lexical_weight: float = 0.20,
        conceptual_semantic_weight: float = 0.80,
        conceptual_k_lex: int = 80,
        conceptual_k_sem: int = 40,
        hybrid_lexical_weight: float = 0.50,
        hybrid_semantic_weight: float = 0.50,
        hybrid_k_lex: int = 60,
        hybrid_k_sem: int = 60,
    ) -> None:
        self.weights = {
            QueryIntent.CODE_EXACT: (code_lexical_weight, code_semantic_weight, code_k_lex, code_k_sem),
            QueryIntent.CONCEPTUAL: (conceptual_lexical_weight, conceptual_semantic_weight, conceptual_k_lex, conceptual_k_sem),
            QueryIntent.HYBRID: (hybrid_lexical_weight, hybrid_semantic_weight, hybrid_k_lex, hybrid_k_sem),
        }

    def fuse(
        self,
        query: str,
        lexical_ranks: dict[str, int],
        semantic_ranks: dict[str, int],
        chunk_metadata: dict[str, dict[str, Any]] | None = None,
        lexical_raw_scores: dict[str, float] | None = None,
        semantic_raw_scores: dict[str, float] | None = None,
    ) -> list[IntentAwareHit]:
        """Aplica o RRF dinâmico ajustando multiplicadores conforme a intenção da query."""
        intent = classify_query_intent(query)
        w_lex, w_sem, k_lex, k_sem = self.weights[intent]

        chunk_meta = chunk_metadata or {}
        raw_lex = lexical_raw_scores or {}
        raw_sem = semantic_raw_scores or {}

        all_cids = set(lexical_ranks.keys()) | set(semantic_ranks.keys())
        hits: list[IntentAwareHit] = []

        for cid in all_cids:
            lex_rank = lexical_ranks.get(cid)
            sem_rank = semantic_ranks.get(cid)

            rrf_lex = (1.0 / (k_lex + lex_rank)) if lex_rank is not None else 0.0
            rrf_sem = (1.0 / (k_sem + sem_rank)) if sem_rank is not None else 0.0

            combined = (w_lex * rrf_lex) + (w_sem * rrf_sem)

            meta = chunk_meta.get(cid, {})
            text = meta.get("text", "")
            source_id = meta.get("source_id", "")

            hits.append(
                IntentAwareHit(
                    chunk_id=cid,
                    combined_score=combined,
                    intent=intent,
                    lexical_rank=lex_rank,
                    semantic_rank=sem_rank,
                    lexical_score=raw_lex.get(cid, 0.0),
                    semantic_score=raw_sem.get(cid, 0.0),
                    text=text,
                    metadata=meta,
                    source_id=source_id,
                )
            )

        hits.sort(key=lambda h: h.combined_score, reverse=True)
        for idx, hit in enumerate(hits, start=1):
            hit.rank = idx

        return hits
