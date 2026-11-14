"""Captures the four v2 visual proofs of the MARK interface.

Run on the live display with the MARK-RUST virtualenv.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

PY_UI = Path(__file__).resolve().parent
if str(PY_UI) not in sys.path:
    sys.path.insert(0, str(PY_UI))

from PyQt6.QtWidgets import QApplication, QDialog, QWidget

OUT = Path(__file__).resolve().parent.parent
SIZE = (1280, 850)
SCRATCH = Path.home() / ".hermes" / "cache" / "scratch" / "sentinel_demo"
EICAR = r"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"

DEMO_CODE = '''\
#include <vulkan/vulkan.h>
#include <vector>

int main() {
    VkApplicationInfo app{VK_STRUCTURE_TYPE_APPLICATION_INFO};
    app.pApplicationName = "mark";
    app.apiVersion = VK_API_VERSION_1_2;
    VkInstanceCreateInfo info{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};
    info.pApplicationInfo = &app;
    VkInstance instance = VK_NULL_HANDLE;
    if (vkCreateInstance(&info, nullptr, &instance) != VK_SUCCESS) {
        return 1;  // falha ao criar a instancia
    }
    vkDestroyInstance(instance, nullptr);
    return 0;
}'''


def pump(app: QApplication, rounds: int = 10) -> None:
    for _ in range(rounds):
        app.processEvents()
        time.sleep(0.005)


def grab(app: QApplication, widget: QWidget, name: str) -> str:
    pump(app, 12)
    widget.repaint()
    pixmap = widget.grab()
    path = OUT / name
    pixmap.save(str(path), "PNG")
    return f"{name}: {pixmap.width()}x{pixmap.height()} ({path.stat().st_size} bytes)"


def wait_for(app: QApplication, predicate, timeout: float = 25.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.05)
    return False


def main() -> int:
    app = QApplication(sys.argv)
    from mark.ui.i18n import set_language
    from mark.ui.main_window import MainWindow

    window = MainWindow()
    window.resize(*SIZE)
    window.show()
    set_language("en")
    window.language_selector.setCurrentIndex(window.language_selector.findData("en"))
    window.open_specialized_chat("general")
    pump(app, 25)

    window.model_selector.setCurrentIndex(0)
    print("MODEL0:", window.model_selector.itemText(0), "| PILL:", window.routing_target_badge.text())

    demo = (
        "Vou revisar a inicializacao do Vulkan antes de compilar.\n"
        "<think>\n1. app.apiVersion precisa ser VK_API_VERSION_1_2.\n"
        "2. A instancia nasce de vkCreateInstance e precisa ser destruida.\n"
        "3. O retorno deve ser comparado com VK_SUCCESS.\n"
        "</think>\n"
        "O esqueleto correto fica assim:\n\n"
        "```cpp\n" + DEMO_CODE + "\n```\n"
        "Compile com `g++ -std=c++20 main.cpp -lvulkan`."
    )
    window._append_bubble(demo, "assistant", None, auto_scroll=True)
    pump(app, 30)
    print(grab(app, window, "v2_1_chat_ide_code_and_think.png"))

    window.open_specialized_chat("engineer")
    pump(app, 20)
    panel = window.engineer_panel
    panel.refresh_profile()
    panel.target_input.setText(str(PY_UI / "mark" / "ui" / "icons.py"))
    panel.action_combo.setCurrentIndex(1)
    panel.run_step()
    wait_for(app, lambda: panel._worker is None, timeout=30)
    pump(app, 20)
    print("HW_BADGE:", panel.hw_badge.text())
    print("STEP:", panel.steps_label.text()[:120])
    print(grab(app, window, "v2_2_engineer_codex_hwprofile.png"))

    window.open_specialized_chat("professor")
    pump(app, 20)
    steps = (
        "Resolvendo por partes.\n"
        "### Step 1\nAchar a aceleracao pela segunda lei: a = F/m.\n"
        "### Step 2\nAplicar a cinematica: v = v0 + a·t.\n"
        "### Step 3\nConferir as unidades do resultado.\n\n"
        "```text\na = 12 N / 3 kg = 4 m/s^2\nv = 0 + 4 * 5 = 20 m/s\n```"
    )
    window._append_bubble(steps, "assistant", None, auto_scroll=True)
    pump(app, 25)
    print("PROFESSOR_BUTTONS:", list(window.professor_panel.buttons))
    print(grab(app, window, "v2_3_professor_astra.png"))

    SCRATCH.mkdir(parents=True, exist_ok=True)
    sample = SCRATCH / "eicar.com"
    sample.write_text(EICAR)
    from mark.ui.sentinel_panel import SentinelDialog

    dialog = SentinelDialog(window)
    dialog.setStyleSheet(window.styleSheet())
    dialog.resize(*SIZE)
    dialog.path_input.setText(str(SCRATCH))
    dialog.show()
    pump(app, 15)
    dialog.start_scan()
    wait_for(app, lambda: dialog._scan_worker is None, timeout=60)
    pump(app, 20)
    print("SENTINEL_STATUS:", dialog.status_label.text())
    if dialog.table.rowCount():
        dialog.table.selectRow(0)
        pump(app, 10)
    print("PERMISSION_CARD:", dialog.permission_card.isVisibleTo(dialog))
    print(grab(app, dialog, "v2_4_sentinel_clamav.png"))
    dialog.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
