"""Hotkey rebinding dialog. Validates by attempting RegisterHotKey."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QCheckBox,
    QKeySequenceEdit,
    QLabel,
    QMessageBox,
)
from PySide6.QtGui import QKeySequence

from .config import Hotkey, MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN
from .hotkey import HotkeyError, HotkeyManager
from .ui import make_app_icon, settings_dialog_stylesheet


def _qkey_to_hotkey(seq: QKeySequence) -> Hotkey:
    """Convert a single-chord QKeySequence to a Hotkey."""
    if seq.isEmpty():
        raise ValueError("Empty key sequence")
    combo = seq[0]
    # Qt6: QKeyCombination
    qt_mods = combo.keyboardModifiers() if hasattr(combo, "keyboardModifiers") else Qt.KeyboardModifiers(int(combo) & 0xFFFF0000)
    qt_key = combo.key() if hasattr(combo, "key") else (int(combo) & 0x0000FFFF)

    mods = 0
    if qt_mods & Qt.ControlModifier:
        mods |= MOD_CONTROL
    if qt_mods & Qt.AltModifier:
        mods |= MOD_ALT
    if qt_mods & Qt.ShiftModifier:
        mods |= MOD_SHIFT
    if qt_mods & Qt.MetaModifier:
        mods |= MOD_WIN
    if mods == 0:
        raise ValueError("Hotkey must include at least one modifier (Ctrl/Alt/Shift/Win)")

    if Qt.Key_A <= qt_key <= Qt.Key_Z:
        vk = ord("A") + (qt_key - Qt.Key_A)
    elif Qt.Key_0 <= qt_key <= Qt.Key_9:
        vk = ord("0") + (qt_key - Qt.Key_0)
    elif Qt.Key_F1 <= qt_key <= Qt.Key_F24:
        vk = 0x70 + (qt_key - Qt.Key_F1)
    else:
        raise ValueError("Only A-Z, 0-9, and F1-F24 keys are supported")

    from .config import MOD_NOREPEAT
    return Hotkey(mods=mods | MOD_NOREPEAT, vk=vk)


class SettingsDialog(QDialog):
    def __init__(self, current_text: str, start_on_login: bool, manager: HotkeyManager, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setWindowIcon(make_app_icon())
        self.setStyleSheet(settings_dialog_stylesheet())
        self._manager = manager
        self._result_text: str | None = None

        self._key_edit = QKeySequenceEdit()
        self._key_edit.setKeySequence(QKeySequence(current_text.replace("Win", "Meta")))
        self._start_on_login = QCheckBox("开机启动")
        self._start_on_login.setChecked(start_on_login)

        info = QLabel("快捷键需要包含至少一个修饰键（Ctrl/Alt/Shift/Win），"
                      "并以 A-Z、0-9 或 F1-F24 中的一个键结束。")
        info.setObjectName("helpLabel")
        info.setWordWrap(True)

        form = QFormLayout()
        form.setContentsMargins(20, 20, 20, 16)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(14)
        form.addRow("全局快捷键：", self._key_edit)
        form.addRow("", self._start_on_login)
        form.addRow(info)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        form.addRow(buttons)
        self.setLayout(form)
        self.resize(440, 220)

    def hotkey_text(self) -> str | None:
        return self._result_text

    def start_on_login(self) -> bool:
        return self._start_on_login.isChecked()

    def _on_accept(self) -> None:
        seq = self._key_edit.keySequence()
        try:
            hk = _qkey_to_hotkey(seq)
        except ValueError as exc:
            QMessageBox.warning(self, "无效快捷键", str(exc))
            return

        # Try to register: temporarily unregister current, attempt new, restore on failure.
        previous = self._manager.current()
        self._manager.unregister()
        try:
            self._manager.register(hk)
        except HotkeyError as exc:
            QMessageBox.warning(self, "无法注册快捷键", str(exc))
            if previous is not None:
                try:
                    self._manager.register(previous)
                except HotkeyError:
                    pass
            return

        self._result_text = hk.display()
        self.accept()
