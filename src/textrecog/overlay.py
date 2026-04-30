"""Per-monitor frameless overlay used to drag-select a region.

For v1 we cover a single monitor (the one the cursor is on at the moment of
the hotkey press). This sidesteps multi-DPI virtual-desktop coordinate hell
without losing much practical capability — users naturally move their cursor
to the target screen before invoking. Cross-monitor drag is a future extension.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QPoint, QPointF, QRect, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QScreen,
)
from PySide6.QtWidgets import QWidget

from .capture import MonitorRect, VirtualDesktop, grab_virtual_desktop


def _match_qscreen(target: MonitorRect) -> QScreen:
    """Best-effort match of an mss MonitorRect to a Qt QScreen.

    Scores each screen by physical-size match plus physical-origin proximity.
    Origin comparison handles dual identical-size monitors that size-only
    matching would alias. Falls back to the primary screen.
    """
    best: tuple[float, QScreen] | None = None
    for s in QGuiApplication.screens():
        dpr = s.devicePixelRatio()
        g = s.geometry()
        phys_w = round(g.width() * dpr)
        phys_h = round(g.height() * dpr)
        # Approximate physical origin: assumes uniform DPR or monitors arranged
        # without DPR boundaries on this axis. Imperfect on truly mixed setups
        # but a good heuristic.
        phys_l = round(g.left() * dpr)
        phys_t = round(g.top() * dpr)
        size_penalty = abs(phys_w - target.width) + abs(phys_h - target.height)
        origin_penalty = abs(phys_l - target.left) + abs(phys_t - target.top)
        score = size_penalty * 1000 + origin_penalty
        if best is None or score < best[0]:
            best = (score, s)
    if best is None:
        return QGuiApplication.primaryScreen()
    return best[1]


def _bgr_to_qimage(bgr) -> QImage:
    h, w, _ = bgr.shape
    # BGR888 expects bytes-per-line = w*3. Pass the buffer directly; copy to
    # detach from the numpy array's lifetime.
    img = QImage(bgr.data, w, h, w * 3, QImage.Format_BGR888)
    return img.copy()


class OverlaySelector(QWidget):
    """A fullscreen-on-one-monitor selection window."""

    selectionChanged = Signal(QRect)  # logical widget coords
    selectionCommitted = Signal(QRect)  # logical widget coords
    cancelled = Signal()

    _DARK = QColor(0, 0, 0, 110)
    _BORDER = QColor(0, 174, 255, 230)

    def __init__(self, screen: QScreen, monitor: MonitorRect, slice_pixmap: QPixmap) -> None:
        super().__init__(parent=None)
        self._monitor = monitor
        self._pixmap = slice_pixmap
        self.setScreen(screen)
        self.setGeometry(screen.geometry())
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)
        self._press: QPointF | None = None
        self._cur: QPointF | None = None
        self._right_cancel_pending = False

    def _selection_rect(self) -> QRect | None:
        if self._press is None or self._cur is None:
            return None
        x1, y1 = self._press.x(), self._press.y()
        x2, y2 = self._cur.x(), self._cur.y()
        l = round(min(x1, x2))
        t = round(min(y1, y2))
        r = round(max(x1, x2))
        b = round(max(y1, y2))
        return QRect(l, t, r - l, b - t)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._pixmap)

        rect = self._selection_rect()
        if rect is None or rect.isEmpty():
            painter.fillRect(self.rect(), self._DARK)
        else:
            full = self.rect()
            # Darken the four bands around the selection.
            top = QRect(full.left(), full.top(), full.width(), max(0, rect.top() - full.top()))
            bottom = QRect(full.left(), rect.bottom() + 1, full.width(), max(0, full.bottom() - rect.bottom()))
            left = QRect(full.left(), rect.top(), max(0, rect.left() - full.left()), rect.height() + 1)
            right = QRect(rect.right() + 1, rect.top(), max(0, full.right() - rect.right()), rect.height() + 1)
            for r in (top, bottom, left, right):
                if r.width() > 0 and r.height() > 0:
                    painter.fillRect(r, self._DARK)
            pen = QPen(self._BORDER)
            pen.setWidth(2)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawRect(rect)
            label = f"{rect.width()} × {rect.height()}"
            painter.setPen(QPen(QColor(255, 255, 255)))
            font = painter.font()
            font.setPointSize(10)
            painter.setFont(font)
            ty = rect.top() - 6
            if ty < 14:
                ty = rect.top() + 16
            painter.fillRect(QRect(rect.left(), ty - 14, painter.fontMetrics().horizontalAdvance(label) + 8, 18), QColor(0, 0, 0, 160))
            painter.drawText(QPoint(rect.left() + 4, ty), label)
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.RightButton:
            self._press = None
            self._cur = None
            self._right_cancel_pending = True
            event.accept()
            return
        if event.button() != Qt.LeftButton:
            return
        event.accept()
        self._press = event.position()
        self._cur = event.position()
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._right_cancel_pending:
            event.accept()
            return
        if self._press is None:
            return
        event.accept()
        self._cur = event.position()
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.RightButton and self._right_cancel_pending:
            self._right_cancel_pending = False
            event.accept()
            self.cancelled.emit()
            self.close()
            return
        if event.button() != Qt.LeftButton or self._press is None:
            return
        event.accept()
        rect = self._selection_rect()
        self._press = None
        self._cur = None
        if rect is None or rect.width() < 4 or rect.height() < 4:
            self.cancelled.emit()
            self.close()
            return
        self.selectionCommitted.emit(rect)
        self.close()

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        event.accept()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._pixmap = QPixmap()
        super().closeEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.cancelled.emit()
            self.close()
            return
        super().keyPressEvent(event)


class OverlayController(QObject):
    regionSelected = Signal(int, int, int, int)  # virtual physical x, y, w, h
    cancelled = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._snapshot: VirtualDesktop | None = None
        self._windows: list[OverlaySelector] = []
        self._busy = False
        self._finishing = False

    def is_active(self) -> bool:
        return bool(self._windows)

    def start_capture(self) -> None:
        if self._busy:
            return
        try:
            self._snapshot = grab_virtual_desktop()
        except Exception as exc:
            print(f"[overlay] failed to grab desktop: {exc}")
            return

        self._busy = True
        self._finishing = False
        self._windows = []

        for monitor in self._snapshot.monitors:
            slice_bgr = self._snapshot.crop(monitor.left, monitor.top, monitor.width, monitor.height)
            qimg = _bgr_to_qimage(slice_bgr)
            screen = _match_qscreen(monitor)
            dpr = screen.devicePixelRatio()
            pix = QPixmap.fromImage(qimg)
            pix.setDevicePixelRatio(dpr)

            win = OverlaySelector(screen, monitor, pix)
            win.selectionCommitted.connect(
                lambda rect, selected_monitor=monitor, selected_dpr=dpr: self._on_committed(
                    rect,
                    selected_monitor,
                    selected_dpr,
                )
            )
            win.cancelled.connect(self._on_cancelled)
            win.destroyed.connect(lambda *_args, closed_window=win: self._on_destroyed(closed_window))
            win.show()
            win.raise_()
            self._windows.append(win)

        if not self._windows:
            self._busy = False
            self._snapshot = None
            return

        for win in self._windows:
            win.activateWindow()
        self._windows[-1].setFocus(Qt.OtherFocusReason)

    def _on_committed(self, rect: QRect, monitor: MonitorRect, dpr: float) -> None:
        if self._finishing:
            return
        self._finishing = True
        # rect is in widget-logical coords (DIPs). Convert to physical px on
        # this monitor, then offset by the monitor's virtual-desktop origin.
        phys_x = round(rect.x() * dpr)
        phys_y = round(rect.y() * dpr)
        phys_w = round(rect.width() * dpr)
        phys_h = round(rect.height() * dpr)
        vx = monitor.left + phys_x
        vy = monitor.top + phys_y
        self.regionSelected.emit(int(vx), int(vy), int(phys_w), int(phys_h))
        self._close_windows()

    def _on_cancelled(self) -> None:
        if self._finishing:
            return
        self._finishing = True
        self._snapshot = None
        self.cancelled.emit()
        self._close_windows()

    def _on_destroyed(self, closed_window: OverlaySelector) -> None:
        self._windows = [win for win in self._windows if win is not closed_window]
        if not self._windows:
            self._busy = False
            self._finishing = False
            self._snapshot = None

    def _close_windows(self) -> None:
        for win in list(self._windows):
            win.close()

    def snapshot(self) -> VirtualDesktop | None:
        return self._snapshot

    def release_snapshot(self) -> None:
        self._snapshot = None
