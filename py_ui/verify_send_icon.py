"""Prova por pixels da seta do botao Send nos tres estados."""

from __future__ import annotations

import sys
from pathlib import Path

PY_UI = Path(__file__).resolve().parent
if str(PY_UI) not in sys.path:
    sys.path.insert(0, str(PY_UI))

from PyQt6.QtWidgets import QApplication  # noqa: E402


def dark_pixels(widget) -> int:
    image = widget.grab().toImage()
    count = 0
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            if color.red() < 90 and color.green() < 90 and color.blue() < 90:
                count += 1
    return count


def main() -> int:
    app = QApplication(sys.argv)
    from mark.ui.main_window import MainWindow

    window = MainWindow()
    window.resize(1400, 900)
    window.show()
    for _ in range(3):
        app.processEvents()

    button = window.send_button
    window._set_send_state()
    app.processEvents()
    idle = dark_pixels(button)

    window._set_stop_state()
    app.processEvents()
    busy = dark_pixels(button)

    window._set_send_state()
    app.processEvents()
    after = dark_pixels(button)

    print(f"SEND_PIXELS_IDLE={idle}")
    print(f"SEND_PIXELS_BUSY_STOP={busy}")
    print(f"SEND_PIXELS_AFTER={after}")
    # Piso: estado sem glifo mede 6 px; seta pintada mede ~38; quadrado do Stop ~72.
    minimo = 25
    print("SETA_VISIVEL_ANTES=" + ("SIM" if idle >= minimo else "NAO"))
    print("SETA_VISIVEL_DEPOIS=" + ("SIM" if after >= minimo else "NAO"))
    window.shutdown()
    window.close()
    app.processEvents()
    return 0 if (idle >= minimo and after >= minimo and busy >= minimo) else 2


if __name__ == "__main__":
    raise SystemExit(main())
