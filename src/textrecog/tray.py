"""System tray icon with Capture / Settings / Quit menu."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .ui import make_app_icon, windows_uses_dark_apps


def _tray_menu_stylesheet() -> str:
    if windows_uses_dark_apps():
        return """
        QMenu {
            background: #1F242D;
            border: 1px solid #343B49;
            border-radius: 8px;
            color: #F8FAFC;
            padding: 6px;
            font-family: "Microsoft YaHei UI", "Segoe UI";
            font-size: 13px;
        }
        QMenu::item {
            color: #F8FAFC;
            padding: 7px 28px 7px 12px;
            border-radius: 6px;
        }
        QMenu::item:disabled {
            color: #667085;
        }
        QMenu::item:selected {
            background: #2F3A4B;
            color: #FFFFFF;
        }
        QMenu::separator {
            height: 1px;
            background: #343B49;
            margin: 6px 4px;
        }
        """
    return """
    QMenu {
        background: #FFFFFF;
        border: 1px solid #E1E5EB;
        border-radius: 8px;
        color: #101828;
        padding: 6px;
        font-family: "Microsoft YaHei UI", "Segoe UI";
        font-size: 13px;
    }
    QMenu::item {
        color: #101828;
        padding: 7px 28px 7px 12px;
        border-radius: 6px;
    }
    QMenu::item:disabled {
        color: #98A2B3;
    }
    QMenu::item:selected {
        background: #EFF6FF;
        color: #101828;
    }
    QMenu::separator {
        height: 1px;
        background: #E1E5EB;
        margin: 6px 4px;
    }
    """


class TrayIcon(QObject):
    captureRequested = Signal()
    settingsRequested = Signal()
    quitRequested = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._icon = make_app_icon()
        self._tray = QSystemTrayIcon(self._icon, parent)
        self._tray.setToolTip("TextRecog - 正在加载 OCR")

        menu = QMenu()
        menu.setStyleSheet(_tray_menu_stylesheet())
        capture_action = QAction("识别截图", menu)
        capture_action.triggered.connect(self.captureRequested.emit)
        settings_action = QAction("设置…", menu)
        settings_action.triggered.connect(self.settingsRequested.emit)
        quit_action = QAction("退出", menu)
        quit_action.triggered.connect(self.quitRequested.emit)

        menu.addAction(capture_action)
        menu.addSeparator()
        menu.addAction(settings_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_activated)
        self._menu = menu  # keep alive

    def show(self) -> None:
        self._tray.show()

    def hide(self) -> None:
        self._tray.hide()

    def set_tooltip(self, text: str) -> None:
        self._tray.setToolTip(text)

    def show_message(self, title: str, message: str, *, warning: bool = False) -> None:
        icon = QSystemTrayIcon.Warning if warning else QSystemTrayIcon.Information
        self._tray.showMessage(title, message, icon, 4000)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.DoubleClick:
            self.captureRequested.emit()
