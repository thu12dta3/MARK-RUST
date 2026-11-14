"""Context Virtualizer (.mctx) para o ecossistema MARK.

Fornece formato de manifesto seguro, integridade por Árvore de Merkle,
fusão híbrida dinâmica sensível à intenção (Dynamic Intent-Aware RRF),
chunking semântico adaptativo (níveis L0 a L4) e auto-reflexão Self-RAG.
"""

from .chunking import (
    AdaptiveSemanticChunker,
    RepresentationLevel,
    SemanticChunk,
    estimate_tokens,
)
from .fusion import (
    DynamicIntentRRF,
    IntentAwareHit,
    QueryIntent,
    classify_query_intent,
)
from .manifest import (
    ChunkingProfile,
    IndexDescriptor,
    IntegritySection,
    MCTXError,
    MCTXManifest,
    MCTXParser,
    MCTXSecurityError,
    MCTXValidationError,
    RetrievalProfile,
    SignatureSection,
    SourceDescriptor,
    StorageConfig,
    compute_canonical_manifest_hash,
    resolve_inside_root,
    sign_manifest,
    verify_manifest_crypto,
    verify_manifest_signature,
)
from .sync_state import (
    DeviceStatus,
    DeviceSyncRecord,
    DeviceSyncRegistry,
    MCTXAuthorizationError,
    MCTXReplayAttackError,
    MCTXSyncError,
    authorize_manifest_sync,
    verify_mctx_sync_gate,
)
from .merkle import (
    MerkleDiff,
    MerkleLeaf,
    MerkleNode,
    MerkleTree,
    build_merkle_tree,
    diff_linear_scan,
    diff_merkle_trees,
)
from .pipeline import MCTXEngine
from .self_rag import (
    EvidencePackage,
    ReflectionTag,
    SelfRAGOrchestrator,
    SelfRAGReflection,
    TokenBudget,
    default_mctx_system_instruction,
    synthesize_grounded_response,
    verify_grounded_citations,
)

__all__ = [
    # Manifest
    "MCTXManifest",
    "MCTXParser",
    "MCTXError",
    "MCTXSecurityError",
    "MCTXValidationError",
    "StorageConfig",
    "SourceDescriptor",
    "IndexDescriptor",
    "RetrievalProfile",
    "ChunkingProfile",
    "IntegritySection",
    "SignatureSection",
    "sign_manifest",
    "verify_manifest_crypto",
    "verify_manifest_signature",
    "compute_canonical_manifest_hash",
    "resolve_inside_root",
    # Sync State & Authorization
    "DeviceStatus",
    "DeviceSyncRecord",
    "DeviceSyncRegistry",
    "MCTXSyncError",
    "MCTXAuthorizationError",
    "MCTXReplayAttackError",
    "authorize_manifest_sync",
    "verify_mctx_sync_gate",
    # Merkle Tree
    "MerkleTree",
    "MerkleNode",
    "MerkleLeaf",
    "MerkleDiff",
    "build_merkle_tree",
    "diff_merkle_trees",
    "diff_linear_scan",
    # Dynamic RRF
    "DynamicIntentRRF",
    "IntentAwareHit",
    "QueryIntent",
    "classify_query_intent",
    # Adaptive Chunking
    "AdaptiveSemanticChunker",
    "SemanticChunk",
    "RepresentationLevel",
    "estimate_tokens",
    # Self-RAG
    "SelfRAGOrchestrator",
    "SelfRAGReflection",
    "EvidencePackage",
    "ReflectionTag",
    "TokenBudget",
    "default_mctx_system_instruction",
    "synthesize_grounded_response",
    "verify_grounded_citations",
    # Unified Pipeline
    "MCTXEngine",
]
