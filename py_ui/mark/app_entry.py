"""Entry point for the MARK desktop application (PyQt6 front-end).

Boots the copied MARK-Python interface on top of the MARK-RUST workspace: the
window talks to the compiled Rust binaries through ``mark.rust_bridge``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PyQt6.QtGui import QSurfaceFormat
from PyQt6.QtWidgets import QApplication


def _ensure_repo_root_on_path() -> Path:
    """Guarantees the py_ui root is importable when launched from a wrapper."""
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root


def _resolve_display() -> None:
    """Fills DISPLAY/WAYLAND_DISPLAY when launched from a session-less shell."""
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    if not os.environ.get("WAYLAND_DISPLAY") and Path(runtime, "wayland-1").exists():
        os.environ["WAYLAND_DISPLAY"] = "wayland-1"
        os.environ.setdefault("XDG_RUNTIME_DIR", runtime)
    if not os.environ.get("DISPLAY") and Path("/tmp/.X11-unix/X0").exists():
        os.environ["DISPLAY"] = ":0"


def main() -> int:
    _ensure_repo_root_on_path()
    _resolve_display()
    # Vsync de 1 frame: o pacing acompanha o monitor (30-120 Hz) sem rasgar.
    surface = QSurfaceFormat.defaultFormat()
    surface.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(surface)
    app = QApplication(sys.argv)
    app.setApplicationName("MARK")
    app.setApplicationDisplayName("MARK")
    app.setOrganizationName("miceworks")
    from .ui.main_window import MainWindow

    window = MainWindow()
    window.resize(1280, 850)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
