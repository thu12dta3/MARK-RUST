"""Minimal Codex-style bar attached to the composer, one row only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from .i18n import tr
from .icons import ACTIVE, IDLE, vector_icon

PERMISSIONS: tuple[tuple[str, str], ...] = (
    ("suggest", "Suggest"),
    ("auto-edit", "Auto-Edit"),
    ("full-auto", "Full Access (bwrap Sandbox)"),
)

PROFILE_PATH = Path.home() / ".config" / "mark" / "hardware_profile.json"


class ScanWorker(QThread):
    """Re-escanreia o hardware pelo binario Rust em background."""

    done = pyqtSignal(dict)

    def run(self) -> None:
        from ..rust_bridge import rust

        try:
            profile = rust.hardware_profile(register=True)
        except Exception as exc:
            profile = {"ok": False, "message": str(exc)}
        self.done.emit(dict(profile))


class EngineerBar(QFrame):
    """Faixa de 34 px: projeto, modo de permissao, acesso web e re-scan."""

    project_changed = pyqtSignal(str)
    permission_changed = pyqtSignal(str)
    web_changed = pyqtSignal(bool)
    hardware_refreshed = pyqtSignal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("engineerBar")
        self.setFixedHeight(34)
        self.setStyleSheet(
            "QFrame#engineerBar { background: #12161B; border: 1px solid #1E2228;"
            " border-bottom: none; border-top-left-radius: 10px; border-top-right-radius: 10px; }"
        )
        self._worker: ScanWorker | None = None
        self._profile: dict[str, Any] = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(8)

        self.project_button = QPushButton()
        self.project_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.project_button.setIcon(vector_icon("library", IDLE, 14))
        self.project_button.setStyleSheet(
            "QPushButton { background: transparent; color: #8E95A0; border: none;"
            " font-size: 11px; text-align: left; padding: 2px 4px; }"
            "QPushButton:hover { color: #00D8F6; }"
        )
        self.project_button.clicked.connect(self.choose_project)
        layout.addWidget(self.project_button, 1)

        self.permission_combo = QComboBox()
        self.permission_combo.setCurrentIndex(2)
        for value, label in PERMISSIONS:
            self.permission_combo.addItem(tr(label), value)
        self.permission_combo.setStyleSheet(
            "QComboBox { background: #16191D; color: #C8D1DC; border: 1px solid #1E2228;"
            " border-radius: 9px; padding: 2px 8px; font-size: 10px; min-width: 150px; }"
        )
        self.permission_combo.currentIndexChanged.connect(
            lambda _index: self.permission_changed.emit(str(self.permission_combo.currentData()))
        )
        layout.addWidget(self.permission_combo)

        self.web_button = QPushButton()
        self.web_button.setCheckable(True)
        self.web_button.setChecked(True)
        self.web_button.setVisible(False)
        self.web_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.web_button.setStyleSheet(
            "QPushButton { background: #16191D; color: #8E95A0; border: 1px solid #1E2228;"
            " border-radius: 9px; padding: 2px 8px; font-size: 10px; }"
            "QPushButton:checked { color: #3FB950; border-color: #29502F; }"
        )
        self.web_button.toggled.connect(self._on_web_toggled)

        self.rescan_button = QPushButton(tr("Re-scan PC"))
        self.rescan_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.rescan_button.setIcon(vector_icon("chip", ACTIVE, 13))
        self.rescan_button.setStyleSheet(
            "QPushButton { background: transparent; color: #00D8F6; border: none;"
            " font-size: 10px; padding: 2px 6px; }"
        )
        self.rescan_button.setVisible(False)
        self.rescan_button.clicked.connect(lambda: self.rescan(True))

        self.project = ""
        self._refresh_labels()
        self.load_profile()
        self._auto_scan_if_stale()

    # ------------------------------------------------------------------ estado
    def _refresh_labels(self) -> None:
        label = self.project or tr("No project (Sandbox)")
        self.project_button.setText(f"{tr('Choose project')}: {label}")
        state = tr("Web Access: ON") if self.web_button.isChecked() else tr("Web Access: OFF")
        self.web_button.setText(state)

    def _on_web_toggled(self, enabled: bool) -> None:
        self.web_button.setText(tr("Web Access: ON") if enabled else tr("Web Access: OFF"))
        self.web_changed.emit(enabled)

    def permission_mode(self) -> str:
        return str(self.permission_combo.currentData() or "suggest")

    def web_access(self) -> bool:
        return bool(self.web_button.isChecked())

    def choose_project(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, tr("Choose project"), self.project)
        if chosen:
            self.project = chosen
            self._refresh_labels()
            self.project_changed.emit(chosen)

    # ---------------------------------------------------------------- hardware
    def load_profile(self) -> None:
        if not PROFILE_PATH.is_file():
            self._profile = {}
            return
        try:
            self._profile = json.loads(PROFILE_PATH.read_text())
        except (OSError, json.JSONDecodeError):
            self._profile = {}

    def _auto_scan_if_stale(self) -> None:
        """Escaneia o hardware em background quando o perfil falta ou envelheceu."""
        import time as _time

        fresh = False
        try:
            if PROFILE_PATH.is_file():
                fresh = (_time.time() - PROFILE_PATH.stat().st_mtime) < 24 * 3600
        except OSError:
            fresh = False
        if fresh:
            return
        from PyQt6.QtCore import QTimer

        QTimer.singleShot(800, lambda: self.rescan(True))

    def hardware_line(self) -> str:
        """Linha unica de hardware cadastrado para o estado vazio do Engineer."""
        if not self._profile:
            self.load_profile()
        profile = self._profile
        if not profile:
            return tr("PC profile not registered yet")
        cpu = profile.get("cpu") or {}
        gpu = profile.get("gpu") or {}
        memory = profile.get("memory") or {}
        model = str(cpu.get("model") or "CPU").split(" CPU")[0].split("@")[0].strip()
        model = model.replace("Intel(R) Core(TM) ", "")
        avx = "AVX2" if cpu.get("avx2") else "no AVX2"
        vram = gpu.get("vram_gib")
        vram_text = f"{float(vram):.0f}GB" if isinstance(vram, (int, float)) else "VRAM n/a"
        capability = gpu.get("compute_capability") or ""
        ram = memory.get("total_gib")
        ram_text = f"{float(ram):.1f}GB" if isinstance(ram, (int, float)) else "RAM n/a"
        gpu_name = str(gpu.get("name") or "no GPU").replace("NVIDIA GeForce ", "")
        return f"PC Registered: {model} {avx} · {gpu_name} {vram_text} {capability} · {ram_text} RAM".strip()

    def rescan(self, register: bool) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self.rescan_button.setDisabled(True)
        worker = ScanWorker(self)
        worker.done.connect(self._on_scanned)
        worker.finished.connect(self._reap)
        self._worker = worker
        worker.start()

    def _reap(self) -> None:
        self.rescan_button.setDisabled(False)
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None

    def _on_scanned(self, profile: dict[str, Any]) -> None:
        self._profile = profile
        self.hardware_refreshed.emit(profile)

    def hardware_prompt(self) -> str:
        """Frase de hardware injetada no system prompt do Engineer."""
        if not self._profile:
            self.load_profile()
        if not self._profile:
            return ""
        cpu = self._profile.get("cpu") or {}
        gpu = self._profile.get("gpu") or {}
        memory = self._profile.get("memory") or {}
        return (
            f"Target machine: {cpu.get('model')} ({cpu.get('cores')}C/{cpu.get('threads')}T, "
            f"AVX2={'yes' if cpu.get('avx2') else 'no'}); GPU {gpu.get('name')} "
            f"{gpu.get('vram_gib')}GB {gpu.get('compute_capability')}; RAM {memory.get('total_gib')}GB. "
            "Write code tuned for this exact hardware."
        )
