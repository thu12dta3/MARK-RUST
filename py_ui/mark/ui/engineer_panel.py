"""Engineer panel: Codex-style loop wired to the Rust mark-engineer binary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .i18n import tr
from .icons import ACTIVE, IDLE, vector_icon

APPROVALS = (
    ("suggest", "Suggest"),
    ("auto-edit", "Auto-Edit"),
    ("full-auto", "Full-Auto [bwrap Sandbox]"),
)
ACTIONS = ("plan", "read", "grep", "shell", "test", "mcp")


class EngineerWorker(QThread):
    """Executa uma acao do Codex no binario Rust sem travar a interface."""

    finished_action = pyqtSignal(dict)

    def __init__(self, payload: dict[str, Any], workspace: str, approval: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._payload = payload
        self._workspace = workspace
        self._approval = approval

    def run(self) -> None:
        from ..rust_bridge import rust

        try:
            result = rust.engineer_action(self._payload, workspace=self._workspace, approval=self._approval)
        except Exception as exc:
            result = {"ok": False, "stderr": str(exc), "stdout": "", "diff": ""}
        self.finished_action.emit(dict(result))


class HardwareWorker(QThread):
    """Le ou registra o perfil de hardware pelo scanner Rust."""

    finished_profile = pyqtSignal(dict)

    def __init__(self, register: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._register = register

    def run(self) -> None:
        from ..rust_bridge import rust

        try:
            profile = rust.hardware_profile(register=self._register)
        except Exception as exc:
            profile = {"ok": False, "message": str(exc)}
        self.finished_profile.emit(dict(profile))


class EngineerPanel(QFrame):
    """Barra Codex: workspace, aprovacao, internet, diff viewer e sandbox."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("engineerPanel")
        self.setStyleSheet(
            "QFrame#engineerPanel { background: #0F1216; border: 1px solid #1E2228; border-radius: 10px; }"
        )
        self._worker: EngineerWorker | None = None
        self._hw_worker: HardwareWorker | None = None
        self._profile: dict[str, Any] = {}
        self._icon_idle = vector_icon("engineer", IDLE, 16)
        self._icon_active = vector_icon("engineer", ACTIVE, 16)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel("Engineer · Codex")
        title.setStyleSheet("color: #EDEDED; font-size: 12px; font-weight: 600;")
        head.addWidget(title)
        self.hw_badge = QLabel(tr("PC profile not registered yet"))
        self.hw_badge.setStyleSheet("color: #8E95A0; font-size: 11px;")
        head.addWidget(self.hw_badge, 1)
        self.scan_button = QPushButton(tr("Scan PC Hardware"))
        self.scan_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.scan_button.setIcon(vector_icon("chip", ACTIVE, 14))
        self.scan_button.setStyleSheet(
            "QPushButton { background: #16191D; color: #00D8F6; border: 1px solid #1E2228;"
            " border-radius: 7px; padding: 4px 10px; font-size: 11px; }"
            "QPushButton:hover { border-color: #00D8F6; }"
        )
        self.scan_button.clicked.connect(lambda: self.register_hardware(True))
        head.addWidget(self.scan_button)
        layout.addLayout(head)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.workspace_input = QLineEdit(str(Path.home() / "MARK-RUST"))
        self.workspace_input.setStyleSheet(
            "QLineEdit { background: #121417; color: #EDEDED; border: 1px solid #1E2228;"
            " border-radius: 7px; padding: 5px 9px; font-size: 11px; }"
        )
        controls.addWidget(QLabel(tr("Workspace")))
        controls.addWidget(self.workspace_input, 2)
        browse = QPushButton(tr("Browse"))
        browse.clicked.connect(self._pick_workspace)
        browse.setStyleSheet(
            "QPushButton { background: #16191D; color: #8E95A0; border: 1px solid #1E2228;"
            " border-radius: 7px; padding: 5px 10px; font-size: 11px; }"
        )
        controls.addWidget(browse)

        self.approval_combo = QComboBox()
        for value, label in APPROVALS:
            self.approval_combo.addItem(label, value)
        self.approval_combo.setStyleSheet(
            "QComboBox { background: #16191D; color: #EDEDED; border: 1px solid #1E2228;"
            " border-radius: 7px; padding: 4px 8px; font-size: 11px; }"
        )
        controls.addWidget(self.approval_combo)

        self.internet_toggle = QPushButton(tr("Internet Access"))
        self.internet_toggle.setCheckable(True)
        self.internet_toggle.setChecked(True)
        self.internet_toggle.setStyleSheet(
            "QPushButton { background: #16191D; color: #8E95A0; border: 1px solid #1E2228;"
            " border-radius: 7px; padding: 5px 10px; font-size: 11px; }"
            "QPushButton:checked { color: #00D8F6; border-color: #00D8F6; }"
        )
        controls.addWidget(self.internet_toggle)
        layout.addLayout(controls)

        run_row = QHBoxLayout()
        run_row.setSpacing(8)
        self.action_combo = QComboBox()
        for action in ACTIONS:
            self.action_combo.addItem(action, action)
        self.action_combo.setStyleSheet(self.approval_combo.styleSheet())
        run_row.addWidget(self.action_combo)
        self.target_input = QLineEdit()
        self.target_input.setPlaceholderText(tr("Path, pattern or shell command"))
        self.target_input.setStyleSheet(self.workspace_input.styleSheet())
        run_row.addWidget(self.target_input, 1)
        self.run_button = QPushButton(tr("Run step"))
        self.run_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.run_button.setStyleSheet(
            "QPushButton { background: #00D8F6; color: #121417; border: none; border-radius: 7px;"
            " padding: 5px 14px; font-size: 11px; font-weight: 600; }"
        )
        self.run_button.clicked.connect(self.run_step)
        run_row.addWidget(self.run_button)
        layout.addLayout(run_row)

        self.steps_label = QLabel(tr("No Codex step executed yet."))
        self.steps_label.setStyleSheet("color: #8E95A0; font-size: 11px;")
        layout.addWidget(self.steps_label)

        self.diff_view = QTextBrowser()
        self.diff_view.setObjectName("engineerDiff")
        self.diff_view.setFixedHeight(96)
        self.diff_view.setStyleSheet(
            "QTextBrowser#engineerDiff { background: #0B0E14; border: 1px solid #262C36;"
            " border-radius: 8px; color: #ABB2BF; font-family: 'JetBrains Mono', monospace; font-size: 11px; }"
        )
        layout.addWidget(self.diff_view)

        self.output_view = QTextBrowser()
        self.output_view.setObjectName("engineerOutput")
        self.output_view.setFixedHeight(96)
        self.output_view.setStyleSheet(
            "QTextBrowser#engineerOutput { background: #0B0E14; border: 1px solid #262C36;"
            " border-radius: 8px; color: #98C379; font-family: 'JetBrains Mono', monospace; font-size: 11px; }"
        )
        layout.addWidget(self.output_view)

    def _pick_workspace(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, tr("Select workspace"), self.workspace_input.text())
        if chosen:
            self.workspace_input.setText(chosen)

    def register_hardware(self, register: bool) -> None:
        if self._hw_worker is not None and self._hw_worker.isRunning():
            return
        self.scan_button.setDisabled(True)
        self.hw_badge.setText(tr("Scanning this PC..."))
        worker = HardwareWorker(register=register, parent=self)
        worker.finished_profile.connect(self._on_profile)
        worker.finished.connect(self._reap_hw)
        self._hw_worker = worker
        worker.start()

    def _reap_hw(self) -> None:
        self.scan_button.setDisabled(False)
        if self._hw_worker is not None:
            self._hw_worker.deleteLater()
            self._hw_worker = None

    def _on_profile(self, profile: dict[str, Any]) -> None:
        self._profile = profile
        if not profile.get("ok"):
            self.hw_badge.setText(tr("Hardware scan failed: {detail}").format(detail=str(profile.get("message") or "")))
            return
        cpu = str(profile.get("cpu", {}).get("model", "unknown"))
        threads = profile.get("cpu", {}).get("threads", "?")
        gpu = str(profile.get("gpu", {}).get("name", "none"))
        vram = profile.get("gpu", {}).get("vram_gib", "?")
        sm = profile.get("gpu", {}).get("compute_capability", "?")
        ram = profile.get("memory", {}).get("total_gib", "?")
        self.hw_badge.setText(
            f"{tr('PC Profile Registered')}: {cpu} {threads}T · {gpu} {vram}GB {sm} · {ram}GB RAM"
        )
        self.steps_label.setText(
            tr("Profile stored at {path}").format(path=str(profile.get("path") or ""))
        )

    def hardware_prompt(self) -> str:
        """Linha de hardware injetada no system prompt do Engineer."""
        if not self._profile.get("ok"):
            return ""
        cpu = self._profile.get("cpu", {})
        gpu = self._profile.get("gpu", {})
        memory = self._profile.get("memory", {})
        return (
            f"Target machine: {cpu.get('model')} ({cpu.get('cores')}C/{cpu.get('threads')}T, "
            f"AVX2={'yes' if cpu.get('avx2') else 'no'}); GPU {gpu.get('name')} "
            f"{gpu.get('vram_gib')}GB {gpu.get('compute_capability')}; RAM {memory.get('total_gib')}GB. "
            "Write code tuned for this exact hardware."
        )

    def run_step(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        action = str(self.action_combo.currentData() or "read")
        target = self.target_input.text().strip()
        payload: dict[str, Any] = {"action": action}
        if action in {"read", "grep"}:
            payload["path" if action == "read" else "query"] = target or "."
        elif action in {"shell", "test"}:
            payload["command"] = target.split() if target else ["uname", "-a"]
            payload["approval"] = self.approval_combo.currentData()
        elif action == "plan":
            payload["content"] = target or "Plan the change"
        elif action == "mcp":
            tool, _, raw_args = target.partition(" ")
            payload["tool"] = tool
            try:
                payload["arguments"] = json.loads(raw_args) if raw_args.strip() else {}
            except json.JSONDecodeError:
                payload["arguments"] = {"text": raw_args.strip()}

        self.run_button.setDisabled(True)
        self.steps_label.setText(tr("Running {action} in the sandbox...").format(action=action))
        worker = EngineerWorker(payload, self.workspace_input.text(), str(self.approval_combo.currentData()), parent=self)
        worker.finished_action.connect(self._on_action)
        worker.finished.connect(self._reap_worker)
        self._worker = worker
        worker.start()

    def _reap_worker(self) -> None:
        self.run_button.setDisabled(False)
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None

    def _on_action(self, result: dict[str, Any]) -> None:
        ok = bool(result.get("ok"))
        trans = result.get("transcript") or []
        steps = " · ".join(str(step) for step in trans[-4:]) or str(result.get("outcome") or "")
        self.steps_label.setText((tr("Step finished") if ok else tr("Step failed")) + f": {steps}"[:220])
        diff = str(result.get("diff") or "")
        if not diff and "outcome" in result:
            diff = str(result.get("outcome"))
        self.diff_view.setHtml(self._diff_html(diff) if diff else f'<span style="color:#5C6370;">{tr("No diff produced")}</span>')
        mcp = result.get("mcp") or {}
        out = "\n".join(
            part
            for part in (
                str(mcp.get("stdout") or "") if mcp else "",
                str(result.get("stdout") or ""),
                str(result.get("stderr") or ""),
            )
            if part.strip()
        ).strip()
        self.output_view.setPlainText(out or tr("(no sandbox output)"))

    @staticmethod
    def _diff_html(diff: str) -> str:
        lines: list[str] = []
        for line in diff.splitlines():
            escaped = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            if line.startswith("+"):
                lines.append(f'<div style="color:#98C379;">{escaped}</div>')
            elif line.startswith("-"):
                lines.append(f'<div style="color:#E06C75;">{escaped}</div>')
            elif line.startswith("@@"):
                lines.append(f'<div style="color:#56B6C2;">{escaped}</div>')
            else:
                lines.append(f'<div style="color:#ABB2BF;">{escaped}</div>')
        return "".join(lines)

    def refresh_profile(self) -> None:
        """Carrega o perfil ja cadastrado (rapido: leitura de JSON local)."""
        path = Path.home() / ".config" / "mark" / "hardware_profile.json"
        if not path.is_file():
            self.hw_badge.setText(tr("PC profile not registered yet"))
            return
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return
        data["ok"] = True
        data["path"] = str(path)
        self._on_profile(data)
