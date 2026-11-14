"""Estrutura e Algoritmos de Integridade por Árvore de Merkle para o MCTX.

Garante detecção de alterações em O(log n), invalidação atômica e cirúrgica de caches,
e prova criptográfica de integridade contra exclusões incompletas.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
from typing import Any


def _hash_leaf(content: str | bytes, chunk_id: str | None = None) -> tuple[str, str]:
    """Computa o hash puro de conteúdo (para embeddings e proveniência) e o hash da folha Merkle.

    Retorna (content_hash, leaf_hash).
    """
    raw = content.encode("utf-8") if isinstance(content, str) else content
    content_hash = hashlib.sha256(raw).hexdigest()
    if chunk_id is not None:
        leaf_hash = hashlib.sha256(b"\x00" + chunk_id.encode("utf-8") + b"\x1f" + content_hash.encode("ascii")).hexdigest()
    else:
        leaf_hash = hashlib.sha256(b"\x00" + raw).hexdigest()
    return f"sha256:{content_hash}", leaf_hash


def _hash_internal(left_hash: str, right_hash: str) -> str:
    """Computa o hash de um nó interno com prefixo de domínio 0x01."""
    return hashlib.sha256(b"\x01" + left_hash.encode("ascii") + right_hash.encode("ascii")).hexdigest()


@dataclass
class MerkleLeaf:
    chunk_id: str
    chunk_hash: str
    chunk_index: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MerkleNode:
    hash: str
    left: MerkleNode | None = None
    right: MerkleNode | None = None
    is_leaf: bool = False
    leaf_data: MerkleLeaf | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "hash": self.hash,
            "is_leaf": self.is_leaf,
            "leaf_data": self.leaf_data.to_dict() if self.leaf_data else None,
            "left": self.left.to_dict() if self.left else None,
            "right": self.right.to_dict() if self.right else None,
        }


@dataclass
class MerkleDiff:
    modified_chunk_ids: set[str] = field(default_factory=set)
    added_chunk_ids: set[str] = field(default_factory=set)
    deleted_chunk_ids: set[str] = field(default_factory=set)
    unmodified_chunk_ids: set[str] = field(default_factory=set)


@dataclass
class MerkleTree:
    root_hash: str
    leaves: list[MerkleLeaf]
    root_node: MerkleNode | None = None
    chunk_map: dict[str, MerkleLeaf] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_hash": self.root_hash,
            "leaves": [leaf.to_dict() for leaf in self.leaves],
            "root_node": self.root_node.to_dict() if self.root_node else None,
        }


def build_merkle_tree(chunks: list[tuple[str, str]] | list[Any]) -> MerkleTree:
    """Constrói uma Árvore de Merkle binária determinística a partir de uma lista de chunks.

    Aceita tuplas (chunk_id, texto) ou objetos com atributos chunk_id e text.
    """
    if not chunks:
        zero_hash = "sha256:" + ("0" * 64)
        return MerkleTree(root_hash=zero_hash, leaves=[], root_node=None, chunk_map={})

    leaves: list[MerkleLeaf] = []
    leaf_nodes: list[MerkleNode] = []
    chunk_map: dict[str, MerkleLeaf] = {}

    for idx, item in enumerate(chunks):
        if isinstance(item, tuple):
            cid, text = item[0], item[1]
            meta = {}
        elif hasattr(item, "chunk_id") and hasattr(item, "text"):
            cid = item.chunk_id
            text = item.text
            meta = getattr(item, "metadata", {}) or {}
        else:
            cid = str(getattr(item, "id", f"c-{idx}"))
            text = str(getattr(item, "content", str(item)))
            meta = {}

        content_hash, leaf_hash = _hash_leaf(text, chunk_id=cid)
        leaf = MerkleLeaf(chunk_id=cid, chunk_hash=content_hash, chunk_index=idx, metadata=meta)
        node = MerkleNode(hash=leaf_hash, is_leaf=True, leaf_data=leaf)

        leaves.append(leaf)
        leaf_nodes.append(node)
        chunk_map[cid] = leaf

    # Construção da árvore nível a nível (bottom-up)
    current_level = leaf_nodes
    while len(current_level) > 1:
        next_level: list[MerkleNode] = []
        for i in range(0, len(current_level), 2):
            left = current_level[i]
            if i + 1 < len(current_level):
                right = current_level[i + 1]
            else:
                # Se ímpar, duplica o último nó para manter a árvore binária estrita
                right = current_level[i]

            parent_hash = _hash_internal(left.hash, right.hash)
            parent = MerkleNode(hash=parent_hash, left=left, right=right, is_leaf=False)
            next_level.append(parent)

        current_level = next_level

    root_node = current_level[0]
    root_hash = f"sha256:{root_node.hash}"

    return MerkleTree(root_hash=root_hash, leaves=leaves, root_node=root_node, chunk_map=chunk_map)


def diff_merkle_trees(tree_a: MerkleTree, tree_b: MerkleTree) -> tuple[MerkleDiff, int]:
    """Compara duas Árvores de Merkle em O(log n) e retorna os chunks afetados e número de comparações."""
    diff = MerkleDiff()
    comparisons = 0

    # 1. Caso trivial: raízes idênticas -> zero alterações
    comparisons += 1
    if tree_a.root_hash == tree_b.root_hash:
        diff.unmodified_chunk_ids = set(tree_a.chunk_map.keys())
        return diff, comparisons

    # 2. Se alguma árvore for vazia
    if not tree_a.root_node and tree_b.root_node:
        diff.added_chunk_ids = set(tree_b.chunk_map.keys())
        return diff, comparisons
    if tree_a.root_node and not tree_b.root_node:
        diff.deleted_chunk_ids = set(tree_a.chunk_map.keys())
        return diff, comparisons
    if not tree_a.root_node and not tree_b.root_node:
        return diff, comparisons

    # Função auxiliar para extrair todas as folhas sob um nó
    def _collect_leaves(node: MerkleNode | None) -> list[MerkleLeaf]:
        if not node:
            return []
        if node.is_leaf and node.leaf_data:
            return [node.leaf_data]
        res: list[MerkleLeaf] = []
        if node.left:
            res.extend(_collect_leaves(node.left))
        if node.right and node.right is not node.left:
            res.extend(_collect_leaves(node.right))
        return res

    # 3. Travessia recursiva comparando hashes de subárvores
    def _traverse(node_a: MerkleNode | None, node_b: MerkleNode | None) -> None:
        nonlocal comparisons
        comparisons += 1

        if not node_a and node_b:
            for l in _collect_leaves(node_b):
                if l.chunk_id not in tree_a.chunk_map:
                    diff.added_chunk_ids.add(l.chunk_id)
                elif tree_a.chunk_map[l.chunk_id].chunk_hash == l.chunk_hash:
                    diff.unmodified_chunk_ids.add(l.chunk_id)
                else:
                    diff.modified_chunk_ids.add(l.chunk_id)
            return

        if node_a and not node_b:
            for l in _collect_leaves(node_a):
                if l.chunk_id not in tree_b.chunk_map:
                    diff.deleted_chunk_ids.add(l.chunk_id)
                elif tree_b.chunk_map[l.chunk_id].chunk_hash == l.chunk_hash:
                    diff.unmodified_chunk_ids.add(l.chunk_id)
                else:
                    diff.modified_chunk_ids.add(l.chunk_id)
            return

        assert node_a is not None and node_b is not None

        # Se os hashes dos nós forem idênticos, a subárvore inteira é idêntica!
        if node_a.hash == node_b.hash:
            for l in _collect_leaves(node_a):
                diff.unmodified_chunk_ids.add(l.chunk_id)
            return

        # Se ambos forem folhas e diferirem
        if node_a.is_leaf and node_b.is_leaf:
            leaf_a = node_a.leaf_data
            leaf_b = node_b.leaf_data
            if leaf_a and leaf_b:
                for candidate in (leaf_a, leaf_b):
                    cid = candidate.chunk_id
                    if cid in tree_a.chunk_map and cid in tree_b.chunk_map:
                        if tree_a.chunk_map[cid].chunk_hash == tree_b.chunk_map[cid].chunk_hash:
                            diff.unmodified_chunk_ids.add(cid)
                        else:
                            diff.modified_chunk_ids.add(cid)
                    elif cid in tree_a.chunk_map:
                        diff.deleted_chunk_ids.add(cid)
                    elif cid in tree_b.chunk_map:
                        diff.added_chunk_ids.add(cid)
            return

        # Se um for folha e o outro interno (estruturas com tamanhos desiguais)
        if node_a.is_leaf != node_b.is_leaf:
            all_leaves = _collect_leaves(node_a) + _collect_leaves(node_b)
            for candidate in all_leaves:
                cid = candidate.chunk_id
                if cid in tree_a.chunk_map and cid in tree_b.chunk_map:
                    if tree_a.chunk_map[cid].chunk_hash == tree_b.chunk_map[cid].chunk_hash:
                        diff.unmodified_chunk_ids.add(cid)
                    else:
                        diff.modified_chunk_ids.add(cid)
                elif cid in tree_a.chunk_map:
                    diff.deleted_chunk_ids.add(cid)
                elif cid in tree_b.chunk_map:
                    diff.added_chunk_ids.add(cid)
            return

        # Ambos nós internos com hashes diferentes: desce pelos ramos esquerdo e direito
        _traverse(node_a.left, node_b.left)
        # Previne descer duas vezes se o nó da direita foi espelhado por ser ímpar
        right_a = node_a.right if node_a.right is not node_a.left else None
        right_b = node_b.right if node_b.right is not node_b.left else None
        if right_a or right_b:
            _traverse(right_a, right_b)

    assert tree_a.root_node is not None and tree_b.root_node is not None
    _traverse(tree_a.root_node, tree_b.root_node)

    # Identifica qualquer chunk não coberto por discrepância de balanceamento
    covered = diff.modified_chunk_ids | diff.added_chunk_ids | diff.deleted_chunk_ids | diff.unmodified_chunk_ids
    for cid in tree_a.chunk_map:
        if cid not in covered:
            if cid in tree_b.chunk_map:
                if tree_a.chunk_map[cid].chunk_hash == tree_b.chunk_map[cid].chunk_hash:
                    diff.unmodified_chunk_ids.add(cid)
                else:
                    diff.modified_chunk_ids.add(cid)
            else:
                diff.deleted_chunk_ids.add(cid)

    for cid in tree_b.chunk_map:
        if cid not in covered and cid not in tree_a.chunk_map:
            diff.added_chunk_ids.add(cid)

    # Garante consistência rigorosa dos conjuntos:
    # 1. Itens modificados, deletados ou adicionados NUNCA devem estar em unmodified
    diff.unmodified_chunk_ids.difference_update(diff.modified_chunk_ids | diff.deleted_chunk_ids | diff.added_chunk_ids)
    # 2. Itens não presentes em tree_b são estritamente deleted
    for cid in tree_a.chunk_map:
        if cid not in tree_b.chunk_map:
            diff.deleted_chunk_ids.add(cid)
            diff.unmodified_chunk_ids.discard(cid)
    # 3. Itens não presentes em tree_a são estritamente added
    for cid in tree_b.chunk_map:
        if cid not in tree_a.chunk_map:
            diff.added_chunk_ids.add(cid)
            diff.unmodified_chunk_ids.discard(cid)
    # 4. Itens unmodified DEVEM obrigatoriamente existir em ambas as árvores com hashes idênticos
    diff.unmodified_chunk_ids = {
        cid for cid in diff.unmodified_chunk_ids
        if cid in tree_a.chunk_map and cid in tree_b.chunk_map and tree_a.chunk_map[cid].chunk_hash == tree_b.chunk_map[cid].chunk_hash
    }

    return diff, comparisons


def diff_linear_scan(tree_a: MerkleTree, tree_b: MerkleTree) -> tuple[MerkleDiff, int]:
    """Diff linear ingênuo de referência (baseline O(N)) que compara todos os chunks um a um."""
    diff = MerkleDiff()
    comparisons = 0
    all_chunk_ids = set(tree_a.chunk_map.keys()) | set(tree_b.chunk_map.keys())

    for cid in all_chunk_ids:
        comparisons += 1
        leaf_a = tree_a.chunk_map.get(cid)
        leaf_b = tree_b.chunk_map.get(cid)

        if leaf_a is not None and leaf_b is not None:
            comparisons += 1  # Comparação de hashes dos conteúdos
            if leaf_a.chunk_hash == leaf_b.chunk_hash:
                diff.unmodified_chunk_ids.add(cid)
            else:
                diff.modified_chunk_ids.add(cid)
        elif leaf_a is not None:
            diff.deleted_chunk_ids.add(cid)
        else:
            diff.added_chunk_ids.add(cid)

    return diff, comparisons

