from __future__ import annotations

import logging
import math
import re
from typing import Any, Generator, Optional

try:
    import mark_core  # type: ignore
except ImportError:
    mark_core = None

from ..config.llm_config import get_local_inference_params

logger = logging.getLogger("mark.cognition.mark_local_provider")

MARK_LOCAL_CONTEXT_WINDOW = 2097152


def parse_intent_and_thinking(raw_text: str) -> dict[str, str]:
    intent = ""
    thinking = ""
    final_text = raw_text

    intent_match = re.search(r"<\|intent\|>(.*?)<\|/intent\|>", raw_text, re.DOTALL)
    if intent_match:
        intent = intent_match.group(1).strip()
        final_text = re.sub(r"<\|intent\|>.*?<\|/intent\|>", "", final_text, flags=re.DOTALL)

    think_match = re.search(r"<think>(.*?)</think>", final_text, re.DOTALL)
    if think_match:
        thinking = think_match.group(1).strip()
        final_text = re.sub(r"<think>.*?</think>", "", final_text, flags=re.DOTALL)

    return {
        "intent": intent,
        "thinking": thinking,
        "response": final_text.strip(),
    }


def calculate_semantic_entropy(top_probs: list[float]) -> float:
    if not top_probs:
        return 0.0
    total = sum(top_probs[:10])
    if total <= 0.0:
        return 0.0
    norm = [p / total for p in top_probs[:10] if p > 0.0]
    return float(-sum(p * math.log2(p) for p in norm))


def run_native_1bit_engine(
    prompt: str,
    system_prompt: str = "",
    max_tokens: int = 512,
    clan_id: int = 2,
    core_loops: int = 1,
    temperature: float = 0.2,
    num_ctx: int = 2097152,
) -> dict[str, Any]:
    """Invoca o motor Rust W1A4 XNOR-POPCNT (mark_core) liberando o GIL."""
    try:
        if mark_core is not None and hasattr(mark_core, "mark_1bit_generate"):
            res = mark_core.mark_1bit_generate(
                prompt,
                system_prompt,
                max_tokens,
                clan_id,
                core_loops,
                temperature,
                num_ctx,
            )
            parsed = parse_intent_and_thinking(res.get("text", ""))
            return {
                "text": parsed["response"],
                "raw_text": res.get("text", ""),
                "intent": res.get("intent", parsed["intent"]),
                "thinking": res.get("thinking", parsed["thinking"]),
                "entropy": float(res.get("entropy", "0.0")),
                "effective_layers": int(res.get("effective_layers", 40)),
                "clan_id": int(res.get("clan_id", clan_id)),
                "kv_cache_mib": int(res.get("kv_cache_mib", 844)),
                "provider": "mark_core_1bit_rust",
            }
    except Exception as exc:
        logger.warning(f"Erro ao invocar mark_core 1-bit: {exc}")
    return {"text": "", "provider": "unavailable"}


class MarkLocalProvider:
    """Provedor nativo para modelos Mark SLM e 1-Bit W1A4 via Rust PyO3."""

    def __init__(self, model_path: Optional[str] = None) -> None:
        self.model_path = model_path or "miceworks/Mark-Bin-32B"
        self.loaded = False
        self.has_rust_core = False
        self.core_loops = 2
        self.clan_id = 2
        self._check_rust_core()

    def _check_rust_core(self) -> None:
        self.has_rust_core = mark_core is not None and hasattr(mark_core, "mark_1bit_generate")

    def set_reasoning_depth(self, depth: str) -> None:
        d = str(depth).lower()
        if d in ("instant", "low", "rapido"):
            self.core_loops = 1
        elif d in ("high", "deep", "profundo"):
            self.core_loops = 3
        else:
            self.core_loops = 2

    def set_clan(self, clan_id: int) -> None:
        self.clan_id = clan_id % 4

    def generate(self, prompt: str, system_prompt: Optional[str] = None, **kwargs: Any) -> str:
        lip = get_local_inference_params()
        num_ctx = int(lip.get("num_ctx", MARK_LOCAL_CONTEXT_WINDOW))
        if self.has_rust_core:
            res = run_native_1bit_engine(
                prompt=prompt,
                system_prompt=system_prompt or "",
                max_tokens=int(kwargs.get("max_tokens", 512)),
                clan_id=self.clan_id,
                core_loops=self.core_loops,
                temperature=float(kwargs.get("temperature", 0.2)),
                num_ctx=num_ctx,
            )
            if res.get("raw_text"):
                return str(res["raw_text"])
        return f"[MarkLocalProvider 1-Bit] {prompt[:80]}"

    def stream_generate_sync(self, prompt: str, system_prompt: Optional[str] = None, **kwargs: Any) -> Generator[str, None, None]:
        out = self.generate(prompt, system_prompt=system_prompt, **kwargs)
        yield out
