"""Global hotkey via Win32 RegisterHotKey + Qt native event filter.

See plan §3.1 for why this beats pynput/keyboard. The chord is consumed by the
OS so it does not leak to the foreground app, no admin needed, and WM_HOTKEY is
delivered to the GUI thread message queue — no cross-thread marshaling.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

from .config import Hotkey

WM_HOTKEY = 0x0312
_HOTKEY_ID = 1

_user32 = ctypes.windll.user32
_user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
_user32.RegisterHotKey.restype = wintypes.BOOL
_user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.UnregisterHotKey.restype = wintypes.BOOL


class HotkeyError(RuntimeError):
    pass


class HotkeyManager(QAbstractNativeEventFilter, QObject):
    triggered = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        QAbstractNativeEventFilter.__init__(self)
        QObject.__init__(self, parent)
        self._registered: Hotkey | None = None

    def is_registered(self) -> bool:
        return self._registered is not None

    def current(self) -> Hotkey | None:
        return self._registered

    def register(self, hotkey: Hotkey) -> None:
        if self._registered is not None:
            self.unregister()
        ok = _user32.RegisterHotKey(None, _HOTKEY_ID, hotkey.mods, hotkey.vk)
        if not ok:
            raise HotkeyError(
                f"Failed to register hotkey {hotkey.display()!r} — likely already in use"
            )
        self._registered = hotkey

    def unregister(self) -> None:
        if self._registered is None:
            return
        _user32.UnregisterHotKey(None, _HOTKEY_ID)
        self._registered = None

    def nativeEventFilter(self, eventType, message):  # noqa: N802 (Qt API)
        if eventType == b"windows_generic_MSG" or eventType == "windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == _HOTKEY_ID:
                self.triggered.emit()
        return False, 0
