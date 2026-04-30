# TextRecog

Windows tray utility for screen-region OCR (Chinese + English).

Press a global hotkey, drag a rectangle, and recognized text appears in a small popup that supports selection / editing / copy.

## Features

- Global hotkey (default **Ctrl+Alt+A**), rebindable from the tray menu.
- Region selection on the monitor where the cursor sits when the hotkey fires.
- Offline OCR via [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) (`lang='ch'`, covers Simplified Chinese + English mixed).
- Result window with plain-text editor: select / edit / copy. Esc closes.
- System tray menu: 识别截图 / 设置… / 退出.

## Requirements

- Windows 10 or 11
- Python 3.11+
- ~1 GB free disk for PaddleOCR + PaddlePaddle dependencies

## Setup

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

First launch will download PaddleOCR detection / recognition / classification models (~10–20 MB) into `~/.paddleocr/`. Subsequent launches reuse the cached models.

## Run

```powershell
python main.py
```

A tray icon (blue "T") appears. Tooltip will read **加载 OCR 模型中…** for a few seconds, then **就绪 (Ctrl+Alt+A)**. Press the hotkey, drag a rectangle, read the recognized text in the popup.

## Configuration

Settings are persisted to `%APPDATA%\TextRecog\TextRecog.ini`:

```ini
hotkey=Ctrl+Alt+A
ocr/lang=ch
ocr/use_angle_cls=true
```

The hotkey can be rebound from **设置…** in the tray menu. Apply attempts to register with Windows and warns on conflict.

## Limitations (v1)

- Region selection is bounded to the monitor where the cursor sits at hotkey time. Cross-monitor drag is not supported.
- Cloud OCR / language switching from the UI is not implemented.

## Project layout

```
main.py                        # entry; sets DPI awareness BEFORE importing Qt
src/textrecog/
  app.py                       # QApplication wiring
  config.py                    # QSettings + hotkey-string parsing
  hotkey.py                    # Win32 RegisterHotKey + native event filter
  overlay.py                   # selection overlay
  capture.py                   # mss screenshot helpers
  ocr.py                       # PaddleOCR worker thread
  result_window.py             # text popup
  tray.py                      # system tray
  settings_dialog.py           # hotkey rebind UI
```

## Packaging

PyInstaller `--onedir` is required (PaddlePaddle ships ~200 MB of native DLLs that PyInstaller's `--onefile` mode cannot reliably bundle). See `build.spec`:

```powershell
pyinstaller build.spec
```

Output lands in `dist\TextRecog\`. Wrap with Inno Setup for distribution.
