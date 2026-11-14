"""Captures the five v3 visual proofs at 1920x1080."""

from __future__ import annotations

import sys
import time
from pathlib import Path

PY_UI = Path(__file__).resolve().parent
if str(PY_UI) not in sys.path:
    sys.path.insert(0, str(PY_UI))

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import QApplication, QWidget

OUT = Path(__file__).resolve().parent.parent
SIZE = (1920, 1080)

DEMO = """\
Analisando o pipeline antes de compilar.
<think>
1. VkApplicationInfo precisa de apiVersion VK_API_VERSION_1_2.
2. vkCreateInstance devolve VkResult; nunca ignorar.
3. Destruir a instancia no fim.
</think>
Segue a inicializacao correta:

```cpp
#include <vulkan/vulkan.h>

int main() {
    VkApplicationInfo app{VK_STRUCTURE_TYPE_APPLICATION_INFO};
    app.pApplicationName = "mark";
    app.apiVersion = VK_API_VERSION_1_2;
    VkInstanceCreateInfo info{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};
    info.pApplicationInfo = &app;
    VkInstance instance = VK_NULL_HANDLE;
    if (vkCreateInstance(&info, nullptr, &instance) != VK_SUCCESS) {
        return 1;  // falha
    }
    vkDestroyInstance(instance, nullptr);
    return 0;
}
```

Compile com `g++ -std=c++20 main.cpp -lvulkan`."""

DIFF_DEMO = """\
```diff
--- a/src/main.cpp
+++ b/src/main.cpp
@@ -1,4 +1,5 @@
 int main() {
-    VkInstance instance;
+    VkInstance instance = VK_NULL_HANDLE;
+    // inicializacao explicita
     return 0;
 }
```"""


def pump(app: QApplication, rounds: int = 12) -> None:
    for _ in range(rounds):
        app.processEvents()
        time.sleep(0.005)


def grab(app: QApplication, widget: QWidget, name: str) -> str:
    pump(app, 14)
    widget.repaint()
    pixmap = widget.grab()
    path = OUT / name
    pixmap.save(str(path), "PNG")
    return f"{name}: {pixmap.width()}x{pixmap.height()} ({path.stat().st_size} bytes)"


def grab_with_popup(app: QApplication, window: QWidget, popup: QWidget, anchor: QWidget, name: str) -> str:
    """Compõe a janela real com o popup realmente renderizado aberto."""
    pump(app, 12)
    base = window.grab()
    overlay = popup.grab()
    origin = anchor.mapTo(window, anchor.rect().bottomLeft())
    painter = QPainter(base)
    painter.drawPixmap(origin.x(), origin.y(), overlay)
    painter.end()
    path = OUT / name
    base.save(str(path), "PNG")
    return f"{name}: {base.width()}x{base.height()} ({path.stat().st_size} bytes)"


def wait_for(app: QApplication, predicate, timeout: float = 30.0) -> bool:
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
    window.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
    window.resize(*SIZE)
    window.show()
    pump(app, 20)
    window.setGeometry(0, 0, SIZE[0], SIZE[1])
    pump(app, 20)
    set_language("en")
    window.language_selector.setCurrentIndex(window.language_selector.findData("en"))
    window.open_specialized_chat("general")
    pump(app, 30)
    print("SCREEN:", app.primaryScreen().size().width(), "x", app.primaryScreen().size().height())
    print("CTX:", window.ctx_status_label.text())
    print("MODELS:", [window.model_selector.itemText(i) for i in range(window.model_selector.count())][:4])

    window._append_bubble(DEMO, "assistant", None, auto_scroll=True)
    pump(app, 30)
    window.model_selector.showPopup()
    pump(app, 18)
    view = window.model_selector.view()
    print(grab_with_popup(app, window, view, window.model_selector, "fhd_v3_1_chat_models_and_code.png"))
    window.model_selector.hidePopup()
    pump(app, 6)
    window.engine_menu.popup(window.engine_button.mapToGlobal(window.engine_button.rect().bottomLeft()))
    pump(app, 18)
    print(grab_with_popup(app, window, window.engine_menu, window.engine_button, "fhd_v3_1b_engine_menu.png"))
    window.engine_menu.hide()
    pump(app, 6)

    window.open_specialized_chat("engineer")
    pump(app, 25)
    window._append_bubble(
        "Vou corrigir a inicializacao da instancia.\n" + DIFF_DEMO +
        "\n```bash\n$ g++ -std=c++20 main.cpp -lvulkan -o build/mark\nbuild ok, 0 warnings\n```",
        "assistant", None, auto_scroll=True,
    )
    pump(app, 25)
    print("BAR_H:", window.engineer_bar.height(), "TITLE:", window.empty_title.text())
    print(grab(app, window, "fhd_v3_2_engineer_codex_minimal.png"))

    window.open_settings()
    tabs = window.settings_widget.tab_widget
    tabs.setCurrentIndex(tabs.count() - 1)
    hub = tabs.widget(tabs.count() - 1)
    hub_tabs = hub.tabs
    hub_tabs.setCurrentIndex(1)
    wait_for(app, lambda: getattr(hub, "hf_view", None) is not None and bool(hub.hf_view._cards), 40)
    pump(app, 40)
    wait_for(app, lambda: bool(hub.hf_view._files), 30)
    print("HF_CARDS:", len(hub.hf_view._cards), "FILES:", len(hub.hf_view._files))
    print(grab(app, window, "fhd_v3_3_hf_splitview_lmstudio.png"))

    tabs.setCurrentIndex(0)
    pump(app, 20)
    print("SLIDER_MAX:", window.settings_widget.slider_ctx.max_val)
    print("RELOAD:", window.settings_widget.reload_inference_button.text())
    print(grab(app, window, "fhd_v3_5_settings_scanner_sync.png"))

    window.open_specialized_chat("general")
    pump(app, 15)
    from mark.ui.voice_panel import VoiceCallDialog

    base = window.grab()
    dialog = VoiceCallDialog(window, "Inicializacao do Vulkan validada. Compile com -lvulkan.")
    dialog.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
    dialog.setFixedSize(940, 640)
    dialog.show()
    pump(app, 25)
    print("DIALOG:", dialog.status.text(), "|", dialog.device_label.text()[:80])
    overlay = dialog.grab()
    painter = QPainter(base)
    painter.drawPixmap((base.width() - overlay.width()) // 2, (base.height() - overlay.height()) // 2, overlay)
    painter.end()
    path = OUT / "fhd_v3_4_voice_call_and_vision.png"
    base.save(str(path), "PNG")
    print(f"fhd_v3_4_voice_call_and_vision.png: {base.width()}x{base.height()} ({path.stat().st_size} bytes)")
    dialog.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
