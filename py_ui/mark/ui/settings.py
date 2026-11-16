"""Settings panel: advanced local inference, universal key vault and privacy.

The key vault tab is a state machine driven by the Rust vault reported through
:mod:`mark.rust_bridge`. A brand-new install renders the *Create Master Password*
panel; an existing vault renders the *Unlock Vault* row, and only an open session
enables the key table, the add-key section and the two password-change modes.
When the Rust binaries are missing the whole panel stays visible, the
master-password actions are disabled and the status label states the reason.
No outcome is ever simulated: every message shown to the user is either a real
return value of the Rust process or a plain statement about local UI state.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..config import (
    get_hardware_cpu_limit,
    get_local_inference_params,
    get_memory_storage_path,
    save_local_inference_params,
    set_memory_storage_path,
)
from ..config.llm_config import LLMKeyVault
from ..memory import reload_memory_backends
from ..rust_bridge import data_home, rust
from ..security.consent import APIConsentManager
from .i18n import tr
from .models_hub import ModelsHubWidget
from .widgets import (
    DirectoryPickerWidget,
    InferenceAutoOptionWidget,
    InferenceNumberInputWidget,
    InferenceSliderWidget,
    InferenceTextInputWidget,
    InferenceToggleWidget,
)

logger = logging.getLogger("mark.ui.settings")

MODEL_CONTEXT_CEILING = 2_097_152
MIN_MASTER_PASSWORD_LENGTH = 12
STRENGTH_LABELS = ("Not set", "Very weak", "Weak", "Fair", "Strong", "Very strong")
STRENGTH_COLORS = ("#30363D", "#F85149", "#F85149", "#E3B341", "#3FB950", "#3FB950")
DANGER_BUTTON_QSS = """
    QPushButton#dangerVaultButton {
        background: #B62324;
        color: #FFFFFF;
        border: 1px solid #B62324;
        border-radius: 6px;
        padding: 7px 16px;
        font-size: 13px;
        font-weight: 600;
    }
    QPushButton#dangerVaultButton:hover {
        background: #DA3633;
        border-color: #F85149;
    }
    QPushButton#dangerVaultButton:pressed {
        background: #8E1B1C;
    }
    QPushButton#dangerVaultButton:disabled {
        background: #2D333B;
        color: #8E95A0;
        border-color: #30363D;
    }
"""


def mask_api_key(secret: str) -> str:
    """Hide an API key behind a fixed, non-reversible mask."""
    if not secret:
        return ""
    if secret.startswith("sk-"):
        return "sk-...****"
    if len(secret) >= 6:
        return f"{secret[:3]}...****"
    return "sk-...****" if len(secret) >= 4 else "****"


def xdg_memory_dir() -> Path:
    """Canonical memory directory: the XDG data root of MARK plus ``memory``."""
    return data_home() / "memory"


def resolve_memory_dirs() -> tuple[Path, Path]:
    """Return ``(effective, configured)`` memory directories.

    ``configured`` is whatever the path helper in :mod:`mark.config` reports.
    ``effective`` is that same path when it already lives inside the MARK XDG
    data root, otherwise the canonical ``<xdg>/mark/memory`` location. The
    settings tab shows the effective directory and offers the migration button,
    so applying it rewrites the configuration through the same helper.
    """
    configured = Path(get_memory_storage_path()).expanduser()
    canonical = xdg_memory_dir()
    try:
        inside = configured.resolve().is_relative_to(data_home().resolve())
    except OSError:
        inside = False
    return (configured if inside else canonical), configured


def password_score(password: str) -> int:
    """Score a password from 0 (empty) to 5 (very strong) for the meter."""
    text = password or ""
    if not text:
        return 0
    has_lower = any(char.islower() for char in text)
    has_upper = any(char.isupper() for char in text)
    has_digit = any(char.isdigit() for char in text)
    has_symbol = any(not char.isalnum() for char in text)
    classes = sum((has_lower, has_upper, has_digit, has_symbol))
    if len(text) < 8:
        return 1
    score = classes
    if len(text) >= MIN_MASTER_PASSWORD_LENGTH:
        score += 1
    if len(text) >= 24:
        score += 1
    if classes < 2:
        score = min(score, 2)
    return max(1, min(5, score))


class SettingsWidget(QWidget):
    """Settings panel: local inference, universal key vault and privacy."""

    back_requested = pyqtSignal()
    key_saved = pyqtSignal(str)
    key_removed = pyqtSignal(str)
    memory_path_updated = pyqtSignal(str)
    reload_inference_engine_requested = pyqtSignal(dict)
    models_discovered = pyqtSignal(object)

    COMMON_PROVIDERS = [
        "DEEPSEEK_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GROQ_API_KEY",
        "MISTRAL_API_KEY",
        "COHERE_API_KEY",
        "OLLAMA_HOST",
        "X_API_KEY",
    ]

    def __init__(
        self,
        vault: LLMKeyVault | None = None,
        on_back: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("settingsWidget")
        self.vault = vault or LLMKeyVault()
        self._vault_unlocked = False
        self._vault_status_cache: dict[str, Any] = {}
        if on_back:
            self.back_requested.connect(on_back)
        self._build_ui()
        self.refresh_vault_state()
        self.load_inference_settings()

    # ------------------------------------------------------------------ build
    def _build_ui(self) -> None:
        self.setStyleSheet("""
            QWidget#settingsWidget {
                background: #1A1D21;
                color: #EAEAEA;
                font-family: Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            }
            QLabel#settingsTitle {
                color: #EAEAEA;
                font-size: 18px;
                font-weight: 600;
                letter-spacing: -0.2px;
            }
            QLabel#settingsSubtitle {
                color: #8B949E;
                font-size: 12px;
            }
            QPushButton#backToChatButton {
                background: #22262B;
                color: #58A6FF;
                border: 1px solid #30363D;
                border-radius: 8px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: 500;
            }
            QPushButton#backToChatButton:hover {
                background: #2D333B;
                border-color: #58A6FF;
            }
            QGroupBox {
                color: #EAEAEA;
                border: 1px solid #30363D;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 14px;
                font-size: 13px;
                font-weight: 600;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 6px;
                color: #58A6FF;
            }
            QTableWidget#keysTable {
                background: #22262B;
                color: #EAEAEA;
                border: 1px solid #30363D;
                border-radius: 8px;
                gridline-color: #30363D;
                font-size: 12px;
                selection-background-color: #2D333B;
                selection-color: #58A6FF;
            }
            QHeaderView::section {
                background: #1A1D21;
                color: #8B949E;
                border: none;
                border-bottom: 1px solid #30363D;
                padding: 6px;
                font-weight: 500;
            }
            QComboBox, QLineEdit {
                background: #22262B;
                color: #EAEAEA;
                border: 1px solid #30363D;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 13px;
            }
            QComboBox:focus, QLineEdit:focus {
                border-color: #58A6FF;
            }
            QPushButton#saveKeyButton {
                background: #58A6FF;
                color: #1A1D21;
                border: none;
                border-radius: 6px;
                padding: 7px 16px;
                font-weight: 600;
                font-size: 13px;
            }
            QPushButton#saveKeyButton:hover {
                background: #79B8FF;
            }
            QPushButton#removeKeyButton {
                background: #22262B;
                color: #F85149;
                border: 1px solid #30363D;
                border-radius: 6px;
                padding: 7px 16px;
                font-weight: 500;
                font-size: 13px;
            }
            QPushButton#removeKeyButton:hover {
                background: #2D333B;
                border-color: #F85149;
            }
            QLabel#vaultStatusLabel {
                font-size: 12px;
                padding: 4px 0px;
            }
            QProgressBar#vaultStrengthBar {
                background: #22262B;
                border: 1px solid #30363D;
                border-radius: 4px;
                height: 8px;
            }
            QProgressBar#vaultStrengthBar::chunk {
                background: #58A6FF;
                border-radius: 3px;
            }
            QTabWidget#settingsTabWidget::pane {
                border: 1px solid #30363D;
                background: #1A1D21;
                border-radius: 8px;
                padding: 6px;
            }
            QTabWidget#settingsTabWidget QTabBar::tab {
                background: #22262B;
                color: #8E95A0;
                padding: 8px 18px;
                margin-right: 4px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-weight: 500;
                font-size: 13px;
            }
            QTabWidget#settingsTabWidget QTabBar::tab:selected {
                background: #2D333B;
                color: #58A6FF;
                border-bottom: 2px solid #58A6FF;
            }
            QTabWidget#settingsTabWidget QTabBar::tab:hover {
                color: #EDEDED;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 24, 36, 24)
        layout.setSpacing(16)

        header_bar = QHBoxLayout()
        header_bar.setSpacing(16)

        self.back_button = QPushButton(tr("← Back to Chat"))
        self.back_button.setObjectName("backToChatButton")
        self.back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_button.clicked.connect(self._handle_back_clicked)
        header_bar.addWidget(self.back_button, alignment=Qt.AlignmentFlag.AlignLeft)

        header_bar.addSpacing(8)

        title_layout = QVBoxLayout()
        title_layout.setSpacing(2)
        self.title_label = QLabel(tr("MARK Settings"))
        self.title_label.setObjectName("settingsTitle")
        title_layout.addWidget(self.title_label)

        self.subtitle_label = QLabel(tr("Advanced local inference guardrails, the sealed key vault and storage."))
        self.subtitle_label.setObjectName("settingsSubtitle")
        title_layout.addWidget(self.subtitle_label)

        header_bar.addLayout(title_layout, 1)
        layout.addLayout(header_bar)

        self.tab_widget = QTabWidget(self)
        self.tab_widget.setObjectName("settingsTabWidget")

        self.inference_tab = self._build_inference_tab()
        self.tab_widget.addTab(self.inference_tab, tr("Advanced Local Inference"))

        self.vault_tab = self._build_vault_tab()
        self.tab_widget.addTab(self.vault_tab, tr("Key Vault & Storage"))

        self.privacy_tab = self._build_privacy_tab()
        self.tab_widget.addTab(self.privacy_tab, tr("Privacy"))
        self.tab_widget.addTab(ModelsHubWidget(parent=self), tr("Models, Roles & API Server"))

        layout.addWidget(self.tab_widget, 1)

    # -------------------------------------------------------------- inference
    def sync_model_limits(self, model_id: str) -> dict[str, Any]:
        """Ajusta a faixa fisica dos sliders ao teto real do modelo escaneado."""
        from .model_scanner import scan_model

        profile = scan_model(model_id)
        context = profile.get("context")
        layers = profile.get("layers")
        params = get_local_inference_params()
        if context and hasattr(self, "slider_ctx"):
            current = int(params.get("num_ctx") or self.slider_ctx.value())
            applied = self.slider_ctx.set_range(512, int(context), current)
            self.slider_ctx.max_val = int(context)
            setattr(self.slider_ctx, "max_value", int(context))
            self._ctx_ceiling = int(context)
            if hasattr(self.slider_ctx, "subtitle_label"):
                self.slider_ctx.subtitle_label.setText(
                    tr("Model ceiling: {ctx} tokens").format(ctx=f"{int(context):,}")
                )
            logger.debug("ctx slider range 512..%s (valor %s)", context, applied)
        if layers and hasattr(self, "slider_gpu"):
            current_layers = int(params.get("num_gpu") or self.slider_gpu.value())
            self.slider_gpu.set_range(0, int(layers), current_layers)
            self.slider_gpu.max_val = int(layers)
            setattr(self.slider_gpu, "max_value", int(layers))
            if hasattr(self.slider_gpu, "subtitle_label"):
                self.slider_gpu.subtitle_label.setText(
                    tr("Model layers: {layers}").format(layers=int(layers))
                )
        return profile

    def _build_inference_tab(self) -> QWidget:
        self._inference_tab_marker = True
        current_params = get_local_inference_params()
        cpu_max = get_hardware_cpu_limit()

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(10)

        # 1. Context size: the model ceiling is 2,097,152 tokens and both the
        # slider and the saved value honour that real ceiling.
        ctx_val = current_params.get("num_ctx", 4096)
        self.slider_ctx = InferenceSliderWidget(
            title=tr("Context Size"),
            min_val=512,
            max_val=MODEL_CONTEXT_CEILING,
            default_val=ctx_val,
            subtitle=tr("The model supports up to 2,097,152 tokens; the engine accepts any value up to that ceiling."),
            parent=content,
        )
        layout.addWidget(self.slider_ctx)

        # 2. GPU offload
        self.slider_gpu = InferenceSliderWidget(
            title=tr("Offload to GPU"),
            min_val=0,
            max_val=99,
            default_val=current_params.get("num_gpu", 16),
            parent=content,
        )
        layout.addWidget(self.slider_gpu)

        # 3. CPU thread pool size
        self.slider_threads = InferenceSliderWidget(
            title=tr("CPU Thread Pool Size"),
            min_val=1,
            max_val=cpu_max,
            default_val=current_params.get("num_thread", min(3, cpu_max)),
            parent=content,
        )
        layout.addWidget(self.slider_threads)

        # 4. Evaluation batch size
        self.input_num_batch = InferenceNumberInputWidget(
            title=tr("Evaluation Batch Size"),
            min_val=128,
            max_val=8192,
            default_val=current_params.get("num_batch", 2048),
            parent=content,
        )
        layout.addWidget(self.input_num_batch)

        # 5. Physical batch size
        self.input_physical_batch = InferenceNumberInputWidget(
            title=tr("Physical Batch Size"),
            min_val=64,
            max_val=2048,
            default_val=current_params.get("physical_batch_size", 512),
            parent=content,
        )
        layout.addWidget(self.input_physical_batch)

        # 6. Reasoning budget message
        self.input_reasoning_budget = InferenceTextInputWidget(
            title=tr("Reasoning Budget Message"),
            placeholder=tr("Enter text here"),
            default_text=str(current_params.get("reasoning_budget_message", "")),
            parent=content,
        )
        layout.addWidget(self.input_reasoning_budget)

        # 7. RoPE base frequency
        self.auto_rope_base = InferenceAutoOptionWidget(
            title=tr("RoPE Base Frequency"),
            checkbox_label=tr("Automatic"),
            default_auto=(current_params.get("rope_freq_base") is None),
            parent=content,
        )
        layout.addWidget(self.auto_rope_base)

        # 8. RoPE frequency scale
        self.auto_rope_scale = InferenceAutoOptionWidget(
            title=tr("RoPE Frequency Scale"),
            checkbox_label=tr("Automatic"),
            default_auto=(current_params.get("rope_freq_scale") is None),
            parent=content,
        )
        layout.addWidget(self.auto_rope_scale)

        # 9. Offload KV cache to GPU memory
        self.toggle_offload_kv = InferenceToggleWidget(
            title=tr("Offload KV Cache to GPU Memory"),
            default_val=bool(current_params.get("offload_kv_cache", True)),
            parent=content,
        )
        layout.addWidget(self.toggle_offload_kv)

        # 10. Keep model in memory
        self.toggle_keep_model = InferenceToggleWidget(
            title=tr("Keep Model in Memory"),
            default_val=bool(current_params.get("keep_model_in_memory", True)),
            parent=content,
        )
        layout.addWidget(self.toggle_keep_model)

        # 11. Try mmap()
        self.toggle_mmap = InferenceToggleWidget(
            title=tr("Try mmap()"),
            default_val=bool(current_params.get("use_mmap", True)),
            parent=content,
        )
        layout.addWidget(self.toggle_mmap)

        # 12. Seed
        self.auto_seed = InferenceAutoOptionWidget(
            title=tr("Seed"),
            checkbox_label=tr("Random Seed"),
            default_auto=(current_params.get("seed") is None),
            parent=content,
        )
        layout.addWidget(self.auto_seed)

        # 13. Flash Attention
        self.toggle_flash_attn = InferenceToggleWidget(
            title=tr("Flash Attention"),
            default_val=bool(current_params.get("flash_attn", True)),
            parent=content,
        )
        layout.addWidget(self.toggle_flash_attn)

        layout.addSpacing(6)
        self.inference_status_label = QLabel("")
        self.inference_status_label.setStyleSheet("font-size: 12px; font-weight: 500; padding: 4px 0px;")
        self.inference_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.inference_status_label.setWordWrap(True)
        layout.addWidget(self.inference_status_label)

        self.engine_status_value = QLabel(tr("Engine: resolved automatically"))
        self.engine_status_value.setObjectName("engineStatusValue")
        self.engine_status_value.setWordWrap(True)
        self.engine_status_value.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.engine_status_value)

        self.sync_models_button = QPushButton(tr("Sync Models"))
        self.sync_models_button.setObjectName("syncModelsButton")
        self.sync_models_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sync_models_button.clicked.connect(self.sync_models)
        layout.addWidget(self.sync_models_button)

        self.reload_inference_button = QPushButton(tr("Reload to apply the changes"))
        self.reload_inference_button.setObjectName("reloadInferenceButton")
        self.reload_inference_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reload_inference_button.setFixedHeight(44)
        self.reload_inference_button.setStyleSheet("""
            QPushButton#reloadInferenceButton {
                background: #4F46E5;
                color: #FFFFFF;
                border: none;
                border-radius: 8px;
                font-family: Inter, sans-serif;
                font-size: 14px;
                font-weight: 600;
                padding: 8px 24px;
            }
            QPushButton#reloadInferenceButton:hover {
                background: #4338CA;
            }
            QPushButton#reloadInferenceButton:pressed {
                background: #3730A3;
            }
            QPushButton#reloadInferenceButton:disabled {
                background: #2D333B;
                color: #8E95A0;
            }
        """)
        self.reload_inference_button.clicked.connect(self.reload_inference_engine)
        layout.addWidget(self.reload_inference_button)

        layout.addStretch(1)
        scroll_area.setWidget(content)
        return scroll_area

    # ------------------------------------------------------------------ vault
    def _build_vault_tab(self) -> QWidget:
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(14)

        # ------------------------------------------------ master password state
        state_group = QGroupBox(tr("Master Password"))
        state_group.setObjectName("vaultStateSection")
        state_layout = QVBoxLayout(state_group)
        state_layout.setContentsMargins(16, 16, 16, 16)
        state_layout.setSpacing(6)

        self.vault_state_label = QLabel(tr("Reading the vault state..."))
        self.vault_state_label.setStyleSheet("font-weight: 600; color: #EAEAEA; font-size: 13px;")
        self.vault_state_label.setWordWrap(True)
        state_layout.addWidget(self.vault_state_label)

        self.vault_details_label = QLabel("")
        self.vault_details_label.setObjectName("vaultStatusLabel")
        self.vault_details_label.setStyleSheet("color: #8B949E; font-size: 12px;")
        self.vault_details_label.setWordWrap(True)
        self.vault_details_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        state_layout.addWidget(self.vault_details_label)

        self.vault_feedback_label = QLabel("")
        self.vault_feedback_label.setObjectName("vaultStatusLabel")
        self.vault_feedback_label.setWordWrap(True)
        state_layout.addWidget(self.vault_feedback_label)

        layout.addWidget(state_group)

        # ------------------------------------------------------- create vault
        self.create_group = QGroupBox(tr("Create Master Password"))
        self.create_group.setObjectName("createVaultSection")
        create_layout = QVBoxLayout(self.create_group)
        create_layout.setContentsMargins(16, 16, 16, 16)
        create_layout.setSpacing(10)

        create_intro = QLabel(
            tr(
                "The Rust core seals every API key, conversation and memory behind one master password. "
                "The password never leaves this machine and cannot be recovered."
            )
        )
        create_intro.setStyleSheet("color: #8B949E; font-size: 12px; font-weight: 400;")
        create_intro.setWordWrap(True)
        create_layout.addWidget(create_intro)

        self.new_password_input = QLineEdit()
        self.new_password_input.setObjectName("newMasterPasswordInput")
        self.new_password_input.setAccessibleName(tr("New master password"))
        self.new_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.new_password_input.setPlaceholderText(tr("New password (at least 12 characters)"))
        self.new_password_input.textChanged.connect(self._handle_new_password_changed)
        create_layout.addWidget(self.new_password_input)

        self.confirm_password_input = QLineEdit()
        self.confirm_password_input.setObjectName("confirmMasterPasswordInput")
        self.confirm_password_input.setAccessibleName(tr("Confirm master password"))
        self.confirm_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm_password_input.setPlaceholderText(tr("Confirm password"))
        create_layout.addWidget(self.confirm_password_input)

        strength_row = QHBoxLayout()
        strength_row.setSpacing(10)
        self.strength_bar = QProgressBar()
        self.strength_bar.setObjectName("vaultStrengthBar")
        self.strength_bar.setRange(0, len(STRENGTH_LABELS) - 1)
        self.strength_bar.setValue(0)
        self.strength_bar.setTextVisible(False)
        self.strength_bar.setFixedHeight(8)
        strength_row.addWidget(self.strength_bar, 1)

        self.strength_label = QLabel(tr("Strength: {label}").format(label=tr(STRENGTH_LABELS[0])))
        self.strength_label.setObjectName("vaultStatusLabel")
        self.strength_label.setStyleSheet("color: #8B949E; font-size: 11px; font-weight: 400;")
        strength_row.addWidget(self.strength_label, alignment=Qt.AlignmentFlag.AlignRight)
        create_layout.addLayout(strength_row)

        self.create_vault_button = QPushButton(tr("Create Vault"))
        self.create_vault_button.setObjectName("saveKeyButton")
        self.create_vault_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.create_vault_button.clicked.connect(self.create_vault)
        create_layout.addWidget(self.create_vault_button, alignment=Qt.AlignmentFlag.AlignLeft)

        layout.addWidget(self.create_group)

        # ------------------------------------------------------- unlock vault
        self.unlock_group = QGroupBox(tr("Unlock Vault"))
        self.unlock_group.setObjectName("unlockVaultSection")
        unlock_layout = QVBoxLayout(self.unlock_group)
        unlock_layout.setContentsMargins(16, 16, 16, 16)
        unlock_layout.setSpacing(10)

        unlock_intro = QLabel(
            tr("Enter the master password to open this session. The Rust core checks it whenever it reads or writes the vault.")
        )
        unlock_intro.setStyleSheet("color: #8B949E; font-size: 12px; font-weight: 400;")
        unlock_intro.setWordWrap(True)
        unlock_layout.addWidget(unlock_intro)

        unlock_row = QHBoxLayout()
        unlock_row.setSpacing(10)
        self.unlock_password_input = QLineEdit()
        self.unlock_password_input.setObjectName("unlockPasswordInput")
        self.unlock_password_input.setAccessibleName(tr("Master password"))
        self.unlock_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.unlock_password_input.setPlaceholderText(tr("Master password"))
        unlock_row.addWidget(self.unlock_password_input, 1)

        self.unlock_vault_button = QPushButton(tr("Unlock Vault"))
        self.unlock_vault_button.setObjectName("saveKeyButton")
        self.unlock_vault_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.unlock_vault_button.clicked.connect(self.unlock_vault)
        unlock_row.addWidget(self.unlock_vault_button)
        unlock_layout.addLayout(unlock_row)

        layout.addWidget(self.unlock_group)

        # ----------------------------------------------------------- key table
        self.keys_group = QGroupBox(tr("Keys Stored in the Vault"))
        self.keys_group.setObjectName("keysVaultSection")
        keys_layout = QVBoxLayout(self.keys_group)
        keys_layout.setContentsMargins(16, 16, 16, 16)
        keys_layout.setSpacing(10)

        keys_note = QLabel(tr("Secrets are sealed with AES-256-GCM and stored with POSIX 0600 permissions."))
        keys_note.setStyleSheet("color: #8B949E; font-size: 12px; font-weight: 400;")
        keys_note.setWordWrap(True)
        keys_layout.addWidget(keys_note)

        self.keys_table = QTableWidget()
        self.keys_table.setObjectName("keysTable")
        self.keys_table.setColumnCount(3)
        self.keys_table.setHorizontalHeaderLabels(
            [
                tr("Variable / Provider Name"),
                tr("Protected Key"),
                tr("Security"),
            ]
        )
        self.keys_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.keys_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.keys_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.keys_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.keys_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.keys_table.setMinimumHeight(150)
        self.keys_table.itemSelectionChanged.connect(self._handle_table_selection_changed)
        keys_layout.addWidget(self.keys_table, 1)

        add_group = QGroupBox(tr("Add or Update a Key"))
        add_group.setObjectName("addKeySection")
        add_layout = QVBoxLayout(add_group)
        add_layout.setContentsMargins(16, 16, 16, 16)
        add_layout.setSpacing(12)

        fields_row = QHBoxLayout()
        fields_row.setSpacing(12)

        provider_col = QVBoxLayout()
        provider_col.setSpacing(4)
        provider_label = QLabel(tr("Variable / Provider Name:"))
        provider_label.setStyleSheet("color: #8B949E; font-size: 11px;")
        self.provider_combo = QComboBox()
        self.provider_combo.setObjectName("providerCombo")
        self.provider_combo.setAccessibleName(tr("Provider name or API variable"))
        self.provider_combo.setEditable(True)
        for provider in self.COMMON_PROVIDERS:
            self.provider_combo.addItem(provider)
        self.provider_combo.setCurrentIndex(-1)
        self.provider_combo.setEditText("")
        combo_line_edit = self.provider_combo.lineEdit()
        if combo_line_edit is not None:
            combo_line_edit.setPlaceholderText(tr("Select or type a variable name"))
        provider_col.addWidget(provider_label)
        provider_col.addWidget(self.provider_combo)
        fields_row.addLayout(provider_col, 1)

        key_col = QVBoxLayout()
        key_col.setSpacing(4)
        key_label = QLabel(tr("Secret Key Value:"))
        key_label.setStyleSheet("color: #8B949E; font-size: 11px;")
        self.key_input = QLineEdit()
        self.key_input.setObjectName("keyInput")
        self.key_input.setAccessibleName(tr("Secret API key value"))
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.setPlaceholderText(tr("Paste the token or secret key here"))
        key_col.addWidget(key_label)
        key_col.addWidget(self.key_input)
        fields_row.addLayout(key_col, 2)

        add_layout.addLayout(fields_row)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(10)

        self.save_button = QPushButton(tr("Save Key"))
        self.save_button.setObjectName("saveKeyButton")
        self.save_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_button.clicked.connect(self.save_key)
        actions_row.addWidget(self.save_button)

        self.remove_button = QPushButton(tr("Remove"))
        self.remove_button.setObjectName("removeKeyButton")
        self.remove_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove_button.clicked.connect(self.remove_key)
        actions_row.addWidget(self.remove_button)

        actions_row.addStretch(1)
        add_layout.addLayout(actions_row)

        self.status_label = QLabel("")
        self.status_label.setObjectName("vaultStatusLabel")
        self.status_label.setWordWrap(True)
        add_layout.addWidget(self.status_label)

        keys_layout.addWidget(add_group)
        layout.addWidget(self.keys_group)

        # ----------------------------------------------------- change password
        self.change_group = QGroupBox(tr("Change Password"))
        self.change_group.setObjectName("changePasswordSection")
        change_layout = QVBoxLayout(self.change_group)
        change_layout.setContentsMargins(16, 16, 16, 16)
        change_layout.setSpacing(12)

        change_intro = QLabel(
            tr("Re-keying keeps every key, conversation and memory. A reset destroys all of them and starts an empty vault.")
        )
        change_intro.setStyleSheet("color: #8B949E; font-size: 12px; font-weight: 400;")
        change_intro.setWordWrap(True)
        change_layout.addWidget(change_intro)

        rekey_group = QGroupBox(tr("Re-key with current password"))
        rekey_group.setObjectName("rekeyVaultSection")
        rekey_layout = QVBoxLayout(rekey_group)
        rekey_layout.setContentsMargins(16, 16, 16, 16)
        rekey_layout.setSpacing(8)

        self.current_password_input = QLineEdit()
        self.current_password_input.setObjectName("currentPasswordInput")
        self.current_password_input.setAccessibleName(tr("Current master password"))
        self.current_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.current_password_input.setPlaceholderText(tr("Current password"))
        rekey_layout.addWidget(self.current_password_input)

        self.rekey_new_password_input = QLineEdit()
        self.rekey_new_password_input.setObjectName("rekeyNewPasswordInput")
        self.rekey_new_password_input.setAccessibleName(tr("New master password"))
        self.rekey_new_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.rekey_new_password_input.setPlaceholderText(tr("New password (at least 12 characters)"))
        rekey_layout.addWidget(self.rekey_new_password_input)

        self.rekey_confirm_password_input = QLineEdit()
        self.rekey_confirm_password_input.setObjectName("rekeyConfirmPasswordInput")
        self.rekey_confirm_password_input.setAccessibleName(tr("Confirm new master password"))
        self.rekey_confirm_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.rekey_confirm_password_input.setPlaceholderText(tr("Confirm new password"))
        rekey_layout.addWidget(self.rekey_confirm_password_input)

        self.rekey_button = QPushButton(tr("Re-key Vault"))
        self.rekey_button.setObjectName("saveKeyButton")
        self.rekey_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.rekey_button.clicked.connect(self.rekey_vault)
        rekey_layout.addWidget(self.rekey_button, alignment=Qt.AlignmentFlag.AlignLeft)

        change_layout.addWidget(rekey_group)

        reset_group = QGroupBox(tr("Reset vault"))
        reset_group.setObjectName("resetVaultSection")
        reset_layout = QVBoxLayout(reset_group)
        reset_layout.setContentsMargins(16, 16, 16, 16)
        reset_layout.setSpacing(8)

        reset_intro = QLabel(
            tr("Every sealed entry is destroyed and a new empty vault is created with the password typed below.")
        )
        reset_intro.setStyleSheet("color: #F85149; font-size: 12px; font-weight: 400;")
        reset_intro.setWordWrap(True)
        reset_layout.addWidget(reset_intro)

        self.reset_new_password_input = QLineEdit()
        self.reset_new_password_input.setObjectName("resetNewPasswordInput")
        self.reset_new_password_input.setAccessibleName(tr("New master password after reset"))
        self.reset_new_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.reset_new_password_input.setPlaceholderText(tr("New password (at least 12 characters)"))
        reset_layout.addWidget(self.reset_new_password_input)

        self.reset_confirm_password_input = QLineEdit()
        self.reset_confirm_password_input.setObjectName("resetConfirmPasswordInput")
        self.reset_confirm_password_input.setAccessibleName(tr("Confirm new master password after reset"))
        self.reset_confirm_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.reset_confirm_password_input.setPlaceholderText(tr("Confirm new password"))
        reset_layout.addWidget(self.reset_confirm_password_input)

        self.reset_button = QPushButton(tr("Reset Vault & Create New Password"))
        self.reset_button.setObjectName("dangerVaultButton")
        self.reset_button.setStyleSheet(DANGER_BUTTON_QSS)
        self.reset_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_button.clicked.connect(self.reset_vault)
        reset_layout.addWidget(self.reset_button, alignment=Qt.AlignmentFlag.AlignLeft)

        change_layout.addWidget(reset_group)

        self.change_status_label = QLabel("")
        self.change_status_label.setObjectName("vaultStatusLabel")
        self.change_status_label.setWordWrap(True)
        change_layout.addWidget(self.change_status_label)

        layout.addWidget(self.change_group)

        # ------------------------------------------------------ memory storage
        memory_group = QGroupBox(tr("Storage and Memory"))
        memory_group.setObjectName("memoryStorageSection")
        mem_layout = QVBoxLayout(memory_group)
        mem_layout.setContentsMargins(16, 16, 16, 16)
        mem_layout.setSpacing(10)

        effective_memory, configured_memory = resolve_memory_dirs()
        self.memory_picker = DirectoryPickerWidget(
            current_path=str(effective_memory),
            label_text=tr("Memory Storage Directory (Semantic/Episodic)"),
            parent=self,
        )
        mem_layout.addWidget(self.memory_picker)

        self.memory_note_label = QLabel("")
        self.memory_note_label.setObjectName("vaultStatusLabel")
        self.memory_note_label.setStyleSheet("color: #8B949E; font-size: 11px;")
        self.memory_note_label.setWordWrap(True)
        mem_layout.addWidget(self.memory_note_label)
        self._update_memory_note(effective_memory, configured_memory)

        mem_actions_row = QHBoxLayout()
        mem_actions_row.setSpacing(10)

        self.apply_memory_button = QPushButton(tr("Apply and Migrate"))
        self.apply_memory_button.setObjectName("saveKeyButton")
        self.apply_memory_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.apply_memory_button.clicked.connect(self.apply_memory_storage_path)
        mem_actions_row.addWidget(self.apply_memory_button)

        self.memory_status_label = QLabel("")
        self.memory_status_label.setObjectName("vaultStatusLabel")
        self.memory_status_label.setWordWrap(True)
        mem_actions_row.addWidget(self.memory_status_label, 1)

        mem_layout.addLayout(mem_actions_row)
        layout.addWidget(memory_group)
        layout.addStretch(1)

        scroll_area.setWidget(container)
        return scroll_area

    def _build_privacy_tab(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        header = QLabel(tr("API Consent and Privacy Management"))
        header.setStyleSheet("font-weight: 600; color: #EAEAEA; font-size: 14px;")
        header.setWordWrap(True)
        layout.addWidget(header)

        desc = QLabel(
            tr(
                "MARK runs under a zero-plaintext-token policy with human-in-the-loop consent. "
                "When 'Remember this decision' is checked on an external API call, the authorisation is stored "
                "with authenticated AES-256-GCM encryption in the secure vault, which removes redundant pop-ups."
            )
        )
        desc.setStyleSheet("color: #8E95A0; font-size: 12px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        table_label = QLabel(tr("Authorised APIs and Tools"))
        table_label.setStyleSheet("font-weight: 600; color: #EAEAEA; font-size: 13px; margin-top: 6px;")
        layout.addWidget(table_label)

        self.permissions_table = QTableWidget()
        self.permissions_table.setObjectName("permissionsTable")
        self.permissions_table.setColumnCount(3)
        self.permissions_table.setHorizontalHeaderLabels(
            [
                tr("API / Provider"),
                tr("Persistence"),
                tr("Status"),
            ]
        )
        self.permissions_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.permissions_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.permissions_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.permissions_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.permissions_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        layout.addWidget(self.permissions_table, 1)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        self.revoke_all_button = QPushButton(tr("Clear API Authorisations"))
        self.revoke_all_button.setObjectName("revokeAllPermissionsButton")
        self.revoke_all_button.setAccessibleName(tr("Clear API Authorisations (Revoke All)"))
        self.revoke_all_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.revoke_all_button.setStyleSheet("""
            QPushButton#revokeAllPermissionsButton {
                background: #DA3633;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 8px 18px;
                font-size: 13px;
                font-weight: 500;
            }
            QPushButton#revokeAllPermissionsButton:hover {
                background: #F85149;
            }
        """)
        self.revoke_all_button.clicked.connect(self.revoke_all_api_permissions)
        self.revoke_all_btn = self.revoke_all_button
        btn_layout.addWidget(self.revoke_all_button)

        self.refresh_permissions_btn = QPushButton(tr("Refresh"))
        self.refresh_permissions_btn.setObjectName("refreshPermissionsButton")
        self.refresh_permissions_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_permissions_btn.clicked.connect(self.refresh_permissions_table)
        btn_layout.addWidget(self.refresh_permissions_btn)

        btn_layout.addStretch(1)
        layout.addLayout(btn_layout)

        self.privacy_status_label = QLabel("")
        self.privacy_status_label.setObjectName("privacyStatusLabel")
        self.privacy_status_label.setStyleSheet("color: #3FB950; font-size: 12px;")
        self.privacy_status_label.setWordWrap(True)
        layout.addWidget(self.privacy_status_label)

        self.refresh_permissions_table()
        return container

    # ----------------------------------------------------------- vault engine
    def _vault_status(self) -> dict[str, Any]:
        """Read the vault state without ever raising into the UI thread."""
        try:
            status = dict(rust.vault_status() or {})
        except Exception as exc:
            logger.error("Vault status failed: %s", exc)
            status = {}
            status["message"] = str(exc)
        status.setdefault("exists", False)
        status.setdefault("sealed", False)
        status.setdefault("path", "")
        status.setdefault("entries", 0)
        status.setdefault("backend", "unavailable")
        return status

    @staticmethod
    def _set_feedback(label: QLabel, text: str, color: str) -> None:
        label.setStyleSheet(f"color: {color}; font-size: 12px;")
        label.setText(text)

    def _update_memory_note(self, effective: Path, configured: Path) -> None:
        try:
            same = configured.resolve() == effective.resolve()
        except OSError:
            same = str(configured) == str(effective)
        if same:
            self.memory_note_label.setStyleSheet("color: #8B949E; font-size: 11px;")
            self.memory_note_label.setText(
                tr("Resolved through the MARK path helper inside the XDG data directory.")
            )
        else:
            self.memory_note_label.setStyleSheet("color: #E3B341; font-size: 11px;")
            self.memory_note_label.setText(
                tr(
                    "The stored configuration points to {stored}; Apply and Migrate moves the databases into the XDG data directory shown above."
                ).format(stored=str(configured))
            )

    def refresh_vault_state(self) -> None:
        """Drive the whole vault tab from the real Rust vault state."""
        status = self._vault_status()
        self._vault_status_cache = status
        available = rust.available()
        exists = bool(status.get("exists"))
        self._vault_unlocked = bool(self._vault_unlocked and exists)

        if not available:
            state_text = tr("Rust vault unavailable")
        elif not exists:
            state_text = tr("No master password yet")
        elif self._vault_unlocked:
            state_text = tr("Vault unlocked for this session")
        else:
            state_text = tr("Vault locked")
        self.vault_state_label.setText(state_text)

        details = [
            tr("Backend: {backend}").format(backend=str(status.get("backend") or "unknown")),
            tr("Vault file: {path}").format(path=str(status.get("path") or tr("not reported"))),
            tr("Sealed entries: {count}").format(count=int(status.get("entries") or 0)),
            tr("State: {state}").format(state=tr("Sealed") if status.get("sealed") else tr("Not sealed")),
        ]
        self.vault_details_label.setText("\n".join(details))

        self.create_group.setVisible(not exists)
        self.unlock_group.setVisible(exists and not self._vault_unlocked)
        gate = exists and self._vault_unlocked
        self.keys_group.setEnabled(gate)
        self.change_group.setVisible(True)
        self.change_group.setEnabled(gate)

        for button in (self.create_vault_button, self.unlock_vault_button, self.rekey_button, self.reset_button):
            button.setEnabled(available)
        self.create_vault_button.setVisible(not exists)
        self.unlock_vault_button.setVisible(exists and not self._vault_unlocked)

        if not available:
            self._set_feedback(
                self.vault_feedback_label,
                tr(
                    "mark-vault was not found in target/release or PATH. Master-password actions stay disabled until the Rust workspace is built."
                ),
                "#E3B341",
            )
        elif self._vault_unlocked:
            self._set_feedback(
                self.vault_feedback_label,
                tr("Vault session open. The Rust core verifies the master password on every read and write."),
                "#8B949E",
            )
        elif exists:
            self._set_feedback(
                self.vault_feedback_label,
                tr("The vault is sealed. Enter the master password to reach the keys."),
                "#E3B341",
            )
        else:
            self._set_feedback(
                self.vault_feedback_label,
                tr("Create the master password to start the vault."),
                "#8B949E",
            )

        self.refresh_keys_table()

    def _handle_new_password_changed(self, text: str) -> None:
        score = password_score(text)
        self._update_strength_meter(score)

    def _update_strength_meter(self, score: int) -> None:
        self.strength_bar.setValue(score)
        color = STRENGTH_COLORS[score]
        self.strength_bar.setStyleSheet(
            "QProgressBar#vaultStrengthBar {"
            "  background: #22262B;"
            "  border: 1px solid #30363D;"
            "  border-radius: 4px;"
            "  height: 8px;"
            "}"
            "QProgressBar#vaultStrengthBar::chunk {"
            f"  background: {color};"
            "  border-radius: 3px;"
            "}"
        )
        self.strength_label.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 400;")
        self.strength_label.setText(tr("Strength: {label}").format(label=tr(STRENGTH_LABELS[score])))

    def create_vault(self) -> bool:
        """Create the vault with the first master password (rust.vault_init)."""
        password = self.new_password_input.text()
        confirm = self.confirm_password_input.text()
        if not rust.available():
            self._set_feedback(
                self.vault_feedback_label,
                tr("The Rust vault binary is unavailable, so no master password can be created."),
                "#F85149",
            )
            return False
        if len(password) < MIN_MASTER_PASSWORD_LENGTH:
            self._set_feedback(
                self.vault_feedback_label,
                tr("Use at least {count} characters for the master password.").format(
                    count=MIN_MASTER_PASSWORD_LENGTH
                ),
                "#F85149",
            )
            return False
        if password != confirm:
            self._set_feedback(
                self.vault_feedback_label,
                tr("The two passwords do not match."),
                "#F85149",
            )
            return False

        result = rust.vault_init(password)
        if result.get("ok"):
            rust.vault_unlock(password)
        message = str(result.get("message") or "").strip()
        if result.get("ok"):
            self.new_password_input.clear()
            self.confirm_password_input.clear()
            self._vault_unlocked = True
            self.refresh_vault_state()
            text = (
                tr("Master password created. Rust vault: {message}").format(message=message)
                if message
                else tr("Master password created.")
            )
            self._set_feedback(self.vault_feedback_label, text, "#3FB950")
            return True

        self._set_feedback(
            self.vault_feedback_label,
            tr("Rust vault refused the request: {message}").format(
                message=message or tr("no message returned")
            ),
            "#F85149",
        )
        return False

    def unlock_vault(self) -> bool:
        """Open the vault session for this window.

        The bridge contract exposes ``vault_status``/``vault_init``/``vault_rekey``/
        ``vault_factory_reset`` only, so this button never claims the password was
        cryptographically checked: it opens the local session and states that the
        Rust core verifies the password on the next read or write.
        """
        password = self.unlock_password_input.text()
        if not rust.available():
            self._set_feedback(
                self.vault_feedback_label,
                tr("The Rust vault binary is unavailable, so the vault cannot be opened."),
                "#F85149",
            )
            return False
        if not password:
            self._set_feedback(
                self.vault_feedback_label,
                tr("Enter the master password."),
                "#F85149",
            )
            return False

        status = self._vault_status()
        if not status.get("exists"):
            self._set_feedback(
                self.vault_feedback_label,
                tr("No vault exists yet. Create a master password first."),
                "#F85149",
            )
            self.refresh_vault_state()
            return False

        result = rust.vault_unlock(password)
        if not result.get("ok"):
            self._set_feedback(
                self.vault_feedback_label,
                tr("The Rust vault rejected the master password: {detail}").format(
                    detail=str(result.get("message") or result.get("error") or "")
                ),
                "#F85149",
            )
            return False
        self.unlock_password_input.clear()
        self._vault_unlocked = True
        self.refresh_vault_state()
        self.refresh_keys_table()
        self._set_feedback(
            self.vault_feedback_label,
            tr("Vault unlocked: {count} sealed entries opened by the Rust core.").format(
                count=int(result.get("count") or 0)
            ),
            "#3FB950",
        )
        return True

    def rekey_vault(self) -> bool:
        """Rotate the master password keeping every entry (rust.vault_rekey)."""
        current = self.current_password_input.text()
        new_password = self.rekey_new_password_input.text()
        confirm = self.rekey_confirm_password_input.text()
        if not rust.available():
            self._set_feedback(
                self.change_status_label,
                tr("The Rust vault binary is unavailable, so the password cannot be rotated."),
                "#F85149",
            )
            return False
        if not current or not new_password:
            self._set_feedback(
                self.change_status_label,
                tr("Fill in the current password and the new password."),
                "#F85149",
            )
            return False
        if len(new_password) < MIN_MASTER_PASSWORD_LENGTH:
            self._set_feedback(
                self.change_status_label,
                tr("Use at least {count} characters for the new password.").format(
                    count=MIN_MASTER_PASSWORD_LENGTH
                ),
                "#F85149",
            )
            return False
        if new_password != confirm:
            self._set_feedback(
                self.change_status_label,
                tr("The new password and its confirmation do not match."),
                "#F85149",
            )
            return False
        if new_password == current:
            self._set_feedback(
                self.change_status_label,
                tr("The new password is identical to the current one."),
                "#E3B341",
            )
            return False

        result = rust.vault_rekey(current, new_password)
        if result.get("ok"):
            self.refresh_keys_table()
        message = str(result.get("message") or "").strip()
        if result.get("ok"):
            entries = int(result.get("entries") or self._vault_status().get("entries") or 0)
            self.current_password_input.clear()
            self.rekey_new_password_input.clear()
            self.rekey_confirm_password_input.clear()
            self.refresh_vault_state()
            text = tr("Vault re-keyed with {count} entries preserved.").format(count=entries)
            if message:
                text = f"{text} {tr('Rust vault: {message}').format(message=message)}"
            self._set_feedback(self.change_status_label, text, "#3FB950")
            return True

        self._set_feedback(
            self.change_status_label,
            tr("Rust vault refused the re-key: {message}").format(
                message=message or tr("no message returned")
            ),
            "#F85149",
        )
        return False

    def reset_vault(self) -> bool:
        """Destroy every entry and create a fresh vault (rust.vault_factory_reset)."""
        password = self.reset_new_password_input.text()
        confirm = self.reset_confirm_password_input.text()
        if not rust.available():
            self._set_feedback(
                self.change_status_label,
                tr("The Rust vault binary is unavailable, so the vault cannot be reset."),
                "#F85149",
            )
            return False
        if len(password) < MIN_MASTER_PASSWORD_LENGTH:
            self._set_feedback(
                self.change_status_label,
                tr("Use at least {count} characters for the new master password.").format(
                    count=MIN_MASTER_PASSWORD_LENGTH
                ),
                "#F85149",
            )
            return False
        if password != confirm:
            self._set_feedback(
                self.change_status_label,
                tr("The new password and its confirmation do not match."),
                "#F85149",
            )
            return False

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle(tr("Reset vault"))
        box.setText(tr("This destroys every key, conversation and memory sealed by the vault."))
        box.setInformativeText(tr("The action cannot be undone. Continue with the new master password?"))
        box.setStandardButtons(QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        yes_button = box.button(QMessageBox.StandardButton.Yes)
        if yes_button is not None:
            yes_button.setText(tr("Reset Vault"))
        box.exec()
        if box.clickedButton() is not yes_button:
            self._set_feedback(self.change_status_label, tr("Reset cancelled."), "#8B949E")
            return False

        result = rust.vault_factory_reset(password)
        if result.get("ok"):
            self.refresh_keys_table()
        message = str(result.get("message") or "").strip()
        if result.get("ok"):
            self.reset_new_password_input.clear()
            self.reset_confirm_password_input.clear()
            self._vault_unlocked = True
            self.refresh_vault_state()
            text = tr("Vault destroyed and re-created with the new master password.")
            if message:
                text = f"{text} {tr('Rust vault: {message}').format(message=message)}"
            self._set_feedback(self.change_status_label, text, "#3FB950")
            return True

        self._set_feedback(
            self.change_status_label,
            tr("Rust vault refused the reset: {message}").format(
                message=message or tr("no message returned")
            ),
            "#F85149",
        )
        return False

    # ---------------------------------------------------------------- privacy
    def revoke_all_api_permissions(self) -> None:
        """Revoke every API authorisation, in the session cache and in the vault."""
        APIConsentManager.revoke_all_permissions()
        self.refresh_permissions_table()
        self.privacy_status_label.setStyleSheet("color: #3FB950; font-size: 12px;")
        self.privacy_status_label.setText(tr("Every API authorisation has been revoked."))

    def refresh_permissions_table(self) -> None:
        """Repaint the permissions table from the consent manager."""
        permissions = APIConsentManager.list_permissions()
        self.permissions_table.setRowCount(0)
        for row_idx, permission in enumerate(permissions):
            self.permissions_table.insertRow(row_idx)
            item_name = QTableWidgetItem(str(permission.get("api_name", "")))
            permanent = permission.get("duration") == "permanent"
            duration_str = tr("Permanent (Secure Vault)") if permanent else tr("Current Session")
            item_duration = QTableWidgetItem(duration_str)
            item_status = QTableWidgetItem(tr("Authorised (Active)"))
            self.permissions_table.setItem(row_idx, 0, item_name)
            self.permissions_table.setItem(row_idx, 1, item_duration)
            self.permissions_table.setItem(row_idx, 2, item_status)

    # -------------------------------------------------------------- inference
    def load_inference_settings(self) -> None:
        """Reload the persisted local inference parameters into the widgets."""
        params = get_local_inference_params()
        if hasattr(self, "slider_ctx"):
            self.slider_ctx.setValue(params.get("num_ctx", 4096))
        if hasattr(self, "slider_gpu"):
            self.slider_gpu.setValue(params.get("num_gpu", 16))
        if hasattr(self, "slider_threads"):
            self.slider_threads.setValue(params.get("num_thread", min(3, get_hardware_cpu_limit())))
        if hasattr(self, "input_num_batch"):
            self.input_num_batch.setValue(params.get("num_batch", 2048))
        if hasattr(self, "input_physical_batch"):
            self.input_physical_batch.setValue(params.get("physical_batch_size", 512))
        if hasattr(self, "input_reasoning_budget"):
            self.input_reasoning_budget.setText(str(params.get("reasoning_budget_message", "")))
        if hasattr(self, "auto_rope_base"):
            self.auto_rope_base.set_auto(params.get("rope_freq_base") is None)
        if hasattr(self, "auto_rope_scale"):
            self.auto_rope_scale.set_auto(params.get("rope_freq_scale") is None)
        if hasattr(self, "toggle_offload_kv"):
            self.toggle_offload_kv.setChecked(bool(params.get("offload_kv_cache", True)))
        if hasattr(self, "toggle_keep_model"):
            self.toggle_keep_model.setChecked(bool(params.get("keep_model_in_memory", True)))
        if hasattr(self, "toggle_mmap"):
            self.toggle_mmap.setChecked(bool(params.get("use_mmap", True)))
        if hasattr(self, "auto_seed"):
            self.auto_seed.set_auto(params.get("seed") is None)
        if hasattr(self, "toggle_flash_attn"):
            self.toggle_flash_attn.setChecked(bool(params.get("flash_attn", True)))

    def sync_models(self) -> dict[str, Any]:
        """Consulta os provedores com chave no cofre e publica os modelos achados."""
        from ..model_discovery import discover_configured_providers

        result = discover_configured_providers()
        providers = result.get("providers") or {}
        count = sum(len(items) for items in providers.values())
        if hasattr(self, "models_discovered"):
            self.models_discovered.emit(result)
        if hasattr(self, "engine_status_value"):
            self.engine_status_value.setText(
                tr("Models discovered: {count}").format(count=count)
            )
            self.engine_status_value.setToolTip(str(sorted(providers)))
        return result

    def set_resolved_engine(self, model_id: str, engine: str, label: str) -> None:
        """Mostra o motor resolvido para o modelo atual (somente leitura)."""
        if not hasattr(self, "engine_status_value"):
            return
        shown = label if model_id else tr("no model selected")
        self.engine_status_value.setText(f"{tr('Engine')}: {shown}")
        self.engine_status_value.setToolTip(
            f"model={model_id or '-'} engine={engine} (resolvido automaticamente)"
        )

    def reload_inference_engine(self) -> dict[str, Any]:
        """Collect, clamp, persist and apply the local inference parameters."""
        if hasattr(self, "slider_ctx"):
            self.slider_ctx._handle_editing_finished()
        if hasattr(self, "slider_gpu"):
            self.slider_gpu._handle_editing_finished()
        if hasattr(self, "slider_threads"):
            self.slider_threads._handle_editing_finished()
        if hasattr(self, "input_num_batch"):
            self.input_num_batch._handle_editing_finished()
        if hasattr(self, "input_physical_batch"):
            self.input_physical_batch._handle_editing_finished()

        requested_ctx = self.slider_ctx.value()
        params = {
            "num_ctx": requested_ctx,
            "num_gpu": self.slider_gpu.value(),
            "num_thread": self.slider_threads.value(),
            "num_batch": self.input_num_batch.value(),
            "physical_batch_size": self.input_physical_batch.value(),
            "reasoning_budget_message": self.input_reasoning_budget.text().strip(),
            "rope_freq_base": None if self.auto_rope_base.is_auto() else 10000.0,
            "rope_freq_scale": None if self.auto_rope_scale.is_auto() else 1.0,
            "offload_kv_cache": self.toggle_offload_kv.isChecked(),
            "keep_model_in_memory": self.toggle_keep_model.isChecked(),
            "use_mmap": self.toggle_mmap.isChecked(),
            "seed": None if self.auto_seed.is_auto() else 42,
            "flash_attn": self.toggle_flash_attn.isChecked(),
        }

        saved = save_local_inference_params(params)

        self.slider_ctx.setValue(saved["num_ctx"])
        self.slider_gpu.setValue(saved["num_gpu"])
        self.slider_threads.setValue(saved["num_thread"])
        self.input_num_batch.setValue(saved["num_batch"])
        self.input_physical_batch.setValue(saved["physical_batch_size"])

        if hasattr(self, "inference_status_label"):
            # The widgets clamp to the same 512..2097152 window as the config
            # guardrail, so this branch only fires when the configured limit is
            # tighter than the slider range (for example after a downgrade).
            if int(saved["num_ctx"]) != int(requested_ctx):
                self.inference_status_label.setStyleSheet("color: #E3B341;")
                self.inference_status_label.setText(
                    tr("Engine guardrail stored {value} tokens instead of the requested context.").format(
                        value=int(saved["num_ctx"])
                    )
                )
            else:
                self.inference_status_label.setStyleSheet("color: #3FB950;")
                self.inference_status_label.setText(tr("Parameters applied. Engine reloaded."))

        self.reload_inference_engine_requested.emit(saved)
        return saved

    # ----------------------------------------------------------------- events
    def _handle_back_clicked(self) -> None:
        self.back_requested.emit()

    def _handle_table_selection_changed(self) -> None:
        selected_rows = self.keys_table.selectedItems()
        if selected_rows:
            provider_name = selected_rows[0].text()
            self.provider_combo.setEditText(provider_name)

    def refresh_keys_table(self) -> None:
        """Preenche a tabela com as chaves reais do cofre Rust, mascaradas."""
        self.keys_table.setRowCount(0)
        if not self._vault_unlocked:
            return
        listing = rust.vault_list()
        if not listing.get("ok"):
            return
        for row, name in enumerate(listing.get("keys", [])):
            entry = rust.vault_get(name)
            secret = str(entry.get("value") or "") if entry.get("ok") else ""
            self.keys_table.insertRow(row)
            item_provider = QTableWidgetItem(str(name).upper())
            item_provider.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            item_key = QTableWidgetItem(mask_api_key(secret))
            item_key.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            item_sec = QTableWidgetItem(tr("Argon2id + AES-256-GCM (Rust)"))
            item_sec.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            item_sec.setForeground(Qt.GlobalColor.darkGray)
            self.keys_table.setItem(row, 0, item_provider)
            self.keys_table.setItem(row, 1, item_key)
            self.keys_table.setItem(row, 2, item_sec)

    def save_key(self) -> bool:
        """Store a key for any provider name, without a hardcoded provider list."""
        if not self._vault_unlocked:
            self._set_feedback(self.status_label, tr("Unlock the vault before changing keys."), "#F85149")
            return False
        provider = self.provider_combo.currentText().strip()
        key_val = self.key_input.text().strip()

        if not provider:
            self._set_feedback(
                self.status_label,
                tr("Enter the provider name or API variable."),
                "#F85149",
            )
            return False

        if not key_val:
            self._set_feedback(
                self.status_label,
                tr("The API key value cannot be empty."),
                "#F85149",
            )
            return False

        try:
            result = rust.vault_set(provider.upper(), key_val)
            if not result.get("ok"):
                raise RuntimeError(str(result.get("message") or result.get("error") or "vault-set-failed"))
            self.key_input.clear()
            self.refresh_keys_table()
            self._set_feedback(
                self.status_label,
                tr("Key '{provider}' saved to the vault.").format(provider=provider),
                "#3FB950",
            )
            self.key_saved.emit(provider)
            return True
        except Exception as exc:
            self._set_feedback(
                self.status_label,
                tr("Failed to save the key: {error}").format(error=str(exc)),
                "#F85149",
            )
            return False

    def remove_key(self) -> bool:
        """Remove the selected or typed key from the vault."""
        if not self._vault_unlocked:
            self._set_feedback(self.status_label, tr("Unlock the vault before changing keys."), "#F85149")
            return False
        provider = self.provider_combo.currentText().strip()
        selected_items = self.keys_table.selectedItems()
        if selected_items:
            provider = selected_items[0].text().strip()

        if not provider:
            self._set_feedback(
                self.status_label,
                tr("Select or type a key to remove."),
                "#F85149",
            )
            return False

        try:
            deleted = rust.vault_delete(provider.upper())
            removed = bool(deleted.get("removed"))
            self.refresh_keys_table()
            if removed:
                self._set_feedback(
                    self.status_label,
                    tr("Key '{provider}' removed from the vault.").format(provider=provider),
                    "#3FB950",
                )
                self.key_removed.emit(provider)
                return True
            self._set_feedback(
                self.status_label,
                tr("Key '{provider}' was not found in the vault.").format(provider=provider),
                "#E3B341",
            )
            return False
        except Exception as exc:
            self._set_feedback(
                self.status_label,
                tr("Failed to remove the key: {error}").format(error=str(exc)),
                "#F85149",
            )
            return False

    def apply_memory_storage_path(self) -> bool:
        """Persist the chosen memory directory and migrate the existing databases."""
        new_path = self.memory_picker.path()
        if not new_path:
            self._set_feedback(
                self.memory_status_label,
                tr("Select a valid path."),
                "#F85149",
            )
            return False

        try:
            report = set_memory_storage_path(new_path, migrate=True)
            reload_memory_backends(new_path)
            migrated_count = len(report.get("migrated_files", []))
            self._set_feedback(
                self.memory_status_label,
                tr("Directory updated. {count} file(s) migrated.").format(count=migrated_count),
                "#3FB950",
            )
            self.memory_path_updated.emit(new_path)
            effective_memory, configured_memory = resolve_memory_dirs()
            self._update_memory_note(effective_memory, configured_memory)
            return True
        except Exception as exc:
            self._set_feedback(
                self.memory_status_label,
                tr("Failed to update the directory: {error}").format(error=str(exc)),
                "#F85149",
            )
            return False


class UniversalKeyVaultDialog(QDialog):
    """Modal dialog hosting the universal key vault panel."""

    def __init__(self, vault: LLMKeyVault | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("MARK · Universal API Key Vault"))
        self.resize(820, 640)
        self.setStyleSheet("background: #1A1D21;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.settings_widget = SettingsWidget(vault=vault, on_back=self.accept, parent=self)
        layout.addWidget(self.settings_widget)
