"""Modal de plugins: integracoes nativas e servidores MCP externos reais."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .config import load_config, save_config
from .plugins import PLUGINS, enabled, save_enabled
from .ui.i18n import tr
from .ui.icons import vector_icon


def mcp_servers(cfg: dict | None = None) -> list[dict]:
    """Servidores MCP declarados no config (stdio ou HTTP)."""
    data = cfg if cfg is not None else load_config()
    raw = data.get("mcp_servers") or {}
    servers: list[dict] = []
    if isinstance(raw, dict):
        for name, spec in raw.items():
            if isinstance(spec, dict):
                servers.append({"name": str(name), **spec})
    elif isinstance(raw, list):
        for spec in raw:
            if isinstance(spec, dict) and spec.get("name"):
                servers.append(dict(spec))
    return servers


def set_mcp_enabled(name: str, value: bool) -> None:
    """Persiste o estado ativo/desativado de um servidor MCP."""
    cfg = load_config() or {}
    states = dict(cfg.get("mcp_server_state") or {})
    states[str(name)] = bool(value)
    cfg["mcp_server_state"] = states
    save_config(cfg)


def mcp_enabled(name: str, cfg: dict | None = None) -> bool:
    data = cfg if cfg is not None else load_config()
    states = data.get("mcp_server_state") or {}
    return bool(states.get(str(name), True))


class PluginsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("MARK plugins"))
        self.setMinimumWidth(560)
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(13)
        title = QLabel(tr("Plugins"))
        title.setStyleSheet("font-size: 22px; font-weight: 700;")
        layout.addWidget(title)
        intro = QLabel(
            tr("Choose the integrations MARK may use. Each card lists the permissions it receives.")
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.switches: dict[str, QCheckBox] = {}
        cfg = load_config()
        for spec in PLUGINS:
            card = QWidget()
            card.setStyleSheet(
                "QWidget { background: #17191a; border: 1px solid #343839; border-radius: 10px; }"
            )
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 12, 14, 12)
            row = QHBoxLayout()
            icon = QLabel()
            icon.setPixmap(vector_icon("tools").pixmap(16, 16))
            icon.setStyleSheet("border: 0; background: transparent;")
            row.addWidget(icon)
            name = QLabel(tr(spec["name"]))
            name.setStyleSheet(
                "font-size: 15px; font-weight: 650; border: 0; background: transparent;"
            )
            row.addWidget(name)
            row.addStretch(1)
            toggle = QCheckBox(tr("Enabled"))
            toggle.setChecked(enabled(spec["id"], cfg))
            toggle.setAccessibleName(tr("Enable plugin {name}").format(name=tr(spec["name"])))
            row.addWidget(toggle)
            card_layout.addLayout(row)
            description = QLabel(tr(spec["description"]))
            description.setWordWrap(True)
            description.setStyleSheet("border: 0; background: transparent;")
            card_layout.addWidget(description)
            permissions = QLabel(
                tr("Permissions: {list}").format(list=" · ".join(tr(p) for p in spec["permissions"]))
            )
            permissions.setWordWrap(True)
            permissions.setStyleSheet(
                "color: #a8b0b2; font-size: 11px; border: 0; background: transparent;"
            )
            card_layout.addWidget(permissions)
            source = QLabel(tr(spec["source"]))
            source.setStyleSheet(
                "color: #899295; font-size: 11px; border: 0; background: transparent;"
            )
            card_layout.addWidget(source)
            layout.addWidget(card)
            self.switches[spec["id"]] = toggle
            toggle.toggled.connect(
                lambda value, plugin_id=spec["id"]: self._save(plugin_id, value)
            )

        servers = mcp_servers(cfg)
        header = QLabel(tr("External MCP servers ({count})").format(count=len(servers)))
        header.setStyleSheet("font-size: 15px; font-weight: 650; margin-top: 6px;")
        layout.addWidget(header)
        if not servers:
            empty = QLabel(
                tr("No MCP server configured. Add one under mcp_servers in the MARK config.")
            )
            empty.setWordWrap(True)
            empty.setStyleSheet("color: #a8b0b2; font-size: 11px;")
            layout.addWidget(empty)
        self.mcp_switches: dict[str, QCheckBox] = {}
        for server in servers:
            row = QHBoxLayout()
            transport = str(server.get("transport") or server.get("type") or "stdio")
            label = QLabel(f"{server['name']} · {transport}")
            label.setStyleSheet("font-size: 13px; border: 0; background: transparent;")
            row.addWidget(label, 1)
            toggle = QCheckBox(tr("Enabled"))
            toggle.setChecked(mcp_enabled(str(server["name"]), cfg))
            toggle.setAccessibleName(
                tr("Enable MCP server {name}").format(name=str(server["name"]))
            )
            toggle.toggled.connect(
                lambda value, name=str(server["name"]): set_mcp_enabled(name, value)
            )
            row.addWidget(toggle)
            layout.addLayout(row)
            self.mcp_switches[str(server["name"])] = toggle

        note = QLabel(
            tr("Enabled plugins and MCP servers are exposed to the Engineer sandbox tool registry.")
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #a8b0b2; font-size: 11px;")
        layout.addWidget(note)
        close = QPushButton(tr("Done"))
        close.clicked.connect(self.accept)
        layout.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)

    def _save(self, plugin_id: str, value: bool) -> None:
        try:
            save_enabled(plugin_id, value)
        except ValueError as exc:
            toggle = self.switches[plugin_id]
            toggle.blockSignals(True)
            toggle.setChecked(not value)
            toggle.blockSignals(False)
            QMessageBox.warning(self, tr("Plugins"), str(exc))

    def is_plugin_enabled(self, plugin_id: str) -> bool:
        toggle = self.switches.get(plugin_id)
        return bool(toggle is not None and toggle.isChecked())

    def is_mcp_enabled(self, name: str) -> bool:
        toggle = self.mcp_switches.get(name)
        return bool(toggle is not None and toggle.isChecked())
