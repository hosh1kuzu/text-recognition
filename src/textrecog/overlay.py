"""Per-monitor frameless overlay used to drag-select a region.

The controller creates one overlay per monitor. A selection starts and ends
within a single monitor overlay; cross-monitor dragging is intentionally not
supported because mixed-DPI coordinate conversion is easy to get wrong.
"""
from __future__ import annotations

import ctypes
import sys
import time

from PySide6.QtCore import QObject, QPoint, QPointF, QRect, Qt, QTimer, Signal
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
from .diagnostics import log_event, log_exception


_VK_RBUTTON = 0x02
_VK_ESCAPE = 0x1B


def _async_key_down(vk: int) -> bool:
    if sys.platform != "win32":
        return False
    try:
        ctypes.windll.user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
        ctypes.windll.user32.GetAsyncKeyState.restype = ctypes.c_short
        return ctypes.windll.user32.GetAsyncKeyState(vk) < 0
    except (AttributeError, OSError):
        return False


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

    _DARK = QColor(0, 0, 0, 122)
    _BORDER = QColor(6, 182, 212, 245)

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
        self.setFocusPolicy(Qt.StrongFocus)
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
        try:
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
                font.setBold(True)
                painter.setFont(font)
                ty = rect.top() - 6
                if ty < 14:
                    ty = rect.top() + 16
                label_w = painter.fontMetrics().horizontalAdvance(label) + 18
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(17, 24, 39, 230))
                painter.drawRoundedRect(QRect(rect.left(), ty - 18, label_w, 24), 4, 4)
                painter.setPen(QPen(QColor(255, 255, 255)))
                painter.drawText(QPoint(rect.left() + 9, ty - 2), label)
            self._draw_cancel_hint(painter)
        finally:
            painter.end()

    def _draw_cancel_hint(self, painter: QPainter) -> None:
        label = "右键 / Esc 取消"
        font = painter.font()
        font.setPointSize(10)
        font.setBold(True)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        w = metrics.horizontalAdvance(label) + 28
        h = 30
        x = self.width() - w - 24
        y = 24
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(17, 24, 39, 194))
        painter.drawRoundedRect(QRect(x, y, w, h), 15, 15)
        painter.setPen(QPen(QColor(255, 255, 255)))
        painter.drawText(QPoint(x + 14, y + 20), label)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.RightButton:
            log_event("overlay", "right mouse press cancel")
            self._press = None
            self._cur = None
            self._right_cancel_pending = True
            self.grabMouse()
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
            log_event("overlay", "right mouse release cancel")
            self._right_cancel_pending = False
            self.releaseMouse()
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
        # _on_committed calls _close_windows() which already closes this window.

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        event.accept()

    def closeEvent(self, event) -> None:  # noqa: N802
        self.releaseMouse()
        self.releaseKeyboard()
        self._pixmap = QPixmap()
        super().closeEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            log_event("overlay", "escape key cancel")
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
        self._cancel_poll_skip_until = 0.0
        self._async_right_cancel_pending = False
        self._cancel_timer = QTimer(self)
        self._cancel_timer.setInterval(40)
        self._cancel_timer.timeout.connect(self._poll_cancel_inputs)

    def is_active(self) -> bool:
        return bool(self._windows)

    def debug_state(self) -> dict:
        return {
            "busy": self._busy,
            "finishing": self._finishing,
            "windows": len(self._windows),
            "has_snapshot": self._snapshot is not None,
        }

    def start_capture(self) -> None:
        log_event("overlay", "start_capture enter", **self.debug_state())
        if self._busy:
            log_event("overlay", "start_capture ignored: busy", **self.debug_state())
            return
        try:
            self._snapshot = grab_virtual_desktop()
        except Exception as exc:
            log_exception("overlay", "failed to grab desktop", exc)
            return

        self._busy = True
        self._finishing = False
        self._windows = []
        log_event(
            "overlay",
            "desktop grabbed",
            origin=(self._snapshot.origin_x, self._snapshot.origin_y),
            size=(self._snapshot.width, self._snapshot.height),
            monitors=len(self._snapshot.monitors),
        )

        for monitor in self._snapshot.monitors:
            log_event("overlay", "create selector", monitor=monitor)
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
            log_event(
                "overlay",
                "selector shown",
                screen=screen.name(),
                dpr=dpr,
                geometry=(screen.geometry().x(), screen.geometry().y(), screen.geometry().width(), screen.geometry().height()),
                windows=len(self._windows),
            )

        if not self._windows:
            self._busy = False
            self._snapshot = None
            log_event("overlay", "start_capture no windows")
            return

        for win in self._windows:
            win.activateWindow()
        self._windows[-1].setFocus(Qt.OtherFocusReason)
        self._windows[-1].grabKeyboard()
        self._cancel_poll_skip_until = time.monotonic() + 0.15
        self._async_right_cancel_pending = False
        self._cancel_timer.start()
        log_event("overlay", "start_capture ready", **self.debug_state())

    def _on_committed(self, rect: QRect, monitor: MonitorRect, dpr: float) -> None:
        log_event("overlay", "committed enter", rect=(rect.x(), rect.y(), rect.width(), rect.height()), monitor=monitor, dpr=dpr, **self.debug_state())
        if self._finishing:
            log_event("overlay", "committed ignored: finishing", **self.debug_state())
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
        self._busy = False
        self._finishing = False
        try:
            log_event("overlay", "emit regionSelected", x=vx, y=vy, w=phys_w, h=phys_h)
            self.regionSelected.emit(int(vx), int(vy), int(phys_w), int(phys_h))
        finally:
            self._close_windows()

    def _on_cancelled(self) -> None:
        log_event("overlay", "cancelled enter", **self.debug_state())
        if self._finishing:
            log_event("overlay", "cancelled ignored: finishing", **self.debug_state())
            return
        self._finishing = True
        self.cancelled.emit()
        self._close_windows(clear_snapshot=True)

    def _poll_cancel_inputs(self) -> None:
        if not self._busy or self._finishing or not self._windows:
            self._cancel_timer.stop()
            return
        if _async_key_down(_VK_ESCAPE):
            log_event("overlay", "async escape cancel", **self.debug_state())
            self._on_cancelled()
            return
        if time.monotonic() < self._cancel_poll_skip_until:
            return
        right_down = _async_key_down(_VK_RBUTTON)
        if right_down:
            if not self._async_right_cancel_pending:
                self._async_right_cancel_pending = True
                log_event("overlay", "async right button down", **self.debug_state())
            return
        if self._async_right_cancel_pending:
            self._async_right_cancel_pending = False
            log_event("overlay", "async right button release cancel", **self.debug_state())
            self._on_cancelled()

    def _on_destroyed(self, closed_window: OverlaySelector) -> None:
        self._windows = [win for win in self._windows if win is not closed_window]
        log_event("overlay", "window destroyed", windows=len(self._windows), busy=self._busy, finishing=self._finishing)
        if not self._windows:
            self._busy = False
            self._finishing = False

    def _close_windows(self, *, clear_snapshot: bool = False) -> None:
        log_event("overlay", "close_windows", count=len(self._windows), clear_snapshot=clear_snapshot, **self.debug_state())
        self._cancel_timer.stop()
        self._async_right_cancel_pending = False
        windows = list(self._windows)
        self._windows = []
        self._busy = False
        self._finishing = False
        if clear_snapshot:
            self._snapshot = None
        for win in windows:
            try:
                win.close()
            except RuntimeError:
                log_event("overlay", "close_windows skipped deleted window")
                pass
        log_event("overlay", "close_windows done", **self.debug_state())

    def snapshot(self) -> VirtualDesktop | None:
        return self._snapshot

    def release_snapshot(self) -> None:
        log_event("overlay", "release_snapshot", had_snapshot=self._snapshot is not None)
        self._snapshot = None
