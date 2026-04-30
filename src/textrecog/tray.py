"""System tray icon with Capture / Settings / Quit menu."""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


def _make_icon() -> QIcon:
    pix = QPixmap(64, 64)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(0, 122, 204))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(4, 4, 56, 56, 12, 12)
    p.setPen(QColor("white"))
    f = QFont()
    f.setPointSize(28)
    f.setBold(True)
    p.setFont(f)
    p.drawText(pix.rect(), Qt.AlignCenter, "T")
    p.end()
    return QIcon(pix)


class TrayIcon(QObject):
    captureRequested = Signal()
    settingsRequested = Signal()
    quitRequested = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._icon = _make_icon()
        self._tray = QSystemTrayIcon(self._icon, parent)
        self._tray.setToolTip("TextRecog - loading OCR model")

        menu = QMenu()
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
