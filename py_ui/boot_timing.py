"""Startup timing: process start -> window visible -> first painted frame."""

from __future__ import annotations

import sys
import time
from pathlib import Path

T0 = time.perf_counter()
PY_UI = Path(__file__).resolve().parent
if str(PY_UI) not in sys.path:
    sys.path.insert(0, str(PY_UI))

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication


def main() -> int:
    app = QApplication(sys.argv)
    from mark.ui.main_window import MainWindow

    t_import = time.perf_counter() - T0
    window = MainWindow()
    t_ctor = time.perf_counter() - T0
    window.resize(1600, 900)
    window.show()
    t_show = time.perf_counter() - T0
    for _ in range(3):
        app.processEvents()
    pixmap = window.grab()
    t_paint = time.perf_counter() - T0
    print(f"IMPORT_MS={t_import*1000:.0f}")
    print(f"CTOR_MS={t_ctor*1000:.0f}")
    print(f"SHOW_MS={t_show*1000:.0f}")
    print(f"FIRST_PAINT_MS={t_paint*1000:.0f}")
    print(f"PAINTED={pixmap.width()}x{pixmap.height()}")
    window.shutdown()
    window.close()
    app.processEvents()
    return 0 if t_paint < 0.700 else 3


if __name__ == "__main__":
    raise SystemExit(main())
