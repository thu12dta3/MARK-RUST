"""Hugging Face browser in an LM Studio style split view."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import (
  QComboBox,
  QFrame,
  QHBoxLayout,
  QLabel,
  QLineEdit,
  QProgressBar,
  QPushButton,
  QScrollArea,
  QSplitter,
  QTextBrowser,
  QVBoxLayout,
  QWidget,
)

from .i18n import tr
from .icons import ACTIVE, IDLE, vector_icon

API = "https://huggingface.co/api"
VRAM_GIB = 8.0
FULL_OFFLOAD_GIB = 6.8
PARTIAL_OFFLOAD_GIB = 18.0

SORTS: tuple[tuple[str, str], ...] = (
  ("relevance", "Relevance"),
  ("downloads", "Most Downloads"),
  ("likes", "Most Likes"),
  ("lastModified", "Recently Updated"),
)

FAMILY_COLORS = {
  "qwen": "#8B5CF6",
  "deepseek": "#2F81F7",
  "mark": "#00D8F6",
  "llama": "#F0883E",
  "gemma": "#3FB950",
  "mistral": "#E3B341",
}


def models_root() -> Path:
  override = os.environ.get("MARK_MODEL_ROOT")
  if override:
    return Path(override).expanduser()
  xdg = os.environ.get("XDG_DATA_HOME")
  base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
  return base / "mark" / "models"


def human_size(num_bytes: float) -> str:
  value = float(num_bytes or 0)
  for unit in ("B", "KB", "MB", "GB", "TB"):
    if value < 1024 or unit == "TB":
      return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
    value /= 1024
  return f"{value:.1f} TB"


def family_of(repo_id: str) -> str:
  haystack = repo_id.lower()
  for family in FAMILY_COLORS:
    if family in haystack:
      return family
  return "other"


def fit_badge(size_gib: float) -> tuple[str, str]:
  if size_gib <= FULL_OFFLOAD_GIB:
    return "Full GPU Offload", "#3FB950"
  if size_gib <= PARTIAL_OFFLOAD_GIB:
    return "Partial Offload", "#E3B341"
  return "Too Large", "#E06C75"


class HubSearchWorker(QThread):
  """Busca repositorios reais na API publica do Hugging Face."""

  done = pyqtSignal(list, str)

  def __init__(self, query: str, sort: str, scope: str, parent: QWidget | None = None) -> None:
    super().__init__(parent)
    self._query = query
    self._sort = sort
    self._scope = scope

  def run(self) -> None:
    params = [f"limit=60", f"sort={self._sort or 'downloads'}", "direction=-1", "full=true"]
    if self._query:
      params.append(f"search={urllib.parse.quote(self._query)}")
    if self._scope == "miceworks":
      params.append("author=miceworks")
    url = f"{API}/models?{'&'.join(params)}"
    try:
      request = urllib.request.Request(url, headers={"User-Agent": "MARK/1.0"})
      with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode())
    except (urllib.error.URLError, OSError, ValueError) as exc:
      self.done.emit([], f"Hub request failed: {exc}")
      return
    repos: list[dict[str, Any]] = []
    for item in payload if isinstance(payload, list) else []:
      repo_id = item.get("id") or item.get("modelId") or ""
      if not repo_id:
        continue
      tags = [str(tag) for tag in (item.get("tags") or [])]
      lower_tags = " ".join(tags).lower()
      fmt = "GGUF" if "gguf" in lower_tags else "Safetensors"
      if "1-bit" in lower_tags or "1bit" in repo_id.lower():
        fmt = "1-Bit"
      caps: list[str] = []
      if "vision" in lower_tags or "-vl" in repo_id.lower():
        caps.append("Vision")
      if "reasoning" in lower_tags or "r1" in repo_id.lower():
        caps.append("Reasoning")
      if "tool" in lower_tags or "instruct" in lower_tags or "coder" in repo_id.lower():
        caps.append("Tool Use")
      repos.append(
        {
          "id": repo_id,
          "downloads": int(item.get("downloads") or 0),
          "likes": int(item.get("likes") or 0),
          "updated": str(item.get("lastModified") or ""),
          "pipeline": str(item.get("pipeline_tag") or ""),
          "format": fmt,
          "caps": caps,
          "tags": tags[:8],
        }
      )
    self.done.emit(repos, "")


class DetailsWorker(QThread):
  """Busca arquivos reais e o README de um repositorio."""

  done = pyqtSignal(dict)

  def __init__(self, repo_id: str, parent: QWidget | None = None) -> None:
    super().__init__(parent)
    self._repo_id = repo_id

  def run(self) -> None:
    try:
      request = urllib.request.Request(
        f"{API}/models/{self._repo_id}?blobs=true",
        headers={"User-Agent": "MARK/1.0"},
      )
      with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode())
    except (urllib.error.URLError, OSError, ValueError) as exc:
      self.done.emit({"ok": False, "message": str(exc)})
      return
    files: list[dict[str, Any]] = []
    for sibling in payload.get("siblings") or []:
      name = str(sibling.get("rfilename") or "")
      if not name.endswith((".gguf", ".safetensors")):
        continue
      size = sibling.get("size") or 0
      files.append({"name": name, "size": int(size), "gib": round(int(size) / (1024 ** 3), 2)})
    readme = ""
    try:
      readme_request = urllib.request.Request(
        f"https://huggingface.co/{self._repo_id}/raw/main/README.md",
        headers={"User-Agent": "MARK/1.0"},
      )
      with urllib.request.urlopen(readme_request, timeout=15) as response:
        readme = response.read(6000).decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError):
      readme = ""
    self.done.emit(
      {
        "ok": True,
        "files": files,
        "readme": readme,
        "tags": payload.get("tags") or [],
        "pipeline": payload.get("pipeline_tag") or "",
        "arch": str((payload.get("config") or {}).get("architectures") or ""),
      }
    )


class DownloadWorker(QThread):
  """Download com Range resume, MB/s e ETA fora da thread da interface."""

  progress = pyqtSignal(int, int, float)
  finished_file = pyqtSignal(str, bool, str)

  def __init__(self, repo_id: str, filename: str, destination: Path, parent: QWidget | None = None) -> None:
    super().__init__(parent)
    self._repo_id = repo_id
    self._filename = filename
    self._destination = destination

  def run(self) -> None:
    url = f"https://huggingface.co/{self._repo_id}/resolve/main/{self._filename}"
    target = self._destination / self._filename.split("/")[-1]
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + ".part")
    existing = part.stat().st_size if part.is_file() else 0
    headers = {"User-Agent": "MARK/1.0"}
    if existing:
      headers["Range"] = f"bytes={existing}-"
    try:
      request = urllib.request.Request(url, headers=headers)
      with urllib.request.urlopen(request, timeout=60) as response:
        total = int(response.headers.get("Content-Length") or 0) + existing
        mode = "ab" if response.status == 206 else "wb"
        if response.status != 206:
          existing = 0
        start = time.time()
        downloaded = existing
        with part.open(mode) as handle:
          while True:
            chunk = response.read(1024 * 256)
            if not chunk:
              break
            handle.write(chunk)
            downloaded += len(chunk)
            elapsed = max(0.001, time.time() - start)
            speed = (downloaded - existing) / elapsed / (1024 * 1024)
            self.progress.emit(downloaded, total, speed)
    except (urllib.error.URLError, OSError) as exc:
      self.finished_file.emit(str(target), False, str(exc))
      return
    part.replace(target)
    self.finished_file.emit(str(target), True, "")


class ModelCard(QFrame):
  """Card clicavel de repositorio, com badge de familia e capacidades."""

  clicked = pyqtSignal(str)

  def __init__(self, repo: dict[str, Any], parent: QWidget | None = None) -> None:
    super().__init__(parent)
    self._repo = repo
    self._active = False
    self.setCursor(Qt.CursorShape.PointingHandCursor)
    self.setStyleSheet(self._style(False))
    layout = QVBoxLayout(self)
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(4)

    head = QHBoxLayout()
    head.setSpacing(6)
    family = family_of(repo["id"])
    badge = QLabel(family.upper() if family != "other" else "HF")
    colour = FAMILY_COLORS.get(family, "#8E95A0")
    badge.setStyleSheet(
      f"background: {colour}22; color: {colour}; border: 1px solid {colour}55;"
      " border-radius: 5px; padding: 1px 6px; font-size: 9px; font-weight: 700;"
    )
    head.addWidget(badge)
    title = QLabel(repo["id"].split("/")[-1])
    title.setStyleSheet("color: #EDEDED; font-size: 12px; font-weight: 600;")
    head.addWidget(title, 1)
    meta = QLabel(f"{repo.get('downloads', 0):,} ↓ · {repo.get('likes', 0):,} ")
    meta.setStyleSheet("color: #5F6672; font-size: 9px;")
    head.addWidget(meta)
    layout.addLayout(head)

    owner = QLabel(repo["id"].split("/")[0] + f" · {repo.get('format', 'HF')}")
    owner.setStyleSheet("color: #8E95A0; font-size: 10px;")
    layout.addWidget(owner)

    caps = QHBoxLayout()
    caps.setSpacing(4)
    colours = {"Vision": "#E3B341", "Tool Use": "#61AFEF", "Reasoning": "#3FB950"}
    for capability in repo.get("caps", []):
      chip = QLabel(capability)
      colour = colours.get(capability, "#8E95A0")
      chip.setStyleSheet(
        f"background: {colour}1A; color: {colour}; border-radius: 5px;"
        " padding: 1px 5px; font-size: 9px;"
      )
      caps.addWidget(chip)
    caps.addStretch(1)
    layout.addLayout(caps)

  def _style(self, active: bool) -> str:
    border = ACTIVE if active else "#262C36"
    return (
      "QFrame { background: #161B22; border: 1px solid " + border + "; border-radius: 8px; }"
    )

  def set_active(self, active: bool) -> None:
    self._active = active
    self.setStyleSheet(self._style(active))

  def mousePressEvent(self, event) -> None: # noqa: N802
    self.clicked.emit(self._repo["id"])
    super().mousePressEvent(event)


class HFSplitView(QWidget):
  """Navegador do Hub com lista de cards e inspetor de download."""

  def __init__(self, parent: QWidget | None = None) -> None:
    super().__init__(parent)
    self._cards: list[ModelCard] = []
    self._active_id = ""
    self._search_worker: HubSearchWorker | None = None
    self._details_worker: DetailsWorker | None = None
    self._download_worker: DownloadWorker | None = None
    self._files: list[dict[str, Any]] = []
    self._build()
    self.search("", "downloads", "all")

  def _build(self) -> None:
    layout = QVBoxLayout(self)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(8)

    top = QHBoxLayout()
    top.setSpacing(8)
    self.search_input = QLineEdit()
    self.search_input.setPlaceholderText(tr("Search models on Hugging Face..."))
    self.search_input.setStyleSheet(
      "QLineEdit { background: #121417; color: #EDEDED; border: 1px solid #1E2228;"
      " border-radius: 8px; padding: 7px 10px; font-size: 12px; }"
    )
    self.search_input.addAction(vector_icon("chat", IDLE, 14), QLineEdit.ActionPosition.LeadingPosition)
    self.search_input.returnPressed.connect(self._on_search)
    top.addWidget(self.search_input, 1)

    self.filter_buttons: dict[str, QPushButton] = {}
    for scope, label in (("all", "All Hub"), ("popular", "Staff Picks / Popular"), ("miceworks", "Miceworks Collection")):
      button = QPushButton(tr(label))
      button.setCheckable(True)
      button.setChecked(scope == "all")
      button.setCursor(Qt.CursorShape.PointingHandCursor)
      button.setStyleSheet(
        "QPushButton { background: #16191D; color: #8E95A0; border: 1px solid #1E2228;"
        " border-radius: 7px; padding: 5px 10px; font-size: 11px; }"
        "QPushButton:checked { color: #00D8F6; border-color: #00D8F6; }"
      )
      button.clicked.connect(lambda _checked=False, s=scope: self._set_scope(s))
      self.filter_buttons[scope] = button
      top.addWidget(button)

    self.sort_combo = QComboBox()
    for value, label in SORTS:
      self.sort_combo.addItem(tr(label), value)
    self.sort_combo.setStyleSheet(
      "QComboBox { background: #16191D; color: #EDEDED; border: 1px solid #1E2228;"
      " border-radius: 7px; padding: 5px 8px; font-size: 11px; }"
    )
    self.sort_combo.currentIndexChanged.connect(lambda _i: self._on_search())
    top.addWidget(self.sort_combo)
    layout.addLayout(top)

    self.status_label = QLabel(tr("Loading the Hugging Face Hub..."))
    self.status_label.setStyleSheet("color: #8E95A0; font-size: 11px;")
    layout.addWidget(self.status_label)

    splitter = QSplitter(Qt.Orientation.Horizontal)
    splitter.setStyleSheet("QSplitter::handle { background: #1E2228; width: 1px; }")

    left = QScrollArea()
    left.setWidgetResizable(True)
    left.setFrameShape(QFrame.Shape.NoFrame)
    left.setStyleSheet("QScrollArea { background: transparent; border: none; }")
    self.list_host = QWidget()
    self.list_layout = QVBoxLayout(self.list_host)
    self.list_layout.setContentsMargins(0, 0, 6, 0)
    self.list_layout.setSpacing(6)
    self.list_layout.addStretch(1)
    left.setWidget(self.list_host)
    splitter.addWidget(left)

    right = QWidget()
    rlayout = QVBoxLayout(right)
    rlayout.setContentsMargins(10, 0, 0, 0)
    rlayout.setSpacing(8)
    self.title_label = QLabel(tr("Model Details & Download Options"))
    self.title_label.setStyleSheet("color: #EDEDED; font-size: 16px; font-weight: 600;")
    rlayout.addWidget(self.title_label)
    self.meta_label = QLabel("")
    self.meta_label.setStyleSheet("color: #8E95A0; font-size: 11px;")
    rlayout.addWidget(self.meta_label)
    self.spec_label = QLabel("")
    self.spec_label.setWordWrap(True)
    self.spec_label.setStyleSheet(
      "color: #C8D1DC; font-size: 11px; font-family: 'JetBrains Mono', monospace;"
    )
    rlayout.addWidget(self.spec_label)

    self.files_host = QWidget()
    self.files_layout = QVBoxLayout(self.files_host)
    self.files_layout.setContentsMargins(0, 0, 0, 0)
    self.files_layout.setSpacing(6)
    rlayout.addWidget(self.files_host)

    self.progress = QProgressBar()
    self.progress.setRange(0, 100)
    self.progress.setTextVisible(True)
    self.progress.setStyleSheet(
      "QProgressBar { background: #121417; border: 1px solid #1E2228; border-radius: 6px;"
      " color: #C8D1DC; font-size: 10px; height: 14px; }"
      "QProgressBar::chunk { background: #00D8F6; border-radius: 5px; }"
    )
    rlayout.addWidget(self.progress)

    self.readme = QTextBrowser()
    self.readme.setStyleSheet(
      "QTextBrowser { background: #0B0E14; border: 1px solid #262C36; border-radius: 8px;"
      " color: #ABB2BF; font-size: 11px; }"
    )
    self.readme.setOpenExternalLinks(True)
    rlayout.addWidget(self.readme, 1)
    splitter.addWidget(right)
    splitter.setSizes([int(1920 * 0.42), int(1920 * 0.58)])
    layout.addWidget(splitter, 1)

  # ------------------------------------------------------------------ busca
  def _set_scope(self, scope: str) -> None:
    for key, button in self.filter_buttons.items():
      button.setChecked(key == scope)
    self._scope = scope
    self._on_search()

  def _on_search(self) -> None:
    self.search(
      self.search_input.text().strip(),
      str(self.sort_combo.currentData() or "downloads"),
      getattr(self, "_scope", "all"),
    )

  def search(self, query: str, sort: str, scope: str) -> None:
    if self._search_worker is not None and self._search_worker.isRunning():
      return
    self.status_label.setText(tr("Querying the Hugging Face Hub..."))
    worker = HubSearchWorker(query, sort, scope, self)
    worker.done.connect(self._on_results)
    worker.finished.connect(self._reap_search)
    self._search_worker = worker
    worker.start()

  def _reap_search(self) -> None:
    if self._search_worker is not None:
      self._search_worker.deleteLater()
      self._search_worker = None

  def _on_results(self, repos: list[dict[str, Any]], error: str) -> None:
    for card in self._cards:
      card.deleteLater()
    self._cards = []
    if error:
      self.status_label.setText(error)
      return
    for repo in repos:
      card = ModelCard(repo, self.list_host)
      card.clicked.connect(self.select_repo)
      self.list_layout.insertWidget(self.list_layout.count() - 1, card)
      self._cards.append(card)
    self.status_label.setText(
      tr("{count} repositories from the whole Hub").format(count=len(repos))
    )
    if self._cards:
      self.select_repo(self._cards[0]._repo["id"])

  # --------------------------------------------------------------- inspetor
  def select_repo(self, repo_id: str) -> None:
    self._active_id = repo_id
    for card in self._cards:
      card.set_active(card._repo["id"] == repo_id)
    self.title_label.setText(repo_id)
    self.meta_label.setText(tr("Loading files..."))
    self.spec_label.setText("")
    self.readme.setHtml("")
    while self.files_layout.count():
      item = self.files_layout.takeAt(0)
      widget = item.widget()
      if widget is not None:
        widget.deleteLater()
    worker = DetailsWorker(repo_id, self)
    worker.done.connect(self._on_details)
    worker.finished.connect(self._reap_details)
    self._details_worker = worker
    worker.start()

  def _reap_details(self) -> None:
    if self._details_worker is not None:
      self._details_worker.deleteLater()
      self._details_worker = None

  def _on_details(self, payload: dict[str, Any]) -> None:
    if not payload.get("ok"):
      self.meta_label.setText(tr("Details failed: {detail}").format(detail=str(payload.get("message") or "")))
      return
    self._files = list(payload.get("files") or [])
    total_gib = sum(float(item.get("gib") or 0) for item in self._files)
    self.meta_label.setText(
      tr("{files} files · {size} · VRAM budget {vram} GiB").format(
        files=len(self._files), size=human_size(total_gib * 1024 ** 3), vram=f"{VRAM_GIB:.1f}"
      )
    )
    tags = ", ".join(str(tag) for tag in (payload.get("tags") or [])[:6])
    self.spec_label.setText(
      f"ARCH: {payload.get('arch') or payload.get('pipeline') or 'n/a'} · "
      f"FORMAT: {'GGUF' if any(f['name'].endswith('.gguf') for f in self._files) else 'Safetensors'} · "
      f"TAGS: {tags or 'n/a'}"
    )
    if not self._files:
      empty = QLabel(tr("This repository has no .gguf or .safetensors files."))
      empty.setStyleSheet("color: #8E95A0; font-size: 11px;")
      self.files_layout.addWidget(empty)
    for item in self._files[:24]:
      self.files_layout.addWidget(self._file_card(item))
    self.readme.setHtml(
      "<pre style='white-space:pre-wrap; color:#ABB2BF;'>"
      + (payload.get("readme") or tr("(no README)"))[:4000].replace("<", "&lt;")
      + "</pre>"
    )

  def _file_card(self, item: dict[str, Any]) -> QWidget:
    card = QFrame()
    card.setStyleSheet("QFrame { background: #12161B; border: 1px solid #262C36; border-radius: 7px; }")
    row = QHBoxLayout(card)
    row.setContentsMargins(10, 6, 8, 6)
    row.setSpacing(8)
    name = QLabel(item["name"])
    name.setStyleSheet("color: #C8D1DC; font-size: 11px; border: none;")
    row.addWidget(name, 1)
    size = QLabel(human_size(item["size"]) if item.get("size") else "size n/a")
    size.setStyleSheet("color: #5F6672; font-size: 10px; border: none;")
    row.addWidget(size)
    label, colour = fit_badge(float(item.get("gib") or 0))
    badge = QLabel(tr(label))
    badge.setStyleSheet(
      f"color: {colour}; border: 1px solid {colour}55; border-radius: 5px;"
      " padding: 1px 6px; font-size: 9px;"
    )
    row.addWidget(badge)
    button = QPushButton(tr("Download"))
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setStyleSheet(
      "QPushButton { background: #00D8F6; color: #121417; border: none; border-radius: 6px;"
      " padding: 3px 10px; font-size: 10px; font-weight: 600; }"
    )
    button.clicked.connect(lambda _checked=False, f=item["name"]: self.start_download(f))
    row.addWidget(button)
    return card

  # --------------------------------------------------------------- shutdown
  def shutdown(self) -> None:
    """Encerra as threads do split view antes do fechamento da aplicacao."""
    for name in ("_search_worker", "_details_worker", "_download_worker"):
      worker = getattr(self, name, None)
      if worker is not None and worker.isRunning():
        try:
          worker.quit()
          worker.wait(2500)
        except RuntimeError:
          pass

  # --------------------------------------------------------------- download
  def start_download(self, filename: str) -> None:
    if self._download_worker is not None and self._download_worker.isRunning():
      return
    if not self._active_id:
      return
    worker = DownloadWorker(self._active_id, filename, models_root(), self)
    worker.progress.connect(self._on_progress)
    worker.finished_file.connect(self._on_downloaded)
    worker.finished.connect(self._reap_download)
    self._download_worker = worker
    worker.start()

  def _reap_download(self) -> None:
    if self._download_worker is not None:
      self._download_worker.deleteLater()
      self._download_worker = None

  def _on_progress(self, downloaded: int, total: int, speed: float) -> None:
    percent = int(downloaded * 100 / total) if total else 0
    self.progress.setValue(percent)
    remaining = (total - downloaded) / (speed * 1024 * 1024) if speed > 0 else 0
    self.progress.setFormat(f"{percent}% · {speed:.1f} MB/s · ETA {remaining:.0f}s")

  def _on_downloaded(self, path: str, ok: bool, error: str) -> None:
    if ok:
      self.progress.setValue(100)
      self.progress.setFormat(tr("saved") + f" · {path}")
    else:
      self.progress.setFormat(tr("failed") + f": {error}"[:120])
