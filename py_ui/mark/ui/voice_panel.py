"""Voice call dialog: live waveform, mute state and real TTS dispatch."""

from __future__ import annotations

import math
import shutil
import subprocess
import time
from typing import Any

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .i18n import tr
from .icons import ACTIVE, IDLE, vector_icon
from .perf import frame_interval_ms


class Waveform(QWidget):
    """Ondas de voz animadas no ritmo do monitor (30-120 Hz)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(120)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(frame_interval_ms())

    def _tick(self) -> None:
        self._phase += 0.28
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#0B0E14"))
        pen = QPen(QColor("#00D8F6"))
        pen.setWidthF(2.0)
        painter.setPen(pen)
        width = self.width()
        height = self.height()
        middle = height / 2
        step = 8
        for index, x in enumerate(range(0, width, step)):
            envelope = math.sin((index * 0.35) + self._phase)
            amplitude = abs(envelope) * (height * 0.34) + 4
            painter.drawLine(x, int(middle - amplitude), x, int(middle + amplitude))


class VoiceCallDialog(QDialog):
    """Chamada de voz in-app com mute sincronizado e TTS real quando disponivel."""

    mute_changed = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None, last_reply: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("MARK · Voice Call")
        self.resize(560, 420)
        self.setStyleSheet(parent.styleSheet() if parent is not None else "")
        self._muted = False
        self._last_reply = last_reply
        self._started = time.time()
        self._build()
        self._ticker = QTimer(self)
        self._ticker.timeout.connect(self._update_status)
        self._ticker.start(500)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        head = QHBoxLayout()
        title = QLabel(tr("Voice Call"))
        title.setStyleSheet("color: #EDEDED; font-size: 16px; font-weight: 600;")
        head.addWidget(title)
        head.addStretch(1)
        self.status = QLabel(tr("Connecting..."))
        self.status.setStyleSheet("color: #3FB950; font-size: 11px;")
        head.addWidget(self.status)
        layout.addLayout(head)

        self.wave = Waveform(self)
        layout.addWidget(self.wave, 1)

        self.device_label = QLabel("")
        self.device_label.setWordWrap(True)
        self.device_label.setStyleSheet("color: #8E95A0; font-size: 10px;")
        layout.addWidget(self.device_label)

        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.mute_button = QPushButton(tr("Mute"))
        self.mute_button.setCheckable(True)
        self.mute_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mute_button.setIcon(vector_icon("call", IDLE, 16))
        self.mute_button.setStyleSheet(
            "QPushButton { background: #16191D; color: #C8D1DC; border: 1px solid #1E2228;"
            " border-radius: 9px; padding: 7px 16px; font-size: 12px; }"
            "QPushButton:checked { color: #E06C75; border-color: #5A2226; }"
        )
        self.mute_button.toggled.connect(self._on_mute)
        controls.addWidget(self.mute_button)

        self.speak_button = QPushButton(tr("Speak last reply"))
        self.speak_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.speak_button.setStyleSheet(
            "QPushButton { background: #16191D; color: #00D8F6; border: 1px solid #1E2228;"
            " border-radius: 9px; padding: 7px 16px; font-size: 12px; }"
        )
        self.speak_button.clicked.connect(self.speak)
        controls.addWidget(self.speak_button)

        end = QPushButton(tr("End call"))
        end.setCursor(Qt.CursorShape.PointingHandCursor)
        end.setStyleSheet(
            "QPushButton { background: #E06C75; color: #121417; border: none;"
            " border-radius: 9px; padding: 7px 18px; font-size: 12px; font-weight: 600; }"
        )
        end.clicked.connect(self.close)
        controls.addWidget(end)
        controls.addStretch(1)
        layout.addLayout(controls)

        engine = self._tts_engine()
        device = self._input_device()
        self.device_label.setText(
            f"{tr('Microphone')}: {device} · TTS: {engine or tr('no engine installed')}"
        )

    # ------------------------------------------------------------------ estado
    def _update_status(self) -> None:
        elapsed = int(time.time() - self._started)
        minutes, seconds = divmod(elapsed, 60)
        state = tr("Muted") if self._muted else tr("Live")
        self.status.setText(f"{state} · {minutes:02d}:{seconds:02d}")

    def _on_mute(self, muted: bool) -> None:
        self._muted = muted
        self.mute_button.setText(tr("Unmute") if muted else tr("Mute"))
        self.mute_changed.emit(muted)
        self._update_status()

    @staticmethod
    def _tts_engine() -> str:
        for candidate in ("piper", "espeak-ng", "espeak", "spd-say"):
            if shutil.which(candidate):
                return candidate
        return ""

    @staticmethod
    def _input_device() -> str:
        try:
            import pulsectl  # type: ignore

            with pulsectl.Pulse("mark-voice") as pulse:
                source = pulse.server_info().default_source_name
                return source or "default"
        except Exception:
            pass
        try:
            from ..audio import pulse_devices

            devices = pulse_devices()
            return str(devices[0]) if devices else tr("system default")
        except Exception:
            return tr("system default")

    def speak(self) -> None:
        """Fala a ultima resposta com o motor TTS realmente instalado."""
        engine = self._tts_engine()
        text = (self._last_reply or "").strip()
        if not text:
            self.device_label.setText(tr("Nothing to speak yet."))
            return
        if not engine:
            self.device_label.setText(tr("No TTS engine installed (piper, espeak-ng or spd-say)."))
            return
        try:
            if engine == "spd-say":
                subprocess.Popen([engine, text[:400]])
            else:
                subprocess.Popen([engine, text[:400]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            self.device_label.setText(tr("TTS failed: {detail}").format(detail=str(exc)))
            return
        self.device_label.setText(f"TTS: {engine} · {len(text)} chars")
