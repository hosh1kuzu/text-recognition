# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概览

仅运行于 Windows 的系统托盘工具：按下全局快捷键（默认 `Ctrl+Alt+A`），在光标所在显示器上拖选区域，弹窗显示离线 OCR 结果（PaddleOCR `lang='ch'`，简体中文 + 英文混合）。技术栈：PySide6 + Python 3.11+。

## 常用命令

项目预设存在名为 **`textrecog`** 的 conda 环境，路径 `E:\Dev\Envs\Conda`。`.bat` 脚本会调用该环境——若在其他机器上工作，请修改 `run.bat` / `build.bat` 中的 `CONDA` 路径。

- **开发运行：** `run.bat` —— 在 `textrecog` conda 环境中执行 `python main.py`。
- **打包：** `build.bat` —— 清空 `build/` 与 `dist/`，然后运行 `pyinstaller build.spec`，产物为 `dist\TextRecog\TextRecog.exe`。
- **不使用 conda 时：** `python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt && python main.py`。
- 仓库**未配置测试与 lint**。

首次启动会下载 PaddleOCR 检测/识别/方向分类模型（约 10–20 MB）至 `~/.paddleocr/`。

用户配置持久化于 `%APPDATA%\TextRecog\TextRecog.ini`（QSettings INI 格式），键名：`hotkey`、`ocr/lang`、`ocr/use_angle_cls`。

## 架构

`main.py` → `src/textrecog/app.py::TextRecogApp` 通过 Qt signal 把所有单例串起来，每个模块职责单一：

| 模块 | 职责 |
|---|---|
| `hotkey.py` | Win32 `RegisterHotKey` + `QAbstractNativeEventFilter` 监听 `WM_HOTKEY`，发出 `triggered` 信号 |
| `capture.py` | `mss` 抓整个虚拟桌面 → `VirtualDesktop`（BGR ndarray + 各显示器矩形） |
| `overlay.py` | 单显示器无边框选区窗口；发出虚拟桌面物理像素坐标的矩形 |
| `ocr.py` | `PaddleOCR` 跑在专用 `QThread`，`recognize()` 通过 `QMetaObject.invokeMethod` 跨线程调用 |
| `result_window.py` | `QPlainTextEdit` 弹窗，定位在选区附近，Esc 关闭 |
| `tray.py` | `QSystemTrayIcon` + 菜单；发出 `captureRequested` / `settingsRequested` / `quitRequested` |
| `settings_dialog.py` | `QKeySequenceEdit` 重绑 UI；通过实际调用 `RegisterHotKey` 来验证可用性 |
| `config.py` | `QSettings` 封装 + `Hotkey` 解析器（字符串 ↔ Win32 修饰键标志 + VK 码） |

截图流程：快捷键 → `OverlayController.start_capture` 通过 mss 抓整个虚拟桌面 → 找到光标所在显示器并切片 → 在该显示器上显示 `OverlaySelector` → 用户拖选 → 物理像素矩形从已缓存的快照中裁剪 → `OcrService.recognize` → `ResultWindow.set_text`。

## 关键约束 —— 不可违反

以下是承重设计决策，违背会导致难以察觉的故障。

1. **DPI 感知必须在任何 Qt 导入之前设置。** `main.py` 在 `from textrecog.app import main` 之前调用 `SetProcessDpiAwarenessContext(per-monitor-v2)`。如果不设置，在 >100% 缩放的显示器上 `mss` 会返回逻辑像素，矩形 → 图像的映射会静默错位。**不要**在该代码块之上添加 Qt import。

2. **PaddleOCR 必须只在一个工作线程上运行。** 单个 `PaddleOCR` 实例的 `.ocr()` 调用并不并发安全，且 PaddlePaddle 的 MKL/OpenMP 在多 Python 线程下可能死锁。当前架构通过专用 `QThread` 上的 `_Worker` 串行化推理，请保持该模式。队列长度为 1 已足够——用户在第一个结果窗口出现前无法再次拖选。

3. **PyInstaller 必须使用 `--onedir`（即 `build.spec`）。** PaddlePaddle 自带约 200 MB 原生 DLL（mklml、libiomp5、mkldnn 等），`--onefile` 模式每次冷启动会解压到 `%TEMP%`（5–15 秒），且打包不可靠。`build.spec` 已显式收集 `paddle` 与 `paddleocr` 的 data files、动态库、submodule 与 metadata。

4. **三种坐标系不可混用。** 代码中并存：
   - **虚拟桌面物理像素** —— `mss` 与 `capture.py` 使用；`OverlayController.regionSelected` 发出的；`ocr.py` 接收的。
   - **Qt 逻辑坐标（DIP）** —— `QScreen.geometry()`、`OverlaySelector` 内部的 widget 坐标。乘以 `devicePixelRatio` 转为物理像素。
   - **Win32 光标坐标** —— `GetCursorPos` 返回物理像素（因为已设置 per-monitor-v2 DPI 感知）。

   转换时遵循既有模式：`OverlaySelector` 上报 widget 逻辑矩形 → `OverlayController._on_committed` 乘以 `self._dpr` → 加上该显示器在虚拟桌面上的原点。**不要**在一个表达式里混用不同坐标系。

5. **v1 设计上仅支持单显示器截图。** 选区蒙版只覆盖快捷键按下时光标所在的那块显示器。跨显示器拖选被刻意不支持，避免混合 DPR 的坐标地狱。若要扩展到多显示器，请先做规划——不要硬塞补丁。

6. **快捷键走 Win32 `RegisterHotKey`，不用 pynput / keyboard。** 这样 OS 会消费按键组合（不会泄露给前台应用）、不需要管理员权限，且 `WM_HOTKEY` 直接进 GUI 线程消息队列（无需跨线程 marshaling）。请保持此路径。
