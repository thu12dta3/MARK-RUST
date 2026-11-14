"""Sentinel panel: read-only ClamAV scan with explicit deletion authorisation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .i18n import tr
from .icons import ACTIVE, IDLE, vector_icon


class SentinelScanWorker(QThread):
    """Roda o clamscan somente-leitura pelo binario Rust."""

    done = pyqtSignal(dict)

    def __init__(self, path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._path = path

    def run(self) -> None:
        from ..rust_bridge import rust

        try:
            result = rust.sentinel_scan(self._path)
        except Exception as exc:
            result = {"ok": False, "message": str(exc), "infected": []}
        self.done.emit(dict(result))


class SentinelDeleteWorker(QThread):
    """Remove um arquivo autorizado pelo usuario, com auditoria no Rust."""

    done = pyqtSignal(dict)

    def __init__(self, path: str, threat: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._path = path
        self._threat = threat

    def run(self) -> None:
        from ..rust_bridge import rust

        try:
            result = rust.sentinel_delete(self._path, self._threat)
        except Exception as exc:
            result = {"ok": False, "message": str(exc)}
        self.done.emit(dict(result))


class SentinelDialog(QDialog):
    """Antivirus & Threats · Sentinel (ClamAV read-only + permissao explicita)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sentinel")
        self.resize(980, 680)
        self.setStyleSheet(parent.styleSheet() if parent is not None else "")
        self._scan_worker: SentinelScanWorker | None = None
        self._delete_worker: SentinelDeleteWorker | None = None
        self._selected: dict[str, Any] | None = None
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel(tr("Antivirus & Threats · Sentinel"))
        title.setStyleSheet("color: #EDEDED; font-size: 15px; font-weight: 600;")
        head.addWidget(title)
        head.addStretch(1)
        mode = QLabel(tr("ClamAV · read-only mode"))
        mode.setStyleSheet("color: #3FB950; font-size: 11px; font-weight: 600;")
        head.addWidget(mode)
        layout.addLayout(head)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.path_input = QLineEdit(str(Path.home() / "Downloads"))
        self.path_input.setStyleSheet(
            "QLineEdit { background: #121417; color: #EDEDED; border: 1px solid #1E2228;"
            " border-radius: 7px; padding: 6px 10px; font-size: 12px; }"
        )
        row.addWidget(self.path_input, 1)
        browse = QPushButton(tr("Browse"))
        browse.clicked.connect(self._pick_folder)
        browse.setStyleSheet(
            "QPushButton { background: #16191D; color: #8E95A0; border: 1px solid #1E2228;"
            " border-radius: 7px; padding: 6px 12px; font-size: 12px; }"
        )
        row.addWidget(browse)
        self.scan_button = QPushButton(tr("Scan (read-only)"))
        self.scan_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.scan_button.setIcon(vector_icon("shield", ACTIVE, 16))
        self.scan_button.setStyleSheet(
            "QPushButton { background: #00D8F6; color: #121417; border: none; border-radius: 7px;"
            " padding: 6px 14px; font-size: 12px; font-weight: 600; }"
        )
        self.scan_button.clicked.connect(self.start_scan)
        row.addWidget(self.scan_button)
        layout.addLayout(row)

        self.status_label = QLabel(tr("Nothing scanned yet. clamscan runs without --remove."))
        self.status_label.setStyleSheet("color: #8E95A0; font-size: 11px;")
        layout.addWidget(self.status_label)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([tr("File"), tr("Threat"), tr("Size"), "SHA-256"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setStyleSheet(
            "QTableWidget { background: #121417; color: #EDEDED; border: 1px solid #1E2228;"
            " border-radius: 8px; font-size: 11px; }"
            "QHeaderView::section { background: #16191D; color: #8E95A0; border: none; padding: 6px; }"
        )
        self.table.itemSelectionChanged.connect(self._on_selection)
        layout.addWidget(self.table, 1)

        self.permission_card = QFrame()
        self.permission_card.setObjectName("deletionPermission")
        self.permission_card.setStyleSheet(
            "QFrame#deletionPermission { background: #1A1214; border: 1px solid #5A2226;"
            " border-left: 3px solid #E06C75; border-radius: 10px; }"
        )
        card = QVBoxLayout(self.permission_card)
        card.setContentsMargins(12, 10, 12, 10)
        card.setSpacing(6)
        warn = QLabel(tr("Deletion requires your explicit authorisation"))
        warn.setStyleSheet("color: #E06C75; font-size: 12px; font-weight: 600;")
        card.addWidget(warn)
        self.permission_detail = QLabel("")
        self.permission_detail.setWordWrap(True)
        self.permission_detail.setStyleSheet(
            "color: #C8D1DC; font-size: 11px; font-family: 'JetBrains Mono', monospace;"
        )
        card.addWidget(self.permission_detail)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.authorize_button = QPushButton(tr("Authorize File Deletion"))
        self.authorize_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.authorize_button.setStyleSheet(
            "QPushButton { background: #E06C75; color: #121417; border: none; border-radius: 7px;"
            " padding: 6px 14px; font-size: 11px; font-weight: 700; }"
        )
        self.authorize_button.clicked.connect(self.authorize_deletion)
        buttons.addWidget(self.authorize_button)
        self.ignore_button = QPushButton(tr("Ignore / Keep"))
        self.ignore_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ignore_button.setStyleSheet(
            "QPushButton { background: #16191D; color: #8E95A0; border: 1px solid #1E2228;"
            " border-radius: 7px; padding: 6px 14px; font-size: 11px; }"
        )
        self.ignore_button.clicked.connect(self._ignore_selection)
        buttons.addWidget(self.ignore_button)
        buttons.addStretch(1)
        card.addLayout(buttons)
        self.permission_card.setVisible(False)
        layout.addWidget(self.permission_card)

    def closeEvent(self, event) -> None:  # noqa: N802
        """Nunca deixa thread do scan viva ao fechar o dialogo."""
        for name in ("_scan_worker", "_delete_worker"):
            worker = getattr(self, name, None)
            if worker is not None and worker.isRunning():
                worker.quit()
                worker.wait(3000)
        super().closeEvent(event)

    def _pick_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, tr("Select a folder to scan"), self.path_input.text())
        if chosen:
            self.path_input.setText(chosen)

    def start_scan(self) -> None:
        if self._scan_worker is not None and self._scan_worker.isRunning():
            return
        path = self.path_input.text().strip()
        if not path:
            return
        self.scan_button.setDisabled(True)
        self.status_label.setText(tr("Scanning {path} with clamscan (no removal)...").format(path=path))
        worker = SentinelScanWorker(path, parent=self)
        worker.done.connect(self._on_scan_done)
        worker.finished.connect(self._reap_scan)
        self._scan_worker = worker
        worker.start()

    def _reap_scan(self) -> None:
        self.scan_button.setDisabled(False)
        if self._scan_worker is not None:
            self._scan_worker.deleteLater()
            self._scan_worker = None

    def _on_scan_done(self, result: dict[str, Any]) -> None:
        infected = list(result.get("infected") or [])
        self.table.setRowCount(0)
        for row, entry in enumerate(infected):
            self.table.insertRow(row)
            values = (
                str(entry.get("path") or entry.get("file") or ""),
                str(entry.get("threat") or entry.get("signature") or ""),
                str(entry.get("size") or entry.get("size_bytes") or ""),
                str(entry.get("sha256") or ""),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                self.table.setItem(row, column, item)
        engine = str(result.get("engine") or "clamscan")
        if not result.get("ok"):
            self.status_label.setText(
                tr("Scan failed: {detail}").format(detail=str(result.get("message") or ""))
            )
            return
        self.status_label.setText(
            tr("{engine} scanned {count} files · {threats} threat(s) · read-only, nothing removed").format(
                engine=engine,
                count=int(result.get("scanned") or 0),
                threats=len(infected),
            )
        )
        self.permission_card.setVisible(bool(infected))
        if infected:
            self.table.selectRow(0)

    def _on_selection(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            self._selected = None
            self.permission_card.setVisible(False)
            return
        row = rows[0].row()
        self._selected = {
            "path": self.table.item(row, 0).text() if self.table.item(row, 0) else "",
            "threat": self.table.item(row, 1).text() if self.table.item(row, 1) else "",
            "size": self.table.item(row, 2).text() if self.table.item(row, 2) else "",
            "sha256": self.table.item(row, 3).text() if self.table.item(row, 3) else "",
        }
        self.permission_detail.setText(
            f"{tr('File')}: {self._selected['path']}\n"
            f"{tr('Threat')}: {self._selected['threat']}\n"
            f"{tr('Size')}: {self._selected['size']}\n"
            f"SHA-256: {self._selected['sha256']}"
        )
        self.permission_card.setVisible(True)

    def _ignore_selection(self) -> None:
        self.permission_card.setVisible(False)
        self.status_label.setText(
            tr("Threat kept. MARK never deletes without your authorisation.")
        )

    def authorize_deletion(self) -> None:
        if self._selected is None:
            return
        path = str(self._selected.get("path") or "")
        threat = str(self._selected.get("threat") or "")
        confirm = QMessageBox.question(
            self,
            tr("Authorize File Deletion"),
            tr("Delete this file permanently?\n\n{path}\n\nThis action is written to the audit log.").format(path=path),
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self.authorize_button.setDisabled(True)
        worker = SentinelDeleteWorker(path, threat, parent=self)
        worker.done.connect(self._on_delete_done)
        worker.finished.connect(self._reap_delete)
        self._delete_worker = worker
        worker.start()

    def _reap_delete(self) -> None:
        self.authorize_button.setDisabled(False)
        if self._delete_worker is not None:
            self._delete_worker.deleteLater()
            self._delete_worker = None

    def _on_delete_done(self, result: dict[str, Any]) -> None:
        if result.get("ok") and result.get("removed"):
            self.status_label.setText(
                tr("File deleted after your authorisation · audit: {path}").format(path=str(result.get("audit") or ""))
            )
            self.permission_card.setVisible(False)
        else:
            self.status_label.setText(
                tr("Deletion refused: {detail}").format(detail=str(result.get("message") or result.get("error") or ""))
            )
