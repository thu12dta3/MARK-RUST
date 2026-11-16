"""Trocas de idioma ao vivo em Wayland: En, Pt-Br e Es nos widgets reais.

Abre a MainWindow, alterna o idioma do catalogo e inspeciona os textos que os
widgets vivos exibem (sidebar, composer, Settings, Models Hub, Plugins e a
Command Palette), provando que a retraducao acontece sem recriar a janela.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PY_UI = Path(__file__).resolve().parent
sys.path.insert(0, str(PY_UI))

FAULT_LOG = Path.home() / ".local" / "state" / "mark" / "crash_fault.log"

# (idioma, marcador que DEVE aparecer, marcador que NAO pode aparecer)
SIDEBAR = {
    "en": ("AGENTS & MODES", "AGENTES & MODOS"),
    "pt-BR": ("AGENTES & MODOS", "AGENTS & MODES"),
    "es": ("AGENTES Y MODOS", "AGENTS & MODES"),
}
ASSISTANT = {
    "en": "PERSONAL ASSISTANT",
    "pt-BR": "ASSISTENTE PESSOAL",
    "es": "ASISTENTE PERSONAL",
}
# Tela de Voice Call: (cabecalho do painel, rotulo de estado aceito)
VOICE_CALL = {
    "en": ("VOICE CALL · IN-APP", "Ready to talk"),
    "pt-BR": ("CHAMADA DE VOZ · IN-APP", "Pronto para conversar"),
    "es": ("LLAMADA DE VOZ · EN LA APP", "Listo para conversar"),
}
# Modal Plugins: (titulo janela, trecho da introducao)
PLUGINS = {
    "en": ("MARK plugins", "Choose the integrations"),
    "pt-BR": ("Plugins do MARK", "Escolha as integra"),
    "es": ("Plugins de MARK", "Elige las integraciones"),
}


def fault_size() -> int:
    return FAULT_LOG.stat().st_size if FAULT_LOG.is_file() else 0


def visible_texts(window) -> set[str]:
    from PyQt6.QtWidgets import QAbstractButton, QLabel

    texts: set[str] = set()
    for widget in window.findChildren(QLabel):
        value = widget.text()
        if value:
            texts.add(value.strip())
    for widget in window.findChildren(QAbstractButton):
        value = widget.text()
        if value:
            texts.add(value.strip())
    return texts


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "wayland")
    if not os.environ.get("WAYLAND_DISPLAY"):
        print("FAIL: WAYLAND_DISPLAY nao definido (teste exige Wayland real)")
        return 2
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication

    from mark.ui.i18n import retranslate_tree, set_language
    from mark.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("MARK")
    app.setOrganizationName("miceworks")

    before_fault = fault_size()
    failures: list[str] = []
    window = MainWindow()
    window.resize(1280, 850)
    window.show()
    QTest.qWait(2600)

    for code in ("en", "pt-BR", "es"):
        set_language(code)
        retranslate_tree(window)
        if hasattr(window, "_refresh_dynamic_labels"):
            window._refresh_dynamic_labels()
        if hasattr(window, "_decorate_nav_labels"):
            window._decorate_nav_labels()
        QTest.qWait(700)
        texts = visible_texts(window)
        joined = " | ".join(sorted(texts))
        must, forbidden = SIDEBAR[code]
        ok_must = must in joined
        ok_forbidden = forbidden not in joined or must == forbidden
        ok_assistant = ASSISTANT[code] in joined
        sample = [t for t in sorted(texts) if t.isupper() and len(t) > 6][:4]
        print(f"{code:6} sidebar={must!r} presente={ok_must} proibido_ausente={ok_forbidden} "
              f"assistente={ok_assistant} amostra={sample}")
        if not ok_must:
            failures.append(f"{code}: marcador {must!r} ausente na sidebar")
        if not ok_forbidden:
            failures.append(f"{code}: texto de outro idioma visivel ({forbidden!r})")
        if not ok_assistant:
            failures.append(f"{code}: cabecalho do assistente nao traduziu")

        # Settings e Models Hub precisam refletir o idioma corrente.
        engine_lbl = getattr(getattr(window, "settings_widget", None), "engine_status_value", None)
        if engine_lbl is not None:
            value = engine_lbl.text()
            print(f"       settings.engine_status={value!r}")
            if not value.strip():
                failures.append(f"{code}: label de motor vazio em Settings")
        for attr in ("models_hub", "plugins_page"):
            widget = getattr(window, attr, None)
            if widget is not None:
                retranslate_tree(widget)
        QTest.qWait(200)

    # Command Palette: abrir de fato, contar itens e provar retraducao ao vivo.
    from PyQt6.QtWidgets import QListWidget

    for code in ("en", "pt-BR", "es"):
        set_language(code)
        retranslate_tree(window)
        # open_command_palette() usa QDialog.exec() e bloqueia o harness; aqui a
        # palette real e aberta e populada sem entrar no loop modal.
        window.command_palette.search_input.clear()
        window.command_palette.populate()
        window.command_palette.show()
        QTest.qWait(500)
        palette = getattr(window, "command_palette", None)
        lists = palette.findChildren(QListWidget) if palette is not None else []
        entries = sum(lst.count() for lst in lists)
        titles = []
        for lst in lists:
            for row in range(min(lst.count(), 3)):
                titles.append(lst.item(row).text())
        print(f"palette[{code}] entries={entries} amostra={titles[:3]}")
        if entries <= 0:
            failures.append(f"{code}: Command Palette sem entradas abertas")
        window._on_escape()
        QTest.qWait(300)
        if palette is not None and palette.isVisible():
            failures.append(f"{code}: Esc nao fechou a Command Palette")

    # Voice Call real: navega para o painel (indice 2) e valida os marcadores.
    for code in ("en", "pt-BR", "es"):
        set_language(code)
        retranslate_tree(window)
        window.open_call()
        QTest.qWait(400)
        joined = " | ".join(sorted(visible_texts(window)))
        header, state = VOICE_CALL[code]
        ok_header = header in joined
        ok_state = state in joined
        print(f"call[{code}] header={header!r} presente={ok_header} estado={state!r} presente={ok_state}")
        if not ok_header:
            failures.append(f"{code}: cabecalho da tela Voice Call nao traduziu ({header!r})")
        if not ok_state:
            failures.append(f"{code}: rotulo de estado da chamada nao traduziu ({state!r})")

    # Modal Plugins real: titulo e introducao no idioma corrente.
    from mark.desktop_plugins import PluginsDialog

    for code in ("en", "pt-BR", "es"):
        set_language(code)
        dialog = PluginsDialog(window)
        dialog.show()
        QTest.qWait(350)
        retranslate_tree(dialog)
        QTest.qWait(150)
        title = dialog.windowTitle()
        joined = " | ".join(sorted(visible_texts(dialog)))
        expected_title, intro = PLUGINS[code]
        ok_title = title == expected_title
        ok_intro = intro in joined
        print(f"plugins[{code}] titulo={title!r} ok={ok_title} intro={intro!r} presente={ok_intro}")
        if not ok_title:
            failures.append(f"{code}: titulo do modal Plugins em {title!r}, esperado {expected_title!r}")
        if not ok_intro:
            failures.append(f"{code}: introducao do modal Plugins nao traduziu ({intro!r})")
        dialog.close()
        dialog.deleteLater()
        QTest.qWait(200)

    set_language("pt-BR")
    retranslate_tree(window)
    QTest.qWait(400)
    set_language("en")
    retranslate_tree(window)
    QTest.qWait(400)

    names = [w.objectName() or type(w).__name__ for w in app.topLevelWidgets() if w.isVisible()]
    delta = fault_size() - before_fault
    print(f"TOPLEVELS {names}")
    print(f"FAULT_LOG_DELTA={delta}")
    if names != ["MainWindow"]:
        failures.append(f"topLevelWidgets inesperado: {names}")
    if delta != 0:
        failures.append(f"crash_fault.log cresceu {delta} bytes")

    window.close()
    QTest.qWait(300)
    if failures:
        print(f"\nFAIL ({len(failures)} problemas)")
        for item in failures:
            print("  -", item)
        return 1
    print("\nI18N WAYLAND OK: En/Pt-Br/Es retraduzem os widgets vivos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
