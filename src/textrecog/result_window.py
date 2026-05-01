"""Small popup that displays recognized text. Selectable, editable, copyable."""
from __future__ import annotations

import ctypes

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .diagnostics import log_event
from .ui import ACCENT, make_app_icon, result_window_stylesheet


_HWND_TOPMOST = -1
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_SHOWWINDOW = 0x0040


def _force_topmost(hwnd: int) -> None:
    ctypes.windll.user32.SetWindowPos(
        ctypes.c_void_p(hwnd),
        ctypes.c_void_p(_HWND_TOPMOST),
        0,
        0,
        0,
        0,
        _SWP_NOMOVE | _SWP_NOSIZE | _SWP_SHOWWINDOW,
    )


class ResultWindow(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("识别结果")
        self.setWindowIcon(make_app_icon())
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint | Qt.WindowCloseButtonHint)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.resize(620, 360)
        self.setMinimumSize(520, 300)
        self.setStyleSheet(result_window_stylesheet())

        self._status = QLabel("识别中…")
        self._status.setObjectName("statusLabel")
        self._status_dot = QLabel()
        self._status_dot.setObjectName("statusDot")
        self._set_status_dot(ACCENT)

        self._editor = QPlainTextEdit()
        self._editor.setReadOnly(False)
        self._editor.setPlaceholderText("（未识别到文字）")
        self._editor.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        font = self._editor.font()
        font.setPointSize(13)
        self._editor.setFont(font)

        self._copy_btn = QPushButton("复制全部")
        self._copy_btn.setFixedWidth(108)
        self._copy_btn.clicked.connect(self._copy_all)
        self._close_btn = QPushButton("关闭")
        self._close_btn.setFixedWidth(88)
        self._close_btn.clicked.connect(self.close)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)
        button_row.addWidget(self._status_dot)
        button_row.addWidget(self._status, 1)
        button_row.addWidget(self._copy_btn)
        button_row.addWidget(self._close_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 14)
        layout.setSpacing(12)
        layout.addWidget(self._editor, 1)
        layout.addLayout(button_row)

    def show_pending(self, anchor_screen_phys: tuple[int, int] | None = None) -> None:
        log_event("result_window", "show pending", anchor=anchor_screen_phys, visible=self.isVisible())
        self._status.setText("识别中…")
        self._set_status_dot(ACCENT)
        self._editor.clear()
        self._position_near(anchor_screen_phys)
        self._show_on_top()

    def set_text(self, text: str) -> None:
        log_event("result_window", "set text", chars=len(text), visible=self.isVisible(), pos=(self.x(), self.y()))
        self._editor.setPlainText(text)
        n = len(text)
        chars = "字符" if n != 1 else "字符"
        self._status.setText(f"完成 · {n} {chars}")
        self._set_status_dot("#12B76A" if text else "#98A2B3")
        self._editor.setFocus()
        # Select-all so user can immediately copy.
        cursor = self._editor.textCursor()
        cursor.select(cursor.SelectionType.Document)
        self._editor.setTextCursor(cursor)
        self._show_on_top()

    def set_error(self, msg: str) -> None:
        log_event("result_window", "set error", message=msg, visible=self.isVisible())
        self._status.setText(f"错误：{msg}")
        self._set_status_dot("#F04438")
        self._editor.setPlainText("")
        self._show_on_top()

    def set_status(self, msg: str) -> None:
        self._status.setText(msg)
        self._set_status_dot(ACCENT)

    def _copy_all(self) -> None:
        text = self._editor.toPlainText()
        QApplication.clipboard().setText(text)
        self._status.setText(f"已复制 · {len(text)} 字符")
        self._set_status_dot("#12B76A")

    def _set_status_dot(self, color: str) -> None:
        self._status_dot.setStyleSheet(
            f"background: {color}; border-radius: 4px;"
            "min-width: 8px; max-width: 8px; min-height: 8px; max-height: 8px;"
        )

    def _position_near(self, anchor_screen_phys: tuple[int, int] | None) -> None:
        # `anchor_screen_phys` is in virtual physical pixels; convert to Qt's
        # logical desktop coords by finding the screen at that physical point.
        if anchor_screen_phys is None:
            return
        ax, ay = anchor_screen_phys
        # Find a screen whose physical region contains the point.
        for s in QGuiApplication.screens():
            dpr = s.devicePixelRatio()
            g = s.geometry()
            phys_l = round(g.left() * dpr)
            phys_t = round(g.top() * dpr)
            phys_r = phys_l + round(g.width() * dpr)
            phys_b = phys_t + round(g.height() * dpr)
            if phys_l <= ax <= phys_r and phys_t <= ay <= phys_b:
                local_logical_x = (ax - phys_l) / dpr
                local_logical_y = (ay - phys_t) / dpr
                pos = QPoint(int(g.left() + local_logical_x), int(g.top() + local_logical_y))
                # Nudge slightly down-right of the anchor.
                self.move(pos + QPoint(8, 8))
                self._clamp_to_screen(s)
                log_event(
                    "result_window",
                    "positioned",
                    anchor=anchor_screen_phys,
                    screen=s.name(),
                    pos=(self.x(), self.y()),
                    size=(self.width(), self.height()),
                )
                return
        log_event("result_window", "position fallback", anchor=anchor_screen_phys)

    def _clamp_to_screen(self, screen) -> None:
        g = screen.availableGeometry()
        x = max(g.left(), min(g.right() - self.width(), self.x()))
        y = max(g.top(), min(g.bottom() - self.height(), self.y()))
        self.move(x, y)

    def _show_on_top(self) -> None:
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()
        _force_topmost(int(self.winId()))
        log_event("result_window", "shown", visible=self.isVisible(), pos=(self.x(), self.y()), size=(self.width(), self.height()))

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)
