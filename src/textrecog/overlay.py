"""Per-monitor frameless overlay used to drag-select a region.

For v1 we cover a single monitor (the one the cursor is on at the moment of
the hotkey press). This sidesteps multi-DPI virtual-desktop coordinate hell
without losing much practical capability — users naturally move their cursor
to the target screen before invoking. Cross-monitor drag is a future extension.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

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


def _get_cursor_physical_pos() -> tuple[int, int]:
    pt = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return int(pt.x), int(pt.y)


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
        if event.button() != Qt.LeftButton:
            return
        self._press = event.position()
        self._cur = event.position()
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._press is None:
            return
        self._cur = event.position()
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton or self._press is None:
            return
        rect = self._selection_rect()
        self._press = None
        self._cur = None
        if rect is None or rect.width() < 4 or rect.height() < 4:
            self.cancelled.emit()
            self.close()
            return
        self.selectionCommitted.emit(rect)
        self.close()

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
        self._window: OverlaySelector | None = None
        self._monitor: MonitorRect | None = None
        self._dpr: float = 1.0
        self._busy = False

    def is_active(self) -> bool:
        return self._window is not None

    def start_capture(self) -> None:
        if self._busy:
            return
        try:
            self._snapshot = grab_virtual_desktop()
        except Exception as exc:
            print(f"[overlay] failed to grab desktop: {exc}")
            return

        cx, cy = _get_cursor_physical_pos()
        target = next(
            (m for m in self._snapshot.monitors
             if m.left <= cx < m.right and m.top <= cy < m.bottom),
            None,
        )
        if target is None:
            target = self._snapshot.monitors[0]

        slice_bgr = self._snapshot.crop(target.left, target.top, target.width, target.height)
        qimg = _bgr_to_qimage(slice_bgr)
        screen = _match_qscreen(target)
        dpr = screen.devicePixelRatio()
        pix = QPixmap.fromImage(qimg)
        pix.setDevicePixelRatio(dpr)

        self._monitor = target
        self._dpr = dpr
        self._busy = True
        win = OverlaySelector(screen, target, pix)
        win.selectionCommitted.connect(self._on_committed)
        win.cancelled.connect(self._on_cancelled)
        win.destroyed.connect(self._on_destroyed)
        win.show()
        win.activateWindow()
        win.raise_()
        win.setFocus(Qt.OtherFocusReason)
        self._window = win

    def _on_committed(self, rect: QRect) -> None:
        if self._monitor is None:
            return
        # rect is in widget-logical coords (DIPs). Convert to physical px on
        # this monitor, then offset by the monitor's virtual-desktop origin.
        phys_x = round(rect.x() * self._dpr)
        phys_y = round(rect.y() * self._dpr)
        phys_w = round(rect.width() * self._dpr)
        phys_h = round(rect.height() * self._dpr)
        vx = self._monitor.left + phys_x
        vy = self._monitor.top + phys_y
        self.regionSelected.emit(int(vx), int(vy), int(phys_w), int(phys_h))

    def _on_cancelled(self) -> None:
        self.cancelled.emit()

    def _on_destroyed(self, *_args) -> None:
        self._window = None
        self._monitor = None
        self._busy = False

    def snapshot(self) -> VirtualDesktop | None:
        return self._snapshot
