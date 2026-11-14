"""Chunking Semântico Adaptativo e Níveis de Representação (L0 a L4) do MCTX.

Substitui a segmentação rígida por janelas fixas por um particionamento adaptativo
que respeita fronteiras estruturais (headings, blocos de código, assinaturas de funções)
e gera múltiplos níveis de representação para escalonamento dinâmico.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import hashlib
import re
from typing import Any


class RepresentationLevel(str, Enum):
    L0 = "L0"  # Metadados e palavras-chave (Descoberta)
    L1 = "L1"  # Resumo curto com referência ao original (Triagem)
    L2 = "L2"  # Fragmento com contexto adjacente (Consulta comum)
    L3 = "L3"  # Fonte ampla, bloco de código ou arquivo completo (Depuração e decisões críticas)
    L4 = "L4"  # Evidências cruzadas, testes e histórico (Auditoria)


@dataclass
class SemanticChunk:
    chunk_id: str
    doc_id: str
    chunk_index: int
    levels: dict[RepresentationLevel, str]
    token_counts: dict[RepresentationLevel, int]
    section: str = ""
    span_start: int = 0
    span_end: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        """Retorna o texto no nível padrão de consulta L2 (ou L3 se L2 não existir)."""
        return self.levels.get(RepresentationLevel.L2) or self.levels.get(RepresentationLevel.L3, "")

    def get_text(self, level: RepresentationLevel = RepresentationLevel.L2) -> str:
        return self.levels.get(level, self.text)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "chunk_index": self.chunk_index,
            "levels": {k.value: v for k, v in self.levels.items()},
            "token_counts": {k.value: v for k, v in self.token_counts.items()},
            "section": self.section,
            "span_start": self.span_start,
            "span_end": self.span_end,
            "metadata": self.metadata,
        }


def estimate_tokens(text: str) -> int:
    """Estimativa de tokens determinística e conservadora (1 token ~ 3.8 caracteres)."""
    if not text:
        return 0
    words = text.split()
    chars = len(text)
    # Usa o maior entre contagem de palavras e chars/3.8
    return max(len(words), max(1, int(chars / 3.8)))


class AdaptiveSemanticChunker:
    """Chunker semântico adaptativo que preserva fronteiras e produz níveis L0-L4."""

    def __init__(self, target_tokens: int = 400, overlap_tokens: int = 50) -> None:
        self.target_tokens = target_tokens
        self.overlap_tokens = overlap_tokens

    def chunk_document(self, doc_id: str, text: str, title: str = "") -> list[SemanticChunk]:
        """Segmenta o texto de um documento respeitando blocos estruturais e semânticos."""
        if not text or not text.strip():
            return []

        # 1. Isola blocos protegidos (blocos de código delimitados por ```)
        raw_blocks = self._split_into_structural_blocks(text)
        chunks: list[SemanticChunk] = []

        chunk_idx = 0
        current_section = title or "Introdução"

        for b_start, b_end, b_text, is_code, section_header in raw_blocks:
            if section_header:
                current_section = section_header

            if is_code:
                # Blocos de código não são quebrados internamente para não mutilar contexto sintático
                c = self._create_semantic_chunk(
                    doc_id=doc_id,
                    chunk_index=chunk_idx,
                    section=current_section,
                    body=b_text,
                    span_start=b_start,
                    span_end=b_end,
                    is_code=True,
                )
                chunks.append(c)
                chunk_idx += 1
            else:
                # Texto narrativo: particiona por sentenças ou parágrafos
                sub_chunks = self._chunk_prose(
                    doc_id=doc_id,
                    start_idx=chunk_idx,
                    section=current_section,
                    prose=b_text,
                    base_offset=b_start,
                )
                for sc in sub_chunks:
                    chunks.append(sc)
                    chunk_idx += 1

        return chunks

    def _split_into_structural_blocks(self, text: str) -> list[tuple[int, int, str, bool, str]]:
        """Divide o texto em tuplas (start, end, content, is_code, section_header)."""
        blocks: list[tuple[int, int, str, bool, str]] = []
        code_block_pattern = re.compile(r"```[a-zA-Z0-9_\-]*\n.*?```", re.DOTALL)
        heading_pattern = re.compile(r"^(#{1,6}\s+[^\n]+)", re.MULTILINE)

        last_pos = 0
        for match in code_block_pattern.finditer(text):
            m_start, m_end = match.span()
            if m_start > last_pos:
                prose = text[last_pos:m_start]
                if prose.strip():
                    blocks.append((last_pos, m_start, prose, False, ""))
            code_text = text[m_start:m_end]
            blocks.append((m_start, m_end, code_text, True, ""))
            last_pos = m_end

        if last_pos < len(text):
            remaining = text[last_pos:]
            if remaining.strip():
                blocks.append((last_pos, len(text), remaining, False, ""))

        # Agora examina os blocos de prosa para detectar cabeçalhos de seção
        refined_blocks: list[tuple[int, int, str, bool, str]] = []
        for b_start, b_end, b_text, is_code, _ in blocks:
            if is_code:
                refined_blocks.append((b_start, b_end, b_text, True, ""))
                continue

            # Divide pelos cabeçalhos Markdown
            h_splits = list(heading_pattern.finditer(b_text))
            if h_splits:
                h_last = 0
                cur_head = ""
                for h in h_splits:
                    hs, he = h.span()
                    if hs > h_last:
                        part = b_text[h_last:hs]
                        if part.strip():
                            refined_blocks.append((b_start + h_last, b_start + hs, part, False, cur_head))
                    cur_head = re.sub(r"^#+\s*", "", h.group(1)).strip()
                    h_last = he

                if h_last < len(b_text):
                    part = b_text[h_last:]
                    if part.strip():
                        refined_blocks.append((b_start + h_last, b_end, part, False, cur_head))
                continue

            # Se não tem cabeçalhos Markdown, verifica declarações de funções/classes em código
            code_decl_splits = list(
                re.finditer(
                    r"^(?:def\s+[a-zA-Z0-9_]+|class\s+[a-zA-Z0-9_]+|fn\s+[a-zA-Z0-9_]+|pub\s+fn\s+[a-zA-Z0-9_]+|async\s+def\s+[a-zA-Z0-9_]+)",
                    b_text,
                    re.MULTILINE,
                )
            )
            if code_decl_splits:
                cd_last = 0
                cur_decl = ""
                for cd in code_decl_splits:
                    cs, ce = cd.span()
                    if cs > cd_last:
                        part = b_text[cd_last:cs]
                        if part.strip():
                            refined_blocks.append((b_start + cd_last, b_start + cs, part, True, cur_decl))
                    cur_decl = cd.group(0).strip()
                    cd_last = cs

                if cd_last < len(b_text):
                    part = b_text[cd_last:]
                    if part.strip():
                        refined_blocks.append((b_start + cd_last, b_end, part, True, cur_decl))
                continue

            refined_blocks.append((b_start, b_end, b_text, False, ""))

        return refined_blocks or [(0, len(text), text, False, "")]

    def _chunk_prose(
        self,
        doc_id: str,
        start_idx: int,
        section: str,
        prose: str,
        base_offset: int,
    ) -> list[SemanticChunk]:
        """Agrupa sentenças de prosa respeitando a meta de tokens e produzindo chunks semânticos."""
        paragraphs = [p.strip() for p in prose.split("\n\n") if p.strip()]
        if not paragraphs:
            return []

        chunks: list[SemanticChunk] = []
        cur_buffer: list[str] = []
        cur_tokens = 0
        cur_offset = base_offset
        chunk_counter = start_idx

        for p in paragraphs:
            p_tok = estimate_tokens(p)
            if cur_tokens + p_tok > self.target_tokens and cur_buffer:
                body = "\n\n".join(cur_buffer)
                chunks.append(
                    self._create_semantic_chunk(
                        doc_id=doc_id,
                        chunk_index=chunk_counter,
                        section=section,
                        body=body,
                        span_start=cur_offset,
                        span_end=cur_offset + len(body),
                        is_code=False,
                    )
                )
                chunk_counter += 1
                cur_offset += len(body) + 2
                cur_buffer = [p]
                cur_tokens = p_tok
            else:
                cur_buffer.append(p)
                cur_tokens += p_tok

        if cur_buffer:
            body = "\n\n".join(cur_buffer)
            chunks.append(
                self._create_semantic_chunk(
                    doc_id=doc_id,
                    chunk_index=chunk_counter,
                    section=section,
                    body=body,
                    span_start=cur_offset,
                    span_end=cur_offset + len(body),
                    is_code=False,
                )
            )

        return chunks

    def _create_semantic_chunk(
        self,
        doc_id: str,
        chunk_index: int,
        section: str,
        body: str,
        span_start: int,
        span_end: int,
        is_code: bool = False,
    ) -> SemanticChunk:
        """Gera os níveis L0, L1, L2, L3 e L4 para o fragmento textual."""
        cid = f"{doc_id}_c{chunk_index}"

        # L0: Descoberta e Metadados
        l0 = f"[{doc_id}#{chunk_index}] Seção: {section} | Tipo: {'Código' if is_code else 'Texto'}"

        # L1: Resumo Executivo conciso
        first_line = body.strip().splitlines()[0] if body.strip() else ""
        if is_code:
            l1 = f"Código ({section}): {first_line[:80]}... [Ver L3]"
        else:
            sentences = re.split(r"(?<=[.!?])\s+", body.strip())
            lead = sentences[0] if sentences else body[:60]
            if len(lead) > 60:
                lead = lead[:57] + "..."
            l1 = lead
            if len(l1) >= len(body):
                l1 = body[: max(25, int(len(body) * 0.6))].rstrip() + "..."

        # L2: Fragmento balanceado para consulta
        l2 = f"[Seção: {section}]\n{body}"

        # L3: Fonte completa e integral (verbatim)
        l3 = body

        # L4: Auditoria, proveniência e integridade
        body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        l4 = f"ChunkID: {cid} | DocID: {doc_id} | Hash: sha256:{body_hash} | Offsets: [{span_start}:{span_end}] | Seção: {section}"

        levels = {
            RepresentationLevel.L0: l0,
            RepresentationLevel.L1: l1,
            RepresentationLevel.L2: l2,
            RepresentationLevel.L3: l3,
            RepresentationLevel.L4: l4,
        }

        token_counts = {k: estimate_tokens(v) for k, v in levels.items()}

        return SemanticChunk(
            chunk_id=cid,
            doc_id=doc_id,
            chunk_index=chunk_index,
            levels=levels,
            token_counts=token_counts,
            section=section,
            span_start=span_start,
            span_end=span_end,
            metadata={"is_code": is_code, "body_hash": body_hash},
        )
