"""Persistent settings + hotkey-string parser used by HotkeyManager.

Hotkey strings use the conventional Qt-like form: modifiers joined with '+',
ending with the key name. Examples: 'Ctrl+Alt+A', 'Ctrl+Shift+F2', 'Win+Z'.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings


# Win32 modifier flags.
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

_MOD_ALIASES = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "super": MOD_WIN,
    "meta": MOD_WIN,
}

_MOD_DISPLAY_ORDER = [
    (MOD_CONTROL, "Ctrl"),
    (MOD_ALT, "Alt"),
    (MOD_SHIFT, "Shift"),
    (MOD_WIN, "Win"),
]


def _vk_for_key(name: str) -> int:
    n = name.strip().upper()
    if len(n) == 1 and ("A" <= n <= "Z" or "0" <= n <= "9"):
        return ord(n)
    if n.startswith("F") and n[1:].isdigit():
        num = int(n[1:])
        if 1 <= num <= 24:
            return 0x70 + (num - 1)  # VK_F1 = 0x70
    specials = {
        "SPACE": 0x20, "TAB": 0x09, "ENTER": 0x0D, "RETURN": 0x0D,
        "ESC": 0x1B, "ESCAPE": 0x1B, "BACKSPACE": 0x08, "DELETE": 0x2E,
        "INSERT": 0x2D, "HOME": 0x24, "END": 0x23, "PAGEUP": 0x21,
        "PAGEDOWN": 0x22, "LEFT": 0x25, "UP": 0x26, "RIGHT": 0x27, "DOWN": 0x28,
    }
    if n in specials:
        return specials[n]
    raise ValueError(f"Unknown key name: {name!r}")


def _vk_to_display(vk: int) -> str:
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk)
    if 0x70 <= vk <= 0x87:
        return f"F{vk - 0x70 + 1}"
    rev = {
        0x20: "Space", 0x09: "Tab", 0x0D: "Enter", 0x1B: "Esc",
        0x08: "Backspace", 0x2E: "Delete", 0x2D: "Insert",
        0x24: "Home", 0x23: "End", 0x21: "PageUp", 0x22: "PageDown",
        0x25: "Left", 0x26: "Up", 0x27: "Right", 0x28: "Down",
    }
    return rev.get(vk, f"VK_{vk:#x}")


@dataclass(frozen=True)
class Hotkey:
    mods: int
    vk: int

    @classmethod
    def parse(cls, text: str) -> "Hotkey":
        parts = [p.strip() for p in text.split("+") if p.strip()]
        if not parts:
            raise ValueError("Empty hotkey")
        mods = 0
        for token in parts[:-1]:
            key = token.lower()
            if key not in _MOD_ALIASES:
                raise ValueError(f"Unknown modifier: {token!r}")
            mods |= _MOD_ALIASES[key]
        if mods == 0:
            raise ValueError("Hotkey must include at least one modifier")
        vk = _vk_for_key(parts[-1])
        return cls(mods=mods | MOD_NOREPEAT, vk=vk)

    def display(self) -> str:
        out = [name for flag, name in _MOD_DISPLAY_ORDER if self.mods & flag]
        out.append(_vk_to_display(self.vk))
        return "+".join(out)


DEFAULT_HOTKEY = "Ctrl+Alt+A"


class ConfigStore:
    """Thin wrapper over QSettings — INI format, per-user."""

    def __init__(self) -> None:
        self._s = QSettings(QSettings.IniFormat, QSettings.UserScope, "TextRecog", "TextRecog")

    @property
    def hotkey_text(self) -> str:
        return str(self._s.value("hotkey", DEFAULT_HOTKEY))

    @hotkey_text.setter
    def hotkey_text(self, value: str) -> None:
        Hotkey.parse(value)  # validate
        self._s.setValue("hotkey", value)
        self._s.sync()

    @property
    def ocr_lang(self) -> str:
        return str(self._s.value("ocr/lang", "ch"))

    @property
    def ocr_use_angle_cls(self) -> bool:
        v = self._s.value("ocr/use_angle_cls", False)
        if isinstance(v, str):
            return v.lower() in ("1", "true", "yes")
        return bool(v)

    def file_path(self) -> str:
        return self._s.fileName()
