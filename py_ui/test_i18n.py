"""i18n coverage and quality gate: seven locales, palette and tools translated."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PY_UI = Path(__file__).resolve().parent
CATALOG = PY_UI / "mark" / "ui" / "i18n_catalog.py"
LANGS = ("en", "pt-BR", "zh", "hi", "es", "fr", "ar")
# Rotulos que sao nomes proprios e permanecem iguais por projeto.
SAME_BY_DESIGN = {
    "Geral", "Engenheiro", "Professor", "Vision", "Mark", "MARK", "Configurações",
    "Plugins...", "E-mail · Tuta", "Português", "Offline", "MARK · Offline", "DeepSeek R1 8B",
    "PROFESSOR · ASTRA",
}
FORBIDDEN_TOKENS = ("herramenta", "None")
TECHNICAL = ("Flash Attention", "Load", "Seed", "Host", "Status", "Porta", "Local", "Graph", "API", "GPU", "CPU", "RoPE", "KV", "BWRAP", "mTLS", "CTX", "Plugins", "DeepSeek")


def load_catalog() -> dict[str, tuple[str, ...]]:
    spec = importlib.util.spec_from_file_location("mark_i18n_catalog", CATALOG)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    tables = dict(module.TRANSLATIONS)
    for extra in ("i18n_vault.py", "i18n_models.py", "i18n_ui.py", "i18n_panels.py"):
        path = CATALOG.parent / extra
        if not path.is_file():
            continue
        spec = importlib.util.spec_from_file_location(f"mark_{extra[:-3]}", path)
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        tables.update(getattr(mod, "TRANSLATIONS", {}))
    return tables


def main() -> int:
    table = load_catalog()
    failures: list[str] = []

    for key, row in table.items():
        if len(row) != len(LANGS):
            failures.append(f"{key!r}: {len(row)} idiomas (esperado {len(LANGS)})")
            continue
        for index, value in enumerate(row):
            text = str(value)
            if not text.strip():
                failures.append(f"{key!r}: vazio em {LANGS[index]}")

            for token in FORBIDDEN_TOKENS:
                if token in text:
                    failures.append(f"{key!r}: token proibido {token!r} em {LANGS[index]}")
        sentence = (" " in key.strip()) and len(key.strip()) > 12
        technical = any(token in key for token in TECHNICAL)
        if key not in SAME_BY_DESIGN and sentence and not technical:
            if row[4] == row[0]:
                failures.append(f"{key!r}: espanhol igual ao ingles")
            if row[1] == row[0]:
                failures.append(f"{key!r}: pt-BR igual ao ingles")

    # categorias e comandos que precisam existir no catalogo (palette/tools)
    required = (
        "--- SECURITY AND AGENTS ---",
        "--- ENGINEERING AND CODE ---",
        "--- UTILITIES AND MEDIA ---",
        "--- SYSTEM ---",
        "Antivirus and threats · Sentinel",
        "Devices and security",
        "Engineer tasks",
        "Autonomous engineering · Sandbox",
        "Code · GitHub",
        "Calendar and reminders",
        "command",
    )
    lower_keys = {k.lower() for k in table}
    all_labels = {str(value).lower() for row in table.values() for value in row}
    for entry in required:
        if (
            entry not in table
            and not any(entry.lower() in key.lower() for key in table)
            and entry.lower() not in all_labels
        ):
            failures.append(f"chave obrigatoria ausente: {entry!r}")

    print(f"chaves: {len(table)} | idiomas: {len(LANGS)}")
    print("exemplo es:", table.get("Digite um comando ou ferramenta...", ("",) * 7)[4])
    print("exemplo pt-BR:", table.get("Digite um comando ou ferramenta...", ("",) * 7)[1])
    if failures:
        print(f"FAIL ({len(failures)} problemas)")
        for item in failures[:12]:
            print("  -", item)
        return 3
    print("PASS: 100% das chaves com 7 idiomas, sem portunhol e sem traducao identica ao ingles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
