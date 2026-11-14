import re

import json
import logging
import threading
from typing import Any
from .i18n import tr
from .icons import vector_icon

from PyQt6.QtCore import QObject, QSettings, QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QIntValidator, QPainter, QPen
from PyQt6.QtWidgets import (
  QTextBrowser,
  QToolButton,
  QAbstractButton,
  QApplication,
  QCheckBox,
  QComboBox,
  QDialog,
  QFileDialog,
  QFrame,
  QHBoxLayout,
  QLabel,
  QLineEdit,
  QMenu,
  QPushButton,
  QSizePolicy,
  QSlider,
  QTextEdit,
  QVBoxLayout,
  QWidget,
)


from ..desktop_theme import message_html
from ..memory import source_label
from ..config.llm_config import LLMConfig, get_llm_config
from .theme_manager import ThemeManager

logger = logging.getLogger("mark.ui.widgets")



BANNED_MODEL_PATTERNS: tuple[str, ...] = (
  "llama3.2",
  "gpt-4o",
  "claude-3-5-sonnet",
  "qwen2.5-coder:7b",
  "gemini",
  "test-mark",
  "mark-test-302m",
  "302m_iq4_nl",
  "markvl-2.2b:2.2b",
)


def is_banned_model(name: str) -> bool:
  """Indica modelos legados proibidos no seletor de modelos do composer."""
  clean = str(name or "").strip().lower()
  return any(pattern in clean for pattern in BANNED_MODEL_PATTERNS)


class MessageBubbleWidget(QFrame):
  """Widget de mensagem do MARK e do Usuario no estilo Minimalismo Tecnico Radical.
  
  As mensagens flutuam na grade, separadas exclusivamente por espacamento negativo,
  sem bolhas delimitadas, sem bordas visiveis e sem raio de curvatura.
  """

  def __init__(
    self,
    text: str,
    role: str = "assistant",
    source: str = "",
    link_handler: Any = None,
    parent: QWidget | None = None,
  ) -> None:
    super().__init__(parent)
    self.role = role
    self.text = text
    self.source = source
    self._link_handler = link_handler
    self._build_ui()

  def _build_ui(self) -> None:
    is_user = self.role == "user"
    self.setObjectName("userBubble" if is_user else "assistantBubble")
    self.setMaximumWidth(680 if is_user else 760)
    self.setSizePolicy(
      QSizePolicy.Policy.Preferred if is_user else QSizePolicy.Policy.Expanding,
      QSizePolicy.Policy.Preferred,
    )

    # Claude/Linear: sem bordas duras, usuario com fundo carvão #20252C e raio 8px, MARK direto sobre fundo #121417
    if is_user:
      self.setStyleSheet(
        "background: #20252C; border: none; border-radius: 8px; padding: 8px 14px; margin: 0px 0px 0px 48px;"
      )
    else:
      self.setStyleSheet(
        "background: #121417; border: none; border-radius: 0px; padding: 6px 0px; margin: 0px;"
      )

    layout = QVBoxLayout(self)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(3)

    # Identificacao Discreta: Remetente/hora em texto secundario fino sans-serif apenas para o usuario
    if is_user:
      orig = source_label(self.source)
      sender_title = tr("Você") if not orig else f"{tr('Você')} · {orig}"
      self.who = QLabel(sender_title)
      self.who.setObjectName("messageSender")
      self.who.setStyleSheet(
        "color: #8E95A0; font-family: Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; "
        "font-size: 10px; font-weight: 500; border: none; background: transparent; padding: 0px; margin: 0px;"
      )
      self.who.setAlignment(Qt.AlignmentFlag.AlignRight)
      layout.addWidget(self.who)
    else:
      self.who = None

    # Widget interno de mensagem: sem bordas, margens ou fundos, tipografia sans-serif suave e confortavel
    self.content_view = MessageContentView(self.text, role=self.role)
    self.label = self.content_view.prose_label
    self.label.setObjectName("messageBody")
    self.label.setTextFormat(Qt.TextFormat.RichText)
    self.label.setWordWrap(True)
    self.label.setStyleSheet(
      "color: #EDEDED; font-family: Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; "
      "font-size: 13px; font-weight: 400; border: none; background: transparent; "
      "selection-background-color: #00D8F6; selection-color: #121417; margin: 0px; padding: 0px;"
    )
    self.label.setTextInteractionFlags(
      Qt.TextInteractionFlag.TextSelectableByMouse
      | Qt.TextInteractionFlag.LinksAccessibleByMouse
      | Qt.TextInteractionFlag.LinksAccessibleByKeyboard
    )
    def _handle_link(url_str: str) -> None:
      if url_str.startswith("mark-copy://"):
        from urllib.parse import unquote
        code_to_copy = unquote(url_str[12:])
        cb = QApplication.clipboard()
        if cb:
          cb.setText(code_to_copy)
        return
      if self._link_handler:
        self._link_handler(url_str)

    self.label.linkActivated.connect(_handle_link)

    if is_user:
      self.label.setAlignment(Qt.AlignmentFlag.AlignLeft)
      lines = self.text.splitlines() if self.text else [""]
      longest_line = max(lines, key=lambda s: self.label.fontMetrics().horizontalAdvance(s)) if lines else ""
      raw_advance = self.label.fontMetrics().horizontalAdvance(longest_line)
      if len(lines) == 1 and raw_advance <= 640:
        self.label.setWordWrap(False)
        self.setMinimumWidth(max(96, raw_advance + 32))
      else:
        self.label.setWordWrap(True)
        self.setMinimumWidth(min(700, max(160, raw_advance + 36)))
    else:
      self.label.setAlignment(Qt.AlignmentFlag.AlignLeft)
      self.label.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

      def context_menu(position, value=self.text, target=self.label):
        menu = QMenu(target)
        menu.setStyleSheet(
          "background: #16191D; color: #EDEDED; font-family: Inter, sans-serif; "
          "border: 1px solid #1E2228; border-radius: 8px; padding: 4px;"
        )
        menu.addAction("Copiar resposta", lambda: QApplication.clipboard().setText(value))
        menu.exec(target.mapToGlobal(position))

      self.label.customContextMenuRequested.connect(context_menu)

    layout.addWidget(self.content_view)


class ErrorCardWidget(QFrame):
  """Card de erro amigável, acolhedor e acionável para o fluxo de conversa.
  
  Apresenta explicação simplificada da falha e ações diretas de recuperação:
  - Botão [Tentar Novamente]
  - Botão [Alternar Modelo/Provedor]
  """

  retry_requested = pyqtSignal()
  switch_model_requested = pyqtSignal()

  def __init__(
    self,
    error_text: str,
    title: str = "Falha no Processamento",
    retry_callback: Any = None,
    switch_model_callback: Any = None,
    parent: QWidget | None = None,
  ) -> None:
    super().__init__(parent)
    self.setObjectName("errorCard")
    self.error_text = error_text
    self.title = title
    if retry_callback is not None:
      self.retry_requested.connect(retry_callback)
    if switch_model_callback is not None:
      self.switch_model_requested.connect(switch_model_callback)
    self._build_ui()

  def _build_ui(self) -> None:
    self.setMaximumWidth(780)
    self.setStyleSheet("""
      QFrame#errorCard {
        background: #231C20;
        border: 1px solid #5C2D35;
        border-radius: 8px;
        padding: 12px 16px;
        margin: 0px 48px 0px 0px;
      }
    """)

    layout = QVBoxLayout(self)
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(8)

    # Header: Ícone e Título
    header_layout = QHBoxLayout()
    header_layout.setContentsMargins(0, 0, 0, 0)
    header_layout.setSpacing(8)

    self.icon_label = QLabel("")
    self.icon_label.setObjectName("errorIcon")
    self.icon_label.setStyleSheet("font-size: 14px; border: none; background: transparent;")

    self.title_label = QLabel(self.title)
    self.title_label.setObjectName("errorTitle")
    self.title_label.setStyleSheet(
      "color: #FF7B72; font-family: Inter, -apple-system, BlinkMacSystemFont, sans-serif; "
      "font-size: 13px; font-weight: 500; border: none; background: transparent;"
    )

    header_layout.addWidget(self.icon_label)
    header_layout.addWidget(self.title_label)
    header_layout.addStretch(1)
    layout.addLayout(header_layout)

    # Corpo: Explicação clara e simplificada
    self.body_label = QLabel(self.error_text)
    self.body_label.setObjectName("errorBody")
    self.body_label.setWordWrap(True)
    self.body_label.setStyleSheet(
      "color: #EDEDED; font-family: Inter, -apple-system, BlinkMacSystemFont, sans-serif; "
      "font-size: 12px; font-weight: 400; line-height: 1.4; border: none; background: transparent;"
    )
    layout.addWidget(self.body_label)

    # Ações diretas de recuperação
    actions_layout = QHBoxLayout()
    actions_layout.setContentsMargins(0, 4, 0, 0)
    actions_layout.setSpacing(8)

    self.retry_button = QPushButton("Tentar Novamente")
    self.retry_button.setObjectName("retryButton")
    self.retry_button.setCursor(Qt.CursorShape.PointingHandCursor)
    self.retry_button.setStyleSheet("""
      QPushButton#retryButton {
        background: #20252C;
        color: #00D8F6;
        border: 1px solid #1E2228;
        border-radius: 6px;
        padding: 6px 14px;
        font-family: Inter, sans-serif;
        font-size: 12px;
        font-weight: 500;
      }
      QPushButton#retryButton:hover {
        background: #262B33;
        border-color: #00D8F6;
      }
      QPushButton#retryButton:pressed {
        background: #16191D;
      }
    """)
    self.retry_button.clicked.connect(self.retry_requested.emit)
    actions_layout.addWidget(self.retry_button)

    self.switch_model_button = QPushButton("Alternar Modelo/Provedor")
    self.switch_model_button.setObjectName("switchModelButton")
    self.switch_model_button.setCursor(Qt.CursorShape.PointingHandCursor)
    self.switch_model_button.setStyleSheet("""
      QPushButton#switchModelButton {
        background: #20252C;
        color: #8E95A0;
        border: 1px solid #1E2228;
        border-radius: 6px;
        padding: 6px 14px;
        font-family: Inter, sans-serif;
        font-size: 12px;
        font-weight: 500;
      }
      QPushButton#switchModelButton:hover {
        background: #262B33;
        color: #EDEDED;
        border-color: #8E95A0;
      }
      QPushButton#switchModelButton:pressed {
        background: #16191D;
      }
    """)
    self.switch_model_button.clicked.connect(self.switch_model_requested.emit)
    actions_layout.addWidget(self.switch_model_button)

    actions_layout.addStretch(1)
    layout.addLayout(actions_layout)


class ThinkingIndicatorWidget(QFrame):
  """Widget de feedback visual para estado de pensamento ("MARK está pensando...").
  
  Apresenta estética Soft Minimal Tech com indicador de pulsação discreto
  até que o streaming de resposta comece.
  """

  def __init__(self, parent: QWidget | None = None) -> None:
    super().__init__(parent)
    self.setObjectName("thinkingIndicator")
    self._step = 0
    self._timer = QTimer(self)
    self._timer.setInterval(400)
    self._timer.timeout.connect(self._animate_dots)
    self._build_ui()

  def _build_ui(self) -> None:
    self.setStyleSheet("""
      QFrame#thinkingIndicator {
        background: #121417;
        border: none;
        border-radius: 0px;
        padding: 8px 0px;
        margin: 0px 48px 0px 0px;
      }
    """)
    layout = QHBoxLayout(self)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)

    self.dot_label = QLabel("●")
    self.dot_label.setObjectName("thinkingDot")
    self.dot_label.setStyleSheet("color: #00D8F6; font-size: 11px; border: none; background: transparent;")

    self.text_label = QLabel("MARK está pensando...")
    self.text_label.setObjectName("thinkingText")
    self.text_label.setStyleSheet(
      "color: #8E95A0; font-family: Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; "
      "font-size: 13px; font-weight: 400; border: none; background: transparent;"
    )

    layout.addWidget(self.dot_label)
    layout.addWidget(self.text_label)
    layout.addStretch(1)

  def _animate_dots(self) -> None:
    self._step = (self._step + 1) % 4
    dots = "." * (self._step + 1)
    self.text_label.setText(f"MARK está pensando{dots}")

  def start(self) -> None:
    self.show()
    if not self._timer.isActive():
      self._timer.start()

  def stop(self) -> None:
    if self._timer.isActive():
      self._timer.stop()
    self.hide()

  def is_thinking(self) -> bool:
    return self._timer.isActive() and self.isVisible()


class ChatWidget(QWidget):
  """Widget container de mensagens com visual suave, acolhedor e espacamento fluido."""

  def __init__(self, parent: QWidget | None = None) -> None:
    super().__init__(parent)
    self.setObjectName("chatContent")
    self._thinking_widget: ThinkingIndicatorWidget | None = None
    self.chat_layout = QVBoxLayout(self)
    self.chat_layout.setContentsMargins(16, 16, 16, 16)
    self.chat_layout.setSpacing(ThemeManager.TOKENS.CHAT_MESSAGE_SPACING)
    self.setStyleSheet("""
      QWidget { background: #121417; border: none; }
      QLabel, QTextEdit, QTextBrowser {
        border: none;
        background: transparent;
        selection-background-color: #00D8F6;
        selection-color: #121417;
      }
    """)

  def add_bubble(
    self,
    text: str,
    role: str = "assistant",
    source: str = "",
    link_handler: Any = None,
  ) -> MessageBubbleWidget:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(0)
    bubble = MessageBubbleWidget(
      text=text,
      role=role,
      source=source,
      link_handler=link_handler,
    )
    if role == "user":
      row.addStretch(1)
    row.addWidget(bubble, 1 if role == "assistant" else 0)
    if role == "assistant":
      row.addStretch(1)
    wrapper = QWidget()
    wrapper.setStyleSheet("background: transparent; border: none; margin: 0px; padding: 0px;")
    wrapper.setLayout(row)
    self.chat_layout.addWidget(wrapper)
    return bubble

  def show_thinking(self) -> ThinkingIndicatorWidget:
    if self._thinking_widget is None:
      self._thinking_widget = ThinkingIndicatorWidget(self)
      self.chat_layout.addWidget(self._thinking_widget)
    self._thinking_widget.start()
    return self._thinking_widget

  def hide_thinking(self) -> None:
    if self._thinking_widget is not None:
      self._thinking_widget.stop()
      self.chat_layout.removeWidget(self._thinking_widget)
      self._thinking_widget.deleteLater()
      self._thinking_widget = None



class ModelDiscoveryWorker(QThread):
  """Worker assíncrono para verificar modelos locais do Ollama e chaves de nuvem sem travar a interface."""

  discovery_finished = pyqtSignal(list, dict)

  def __init__(self, config: LLMConfig | None = None, parent: QObject | None = None) -> None:
    super().__init__(parent)
    self.config = config

  def run(self) -> None:
    try:
      from ..cognition.provider_adapter import OllamaProviderAdapter

      installed_ollama = OllamaProviderAdapter.get_installed_models(timeout=1.5)
    except Exception as exc:
      logger.debug("Falha na descoberta de modelos Ollama: %s", exc)
      installed_ollama = []

    try:
      cfg = self.config or get_llm_config()
      available_cloud = cfg.get_available_providers()
    except Exception as exc:
      logger.debug("Falha na descoberta de provedores em nuvem: %s", exc)
      available_cloud = {}

    self.discovery_finished.emit(installed_ollama, available_cloud)


class ProviderSelectorWidget(QComboBox):
  """Seletor de modelos e provedores de IA com deteccao dinamica em tempo real."""

  def __init__(self, parent: QWidget | None = None, settings: QSettings | None = None) -> None:
    super().__init__(parent)
    self.setObjectName("modelSelector")
    self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
    self.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)
    if self.view() is not None:
      self.view().setTextElideMode(Qt.TextElideMode.ElideNone)
    self._badge_widget: QLabel | None = None
    self._models_meta: list[dict[str, Any]] = []
    self._config: LLMConfig | None = None
    self._worker: ModelDiscoveryWorker | None = None
    self._settings = settings or QSettings("Bannaman6655 Productions", "MARK")
    self.currentIndexChanged.connect(self._on_index_changed)

  def set_badge_widget(self, badge: QLabel) -> None:
    self._badge_widget = badge
    self._update_badge()

  def start_async_discovery(self) -> None:
    """Inicia deteccao em segundo plano para nao congelar a UI."""
    if self._worker is not None and self._worker.isRunning():
      return
    self._worker = ModelDiscoveryWorker(self._config, parent=self)
    self._worker.discovery_finished.connect(self._on_discovery_finished)
    self._worker.start()

  def _on_discovery_finished(self, installed_ollama: list[str], available_cloud: dict[str, Any]) -> None:
    self._apply_discovered_models([m for m in installed_ollama if not is_banned_model(m)], available_cloud)

  def showPopup(self) -> None:
    self.start_async_discovery()
    super().showPopup()

  def focusInEvent(self, event: Any) -> None:
    self.start_async_discovery()
    super().focusInEvent(event)

  def populate_from_config(
    self,
    config: LLMConfig | None = None,
    installed_models: list[str] | None = None,
    available_providers: dict[str, Any] | None = None,
    async_discovery: bool = False,
  ) -> None:
    """Popula o seletor com modelos reais instalados no Ollama e provedores em nuvem com chaves validas."""
    self._config = config or get_llm_config()

    if installed_models is not None or available_providers is not None:
      self._apply_discovered_models(
        [m for m in (installed_models or []) if not is_banned_model(m)],
        available_providers if available_providers is not None else {},
      )
      return

    if async_discovery:
      self.start_async_discovery()
      return

    # Sincrono (para testes headless e renderizacao imediata)
    try:
      from ..cognition.provider_adapter import OllamaProviderAdapter

      ollama_models = OllamaProviderAdapter.get_installed_models(timeout=1.0)
    except Exception:
      ollama_models = []

    try:
      cloud_provs = self._config.get_available_providers()
    except Exception:
      cloud_provs = {}

    self._apply_discovered_models([m for m in ollama_models if not is_banned_model(m)], cloud_provs)

  def _pin_local_mark_model(self) -> None:
    """Mantem o Mark-Bin-32B no topo mesmo depois de uma varredura do Ollama."""
    for index in range(self.count()):
      if "Mark-Bin-32B" in self.itemText(index):
        return
    try:
      from ..rust_bridge import rust

      if not rust.engine_status().get("checkpoint"):
        return
    except Exception:
      return
    self.insertItem(0, "Mark-Bin-32B (1-Bit W1A4, 2M context)", "mark")

  def _format_local_model_name(self, tag: str) -> str:
    """Formata o nome de exibicao amigavel de um modelo Ollama baixado garantindo o nome completo."""
    lower = tag.lower()
    if "302m" in lower or "300m" in lower:
      return f"Mark Engineer 300M ({tag})"
    if "mark-engineer" in lower:
      return f"Mark Engineer 1.5B ({tag})"
    if "mark-general" in lower:
      return f"Mark General 1.5B ({tag})"
    if "mark-vl" in lower:
      return f"MarkVL 2.2B ({tag})"
    if "qwen2.5-coder-32b" in lower:
      return f"Qwen 2.5 Coder 32B ({tag})"
    if "qwen2.5-coder-7b" in lower or ("qwen2.5-coder" in lower and "7b" in lower):
      return f"Qwen 2.5 Coder 7B ({tag})"
    if "qwen2.5-coder" in lower:
      return f"Qwen 2.5 Coder ({tag})"
    if "qwen3-vl" in lower:
      return f"Qwen3 VL ({tag})"
    if "llama-3.3" in lower:
      return f"Llama 3.3 ({tag})"
    if "llama3" in lower:
      return f"Llama 3 ({tag})"
    if "deepseek" in lower:
      return f"DeepSeek ({tag})"
    return tag

  def _format_cloud_model_name(self, provider: str, model_id: str) -> str:
    """Formata o nome exato do modelo de nuvem configurado."""
    mid_lower = model_id.lower()
    if provider.strip().lower() in {"gemini", "google"}:
      return model_id
    if "claude-3-5-sonnet" in mid_lower or "claude-3.5-sonnet" in mid_lower:
      return "Claude 3.5 Sonnet"
    if "gpt-4o" in mid_lower:
      return "GPT-4o"
    if "gemini-2.0-flash" in mid_lower or "gemini-2" in mid_lower:
      return "Gemini 2.0 Flash"
    if "deepseek" in mid_lower:
      return "DeepSeek V3"
    if "llama-3.3" in mid_lower:
      return f"Llama 3.3 ({provider.capitalize()})"
    if "mistral-large" in mid_lower:
      return "Mistral Large"
    if "openrouter" in mid_lower or model_id == "openrouter/auto":
      return "OpenRouter Auto"
    return f"{model_id} ({provider.capitalize()})"

  def _apply_discovered_models(
    self, installed_ollama: list[str], available_cloud: dict[str, Any]
  ) -> None:
    installed_ollama = [m for m in (installed_ollama or []) if not is_banned_model(m)]
    available_cloud = {k: v for k, v in dict(available_cloud or {}).items() if not is_banned_model(k)}
    self.blockSignals(True)
    prev_data = self.currentData()
    prev_text = self.currentText()
    prev_meta = (
      self._models_meta[self.currentIndex()]
      if 0 <= self.currentIndex() < len(self._models_meta)
      else None
    )
    saved_data = self._settings.value("chat/selected_model")
    self.clear()
    self._models_meta = []

    valid_items_count = 0

    # 1. Modelos Locais (Ollama)
    # Excluir MarkVL do seletor de chat geral (reservado exclusivamente para visao automatica)
    chat_ollama = [
      tag for tag in installed_ollama
      if not any(k in tag.lower() for k in ("markvl", "mark-vl"))
    ]
    if chat_ollama:
      for idx, tag in enumerate(chat_ollama):
        display_name = self._format_local_model_name(tag)
        # O primeiro modelo local recebe data='mark' para compatibilidade das rotas locais
        data_val = "mark" if idx == 0 else f"ollama:{tag}"
        self.addItem(display_name, data_val)
        item_meta = {
          "id": tag,
          "name": display_name,
          "provider": "ollama",
          "type": "Local Ollama",
          "data": data_val,
          "enabled": True,
        }
        self._models_meta.append(item_meta)
        item_idx = self.count() - 1
        tooltip = f"Modelo: {tag} · Processamento: Local Ollama (Ollama)"
        self.setItemData(item_idx, tooltip, Qt.ItemDataRole.ToolTipRole)
        valid_items_count += 1
    else:
      self.addItem("Nenhum modelo Ollama instalado", None)
      item_idx = self.count() - 1
      std_item = self.model().item(item_idx)
      if std_item is not None:
        std_item.setEnabled(False)
      self._models_meta.append({
        "id": "none_ollama",
        "name": "Nenhum modelo Ollama instalado",
        "provider": "ollama",
        "type": "Local Ollama",
        "data": None,
        "enabled": False,
      })

    # 2. Modelos em Nuvem com chaves validas
    for prov_name, profile in available_cloud.items():
      model_id = getattr(profile, "model", "") or prov_name
      display_name = self._format_cloud_model_name(prov_name, model_id)
      data_val = f"{prov_name}:{model_id}"
      self.addItem(display_name, data_val)
      item_meta = {
        "id": model_id,
        "name": display_name,
        "provider": prov_name,
        "type": "Nuvem",
        "data": data_val,
        "enabled": True,
      }
      self._models_meta.append(item_meta)
      item_idx = self.count() - 1
      tooltip = f"Modelo: {display_name} · Processamento: Nuvem ({prov_name.capitalize()})"
      self.setItemData(item_idx, tooltip, Qt.ItemDataRole.ToolTipRole)
      valid_items_count += 1

    # 3. Se nenhum provedor/modelo estiver ativo/configurado:
    if valid_items_count == 0:
      self.clear()
      self._models_meta = []
      self.addItem("Nenhum provedor ativo - Configure as Chaves", None)
      item_idx = self.count() - 1
      std_item = self.model().item(item_idx)
      if std_item is not None:
        std_item.setEnabled(False)
      self._models_meta.append({
        "id": "none_active",
        "name": "Nenhum provedor ativo - Configure as Chaves",
        "provider": "none",
        "type": "Indisponível",
        "data": None,
        "enabled": False,
      })

    # Restaura a selecao da sessao atual ou a ultima escolha salva.
    restored = False
    preferred_key = self._selection_key(prev_meta) if prev_meta else saved_data
    if preferred_key is not None:
      for i, meta in enumerate(self._models_meta):
        if meta.get("enabled", True) and self._selection_key(meta) == preferred_key:
          self.setCurrentIndex(i)
          restored = True
          break

    if not restored and prev_data is not None:
      for i, meta in enumerate(self._models_meta):
        if meta.get("enabled", True) and (
          meta.get("data") == prev_data or meta.get("name") == prev_text
        ):
          self.setCurrentIndex(i)
          restored = True
          break

    if not restored:
      for i, meta in enumerate(self._models_meta):
        if meta.get("enabled", True) and meta.get("data") is not None:
          self.setCurrentIndex(i)
          restored = True
          break

    if not restored:
      self.setCurrentIndex(0)

    self.blockSignals(False)
    if saved_data is None and prev_meta is None:
      self._persist_current_selection()
    self.adjustSize()
    text_w = self.fontMetrics().horizontalAdvance(self.currentText()) + 36
    self.setMinimumWidth(max(150, min(450, max(self.sizeHint().width(), text_w))))
    if self.view() is not None:
      max_item_w = max(
        (self.fontMetrics().horizontalAdvance(self.itemText(i)) + 44 for i in range(self.count())),
        default=240,
      )
      self.view().setMinimumWidth(max(max_item_w, self.minimumWidth()))
    self._update_badge()
    self._pin_local_mark_model()

  def _on_index_changed(self, index: int) -> None:
    self._persist_current_selection(index)
    self.adjustSize()
    text_w = self.fontMetrics().horizontalAdvance(self.currentText()) + 36
    self.setMinimumWidth(max(150, min(450, max(self.sizeHint().width(), text_w))))
    self._update_badge()

  def _persist_current_selection(self, index: int | None = None) -> None:
    selected_index = self.currentIndex() if index is None else index
    if 0 <= selected_index < len(self._models_meta):
      meta = self._models_meta[selected_index]
      selected = self._selection_key(meta)
      if selected is not None:
        self._settings.setValue("chat/selected_model", selected)
        self._settings.sync()

  @staticmethod
  def _selection_key(meta: dict[str, Any]) -> str | None:
    provider = meta.get("provider")
    model_id = meta.get("id")
    if provider and model_id and meta.get("enabled", True):
      return f"{provider}:{model_id}"
    return None

  def _update_badge(self) -> None:
    idx = self.currentIndex()
    if 0 <= idx < len(self._models_meta):
      meta = self._models_meta[idx]
      ptype = meta.get("type", "Nuvem")
      mname = meta.get("name", self.currentText())
      prov = meta.get("provider", "")
      enabled = meta.get("enabled", True)

      if not enabled or meta.get("data") is None:
        self.setToolTip("Nenhum provedor ou modelo ativo.")
        if self._badge_widget is not None:
          self._badge_widget.setText("Indisponível")
          self._badge_widget.setToolTip("Configure modelos no Ollama ou chaves de API no cofre.")
          self._badge_widget.setProperty("processing", "disabled")
          self._badge_widget.adjustSize()
          self._badge_widget.setMinimumWidth(self._badge_widget.sizeHint().width())
          style = self._badge_widget.style()
          if style:
            style.unpolish(self._badge_widget)
            style.polish(self._badge_widget)
        return

      self.setToolTip(f"{mname} · Processamento: {ptype}")
      if self._badge_widget is not None:
        self._badge_widget.setText(ptype)
        self._badge_widget.setToolTip(f"Processamento {ptype} via provedor {prov.capitalize()}")
        self._badge_widget.setProperty("processing", "local" if ptype == "Local Ollama" else "cloud")
        self._badge_widget.adjustSize()
        self._badge_widget.setMinimumWidth(self._badge_widget.sizeHint().width())
        style = self._badge_widget.style()
        if style:
          style.unpolish(self._badge_widget)
          style.polish(self._badge_widget)

  def current_model(self) -> str:
    idx = self.currentIndex()
    if 0 <= idx < len(self._models_meta):
      return self._models_meta[idx]["name"]
    return self.currentText()

  def current_provider(self) -> str:
    idx = self.currentIndex()
    if 0 <= idx < len(self._models_meta):
      return str(self._models_meta[idx].get("provider", "ollama"))
    return "ollama"

  def current_model_id(self) -> str:
    idx = self.currentIndex()
    if 0 <= idx < len(self._models_meta):
      return str(self._models_meta[idx].get("id", ""))
    return ""

  def processing_type(self) -> str:
    idx = self.currentIndex()
    if 0 <= idx < len(self._models_meta):
      return self._models_meta[idx]["type"]
    return "Local Ollama" if "Local" in self.currentText() else "Nuvem"

  def select_model_by_name(self, name: str) -> bool:
    name_lower = name.lower()
    for i in range(self.count()):
      meta = self._models_meta[i] if i < len(self._models_meta) else {}
      if not meta.get("enabled", True):
        continue
      if name_lower in self.itemText(i).lower() or name_lower in meta.get("id", "").lower():
        self.setCurrentIndex(i)
        return True
    return False


class ActionConsentDialog(QDialog):
  """Modal de confirmação Human-in-the-Loop para operações mutantes/sensíveis de ferramentas."""

  def __init__(
    self,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    parent: QWidget | None = None,
  ) -> None:
    super().__init__(parent)
    self.tool_name = tool_name
    self.arguments = arguments or {}
    self.granted: bool = False
    self._build_ui()

  def _build_ui(self) -> None:
    self.setWindowTitle("Confirmação de Ação · Human-in-the-Loop")
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
      QLabel#toolHighlight {
        color: #00D8F6;
        font-family: monospace;
        font-weight: 500;
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

    title = QLabel("Permissão de Execução Agentizada")
    title.setObjectName("dialogTitle")
    layout.addWidget(title)

    prompt = QLabel(f"Permitir execução da ferramenta <span style='font-weight:500; color:#EDEDED;'>{self.tool_name}</span>?")
    prompt.setObjectName("dialogPrompt")
    prompt.setTextFormat(Qt.TextFormat.RichText)
    prompt.setWordWrap(True)
    layout.addWidget(prompt)

    desc = QLabel(
      "Esta operação pode alterar arquivos externos, realizar commits ou disparar chamadas externas que exigem consentimento."
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
      args_box.setMaximumHeight(120)
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


class ConsentBridge(QObject):
  """Ponte thread-safe entre tarefas em background (QThread) e a UI principal para obter consentimento."""

  request_consent = pyqtSignal(str, dict, object)

  def __init__(self, parent: QWidget | None = None) -> None:
    super().__init__(parent)
    self.parent_widget = parent
    self.request_consent.connect(self._handle_request)

  def _handle_request(self, tool_name: str, arguments: dict[str, Any], event: Any) -> None:
    dialog = ActionConsentDialog(tool_name, arguments, parent=self.parent_widget)
    dialog.exec()
    event.is_approved = dialog.granted
    event.remember = getattr(dialog, "remember_decision", False)
    event.set()

  def ask_consent(self, tool_name: str, arguments: dict[str, Any], timeout: float = 60.0) -> bool:
    from ..security.consent import APIConsentManager
    if APIConsentManager.has_permission(tool_name):
      return True

    event = threading.Event()
    event.is_approved = False
    event.remember = False
    self.request_consent.emit(tool_name, arguments, event)
    signaled = event.wait(timeout=timeout)
    if not signaled:
      return False

    if getattr(event, "is_approved", False):
      duration = "permanent" if getattr(event, "remember", False) else "session"
      APIConsentManager.grant_permission(tool_name, True, duration=duration)
      return True

    return False


class GodsEyeStatusWidget(QFrame):
  """Painel de visibilidade em tempo real para o ciclo de execução agentizada (God's Eye View).

  Reflete as fases:
  - Ferramenta Solicitada ("Aguardando Ferramenta")
  - Ação Executada ("Lendo Repositório" / execução em andamento)
  - Sucesso Confirmado ("Analisando Resultado" / observação anexada com sucesso)
  """

  cancel_requested = pyqtSignal()

  def __init__(self, parent: QWidget | None = None) -> None:
    super().__init__(parent)
    self.setObjectName("godsEyeStatusWidget")
    self._current_phase = "IDLE"
    self._build_ui()
    self.hide()

  def _build_ui(self) -> None:
    self.setStyleSheet("""
      QFrame#godsEyeStatusWidget {
        background: #16191D;
        border: 1px solid #1E2228;
        border-radius: 8px;
        padding: 10px 14px;
        margin: 4px 0px;
      }
      QLabel#godsEyeTitle {
        color: #00D8F6;
        font-family: Inter, sans-serif;
        font-size: 11px;
        font-weight: 500;
        letter-spacing: 0.8px;
      }
      QLabel#phaseBadge {
        color: #121417;
        font-size: 11px;
        font-weight: 500;
        padding: 2px 8px;
        border-radius: 4px;
      }
      QLabel#phaseBadge[phase="requested"] {
        background: #D29922;
        color: #121417;
      }
      QLabel#phaseBadge[phase="executing"] {
        background: #00D8F6;
        color: #121417;
      }
      QLabel#phaseBadge[phase="confirmed"] {
        background: #3FB950;
        color: #121417;
      }
      QLabel#godsEyeAction {
        color: #EDEDED;
        font-size: 13px;
        font-weight: 500;
      }
      QLabel#godsEyeStep {
        color: #8E95A0;
        font-size: 11px;
        font-weight: 400;
      }
      QPushButton#godsEyeCancelBtn {
        background: #20252C;
        color: #F85149;
        border: 1px solid #1E2228;
        border-radius: 6px;
        padding: 4px 10px;
        font-size: 12px;
        font-weight: 500;
      }
      QPushButton#godsEyeCancelBtn:hover {
        background: #F85149;
        color: #FFFFFF;
        border-color: #F85149;
      }
    """)

    layout = QHBoxLayout(self)
    layout.setContentsMargins(12, 8, 12, 8)
    layout.setSpacing(12)

    col_info = QVBoxLayout()
    col_info.setSpacing(2)

    header_row = QHBoxLayout()
    header_row.setSpacing(8)

    self.title_label = QLabel("GOD'S EYE VIEW · EXECUÇÃO AGENTIZADA")
    self.title_label.setObjectName("godsEyeTitle")
    header_row.addWidget(self.title_label)

    self.phase_badge = QLabel("Ferramenta Solicitada")
    self.phase_badge.setObjectName("phaseBadge")
    self.phase_badge.setProperty("phase", "requested")
    header_row.addWidget(self.phase_badge)

    self.step_label = QLabel("Passo 1/3")
    self.step_label.setObjectName("godsEyeStep")
    header_row.addWidget(self.step_label)

    header_row.addStretch(1)
    col_info.addLayout(header_row)

    self.action_label = QLabel("Aguardando Ferramenta")
    self.action_label.setObjectName("godsEyeAction")
    col_info.addWidget(self.action_label)

    layout.addLayout(col_info, 1)

    self.cancel_button = QPushButton("Cancelar Tarefa")
    self.cancel_button.setObjectName("godsEyeCancelBtn")
    self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
    self.cancel_button.clicked.connect(self._on_cancel_clicked)
    layout.addWidget(self.cancel_button)

  def _on_cancel_clicked(self) -> None:
    self.action_label.setText("Cancelando tarefa...")
    self.cancel_button.setEnabled(False)
    self.cancel_requested.emit()

  def update_state(self, phase_category: str, tool_name: str, action_detail: str, step_info: str = "") -> None:
    """Atualiza o painel com as três fases canônicas:

    - 'Ferramenta Solicitada' -> 'Aguardando Ferramenta' (ou detalhe da solicitação)
    - 'Ação Executada' -> 'Lendo Repositório' / execução em andamento
    - 'Sucesso Confirmado' -> 'Analisando Resultado' / resultado obtido
    """
    cat_lower = phase_category.lower()
    is_tool_phase = (
      bool(tool_name)
      or any(kw in cat_lower for kw in ("solicitada", "request", "waiting", "executada", "executando", "execut", "confirmado", "sucesso", "confirm", "cancelado", "falha"))
      or any(kw in step_info.lower() for kw in ("passo 2", "passo 3", "2/", "3/"))
    )
    if not is_tool_phase:
      return

    self.show()
    self.cancel_button.setEnabled(True)
    if "solicitada" in cat_lower or "request" in cat_lower or "waiting" in cat_lower:
      self.phase_badge.setText("Ferramenta Solicitada")
      self.phase_badge.setProperty("phase", "requested")
      display_action = action_detail or "Aguardando Ferramenta"
    elif "executada" in cat_lower or "executando" in cat_lower or "execut" in cat_lower:
      self.phase_badge.setText("Ação Executada")
      self.phase_badge.setProperty("phase", "executing")
      display_action = action_detail or (f"Executando {tool_name}..." if tool_name else "Lendo Repositório")
    elif "confirmado" in cat_lower or "sucesso" in cat_lower or "confirm" in cat_lower:
      self.phase_badge.setText("Sucesso Confirmado")
      self.phase_badge.setProperty("phase", "confirmed")
      display_action = action_detail or "Analisando Resultado"
    else:
      self.phase_badge.setText(phase_category)
      self.phase_badge.setProperty("phase", "requested")
      display_action = action_detail

    style = self.phase_badge.style()
    if style:
      style.unpolish(self.phase_badge)
      style.polish(self.phase_badge)

    self.action_label.setText(display_action)
    if step_info:
      self.step_label.setText(step_info)
      self.step_label.show()
    else:
      self.step_label.hide()

  def reset(self) -> None:
    self.hide()
    self.action_label.setText("")
    self.step_label.setText("")
    self.cancel_button.setEnabled(True)


class CitationViewerDialog(QDialog):
  """Diálogo modal para visualização do trecho original e metadados de uma citação."""

  def __init__(
    self,
    doc_id: str,
    excerpt: str,
    title: str = "",
    page: int | str | None = None,
    parent: QWidget | None = None,
  ) -> None:
    super().__init__(parent)
    self.setWindowTitle(f"Citação da Biblioteca — [{doc_id}]")
    self.setMinimumSize(540, 360)
    self.setStyleSheet("""
      QDialog {
        background-color: #16191D;
        color: #EDEDED;
        font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      }
      QLabel {
        color: #EDEDED;
      }
      QPushButton {
        background: #20252C;
        color: #EDEDED;
        border: 1px solid #1E2228;
        border-radius: 6px;
        padding: 6px 16px;
        font-size: 13px;
        font-weight: 500;
      }
      QPushButton:hover {
        background: #262B33;
        border-color: #00D8F6;
      }
      QTextEdit {
        background: #0B0D0F;
        color: #EDEDED;
        border: 1px solid #1E2228;
        border-radius: 8px;
        padding: 12px;
        font-size: 13px;
        font-weight: 400;
        line-height: 1.5;
      }
    """)

    layout = QVBoxLayout(self)
    layout.setContentsMargins(24, 20, 24, 20)
    layout.setSpacing(14)

    # Cabeçalho
    header_layout = QHBoxLayout()
    header_title = QLabel(f"Documento: {title or doc_id}")
    header_title.setStyleSheet("font-size: 15px; font-weight: 500; color: #00D8F6;")
    header_layout.addWidget(header_title)
    header_layout.addStretch()

    badge = QLabel(" Ancoragem Verificada")
    badge.setStyleSheet("""
      background: rgba(63, 185, 80, 0.2);
      color: #3FB950;
      border: 1px solid rgba(63, 185, 80, 0.4);
      border-radius: 4px;
      padding: 3px 8px;
      font-size: 11px;
      font-weight: 500;
    """)
    header_layout.addWidget(badge)
    layout.addLayout(header_layout)

    # Metadados
    meta_parts = [f"DocID: <code style='color:#00D8F6;'>{doc_id}</code>"]
    if page:
      meta_parts.append(f"Página: <span style='font-weight:500;'>{page}</span>")
    meta_label = QLabel(" · ".join(meta_parts))
    meta_label.setStyleSheet("color: #8E95A0; font-size: 12px; font-weight: 400;")
    layout.addWidget(meta_label)

    # Trecho original
    section_label = QLabel("Trecho Original Ancorado:")
    section_label.setStyleSheet("font-size: 12px; font-weight: 500; color: #8E95A0; margin-top: 4px;")
    layout.addWidget(section_label)

    self.text_area = QTextEdit()
    self.text_area.setReadOnly(True)
    self.text_area.setPlainText(excerpt)
    layout.addWidget(self.text_area, 1)

    # Botão fechar
    btn_layout = QHBoxLayout()
    btn_layout.addStretch()
    close_btn = QPushButton("Fechar")
    close_btn.clicked.connect(self.accept)
    btn_layout.addWidget(close_btn)
    layout.addLayout(btn_layout)


class DirectoryPickerWidget(QWidget):
  """Widget de seleção de diretório padronizado herdando os tokens do ThemeManager."""

  directory_changed = pyqtSignal(str)

  def __init__(
    self,
    current_path: str = "",
    label_text: str = "Diretório de Armazenamento de Memória (Semântica/Episódica)",
    parent: QWidget | None = None,
  ) -> None:
    super().__init__(parent)
    self.setObjectName("directoryPickerWidget")
    self._label_text = label_text
    self._current_path = current_path
    self._build_ui()

  def _build_ui(self) -> None:
    t = ThemeManager.TOKENS
    layout = QVBoxLayout(self)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)

    self.label = QLabel(self._label_text)
    self.label.setObjectName("directoryPickerLabel")
    self.label.setStyleSheet(
      f"color: {t.TEXT_PRIMARY}; font-family: {t.FONT_FAMILY}; font-size: 13px; font-weight: 500;"
    )
    layout.addWidget(self.label)

    row = QHBoxLayout()
    row.setSpacing(8)

    self.path_input = QLineEdit(self._current_path)
    self.path_input.setObjectName("directoryPickerInput")
    self.path_input.setReadOnly(True)
    self.path_input.setPlaceholderText("Nenhum diretório selecionado")
    self.path_input.setStyleSheet(
      f"QLineEdit#directoryPickerInput {{"
      f" background: {t.BG_SURFACE};"
      f" color: {t.TEXT_PRIMARY};"
      f" border: 1px solid {t.BORDER_SUBTLE};"
      f" border-radius: 6px;"
      f" padding: 6px 10px;"
      f" font-family: {t.FONT_FAMILY_MONO};"
      f" font-size: 12px;"
      f"}}"
    )
    row.addWidget(self.path_input, 1)

    self.browse_button = QPushButton("Procurar...")
    self.browse_button.setObjectName("directoryPickerBrowseButton")
    self.browse_button.setCursor(Qt.CursorShape.PointingHandCursor)
    self.browse_button.setStyleSheet(
      f"QPushButton#directoryPickerBrowseButton {{"
      f" background: {t.BG_PANEL};"
      f" color: {t.ACCENT_CYAN};"
      f" border: 1px solid {t.BORDER_SUBTLE};"
      f" border-radius: 6px;"
      f" padding: 6px 14px;"
      f" font-family: {t.FONT_FAMILY};"
      f" font-size: 12px;"
      f" font-weight: 500;"
      f"}}"
      f"QPushButton#directoryPickerBrowseButton:hover {{"
      f" background: {t.BG_FOCUS};"
      f" border-color: {t.BORDER_ACTIVE};"
      f"}}"
    )
    self.browse_button.clicked.connect(self._handle_browse)
    row.addWidget(self.browse_button)

    layout.addLayout(row)

  def _handle_browse(self) -> None:
    initial = self.path_input.text().strip() or str(Path.home())
    selected = QFileDialog.getExistingDirectory(
      self,
      "Selecionar Diretório de Armazenamento",
      initial,
    )
    if selected:
      self.set_path(selected)
      self.directory_changed.emit(selected)

  def path(self) -> str:
    return self.path_input.text().strip()

  def set_path(self, path: str) -> None:
    self._current_path = path
    self.path_input.setText(path)


# ============================================================================
# Componentes de Inferência Local Avançada (Estilo LM Studio com Guardrails)
# ============================================================================


class ToggleSwitch(QAbstractButton):
  """Switch de estilo moderno/iOS com desenho antialiased e estado ativo em azul vibrante."""

  def __init__(self, checked: bool = False, parent: QWidget | None = None) -> None:
    super().__init__(parent)
    self.setCheckable(True)
    self.setChecked(checked)
    self.setCursor(Qt.CursorShape.PointingHandCursor)
    self.setFixedSize(44, 24)
    self.toggled.connect(self._on_toggled)

  def _on_toggled(self, _checked: bool) -> None:
    self.update()

  def setChecked(self, checked: bool) -> None:
    super().setChecked(checked)
    self.update()

  def paintEvent(self, _event: Any) -> None:
    painter = QPainter(self)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Fundo do pill
    bg_color = QColor("#2563EB") if self.isChecked() else QColor("#30363D")
    painter.setBrush(QBrush(bg_color))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(0, 0, self.width(), self.height(), 12, 12)

    # Knob circular branco
    knob_color = QColor("#FFFFFF")
    painter.setBrush(QBrush(knob_color))
    knob_x = 22 if self.isChecked() else 2
    painter.drawEllipse(knob_x, 2, 20, 20)
    painter.end()


class InferenceToggleWidget(QWidget):
  """Widget de linha com label de parâmetro, badge opcional e ToggleSwitch moderno."""

  toggled = pyqtSignal(bool)

  def __init__(
    self,
    title: str,
    default_val: bool = True,
    badge: str | None = None,
    subtitle: str | None = None,
    parent: QWidget | None = None,
  ) -> None:
    super().__init__(parent)
    self._build_ui(title, default_val, badge, subtitle)

  def _build_ui(self, title: str, default_val: bool, badge: str | None, subtitle: str | None) -> None:
    t = ThemeManager.TOKENS
    layout = QHBoxLayout(self)
    layout.setContentsMargins(0, 8, 0, 8)
    layout.setSpacing(10)

    left_layout = QVBoxLayout()
    left_layout.setSpacing(2)

    title_row = QHBoxLayout()
    title_row.setSpacing(8)

    self.title_label = QLabel(title)
    self.title_label.setStyleSheet(
      f"color: {t.TEXT_PRIMARY}; font-family: {t.FONT_FAMILY}; font-size: 13px; font-weight: 500;"
    )
    title_row.addWidget(self.title_label)

    if badge:
      badge_label = QLabel(badge)
      badge_label.setStyleSheet(
        "background: #22262B; color: #8E95A0; border: 1px solid #30363D; "
        "border-radius: 4px; padding: 1px 6px; font-size: 10px; font-family: monospace; font-weight: 600;"
      )
      title_row.addWidget(badge_label)

    title_row.addStretch(1)
    left_layout.addLayout(title_row)

    if subtitle:
      self.subtitle_label = QLabel(subtitle)
      self.subtitle_label.setStyleSheet(
        f"color: {t.TEXT_SECONDARY}; font-family: {t.FONT_FAMILY}; font-size: 11px;"
      )
      left_layout.addWidget(self.subtitle_label)

    layout.addLayout(left_layout, 1)

    self.switch = ToggleSwitch(checked=default_val, parent=self)
    self.switch.toggled.connect(self.toggled.emit)
    layout.addWidget(self.switch, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

  def isChecked(self) -> bool:
    return self.switch.isChecked()

  def setChecked(self, checked: bool) -> None:
    self.switch.setChecked(checked)


class InferenceSliderWidget(QWidget):
  """Slider horizontal com rótulo, subtítulo opcional e caixa de texto sincronizada e validada."""

  valueChanged = pyqtSignal(int)

  def __init__(
    self,
    title: str,
    min_val: int,
    max_val: int,
    default_val: int = 0,
    subtitle: str | None = None,
    parent: QWidget | None = None,
  ) -> None:
    super().__init__(parent)
    self.min_val = int(min_val)
    self.max_val = int(max_val)
    self._current_value = max(self.min_val, min(self.max_val, int(default_val)))
    self._build_ui(title, subtitle)

  def _build_ui(self, title: str, subtitle: str | None) -> None:
    t = ThemeManager.TOKENS
    layout = QVBoxLayout(self)
    layout.setContentsMargins(0, 8, 0, 8)
    layout.setSpacing(6)

    top_row = QHBoxLayout()
    top_row.setSpacing(8)

    text_col = QVBoxLayout()
    text_col.setSpacing(2)

    self.title_label = QLabel(title)
    self.title_label.setStyleSheet(
      f"color: {t.TEXT_PRIMARY}; font-family: {t.FONT_FAMILY}; font-size: 13px; font-weight: 500;"
    )
    text_col.addWidget(self.title_label)

    self.subtitle_label = QLabel(subtitle or "")
    self.subtitle_label.setStyleSheet(
      f"color: {t.TEXT_SECONDARY}; font-family: {t.FONT_FAMILY}; font-size: 11px;"
    )
    self.subtitle_label.setVisible(bool(subtitle))
    text_col.addWidget(self.subtitle_label)

    top_row.addLayout(text_col, 1)

    self.line_edit = QLineEdit(str(self._current_value))
    self.line_edit.setFixedWidth(74)
    self.line_edit.setFixedHeight(28)
    self.line_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self.line_edit.setValidator(QIntValidator(self.min_val, self.max_val, self))
    self.line_edit.setStyleSheet(
      "QLineEdit {"
      " background: #22262B;"
      " color: #EDEDED;"
      " border: 1px solid #30363D;"
      " border-radius: 6px;"
      " font-family: Inter, sans-serif;"
      " font-size: 12px;"
      " font-weight: 500;"
      " padding: 2px 6px;"
      "}"
      "QLineEdit:focus {"
      " border-color: #58A6FF;"
      " background: #262B33;"
      "}"
    )
    self.line_edit.editingFinished.connect(self._handle_editing_finished)
    self.line_edit.returnPressed.connect(self._handle_editing_finished)
    orig_slider_focus_out = self.line_edit.focusOutEvent

    def _on_slider_edit_focus_out(ev: Any) -> None:
      self._handle_editing_finished()
      orig_slider_focus_out(ev)

    self.line_edit.focusOutEvent = _on_slider_edit_focus_out
    top_row.addWidget(self.line_edit, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    layout.addLayout(top_row)

    self.slider = QSlider(Qt.Orientation.Horizontal)
    self.slider.setRange(self.min_val, self.max_val)
    self.slider.setValue(self._current_value)
    self.slider.setStyleSheet(
      "QSlider::groove:horizontal {"
      " border: none;"
      " height: 4px;"
      " background: #30363D;"
      " border-radius: 2px;"
      "}"
      "QSlider::sub-page:horizontal {"
      " background: #58A6FF;"
      " border-radius: 2px;"
      "}"
      "QSlider::handle:horizontal {"
      " background: #C9D1D9;"
      " border: none;"
      " width: 14px;"
      " height: 14px;"
      " margin: -5px 0;"
      " border-radius: 7px;"
      "}"
      "QSlider::handle:horizontal:hover {"
      " background: #FFFFFF;"
      "}"
    )
    self.slider.valueChanged.connect(self._on_slider_value_changed)
    layout.addWidget(self.slider)

  def _on_slider_value_changed(self, val: int) -> None:
    clamped = max(self.min_val, min(self.max_val, int(val)))
    self._current_value = clamped
    if self.line_edit.text() != str(clamped):
      self.line_edit.setText(str(clamped))
    self.valueChanged.emit(clamped)

  def _handle_editing_finished(self) -> None:
    raw_text = self.line_edit.text().strip()
    try:
      val = int(raw_text)
    except (ValueError, TypeError):
      val = self.min_val

    clamped = max(self.min_val, min(self.max_val, val))
    self._current_value = clamped
    self.line_edit.setText(str(clamped))
    if self.slider.value() != clamped:
      self.slider.setValue(clamped)
    self.valueChanged.emit(clamped)

  def value(self) -> int:
    return self._current_value

  def setValue(self, val: int) -> None:
    clamped = max(self.min_val, min(self.max_val, int(val)))
    self._current_value = clamped
    self.line_edit.setText(str(clamped))
    self.slider.setValue(clamped)

  def setSubtitle(self, text: str) -> None:
    self.subtitle_label.setText(text)
    self.subtitle_label.setVisible(bool(text))


# Alias de conformidade
LabeledSlider = InferenceSliderWidget


class InferenceNumberInputWidget(QWidget):
  """Campo numérico com rótulo, badge opcional e auto-clamping em perda de foco / Enter."""

  valueChanged = pyqtSignal(int)

  def __init__(
    self,
    title: str,
    min_val: int,
    max_val: int,
    default_val: int,
    badge: str | None = None,
    parent: QWidget | None = None,
  ) -> None:
    super().__init__(parent)
    self.min_val = int(min_val)
    self.max_val = int(max_val)
    self._current_value = max(self.min_val, min(self.max_val, int(default_val)))
    self._build_ui(title, badge)

  def _build_ui(self, title: str, badge: str | None) -> None:
    t = ThemeManager.TOKENS
    layout = QHBoxLayout(self)
    layout.setContentsMargins(0, 6, 0, 6)
    layout.setSpacing(10)

    left_row = QHBoxLayout()
    left_row.setSpacing(8)

    self.title_label = QLabel(title)
    self.title_label.setStyleSheet(
      f"color: {t.TEXT_PRIMARY}; font-family: {t.FONT_FAMILY}; font-size: 13px; font-weight: 500;"
    )
    left_row.addWidget(self.title_label)

    if badge:
      badge_label = QLabel(badge)
      badge_label.setStyleSheet(
        "background: #22262B; color: #8E95A0; border: 1px solid #30363D; "
        "border-radius: 4px; padding: 1px 6px; font-size: 10px; font-family: monospace; font-weight: 600;"
      )
      left_row.addWidget(badge_label)

    left_row.addStretch(1)
    layout.addLayout(left_row, 1)

    self.line_edit = QLineEdit(str(self._current_value))
    self.line_edit.setFixedWidth(74)
    self.line_edit.setFixedHeight(28)
    self.line_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self.line_edit.setValidator(QIntValidator(self.min_val, self.max_val, self))
    self.line_edit.setStyleSheet(
      "QLineEdit {"
      " background: #22262B;"
      " color: #EDEDED;"
      " border: 1px solid #30363D;"
      " border-radius: 6px;"
      " font-family: Inter, sans-serif;"
      " font-size: 12px;"
      " font-weight: 500;"
      " padding: 2px 6px;"
      "}"
      "QLineEdit:focus {"
      " border-color: #58A6FF;"
      " background: #262B33;"
      "}"
    )
    self.line_edit.editingFinished.connect(self._handle_editing_finished)
    self.line_edit.returnPressed.connect(self._handle_editing_finished)
    orig_num_focus_out = self.line_edit.focusOutEvent

    def _on_num_edit_focus_out(ev: Any) -> None:
      self._handle_editing_finished()
      orig_num_focus_out(ev)

    self.line_edit.focusOutEvent = _on_num_edit_focus_out
    layout.addWidget(self.line_edit, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

  def _handle_editing_finished(self) -> None:
    raw_text = self.line_edit.text().strip()
    try:
      val = int(raw_text)
    except (ValueError, TypeError):
      val = self.min_val

    clamped = max(self.min_val, min(self.max_val, val))
    self._current_value = clamped
    self.line_edit.setText(str(clamped))
    self.valueChanged.emit(clamped)

  def value(self) -> int:
    return self._current_value

  def setValue(self, val: int) -> None:
    clamped = max(self.min_val, min(self.max_val, int(val)))
    self._current_value = clamped
    self.line_edit.setText(str(clamped))


class InferenceTextInputWidget(QWidget):
  """Campo de entrada de texto com rótulo no topo e placeholder escuro."""

  textChanged = pyqtSignal(str)

  def __init__(self, title: str, placeholder: str = "", default_text: str = "", parent: QWidget | None = None) -> None:
    super().__init__(parent)
    t = ThemeManager.TOKENS
    layout = QVBoxLayout(self)
    layout.setContentsMargins(0, 6, 0, 6)
    layout.setSpacing(6)

    self.title_label = QLabel(title)
    self.title_label.setStyleSheet(
      f"color: {t.TEXT_PRIMARY}; font-family: {t.FONT_FAMILY}; font-size: 13px; font-weight: 500;"
    )
    layout.addWidget(self.title_label)

    self.input = QLineEdit(default_text)
    self.input.setPlaceholderText(placeholder)
    self.input.setStyleSheet(
      "QLineEdit {"
      " background: #22262B;"
      " color: #EDEDED;"
      " border: 1px solid #30363D;"
      " border-radius: 6px;"
      " font-family: Inter, sans-serif;"
      " font-size: 13px;"
      " padding: 6px 10px;"
      "}"
      "QLineEdit:focus {"
      " border-color: #58A6FF;"
      " background: #262B33;"
      "}"
    )
    self.input.textChanged.connect(self.textChanged.emit)
    layout.addWidget(self.input)

  def text(self) -> str:
    return self.input.text()

  def setText(self, val: str) -> None:
    self.input.setText(val)


class InferenceAutoOptionWidget(QWidget):
  """Opção com checkbox (ex: Automático / Seed Aleatória) e entrada manual opcional."""

  valueChanged = pyqtSignal(object)

  def __init__(
    self,
    title: str,
    checkbox_label: str = "Automático",
    default_auto: bool = True,
    parent: QWidget | None = None,
  ) -> None:
    super().__init__(parent)
    t = ThemeManager.TOKENS
    layout = QHBoxLayout(self)
    layout.setContentsMargins(0, 6, 0, 6)
    layout.setSpacing(10)

    self.title_label = QLabel(title)
    self.title_label.setStyleSheet(
      f"color: {t.TEXT_PRIMARY}; font-family: {t.FONT_FAMILY}; font-size: 13px; font-weight: 500;"
    )
    layout.addWidget(self.title_label, 1)

    self.checkbox = QCheckBox(checkbox_label)
    self.checkbox.setChecked(default_auto)
    self.checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
    self.checkbox.setStyleSheet(
      "QCheckBox {"
      " color: #EDEDED;"
      " font-family: Inter, sans-serif;"
      " font-size: 13px;"
      "}"
      "QCheckBox::indicator {"
      " width: 16px;"
      " height: 16px;"
      " border: 1px solid #30363D;"
      " border-radius: 4px;"
      " background: #22262B;"
      "}"
      "QCheckBox::indicator:checked {"
      " background: #58A6FF;"
      " border-color: #58A6FF;"
      "}"
    )
    self.checkbox.toggled.connect(self._on_toggled)
    layout.addWidget(self.checkbox, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

  def _on_toggled(self, checked: bool) -> None:
    self.valueChanged.emit(None if checked else 0)

  def is_auto(self) -> bool:
    return self.checkbox.isChecked()

  def set_auto(self, auto: bool) -> None:
    self.checkbox.setChecked(auto)


class InferenceSelectWidget(QWidget):
  """Dropdown moderno para opções como Speculative Decoding."""

  valueChanged = pyqtSignal(str)

  def __init__(self, title: str, options: list[str], default_option: str, parent: QWidget | None = None) -> None:
    super().__init__(parent)
    t = ThemeManager.TOKENS
    layout = QHBoxLayout(self)
    layout.setContentsMargins(0, 6, 0, 6)
    layout.setSpacing(10)

    self.title_label = QLabel(title)
    self.title_label.setStyleSheet(
      f"color: {t.TEXT_PRIMARY}; font-family: {t.FONT_FAMILY}; font-size: 13px; font-weight: 500;"
    )
    layout.addWidget(self.title_label, 1)

    self.combo = QComboBox()
    self.combo.setFixedWidth(130)
    self.combo.setFixedHeight(28)
    self.combo.setStyleSheet(
      "QComboBox {"
      " background: #22262B;"
      " color: #EDEDED;"
      " border: 1px solid #30363D;"
      " border-radius: 6px;"
      " font-family: Inter, sans-serif;"
      " font-size: 12px;"
      " padding: 2px 8px;"
      "}"
      "QComboBox:focus {"
      " border-color: #58A6FF;"
      "}"
    )
    for opt in options:
      self.combo.addItem(opt)
    self.combo.setCurrentText(default_option)
    self.combo.currentTextChanged.connect(self.valueChanged.emit)
    layout.addWidget(self.combo, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

  def currentText(self) -> str:
    return self.combo.currentText()

  def setCurrentText(self, text: str) -> None:
    self.combo.setCurrentText(text)


class InferenceRowNavigationWidget(QWidget):
  """Linha de navegação (ex: Chat Template >)."""

  clicked = pyqtSignal()

  def __init__(self, title: str, parent: QWidget | None = None) -> None:
    super().__init__(parent)
    t = ThemeManager.TOKENS
    self.setCursor(Qt.CursorShape.PointingHandCursor)
    layout = QHBoxLayout(self)
    layout.setContentsMargins(0, 6, 0, 6)
    layout.setSpacing(10)

    self.title_label = QLabel(title)
    self.title_label.setStyleSheet(
      f"color: {t.TEXT_PRIMARY}; font-family: {t.FONT_FAMILY}; font-size: 13px; font-weight: 500;"
    )
    layout.addWidget(self.title_label, 1)

    self.arrow_label = QLabel("›")
    self.arrow_label.setStyleSheet("color: #8E95A0; font-size: 18px; font-weight: 600;")
    layout.addWidget(self.arrow_label, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

  def mousePressEvent(self, _event: Any) -> None:
    self.clicked.emit()






  def set_role_filter(self, role: str, secondary_badge: QLabel | None = None) -> None:
    """Filtra os modelos disponiveis no seletor de acordo com o papel ativo (general, engineer, professor, vision)."""
    from ..config.llm_config import get_role_models_config
    roles_cfg = get_role_models_config()
    rc = roles_cfg.get(role, roles_cfg.get("general", {}))
    avail = rc.get("available_models", ["mark-bin-32b", "mark-engineer-1.5b", "mark-general-1.5b", "mark-slm-v3-150m"])
    primary = rc.get("primary_model", avail[0] if avail else "mark-general-1.5b")
    secondary = rc.get("secondary_model", "mark-slm-v3-150m")

    self.blockSignals(True)
    self.clear()
    self.addItem("--- MOTOR LOCAL & 1-BIT ---", userData=None)
    self.setItemData(0, False, Qt.ItemFlag.ItemIsEnabled)
    target_idx = 1
    for m_id in avail:
      prefix = " 1-Bit " if ("bin-32b" in m_id or "rust-4b" in m_id) else " "
      self.addItem(f"{prefix}{m_id}", userData=m_id)
      if m_id == primary:
        target_idx = self.count() - 1
    self.setCurrentIndex(target_idx)
    self.blockSignals(False)
    self._update_badge()
    if secondary_badge is not None:
      secondary_badge.setText(f"● {tr('Secundário')} ({secondary})")

# ---------------------------------------------------------------------------
# Renderizacao nivel IDE: card de pensamento recolhivel e caixas de codigo
# ---------------------------------------------------------------------------

IDE_KEYWORDS = {
  "fn", "pub", "let", "mut", "impl", "struct", "enum", "match", "if", "else", "for", "while",
  "return", "void", "int", "float", "double", "char", "class", "def", "import", "from", "async",
  "await", "try", "catch", "throw", "const", "static", "use", "mod", "trait", "where", "loop",
  "break", "continue", "in", "as", "unsafe", "extern", "crate", "super", "self", "new", "delete",
  "include", "define", "namespace", "template", "typename", "public", "private", "protected",
  "virtual", "override", "using", "typedef", "sizeof", "switch", "case", "default", "do", "goto",
  "lambda", "with", "elif", "except", "finally", "raise", "yield", "global", "assert", "pass",
  "export", "typeof", "interface", "type", "extends", "implements", "package", "func", "var",
}

IDE_TYPES = {
  "String", "Vec", "Option", "Result", "Box", "Arc", "Rc", "HashMap", "BTreeMap", "Self",
  "u8", "u16", "u32", "u64", "i8", "i16", "i32", "i64", "f32", "f64", "usize", "isize", "bool",
  "Path", "PathBuf", "File", "Duration", "Instant", "VkInstance", "VkApplicationInfo",
  "VkPhysicalDevice", "VkDevice", "VkQueue", "VkSwapchainKHR", "VkCommandBuffer", "VkResult",
  "GLFWwindow", "VkSurfaceKHR", "VkPipeline", "VkShaderModule", "VkBuffer", "VkDeviceMemory",
  "std", "core", "alloc", "List", "Dict", "int64", "float32", "socket", "threading",
}

IDE_CONSTANTS = {"true", "false", "nullptr", "None", "Some", "Ok", "Err", "NULL", "null", "True", "False"}

TOKEN_RE = re.compile(
  r"(?P<comment>//[^\n]*|/\*[\s\S]*?\*/|#[^\n]*)"
  r"|(?P<string>\"(?:[^\"\\\n]|\\.)*\"|'(?:[^'\\\n]|\\.)*')"
  r"|(?P<number>\b(?:0x[0-9A-Fa-f]+|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)[fFuUlL]*\b)"
  r"|(?P<ident>[A-Za-z_][A-Za-z0-9_]*)"
  r"|(?P<punct>[{}()\[\];,.<>:+\-*/%=!&|^~?@$\\]+)"
  r"|(?P<space>\s+)"
)

C_COMMENT = "#5C6370"
C_STRING = "#98C379"
C_NUMBER = "#D19A66"
C_KEYWORD = "#C678DD"
C_KEYWORD_ALT = "#CC7832"
C_TYPE = "#56B6C2"
C_TYPE_ALT = "#E5C07B"
C_FUNC = "#61AFEF"
C_MACRO = "#FFC66D"
C_PUNCT = "#ABB2BF"
C_PUNCT_ALT = "#89DDFF"
C_LINENO = "#4B5263"


def _escape(text: str) -> str:
  return (
    text.replace("&", "&amp;")
    .replace("<", "&lt;")
    .replace(">", "&gt;")
  )


def highlight_code(code: str) -> str:
  """Converte codigo puro em HTML colorido sem alterar a indentacao."""
  out: list[str] = []
  position = 0
  following_paren = -1
  for match in TOKEN_RE.finditer(code):
    kind = match.lastgroup or ""
    token = match.group(0)
    if kind == "space":
      out.append("&nbsp;" * len(token) if "\n" not in token else token.replace("\n", "<br/>"))
      continue
    if following_paren < 0 and "(" in token:
      following_paren = position
    if kind == "comment":
      out.append(f'<span style="color:{C_COMMENT};font-style:italic;">{_escape(token)}</span>')
    elif kind == "string":
      out.append(f'<span style="color:{C_STRING};">{_escape(token)}</span>')
    elif kind == "number":
      out.append(f'<span style="color:{C_NUMBER};">{_escape(token)}</span>')
    elif kind == "ident":
      after = code[match.end():match.end() + 1]
      if token in IDE_CONSTANTS:
        out.append(f'<span style="color:{C_NUMBER};">{_escape(token)}</span>')
      elif token in IDE_KEYWORDS:
        colour = C_KEYWORD_ALT if token in {"fn", "pub", "impl", "struct", "enum", "use", "mod"} else C_KEYWORD
        out.append(f'<span style="color:{colour};">{_escape(token)}</span>')
      elif token in IDE_TYPES or token[:1].isupper():
        colour = C_TYPE_ALT if token[:1].isupper() and token not in IDE_TYPES else C_TYPE
        out.append(f'<span style="color:{colour};">{_escape(token)}</span>')
      elif after == "!":
        out.append(f'<span style="color:{C_MACRO};">{_escape(token)}</span>')
      elif after == "(":
        out.append(f'<span style="color:{C_FUNC};">{_escape(token)}</span>')
      else:
        out.append(f'<span style="color:#DCDFE4;">{_escape(token)}</span>')
    else:
      colour = C_PUNCT_ALT if token in {"::", "->", "=>", "{", "}", "(", ")", "[", "]"} else C_PUNCT
      out.append(f'<span style="color:{colour};">{_escape(token)}</span>')
    position += len(token)
  return "".join(out)


def code_html(code: str) -> str:
  """HTML completo da caixa de codigo com coluna de numeros de linha."""
  lines = code.split("\n")
  width = max(2, len(str(max(1, len(lines)))))
  rows: list[str] = []
  for index, line in enumerate(lines, start=1):
    body = highlight_code(line) if line else "&nbsp;"
    rows.append(
      "<tr>"
      f'<td width="48" nowrap="nowrap" style="color:{C_LINENO}; text-align:right;'
      f' padding:0 12px 0 4px; white-space:nowrap;">{str(index).rjust(width)}</td>'
      f'<td nowrap="nowrap" style="color:#DCDFE4; white-space:nowrap;">{body}</td>'
      "</tr>"
    )
  return (
    '<table cellspacing="0" cellpadding="0" style="border:0;">'
    + "".join(rows)
    + "</table>"
  )


LANGUAGE_LABELS = {
  "rs": "rust", "py": "python", "js": "javascript", "ts": "typescript", "cpp": "cpp",
  "cc": "cpp", "cxx": "cpp", "h": "cpp", "hpp": "cpp", "sh": "bash", "bash": "bash",
  "zsh": "bash", "json": "json", "toml": "toml", "yaml": "yaml", "yml": "yaml",
  "sql": "sql", "html": "html", "css": "css", "md": "markdown", "text": "text",
}


def normalize_language(raw: str) -> str:
  key = (raw or "").strip().lower()
  return LANGUAGE_LABELS.get(key, key or "text")


class ThinkingCard(QFrame):
  """Card recolhivel com o raciocinio interno do modelo."""

  def __init__(self, thinking: str, seconds: float = 0.0, parent: QWidget | None = None) -> None:
    super().__init__(parent)
    self._body_visible = False
    self.setObjectName("thinkingCard")
    self.setStyleSheet(
      "QFrame#thinkingCard { background: #13171F; border: 1px solid #1E2228;"
      " border-left: 2px solid #00D8F6; border-radius: 8px; }"
    )
    layout = QVBoxLayout(self)
    layout.setContentsMargins(10, 6, 10, 8)
    layout.setSpacing(4)
    self.toggle = QToolButton()
    self.toggle.setObjectName("thinkingHeader")
    self.toggle.setCheckable(True)
    self.toggle.setCursor(Qt.CursorShape.PointingHandCursor)
    elapsed = f" · {seconds:.1f}s" if seconds > 0 else ""
    self.toggle.setText(f"{tr('Thought Process')} · {tr('Click to expand/collapse')}{elapsed}")
    self.toggle.setIcon(vector_icon("think", "#00D8F6", 16))
    self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    self.toggle.setStyleSheet(
      "QToolButton#thinkingHeader { background: transparent; border: none; color: #8E95A0;"
      " font-size: 11px; font-weight: 500; padding: 2px 0px; text-align: left; }"
      "QToolButton#thinkingHeader:hover { color: #00D8F6; }"
    )
    self.toggle.toggled.connect(self._set_expanded)
    layout.addWidget(self.toggle)
    self.body = QTextBrowser()
    self.body.setObjectName("thinkingBody")
    self.body.setOpenExternalLinks(False)
    self.body.setStyleSheet(
      "QTextBrowser#thinkingBody { background: transparent; border: none; color: #9AA4B2;"
      " font-size: 12px; }"
    )
    self.body.setHtml(
      f'<div style="color:#9AA4B2; font-size:12px; line-height:150%;">{_escape(thinking).replace(chr(10), "<br/>")}</div>'
    )
    self.body.setVisible(False)
    self.body.setMaximumHeight(220)
    layout.addWidget(self.body)
    self._collapsed_height = 34

  def _set_expanded(self, expanded: bool) -> None:
    self._body_visible = expanded
    self.body.setVisible(expanded)
    glyph = "chevron" if not expanded else "chevron"
    self.toggle.setIcon(vector_icon(glyph, "#00D8F6", 16))


class CodeBlockWidget(QFrame):
  """Container de codigo com badge de linguagem, numeros de linha e copia."""

  def __init__(self, code: str, language: str = "text", parent: QWidget | None = None) -> None:
    super().__init__(parent)
    self._code = code
    self._language = normalize_language(language)
    self.setObjectName("codeBlock")
    self.setStyleSheet(
      "QFrame#codeBlock { background: #0B0E14; border: 1px solid #262C36; border-radius: 10px; }"
    )
    layout = QVBoxLayout(self)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)

    header = QFrame()
    header.setObjectName("codeHeader")
    header.setStyleSheet(
      "QFrame#codeHeader { background: #161B22; border: none; border-top-left-radius: 10px;"
      " border-top-right-radius: 10px; }"
    )
    bar = QHBoxLayout(header)
    bar.setContentsMargins(12, 6, 8, 6)
    bar.setSpacing(8)
    badge = QLabel(self._language)
    badge.setStyleSheet("color: #8E95A0; font-size: 10px; font-weight: 600; letter-spacing: 0.6px;")
    bar.addWidget(badge)
    bar.addStretch(1)
    self.copy_button = QPushButton(tr("Copy code"))
    self.copy_button.setObjectName("copyCodeButton")
    self.copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
    self.copy_button.setIcon(vector_icon("copy", "#8E95A0", 14))
    self.copy_button.setStyleSheet(
      "QPushButton#copyCodeButton { background: transparent; border: 1px solid #262C36;"
      " border-radius: 6px; color: #ABB2BF; font-size: 10px; font-weight: 500; padding: 3px 8px; }"
      "QPushButton#copyCodeButton:hover { color: #00D8F6; border-color: #00D8F6; }"
    )
    self.copy_button.clicked.connect(self.copy_code)
    bar.addWidget(self.copy_button)
    layout.addWidget(header)

    self.view = QTextBrowser()
    self.view.setObjectName("codeBody")
    self.view.setFrameShape(QFrame.Shape.NoFrame)
    self.view.setStyleSheet(
      "QTextBrowser#codeBody { background: #0B0E14; border: none;"
      " font-family: 'JetBrains Mono', 'Fira Code', 'DejaVu Sans Mono', monospace; font-size: 12px; }"
    )
    self.view.setLineWrapMode(QTextBrowser.LineWrapMode.NoWrap)
    self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    self.view.setHtml(f'<div style="font-family:monospace;">{code_html(code)}</div>')
    lines = max(1, len(code.split("\n")))
    self.view.setFixedHeight(min(430, max(56, lines * 18 + 20)))
    layout.addWidget(self.view)

  def copy_code(self) -> None:
    clipboard = QApplication.clipboard()
    if clipboard is not None:
      clipboard.setText(self._code)
    self.copy_button.setText(tr("Copied!"))
    self.copy_button.setIcon(vector_icon("copy", "#00D8F6", 14))
    QTimer.singleShot(1400, self._reset_button)

  def _reset_button(self) -> None:
    self.copy_button.setText(tr("Copy code"))
    self.copy_button.setIcon(vector_icon("copy", "#8E95A0", 14))



class DiffCard(QFrame):
  """Card de unified diff com linhas + em verde e - em vermelho."""

  def __init__(self, diff: str, parent: QWidget | None = None) -> None:
    super().__init__(parent)
    self.setObjectName("diffCard")
    self.setStyleSheet(
      "QFrame#diffCard { background: #0B0E14; border: 1px solid #262C36; border-radius: 10px; }"
    )
    layout = QVBoxLayout(self)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    header = QLabel(tr("Unified Diff"))
    header.setStyleSheet(
      "background: #161B22; color: #ABB2BF; font-size: 10px; font-weight: 600;"
      " padding: 6px 12px; border-top-left-radius: 10px; border-top-right-radius: 10px;"
    )
    layout.addWidget(header)
    view = QTextBrowser()
    view.setObjectName("diffBody")
    view.setFrameShape(QFrame.Shape.NoFrame)
    view.setLineWrapMode(QTextBrowser.LineWrapMode.NoWrap)
    view.setStyleSheet(
      "QTextBrowser#diffBody { background: #0B0E14; border: none;"
      " font-family: 'JetBrains Mono', 'DejaVu Sans Mono', monospace; font-size: 12px; }"
    )
    lines = []
    for line in diff.splitlines():
      escaped = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace(" ", "&nbsp;")
      if line.startswith("+"):
        lines.append(f'<div style="color:#98C379;">{escaped}</div>')
      elif line.startswith("-"):
        lines.append(f'<div style="color:#E06C75;">{escaped}</div>')
      elif line.startswith("@@"):
        lines.append(f'<div style="color:#56B6C2;">{escaped}</div>')
      else:
        lines.append(f'<div style="color:#ABB2BF;">{escaped}</div>')
    view.setHtml("".join(lines))
    view.setFixedHeight(min(320, max(60, len(diff.splitlines()) * 18 + 16)))
    layout.addWidget(view)


class ConsoleCard(QFrame):
  """Card de comando executado no sandbox com exit code e saida."""

  def __init__(self, command: str, output: str, exit_code: int = 0, parent: QWidget | None = None) -> None:
    super().__init__(parent)
    self.setObjectName("consoleCard")
    ok = exit_code == 0
    self.setStyleSheet(
      "QFrame#consoleCard { background: #0B0E14; border: 1px solid #262C36;"
      f" border-left: 2px solid {'#3FB950' if ok else '#E06C75'}; border-radius: 10px; }}"
    )
    layout = QVBoxLayout(self)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    head = QLabel(f"$ {command}")
    head.setStyleSheet(
      "background: #161B22; color: #ABB2BF; font-family: 'JetBrains Mono', monospace;"
      " font-size: 11px; padding: 6px 12px; border-top-left-radius: 10px; border-top-right-radius: 10px;"
    )
    layout.addWidget(head)
    body = QLabel(output.strip() or tr("(no output)"))
    body.setWordWrap(True)
    body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    body.setStyleSheet(
      f"color: {'#98C379' if ok else '#E06C75'}; background: transparent;"
      " font-family: 'JetBrains Mono', monospace; font-size: 11px; padding: 8px 12px;"
    )
    layout.addWidget(body)
    tail = QLabel(tr("exit code") + f": {exit_code}")
    tail.setStyleSheet("color: #5C6370; font-size: 10px; padding: 0 12px 6px 12px;")
    layout.addWidget(tail)



THINK_PATTERN = re.compile(r"<think(?:ing)?>([\s\S]*?)(?:</think(?:ing)?>|$)", re.IGNORECASE)
FENCE_PATTERN = re.compile(r"```([A-Za-z0-9_+-]*)\n([\s\S]*?)(?:```|$)")


def split_thinking(text: str) -> tuple[str, str]:
  """Separa o raciocinio (<think>) da resposta final."""
  match = THINK_PATTERN.search(text or "")
  if not match:
    return "", text or ""
  thinking = match.group(1).strip()
  answer = (text[:match.start()] + text[match.end():]).strip()
  return thinking, answer


def split_segments(text: str) -> list[tuple[str, str, str]]:
  """Divide o texto em segmentos ('prose'|'code', conteudo, linguagem)."""
  segments: list[tuple[str, str, str]] = []
  cursor = 0
  for match in FENCE_PATTERN.finditer(text):
    before = text[cursor:match.start()]
    if before.strip():
      segments.append(("prose", before, ""))
    segments.append(("code", match.group(2).rstrip("\n"), match.group(1)))
    cursor = match.end()
  tail = text[cursor:]
  if tail.strip():
    segments.append(("prose", tail, ""))
  return segments or [("prose", text, "")]


class MessageContentView(QWidget):
  """Conteudo da mensagem: pensamento recolhivel, texto e caixas de codigo."""

  def __init__(self, text: str, role: str = "assistant", parent: QWidget | None = None) -> None:
    super().__init__(parent)
    self.role = role
    layout = QVBoxLayout(self)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    thinking, answer = split_thinking(text)
    self.thinking_card: ThinkingCard | None = None
    if thinking:
      self.thinking_card = ThinkingCard(thinking, parent=self)
      layout.addWidget(self.thinking_card)
    self.prose_label = QLabel()
    self.prose_label.setWordWrap(True)
    self.prose_label.setTextFormat(Qt.TextFormat.RichText)
    self.prose_label.setTextInteractionFlags(
      Qt.TextInteractionFlag.TextSelectableByMouse
      | Qt.TextInteractionFlag.LinksAccessibleByMouse
    )
    self._code_blocks: list[CodeBlockWidget] = []
    first_prose_used = False
    for kind, content, language in split_segments(answer):
      if kind == "code":
        normalized = normalize_language(language)
        if normalized == "diff":
          layout.addWidget(DiffCard(content, self))
          continue
        if normalized in {"bash", "console", "shell"} and content.lstrip().startswith("$"):
          lines = content.strip().split("\n")
          layout.addWidget(ConsoleCard(lines[0].lstrip("$ ").strip(), "\n".join(lines[1:]), 0, self))
          continue
        block = CodeBlockWidget(content, language, self)
        self._code_blocks.append(block)
        layout.addWidget(block)
        continue
      if not first_prose_used:
        self.prose_label.setText(message_html(content))
        layout.addWidget(self.prose_label)
        first_prose_used = True
      else:
        extra = QLabel(message_html(content))
        extra.setWordWrap(True)
        extra.setTextFormat(Qt.TextFormat.RichText)
        extra.setTextInteractionFlags(
          Qt.TextInteractionFlag.TextSelectableByMouse
          | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        layout.addWidget(extra)
    if not first_prose_used:
      self.prose_label.setText("")
      layout.addWidget(self.prose_label)

