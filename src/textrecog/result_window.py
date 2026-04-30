"""Small popup that displays recognized text. Selectable, editable, copyable."""
from __future__ import annotations

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


class ResultWindow(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("识别结果")
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint | Qt.WindowCloseButtonHint)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.resize(560, 320)

        self._status = QLabel("识别中…")
        self._status.setStyleSheet("color: #666;")

        self._editor = QPlainTextEdit()
        self._editor.setReadOnly(False)
        self._editor.setPlaceholderText("（未识别到文字）")
        self._editor.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        font = self._editor.font()
        font.setPointSize(11)
        self._editor.setFont(font)

        self._copy_btn = QPushButton("复制全部")
        self._copy_btn.clicked.connect(self._copy_all)
        self._close_btn = QPushButton("关闭")
        self._close_btn.clicked.connect(self.close)

        button_row = QHBoxLayout()
        button_row.addWidget(self._status, 1)
        button_row.addWidget(self._copy_btn)
        button_row.addWidget(self._close_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(self._editor, 1)
        layout.addLayout(button_row)

    def show_pending(self, anchor_screen_phys: tuple[int, int] | None = None) -> None:
        self._status.setText("识别中…")
        self._editor.clear()
        self._position_near(anchor_screen_phys)
        self.show()
        self.raise_()
        self.activateWindow()

    def set_text(self, text: str) -> None:
        self._editor.setPlainText(text)
        n = len(text)
        chars = "字符" if n != 1 else "字符"
        self._status.setText(f"完成 · {n} {chars}")
        self._editor.setFocus()
        # Select-all so user can immediately copy.
        cursor = self._editor.textCursor()
        cursor.select(cursor.SelectionType.Document)
        self._editor.setTextCursor(cursor)

    def set_error(self, msg: str) -> None:
        self._status.setText(f"错误：{msg}")
        self._editor.setPlainText("")

    def set_status(self, msg: str) -> None:
        self._status.setText(msg)

    def _copy_all(self) -> None:
        text = self._editor.toPlainText()
        QApplication.clipboard().setText(text)
        self._status.setText(f"已复制 · {len(text)} 字符")

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
                return

    def _clamp_to_screen(self, screen) -> None:
        g = screen.availableGeometry()
        x = max(g.left(), min(g.right() - self.width(), self.x()))
        y = max(g.top(), min(g.bottom() - self.height(), self.y()))
        self.move(x, y)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)
