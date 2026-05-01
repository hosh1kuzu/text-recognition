"""Shared visual helpers for TextRecog's modern flat UI."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap


PRIMARY = "#2563EB"
ACCENT = "#06B6D4"
DARK_PANEL = "#181D27"
DARK_SURFACE = "#232936"
DARK_LINE = "#303747"
TEXT_ON_DARK = "#FFFFFF"
TEXT_MUTED_DARK = "#AAB4C4"


def windows_uses_dark_apps() -> bool:
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return int(value) == 0
    except (ImportError, OSError):
        return False


def make_app_icon() -> QIcon:
    """Create the flat scan-text app icon used by tray and windows."""
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(_make_icon_pixmap(size))
    return icon


def _make_icon_pixmap(size: int) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)

    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)

    radius = max(3, round(size * 0.18))
    p.setBrush(QColor(PRIMARY))
    p.drawRoundedRect(0, 0, size, size, radius, radius)

    p.setBrush(QColor(TEXT_ON_DARK))
    line = max(2, round(size * 0.085))
    pad = round(size * 0.22)
    length = round(size * 0.25)
    cap = max(1, line // 2)

    p.drawRoundedRect(pad, pad, length, line, cap, cap)
    p.drawRoundedRect(pad, pad, line, length, cap, cap)
    p.drawRoundedRect(size - pad - length, size - pad - line, length, line, cap, cap)
    p.drawRoundedRect(size - pad - line, size - pad - length, line, length, cap, cap)

    p.drawRoundedRect(
        round(size * 0.36),
        round(size * 0.42),
        round(size * 0.32),
        line,
        cap,
        cap,
    )
    p.drawRoundedRect(
        round(size * 0.36),
        round(size * 0.56),
        round(size * 0.22),
        line,
        cap,
        cap,
    )
    p.end()
    return pix


def result_window_stylesheet() -> str:
    return f"""
    QWidget {{
        background: {DARK_PANEL};
        color: {TEXT_ON_DARK};
        font-family: "Microsoft YaHei UI", "Segoe UI";
        font-size: 14px;
    }}
    QPlainTextEdit {{
        background: {DARK_SURFACE};
        border: 1px solid {DARK_LINE};
        border-radius: 6px;
        color: {TEXT_ON_DARK};
        selection-background-color: {PRIMARY};
        padding: 14px;
        font-size: 18px;
    }}
    QPlainTextEdit:focus {{
        border: 1px solid {ACCENT};
    }}
    QLabel#statusLabel {{
        color: {TEXT_MUTED_DARK};
        font-size: 14px;
    }}
    QLabel#statusDot {{
        border-radius: 4px;
        min-width: 8px;
        max-width: 8px;
        min-height: 8px;
        max-height: 8px;
    }}
    QPushButton {{
        background: {DARK_SURFACE};
        border: 1px solid {DARK_LINE};
        border-radius: 6px;
        color: {TEXT_ON_DARK};
        font-size: 14px;
        min-height: 34px;
        padding: 0 16px;
    }}
    QPushButton:hover {{
        background: #2D3443;
    }}
    QPushButton:pressed {{
        background: #151A23;
    }}
    """


def settings_dialog_stylesheet() -> str:
    if windows_uses_dark_apps():
        return f"""
        QDialog {{
            background: #181D27;
            color: #F8FAFC;
            font-family: "Microsoft YaHei UI", "Segoe UI";
            font-size: 14px;
        }}
        QLabel {{
            color: #F8FAFC;
        }}
        QLabel#helpLabel {{
            color: #AAB4C4;
        }}
        QCheckBox {{
            color: #F8FAFC;
            spacing: 8px;
        }}
        QKeySequenceEdit {{
            background: #232936;
            border: 1px solid #3A4352;
            border-radius: 6px;
            color: #F8FAFC;
            selection-background-color: {PRIMARY};
            padding: 8px 10px;
            min-height: 26px;
        }}
        QKeySequenceEdit:focus {{
            border: 1px solid {ACCENT};
        }}
        QPushButton {{
            background: #232936;
            border: 1px solid #3A4352;
            border-radius: 6px;
            color: #F8FAFC;
            min-width: 72px;
            min-height: 32px;
            padding: 0 12px;
        }}
        QPushButton:hover {{
            background: #2D3443;
        }}
        QPushButton:pressed {{
            background: #151A23;
        }}
        QPushButton:default {{
            background: {PRIMARY};
            border: 1px solid {PRIMARY};
            color: white;
        }}
        QPushButton:disabled {{
            color: #667085;
            border-color: #303747;
        }}
        """
    return f"""
    QDialog {{
        background: #F7F8FA;
        color: #101828;
        font-family: "Microsoft YaHei UI", "Segoe UI";
        font-size: 14px;
    }}
    QLabel#helpLabel {{
        color: #667085;
    }}
    QCheckBox {{
        color: #101828;
        spacing: 8px;
    }}
    QKeySequenceEdit {{
        background: #FFFFFF;
        border: 1px solid #D0D5DD;
        border-radius: 6px;
        color: #101828;
        padding: 8px 10px;
        min-height: 26px;
    }}
    QKeySequenceEdit:focus {{
        border: 1px solid {PRIMARY};
    }}
    QPushButton {{
        background: #FFFFFF;
        border: 1px solid #D0D5DD;
        border-radius: 6px;
        color: #101828;
        min-width: 72px;
        min-height: 32px;
        padding: 0 12px;
    }}
    QPushButton:hover {{
        background: #F3F5F8;
    }}
    QPushButton:default {{
        background: {PRIMARY};
        border: 1px solid {PRIMARY};
        color: white;
    }}
    """
