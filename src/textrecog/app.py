"""QApplication wiring. Owns all singletons and connects their signals."""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt, qInstallMessageHandler
from PySide6.QtWidgets import QApplication, QMessageBox

from .config import ConfigStore, Hotkey
from .diagnostics import install_excepthook, log_event, log_path, setup_logging
from .hotkey import HotkeyError, HotkeyManager
from .ocr import OcrService
from .overlay import OverlayController
from .result_window import ResultWindow
from .settings_dialog import SettingsDialog
from .startup import set_startup_enabled, startup_enabled
from .tray import TrayIcon
from .ui import make_app_icon


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
        self.hotkey_mgr.triggered.connect(lambda: self._request_capture("hotkey"))
        self.tray.captureRequested.connect(lambda: self._request_capture("tray"))
        self.tray.settingsRequested.connect(self._open_settings)
        self.tray.quitRequested.connect(self._quit)

        self.overlay.regionSelected.connect(self._on_region_selected)
        self.overlay.cancelled.connect(lambda: None)

        self.ocr.ready.connect(self._on_ocr_ready)
        self.ocr.failed.connect(self._on_ocr_failed)
        self.ocr.resultReady.connect(self._on_ocr_result)
        self.ocr.statusChanged.connect(self.result_window.set_status)

    def start(self) -> int:
        log_event("app", "start", log_path=str(log_path()))
        self.tray.show()
        self.ocr.start()

        # Register hotkey. If conflict, surface via tray balloon.
        try:
            hk = Hotkey.parse(self.config.hotkey_text)
            self.hotkey_mgr.register(hk)
            log_event("app", "hotkey registered", hotkey=hk.display())
        except (ValueError, HotkeyError) as exc:
            log_event("app", "hotkey registration failed", error=str(exc))
            self.tray.show_message(
                "TextRecog",
                f"Hotkey is unavailable: {exc}\nPlease rebind it in Settings.",
                warning=True,
            )

        return self.qt_app.exec()

    def _on_ocr_ready(self) -> None:
        self._ocr_ready = True
        log_event("app", "ocr ready")
        self._update_ready_tooltip()

    def _on_ocr_failed(self, msg: str) -> None:
        log_event("app", "ocr failed", ready=self._ocr_ready, message=msg)
        if not self._ocr_ready:
            self.tray.set_tooltip("TextRecog - OCR 加载失败")
            self.tray.show_message("TextRecog", msg, warning=True)
        else:
            self.result_window.set_error(msg)

    def _on_region_selected(self, vx: int, vy: int, vw: int, vh: int) -> None:
        log_event("app", "region selected", x=vx, y=vy, w=vw, h=vh, ocr_ready=self._ocr_ready)
        snapshot = self.overlay.snapshot()
        if snapshot is None:
            log_event("app", "region ignored: no snapshot")
            return
        if not self._ocr_ready:
            log_event("app", "region ignored: ocr not ready")
            self.overlay.release_snapshot()
            self.tray.show_message("TextRecog", "OCR 正在加载，请稍后再试。", warning=True)
            return
        try:
            img = snapshot.crop(vx, vy, vw, vh)
        finally:
            self.overlay.release_snapshot()
        if img.size == 0 or img.shape[0] < 2 or img.shape[1] < 2:
            log_event("app", "region ignored: empty crop", shape=img.shape)
            return
        self._last_anchor_phys = (vx, vy)
        log_event("app", "recognize request", shape=img.shape)
        self.result_window.show_pending(self._last_anchor_phys)
        self.ocr.recognize(img)

    def _on_ocr_result(self, text: str) -> None:
        log_event("app", "ocr result", chars=len(text))
        self.result_window.set_text(text)

    def _request_capture(self, source: str) -> None:
        log_event("app", "capture requested", source=source, overlay=self.overlay.debug_state())
        if self.result_window.isVisible():
            log_event("app", "hide result window before capture")
            self.result_window.hide()
        self.overlay.start_capture()

    def _open_settings(self) -> None:
        log_event("app", "open settings")
        current_startup = startup_enabled()
        dlg = SettingsDialog(self.config.hotkey_text, current_startup, self.hotkey_mgr)
        dlg.setWindowModality(Qt.ApplicationModal)
        if dlg.exec() == SettingsDialog.Accepted:
            new_text = dlg.hotkey_text()
            if new_text:
                self.config.hotkey_text = new_text
                if self._ocr_ready:
                    self._update_ready_tooltip()
            new_startup = dlg.start_on_login()
            if new_startup != current_startup:
                try:
                    set_startup_enabled(new_startup)
                    log_event("app", "startup setting changed", enabled=new_startup)
                except OSError as exc:
                    log_event("app", "startup setting failed", enabled=new_startup, error=str(exc))
                    self.tray.show_message("TextRecog", f"无法保存开机启动设置：{exc}", warning=True)

    def _quit(self) -> None:
        log_event("app", "quit requested")
        self.hotkey_mgr.unregister()
        self.ocr.stop()
        self.tray.hide()
        self.qt_app.quit()

    def _update_ready_tooltip(self) -> None:
        cur = self.hotkey_mgr.current()
        suffix = f" ({cur.display()})" if cur is not None else ""
        self.tray.set_tooltip(f"TextRecog - 就绪{suffix}".strip())


def main() -> int:
    setup_logging()
    install_excepthook()

    def qt_message_handler(mode, context, message) -> None:
        log_event(
            "qt",
            "message",
            mode=str(mode),
            file=getattr(context, "file", None),
            line=getattr(context, "line", None),
            function=getattr(context, "function", None),
            text=message,
        )

    qInstallMessageHandler(qt_message_handler)

    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName("TextRecog")
    qt_app.setOrganizationName("TextRecog")

    if not QApplication.instance().platformName().lower().startswith("windows"):
        QMessageBox.critical(None, "TextRecog", "This tool only runs on Windows.")
        return 1

    qt_app.setWindowIcon(make_app_icon())
    app = TextRecogApp(qt_app)
    return app.start()
