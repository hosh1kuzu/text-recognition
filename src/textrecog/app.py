"""QApplication wiring. Owns all singletons and connects their signals."""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from .config import ConfigStore, Hotkey
from .hotkey import HotkeyError, HotkeyManager
from .ocr import OcrService
from .overlay import OverlayController
from .result_window import ResultWindow
from .settings_dialog import SettingsDialog
from .tray import TrayIcon


class TextRecogApp:
    def __init__(self, qt_app: QApplication) -> None:
        self.qt_app = qt_app
        self.qt_app.setQuitOnLastWindowClosed(False)

        self.config = ConfigStore()
        self.hotkey_mgr = HotkeyManager()
        self.qt_app.installNativeEventFilter(self.hotkey_mgr)

        self.ocr = OcrService(
            lang=self.config.ocr_lang,
            use_angle_cls=self.config.ocr_use_angle_cls,
        )
        self.overlay = OverlayController()
        self.tray = TrayIcon()
        self.result_window = ResultWindow()

        self._ocr_ready = False
        self._last_anchor_phys: tuple[int, int] | None = None

        self._wire()

    def _wire(self) -> None:
        self.hotkey_mgr.triggered.connect(self.overlay.start_capture)
        self.tray.captureRequested.connect(self.overlay.start_capture)
        self.tray.settingsRequested.connect(self._open_settings)
        self.tray.quitRequested.connect(self._quit)

        self.overlay.regionSelected.connect(self._on_region_selected)
        self.overlay.cancelled.connect(lambda: None)

        self.ocr.ready.connect(self._on_ocr_ready)
        self.ocr.failed.connect(self._on_ocr_failed)
        self.ocr.resultReady.connect(self._on_ocr_result)
        self.ocr.statusChanged.connect(self.result_window.set_status)

    def start(self) -> int:
        self.tray.show()
        self.ocr.start()

        # Register hotkey. If conflict, surface via tray balloon.
        try:
            hk = Hotkey.parse(self.config.hotkey_text)
            self.hotkey_mgr.register(hk)
        except (ValueError, HotkeyError) as exc:
            self.tray.show_message(
                "TextRecog",
                f"Hotkey is unavailable: {exc}\nPlease rebind it in Settings.",
                warning=True,
            )

        return self.qt_app.exec()

    def _on_ocr_ready(self) -> None:
        self._ocr_ready = True
        self._update_ready_tooltip()

    def _on_ocr_failed(self, msg: str) -> None:
        if not self._ocr_ready:
            self.tray.set_tooltip("TextRecog - OCR load failed")
            self.tray.show_message("TextRecog", msg, warning=True)
        else:
            self.result_window.set_error(msg)

    def _on_region_selected(self, vx: int, vy: int, vw: int, vh: int) -> None:
        snapshot = self.overlay.snapshot()
        if snapshot is None:
            return
        img = snapshot.crop(vx, vy, vw, vh)
        if img.size == 0 or img.shape[0] < 2 or img.shape[1] < 2:
            return
        if not self._ocr_ready:
            self.tray.show_message("TextRecog", "OCR is still loading. Please try again shortly.", warning=True)
            return
        self._last_anchor_phys = (vx, vy)
        self.result_window.show_pending(self._last_anchor_phys)
        self.ocr.recognize(img)

    def _on_ocr_result(self, text: str) -> None:
        self.result_window.set_text(text)

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.config.hotkey_text, self.hotkey_mgr)
        dlg.setWindowModality(Qt.ApplicationModal)
        if dlg.exec() == SettingsDialog.Accepted:
            new_text = dlg.hotkey_text()
            if new_text:
                self.config.hotkey_text = new_text
                if self._ocr_ready:
                    self._update_ready_tooltip()

    def _quit(self) -> None:
        self.hotkey_mgr.unregister()
        self.ocr.stop()
        self.tray.hide()
        self.qt_app.quit()

    def _update_ready_tooltip(self) -> None:
        cur = self.hotkey_mgr.current()
        suffix = f" ({cur.display()})" if cur is not None else ""
        self.tray.set_tooltip(f"TextRecog - ready{suffix}".strip())


def main() -> int:
    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName("TextRecog")
    qt_app.setOrganizationName("TextRecog")

    if not QApplication.instance().platformName().lower().startswith("windows"):
        QMessageBox.critical(None, "TextRecog", "This tool only runs on Windows.")
        return 1

    app = TextRecogApp(qt_app)
    return app.start()
