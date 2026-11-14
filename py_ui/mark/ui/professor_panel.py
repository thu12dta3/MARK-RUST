"""Professor panel in the Astra AI style: subjects plus pedagogical actions."""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .i18n import tr
from .icons import ACTIVE, IDLE, vector_icon

SUBJECTS: tuple[tuple[str, str], ...] = (
    ("mathematics", "Mathematics"),
    ("physics", "Physics & Hardware"),
    ("rust", "Rust & Systems"),
    ("algorithms", "Algorithms"),
    ("chemistry", "Chemistry"),
    ("logic", "Deductive Logic"),
)

ACTIONS: tuple[tuple[str, str, str], ...] = (
    (
        "step",
        "Step-by-Step Solution",
        "Solve this step by step. Return numbered cards 'Step 1', 'Step 2', 'Step 3', each with the "
        "formula or code in a fenced block, then the final answer on its own line.",
    ),
    (
        "hint",
        "Give Me a Hint",
        "Give one Socratic hint only. Do not reveal the final answer and do not solve the exercise.",
    ),
    (
        "first",
        "Explain From First Principles",
        "Explain the underlying physics or mathematics from first principles before any shortcut.",
    ),
    (
        "quiz",
        "Practice Quiz",
        "Create one practice problem, wait for my answer, then correct it step by step.",
    ),
    (
        "check",
        "Check My Work (Attach/Code)",
        "Review my attached work or code and point to the exact line or step where it goes wrong.",
    ),
)


class ProfessorPanel(QFrame):
    """Barra pedagogica com disciplina e cinco acoes estruturadas."""

    def __init__(self, on_action: Callable[[str, str], None] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._on_action = on_action
        self.setObjectName("professorPanel")
        self.setStyleSheet(
            "QFrame#professorPanel { background: #0F1216; border: 1px solid #1E2228; border-radius: 10px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(10)
        head = QLabel("Professor · Astra")
        head.setStyleSheet("color: #EDEDED; font-size: 12px; font-weight: 600;")
        top.addWidget(head)

        self.subject_combo = QComboBox()
        for value, label in SUBJECTS:
            self.subject_combo.addItem(label, value)
        self.subject_combo.setStyleSheet(
            "QComboBox { background: #16191D; color: #EDEDED; border: 1px solid #1E2228;"
            " border-radius: 7px; padding: 4px 8px; font-size: 11px; min-width: 150px; }"
        )
        top.addWidget(self.subject_combo)
        top.addStretch(1)
        self.state_label = QLabel(tr("Pick a subject and an action"))
        self.state_label.setStyleSheet("color: #8E95A0; font-size: 11px;")
        top.addWidget(self.state_label)
        layout.addLayout(top)

        grid = QGridLayout()
        grid.setSpacing(6)
        self.buttons: dict[str, QPushButton] = {}
        for index, (key, label, _directive) in enumerate(ACTIONS):
            button = QPushButton(tr(label))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setIcon(vector_icon("professor", ACTIVE, 14))
            button.setMinimumWidth(168)
            button.setStyleSheet(
                "QPushButton { background: #16191D; color: #C8D1DC; border: 1px solid #1E2228;"
                " border-radius: 7px; padding: 5px 10px; font-size: 11px; text-align: left; }"
                "QPushButton:hover { color: #00D8F6; border-color: #00D8F6; }"
            )
            button.clicked.connect(lambda _checked=False, k=key: self.trigger(k))
            grid.addWidget(button, index // 3, index % 3)
            self.buttons[key] = button
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        layout.addLayout(grid)

    def subject(self) -> str:
        return str(self.subject_combo.currentData() or "mathematics")

    def trigger(self, key: str) -> None:
        directive = ""
        label = ""
        for action_key, action_label, action_directive in ACTIONS:
            if action_key == key:
                directive = action_directive
                label = action_label
                break
        if not directive:
            return
        subject = self.subject_combo.currentText()
        prompt = f"[{subject}] {directive}"
        self.state_label.setText(tr("Applied: {label}").format(label=label))
        if self._on_action is not None:
            self._on_action(prompt, label)
