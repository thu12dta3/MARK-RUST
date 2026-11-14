"""MARK UI internationalisation.

English is the default locale. Seven locales can be switched live at runtime:
en, pt-BR, zh, hi, es, fr, ar.

Translation tables are flat mappings ``source string -> tuple of seven labels``
ordered exactly like :data:`LANGS`. Source strings are the literals that appear
in the widget code, so a table entry is a direct lookup with no key indirection.
"""

from __future__ import annotations

import importlib
from typing import Any, Callable, Iterable, Mapping

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QToolButton,
    QWidget,
)

LANGS: tuple[str, ...] = ("en", "pt-BR", "zh", "hi", "es", "fr", "ar")
LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "pt-BR": "Português",
    "zh": "中文",
    "hi": "हिन्दी",
    "es": "Español",
    "fr": "Français",
    "ar": "العربية",
}
DEFAULT_LANGUAGE = "en"
SOURCE_ATTR = "_i18n_source"
_EXTRA_MODULES: tuple[str, ...] = ("i18n_catalog", "i18n_vault", "i18n_models")

_current: str = DEFAULT_LANGUAGE
_table: dict[str, tuple[str, ...]] = {}
_reverse: dict[str, str] = {}
_listeners: list[Callable[[str], None]] = []
_loaded = False
_settings = QSettings("miceworks", "MARK")


def register(entries: Mapping[str, Iterable[str]]) -> None:
    """Merge ``source -> 7 labels`` entries into the live table."""
    for source, labels in entries.items():
        row = tuple(str(item) for item in labels)
        if len(row) != len(LANGS):
            raise ValueError(f"i18n row for {source!r} needs {len(LANGS)} labels, got {len(row)}")
        _table[str(source)] = row
    _rebuild_reverse()


def _rebuild_reverse() -> None:
    _reverse.clear()
    for source, row in _table.items():
        for label in row:
            if label and label != source:
                _reverse.setdefault(label, source)


def _load_tables() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    for name in _EXTRA_MODULES:
        try:
            module = importlib.import_module(f".{name}", __package__)
        except ImportError:
            continue
        register(getattr(module, "TRANSLATIONS", {}))


def languages() -> tuple[str, ...]:
    return LANGS


def current_language() -> str:
    _load_tables()
    return _current


def saved_language() -> str:
    value = ""
    try:
        import json as _json
        from pathlib import Path as _Path

        cfg_path = _Path.home() / ".config" / "mark" / "config.json"
        if cfg_path.is_file():
            value = str(_json.loads(cfg_path.read_text()).get("language") or "")
    except (OSError, ValueError):
        value = ""
    if not value:
        value = str(_settings.value("ui/language", DEFAULT_LANGUAGE) or DEFAULT_LANGUAGE)
    return value if value in LANGS else DEFAULT_LANGUAGE


def is_rtl(code: str | None = None) -> bool:
    return (code or _current) == "ar"


def tr(text: str) -> str:
    """Translate a source literal into the active locale."""
    if not text:
        return text
    _load_tables()
    row = _table.get(text)
    if row is None:
        source = _reverse.get(text)
        if source is None:
            return text
        row = _table.get(source)
        if row is None:
            return text
    return row[LANGS.index(_current)] or text


def translate_text(text: str) -> str:
    return tr(text)


def on_language_change(callback: Callable[[str], None]) -> None:
    if callback not in _listeners:
        _listeners.append(callback)


def set_language(code: str, notify: bool = True) -> str:
    global _current
    if code not in LANGS:
        code = DEFAULT_LANGUAGE
    _current = code
    _settings.setValue("ui/language", code)
    _settings.sync()
    try:
        import json as _json
        from pathlib import Path as _Path

        cfg_path = _Path.home() / ".config" / "mark" / "config.json"
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        data = _json.loads(cfg_path.read_text()) if cfg_path.is_file() else {}
        data["language"] = code
        tmp = cfg_path.with_suffix(".tmp")
        tmp.write_text(_json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(cfg_path)
    except (OSError, ValueError):
        pass
    if notify:
        for callback in list(_listeners):
            callback(code)
    return _current


def apply_layout_direction() -> None:
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight)


def _tab_label(text: str) -> str:
    """Traduz e escapa o & para que o titulo da aba nao vire atalho sublinhado."""
    return tr(text.replace("&&", "&")).replace("&", "&&")


def _translate_widget(widget: QWidget) -> None:
    text: str | None = None
    setter: Callable[[str], Any] | None = None
    if isinstance(widget, QGroupBox):
        title = widget.title()
        if title:
            widget.setTitle(tr(title))
    elif isinstance(widget, (QLabel, QPushButton, QToolButton, QCheckBox)):
        text = widget.text()
        if text:
            widget.setText(tr(text))
    if isinstance(widget, QLineEdit):
        placeholder = widget.placeholderText()
        if placeholder:
            widget.setPlaceholderText(tr(placeholder))
    for action in widget.actions():
        label = action.text()
        if label:
            action.setText(tr(label))


def _translate_children(node: QWidget) -> None:
    _translate_widget(node)
    if isinstance(node, QTabWidget):
        for index in range(node.count()):
            node.setTabText(index, _tab_label(node.tabText(index)))
    if isinstance(node, QComboBox):
        for index in range(node.count()):
            node.setItemText(index, tr(node.itemText(index)))
    for child in node.findChildren(QWidget):
        _translate_widget(child)
        if isinstance(child, QTabWidget):
            for index in range(child.count()):
                child.setTabText(index, _tab_label(child.tabText(index)))
        if isinstance(child, QComboBox):
            for index in range(child.count()):
                child.setItemText(index, tr(child.itemText(index)))
    if hasattr(node, "menu") and callable(node.menu):  # QToolButton popups
        menu = node.menu()
        if menu is not None:
            for action in menu.actions():
                label = action.text()
                if label:
                    action.setText(tr(label))


def retranslate_tree(root: QWidget) -> None:
    """Rewrite every translatable label under ``root`` in the active locale."""
    _load_tables()
    _translate_children(root)
    title = root.windowTitle()
    if title:
        root.setWindowTitle(tr(title))
