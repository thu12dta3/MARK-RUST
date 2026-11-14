"""Diálogos e modais de autorização e consentimento de usuário para o MARK."""

from __future__ import annotations

import json
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..security.consent import APIConsentManager, get_api_consent_manager


class APIConsentDialog(QDialog):
    """Modal de confirmação e consentimento para APIs externas e ferramentas agentizadas.
    
    Inclui opção 'Lembrar desta decisão' / 'Autorizar sempre para esta API'
    para permitir persistência segura e supressão de pop-ups redundantes.
    """

    def __init__(
        self,
        api_name: str,
        arguments: dict[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.api_name = api_name
        self.tool_name = api_name  # compatibilidade com ActionConsentDialog
        self.arguments = arguments or {}
        self.granted: bool = False
        self.remember_decision: bool = False
        self._build_ui()

    def _build_ui(self) -> None:
        self.setWindowTitle("Autorização de API Externa · MARK")
        self.setModal(True)
        self.setMinimumWidth(440)
        self.setStyleSheet("""
            QDialog {
                background: #16191D;
                color: #EDEDED;
                font-family: Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                border: 1px solid #1E2228;
                border-radius: 8px;
            }
            QLabel#dialogTitle {
                color: #EDEDED;
                font-size: 14px;
                font-weight: 500;
            }
            QLabel#dialogPrompt {
                color: #8E95A0;
                font-size: 13px;
                font-weight: 400;
            }
            QCheckBox {
                color: #EDEDED;
                font-size: 13px;
                spacing: 8px;
                padding-top: 4px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border: 1px solid #30363D;
                border-radius: 4px;
                background: #0B0D0F;
            }
            QCheckBox::indicator:checked {
                background: #3FB950;
                border-color: #3FB950;
            }
            QTextEdit#argsPreview {
                background: #0B0D0F;
                color: #EDEDED;
                border: 1px solid #1E2228;
                border-radius: 6px;
                font-family: monospace;
                font-size: 11px;
                font-weight: 400;
                padding: 8px;
            }
            QPushButton#authorizeBtn {
                background: #3FB950;
                color: #121417;
                border: none;
                border-radius: 6px;
                padding: 8px 18px;
                font-size: 13px;
                font-weight: 500;
            }
            QPushButton#authorizeBtn:hover {
                background: #4CC760;
            }
            QPushButton#cancelBtn {
                background: #20252C;
                color: #8E95A0;
                border: 1px solid #1E2228;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: 500;
            }
            QPushButton#cancelBtn:hover {
                background: #262B33;
                color: #EDEDED;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        title = QLabel("Autorização de Saída Externa / API")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)

        prompt = QLabel(
            f"Permitir chamada à API / Ferramenta externa <span style='font-weight:500; color:#00D8F6;'>{self.api_name}</span>?"
        )
        prompt.setObjectName("dialogPrompt")
        prompt.setTextFormat(Qt.TextFormat.RichText)
        prompt.setWordWrap(True)
        layout.addWidget(prompt)

        desc = QLabel(
            "Por padrão de segurança estrita, conexões e ferramentas externas requerem consentimento. "
            "Ao marcar 'Lembrar desta decisão', esta escolha será gravada de forma criptografada no cofre seguro."
        )
        desc.setObjectName("dialogPrompt")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        if self.arguments:
            layout.addWidget(QLabel("Parâmetros solicitados:"))
            args_box = QTextEdit()
            args_box.setObjectName("argsPreview")
            args_box.setReadOnly(True)
            args_box.setPlainText(json.dumps(self.arguments, indent=2, ensure_ascii=False))
            args_box.setMaximumHeight(100)
            layout.addWidget(args_box)

        # Checkbox: Lembrar desta decisão / Autorizar sempre para esta API
        self.remember_checkbox = QCheckBox("Lembrar desta decisão (Autorizar sempre para esta API)")
        self.remember_checkbox.setObjectName("rememberConsentCheckBox")
        self.remember_checkbox.setChecked(False)
        layout.addWidget(self.remember_checkbox)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch(1)

        cancel_btn = QPushButton("Cancelar")
        cancel_btn.setObjectName("cancelBtn")
        cancel_btn.clicked.connect(self._on_cancel)
        btn_row.addWidget(cancel_btn)

        auth_btn = QPushButton("Autorizar")
        auth_btn.setObjectName("authorizeBtn")
        auth_btn.clicked.connect(self._on_authorize)
        btn_row.addWidget(auth_btn)

        layout.addLayout(btn_row)

    def _on_authorize(self) -> None:
        self.granted = True
        self.remember_decision = self.remember_checkbox.isChecked()
        self.accept()

    def _on_cancel(self) -> None:
        self.granted = False
        self.remember_decision = False
        self.reject()


# Alias para interoperabilidade com o código anterior
ActionConsentDialog = APIConsentDialog
