"""Varredura AST das strings de UI visiveis que nao passam por `tr()`.

Reporta, por arquivo, todo literal entregue a um widget (texto, tooltip,
placeholder, titulo de janela, item de menu, caixa de mensagem) que nao esteja
dentro de uma chamada `tr(...)`. Tambem acusa `tr()` com chave que nao existe no
catalogo e chave de catalogo fora do ingles.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path

PY_UI = Path(__file__).resolve().parent
ROOT = PY_UI / "mark"
CATALOG_FILES = (
    "i18n_catalog.py",
    "i18n_vault.py",
    "i18n_models.py",
    "i18n_ui.py",
    "i18n_panels.py",
)
LANGS = ("en", "pt-BR", "zh", "hi", "es", "fr", "ar")

#: Metodos cujo primeiro argumento e sempre texto visivel.
TEXT_METHODS = (
    "setText",
    "setToolTip",
    "setPlaceholderText",
    "setWindowTitle",
    "setStatusTip",
    "setTabText",
    "setTitle",
    "addItem",
    "addAction",
    "setPrefix",
)
#: Construtores cujo primeiro argumento e texto visivel.
TEXT_CTORS = (
    "QLabel",
    "QPushButton",
    "QToolButton",
    "QCheckBox",
    "QRadioButton",
    "QGroupBox",
    "QAction",
    "QMenu",
    "QDialog",
    "QMessageBox",
    "QListWidgetItem",
    "QTreeWidgetItem",
    "QTableWidgetItem",
)
#: Nomes proprios e rotulos neutros que nao precisam de traducao.
ALLOW_LIST = re.compile(
    r"^(MARK|Mark|miceworks|miceworks/[\w.-]+|[\w.-]+\.(py|rs|gguf|json|toml|so)|[A-Z]{1,4}|[/:@._|·\-+ ]+|\d+[smhd%]?)$"
)
#: Strings tecnicas que nunca aparecem como texto de UI (ids, SQL, mime, CSS).
TECHNICAL_TEXT = re.compile(
    r"^[\w./-]+\.(py|rs|json|toml|yaml|yml|gguf|safetensors|mkbin|bin|so|db|md|log|svg)$"
    r"|^[a-z0-9]+(_[a-z0-9]+)+$"
    r"|^(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|PRAGMA)\b"
    r"|^[a-z]+/[a-z0-9.+-]+$"
    r"|^[#.][\w-]+\s*[:;]"
    r"|^\d+(px|ms|s|MiB|GiB|%)?$"
    r"|^[a-z]{1,3}$"
)

PT_MARKERS = re.compile(
    r"\b(nao|não|para|com|sem|uma|um|os|as|de|da|do|em|que|por|seu|sua|voce|você|"
    r"esta|está|configura|conversa|mensagem|arquivo|criar|abrir|fechar|salvar|excluir|"
    r"adicionar|executar|verificar|nenhum|nenhuma|carregando|pronto|erro|falha)\b",
    re.IGNORECASE,
)


def load_catalog() -> dict[str, tuple[str, ...]]:
    table: dict[str, tuple[str, ...]] = {}
    for name in CATALOG_FILES:
        path = ROOT / "ui" / name
        if not path.is_file():
            continue
        spec = importlib.util.spec_from_file_location(f"cat_{path.stem}", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        table.update(getattr(module, "TRANSLATIONS", {}))
    return table


def _inside_tr(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    current = parents.get(node)
    while current is not None:
        if isinstance(current, ast.Call):
            func = current.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name in ("tr", "translate_text"):
                return True
        current = parents.get(current)
    return False


def scan_file(path: Path, catalog: dict[str, tuple[str, ...]]) -> tuple[list[str], list[str], list[str]]:
    src = path.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src, filename=str(path))
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    hardcoded: list[str] = []
    missing: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = getattr(func, "attr", None) or getattr(func, "id", None)
        if name in ("tr", "translate_text") and node.args:
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                key = arg.value.replace("&&", "&")
                if key and key not in catalog:
                    missing.append(f"{path.relative_to(ROOT.parent)}:{node.lineno}: tr({arg.value!r})")
            continue
        if name not in TEXT_METHODS and name not in TEXT_CTORS:
            continue
        if not node.args:
            continue
        arg = node.args[0]
        if not isinstance(arg, ast.Constant) or not isinstance(arg.value, str):
            continue
        text = arg.value.strip()
        if not text or ALLOW_LIST.match(text):
            continue
        if _inside_tr(node, parents):
            continue
        if not re.search(r"[A-Za-z]", text):
            continue
        if TECHNICAL_TEXT.match(text):
            continue
        hardcoded.append(f"{path.relative_to(ROOT.parent)}:{node.lineno}: {name}({text!r})")
    return hardcoded, missing, []


def main() -> int:
    catalog = load_catalog()
    # chaves do catalogo que ainda estao em portugues
    portuguese_keys = [
        key
        for key in catalog
        if PT_MARKERS.search(key) and key not in ("Geral", "Engenheiro", "Professor", "Evolução", "Biblioteca")
    ]
    files = sorted(p for p in ROOT.rglob("*.py") if "__pycache__" not in p.parts)
    hardcoded: list[str] = []
    missing: list[str] = []
    for path in files:
        h, m, _ = scan_file(path, catalog)
        hardcoded.extend(h)
        missing.extend(m)

    by_file: dict[str, int] = {}
    for item in hardcoded:
        by_file[item.split(":", 1)[0]] = by_file.get(item.split(":", 1)[0], 0) + 1

    active_files = (
        "mark/desktop_plugins.py",
        "mark/desktop_call_dialog.py",
        "mark/ui/main_window.py",
        "mark/ui/widgets.py",
        "mark/desktop_navigation.py",
        "mark/desktop.py",
        "mark/ui/hf_splitview.py",
    )
    dormant_files = ("mark/desktop_vision.py", "mark/desktop_evolution.py")
    active = [item for item in hardcoded if item.split(":", 1)[0] in active_files]
    dormant = [item for item in hardcoded if item.split(":", 1)[0] in dormant_files]
    others = len(hardcoded) - len(active) - len(dormant)
    print(f"arquivos: {len(files)} | chaves no catalogo: {len(catalog)}")
    print(f"strings visiveis sem tr(): {len(hardcoded)}")
    print(f"  telas ativas: {len(active)} | modulos dormentes: {len(dormant)} | outros: {others}")
    active_by_file: dict[str, int] = {}
    for item in active:
        name = item.split(":", 1)[0]
        active_by_file[name] = active_by_file.get(name, 0) + 1
    for name, count in sorted(active_by_file.items(), key=lambda kv: -kv[1]):
        print(f"    {count:4}  {name}")
    print(f"tr() com chave fora do catalogo: {len(missing)}")
    print(f"chaves de catalogo ainda em portugues: {len(portuguese_keys)}")
    print("\n-- por arquivo (top 12) --")
    for name, count in sorted(by_file.items(), key=lambda kv: -kv[1])[:12]:
        print(f"  {count:4}  {name}")
    if missing:
        print("\n-- tr() sem chave no catalogo (top 20) --")
        for item in missing[:20]:
            print("  ", item)
    if "--por-arquivo" in sys.argv:
        print("\n-- todas as strings sem tr() --")
        for item in hardcoded:
            print("  ", item)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
