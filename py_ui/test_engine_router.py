"""Gate do seletor automatico de motor (`mark.engine_router`).

Cobre 20 casos reais: checkpoint SVID, .mkbin, .gguf existente e inexistente,
tags do Ollama, familias de API, desambiguacao local vs cloud, dicas do scanner
e fallbacks seguros.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

PY_UI = Path(__file__).resolve().parent
MODULE = PY_UI / "mark" / "engine_router.py"


def load_router():
    spec = importlib.util.spec_from_file_location("mark_engine_router", MODULE)
    assert spec is not None and spec.loader is not None, "engine_router nao carregou"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


router = load_router()
resolve = router.resolve_engine


def build_cases(tmp: Path) -> list[tuple[str, dict, str, str]]:
    gguf_file = tmp / "qwen2.5-coder-7b.gguf"
    gguf_file.write_bytes(b"GGUF\x00\x00\x00\x03")
    mkbin = tmp / "mark-32b.mkbin"
    mkbin.write_bytes(b"MK")
    svid_dir = tmp / "Mark-Bin-32B"
    svid_dir.mkdir()
    (svid_dir / "isometric_gpu_core.safetensors").write_bytes(b"{}")
    local_deepseek = tmp / "deepseek-coder-6.7b.gguf"
    local_deepseek.write_bytes(b"GGUF\x00\x00\x00\x03")

    return [
        # --- checkpoint nativo SVID / 1-bit -> rust
        ("mark-bin-32b", {}, "rust", "nome canonico do checkpoint"),
        ("Mark-Bin-32B", {}, "rust", "nome com maiusculas"),
        ("mark_32b_1bit", {}, "rust", "diretorio local do upcycling"),
        ("svid-v3-150m", {}, "rust", "familia SVID"),
        ("mark-svid-1bit", {}, "rust", "id anunciado pelo mark-server"),
        ("/srv/modelos/mark-32b.mkbin", {}, "rust", "mkbin inexistente ainda e rust"),
        ("./checkpoints/x.mkbin", {}, "rust", "mkbin relativo"),
        (str(svid_dir), {}, "rust", "diretorio com isometric_gpu_core"),
        ("mark_32b_1bit", {"scanner_source": "svid"}, "rust", "origem svid do scanner"),
        # --- GGUF local -> llamacpp
        ("qwen2.5-coder-7b.gguf", {}, "llamacpp", "gguf sem caminho no disco"),
        (str(gguf_file), {}, "llamacpp", "gguf existente"),
        ("modelo.gguf", {"scanner_source": "gguf"}, "llamacpp", "entrada GGUF do scanner"),
        (str(local_deepseek), {}, "llamacpp", "gguf local com nome de familia cloud"),
        # --- Ollama -> ollama
        ("deepseek-r1:8b-q3_k_l", {}, "ollama", "tag com quantizacao"),
        ("llama3.2:latest", {}, "ollama", "tag latest"),
        ("deepseek-coder:latest", {}, "ollama", "tag local vence familia cloud"),
        ("deepseek-chat", {"scanner_source": "ollama"}, "ollama", "tag real do daemon"),
        ("mistral-small:22b", {"ollama_tags": ["mistral-small:22b"]}, "ollama", "tag na lista real"),
        # --- API remota -> api
        ("gpt-4o", {}, "api", "familia GPT"),
        ("o3-mini", {}, "api", "familia o3"),
        ("claude-3-5-sonnet", {}, "api", "familia Claude"),
        ("gemini-1.5-pro", {}, "api", "familia Gemini"),
        ("grok-2", {}, "api", "familia Grok"),
        ("deepseek-coder", {}, "api", "familia cloud sem evidencia local"),
        ("openrouter/anthropic/claude-3.5-sonnet", {}, "api", "namespace de provedor"),
        ("openai/gpt-4o-mini", {}, "api", "prefixo openai/"),
        ("deepseek/deepseek-chat:free", {}, "api", "barra vence formato de tag"),
        ("meu-modelo", {"api_models": ["meu-modelo"]}, "api", "modelo sincronizado via API"),
        ("", {}, "api", "id vazio cai no fallback remoto"),
    ]


def main() -> int:
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="engine_router_") as tmpdir:
        cases = build_cases(Path(tmpdir))
        for model_id, hints, expected, why in cases:
            got = resolve(model_id, **hints)
            status = "ok" if got == expected else "FAIL"
            print(f"{status:4} {model_id!r:52} -> {got:9} (esperado {expected:9}) {why}")
            if got != expected:
                failures.append(f"{model_id!r}: {got} != {expected} ({why})")

    # cada motor precisa de um rotulo proprio, nao vazio e nao o fallback
    fallback = router.engine_label("desconhecido")
    labels = {}
    for engine in ("rust", "llamacpp", "ollama", "api"):
        label = router.engine_label(engine)
        labels[engine] = label
        if not label.strip():
            failures.append(f"rotulo vazio para {engine}")
    if len(set(labels.values())) != len(labels):
        failures.append(f"rotulos duplicados: {labels}")
    if labels["rust"] == fallback or labels["llamacpp"] == fallback:
        failures.append(f"rotulo colidindo com o fallback: {labels} vs {fallback!r}")

    print(f"\ncasos: {len(cases)}")
    if failures:
        print(f"FAIL ({len(failures)} problemas)")
        for item in failures:
            print("  -", item)
        return 3
    print("PASS: 100% dos casos com motor resolvido corretamente")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
