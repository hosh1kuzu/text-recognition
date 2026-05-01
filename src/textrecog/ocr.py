"""PaddleOCR service.

Paddle's native inference runtime is not reliable inside a Qt worker thread on
Windows, so OCR runs in a separate Python process. The GUI process stays
responsive and polls a small result queue with a QTimer.
"""
from __future__ import annotations

import multiprocessing as mp
import os
import queue
import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

import numpy as np

from .diagnostics import log_event, log_exception, setup_logging


MAX_OCR_PIXELS = 2_000_000
MAX_OCR_SIDE = 1800

_MODEL_SPECS = {
    "ch": {
        "det_lang": "ch",
        "rec_lang": "ch",
        "det_url": "https://paddleocr.bj.bcebos.com/PP-OCRv4/chinese/ch_PP-OCRv4_det_infer.tar",
        "rec_url": "https://paddleocr.bj.bcebos.com/PP-OCRv4/chinese/ch_PP-OCRv4_rec_infer.tar",
        "rec_dict": "ppocr/utils/ppocr_keys_v1.txt",
    },
    "en": {
        "det_lang": "en",
        "rec_lang": "en",
        "det_url": "https://paddleocr.bj.bcebos.com/PP-OCRv3/english/en_PP-OCRv3_det_infer.tar",
        "rec_url": "https://paddleocr.bj.bcebos.com/PP-OCRv4/english/en_PP-OCRv4_rec_infer.tar",
        "rec_dict": "ppocr/utils/en_dict.txt",
    },
}

_CLS_URL = "https://paddleocr.bj.bcebos.com/dygraph_v2.0/ch/ch_ppocr_mobile_v2.0_cls_infer.tar"


def _ocr_process_main(in_queue, out_queue, lang: str, use_angle_cls: bool) -> None:
    setup_logging()
    log_event("ocr-child", "process start", lang=lang, use_angle_cls=use_angle_cls)
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    _hide_child_console_windows()
    try:
        log_event("ocr-child", "initializing engine")
        ocr = _FastPaddleOcr(lang=lang, use_angle_cls=use_angle_cls)
        out_queue.put(("ready", None))
        log_event("ocr-child", "ready")
    except Exception as exc:
        log_exception("ocr-child", "init failed", exc)
        out_queue.put(("failed", _format_exc("OCR init failed", exc)))
        return

    while True:
        cmd, payload = in_queue.get()
        log_event("ocr-child", "command received", command=cmd)
        if cmd == "stop":
            log_event("ocr-child", "stop")
            return
        if cmd != "recognize":
            continue
        try:
            img = payload
            log_event("ocr-child", "recognize start", shape=getattr(img, "shape", None))
            started = time.perf_counter()
            raw = ocr.ocr(img, cls=use_angle_cls)
            text = _extract_text(raw)
            elapsed = time.perf_counter() - started
            out_queue.put(("result", text, elapsed, img.shape[1], img.shape[0]))
            log_event("ocr-child", "recognize done", elapsed=round(elapsed, 3), chars=len(text))
        except Exception as exc:
            log_exception("ocr-child", "recognize failed", exc)
            out_queue.put(("failed", _format_exc("OCR failed", exc)))


def _hide_child_console_windows() -> None:
    """Keep dependency-created helper commands from flashing consoles."""
    if sys.platform != "win32":
        return
    try:
        import subprocess
    except ImportError:
        return

    if getattr(subprocess.Popen, "_textrecog_hidden", False):
        return

    original_init = subprocess.Popen.__init__

    def hidden_init(self, *args, **kwargs):
        kwargs["creationflags"] = (kwargs.get("creationflags") or 0) | subprocess.CREATE_NO_WINDOW
        startup_info = kwargs.get("startupinfo")
        if startup_info is None:
            startup_info = subprocess.STARTUPINFO()
        startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup_info.wShowWindow = subprocess.SW_HIDE
        kwargs["startupinfo"] = startup_info
        original_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = hidden_init
    subprocess.Popen._textrecog_hidden = True


class _FastPaddleOcr:
    """Small OCR-only wrapper around PaddleOCR's TextSystem.

    Importing `paddleocr.PaddleOCR` also imports PP-Structure, table recovery,
    docx export, and other modules this tray OCR tool never uses. This wrapper
    builds the same OCR system from `tools.infer.predict_system.TextSystem`
    without that top-level import chain.
    """

    def __init__(self, lang: str, use_angle_cls: bool) -> None:
        package_dir = _prepare_paddleocr_import_path()
        spec = _MODEL_SPECS.get(lang)
        if spec is None:
            supported = ", ".join(sorted(_MODEL_SPECS))
            raise ValueError(f"Unsupported OCR language {lang!r}; supported: {supported}")

        from ppocr.utils.network import maybe_download
        from tools.infer import predict_system, utility

        base_dir = Path(os.environ.get("PADDLE_OCR_BASE_DIR", Path.home() / ".paddleocr")).expanduser()
        det_model_dir = base_dir / "whl" / "det" / spec["det_lang"] / _model_name_from_url(spec["det_url"])
        rec_model_dir = base_dir / "whl" / "rec" / spec["rec_lang"] / _model_name_from_url(spec["rec_url"])
        cls_model_dir = base_dir / "whl" / "cls" / "ch_ppocr_mobile_v2.0_cls_infer"

        maybe_download(str(det_model_dir), spec["det_url"])
        maybe_download(str(rec_model_dir), spec["rec_url"])
        if use_angle_cls:
            maybe_download(str(cls_model_dir), _CLS_URL)

        args = utility.init_args().parse_args([])
        args.use_gpu = False
        args.use_xpu = False
        args.use_npu = False
        args.use_mlu = False
        args.use_gcu = False
        args.use_onnx = False
        args.show_log = False
        args.cpu_threads = 2
        args.lang = lang
        args.use_angle_cls = use_angle_cls
        args.det_algorithm = "DB"
        args.rec_algorithm = "SVTR_LCNet"
        args.det_model_dir = str(det_model_dir)
        args.rec_model_dir = str(rec_model_dir)
        args.cls_model_dir = str(cls_model_dir)
        args.rec_char_dict_path = str(package_dir / spec["rec_dict"])
        args.rec_image_shape = "3, 48, 320"

        self._system = predict_system.TextSystem(args)
        self._use_angle_cls = use_angle_cls

    def ocr(self, img: np.ndarray, cls: bool = False):
        boxes, recs, _time_dict = self._system(img, cls=bool(cls and self._use_angle_cls))
        if boxes is None or recs is None:
            return [None]
        return [[[box.tolist(), rec] for box, rec in zip(boxes, recs)]]


def _prepare_paddleocr_import_path() -> Path:
    import importlib.util

    spec = importlib.util.find_spec("paddleocr")
    if spec is None or not spec.submodule_search_locations:
        raise ModuleNotFoundError("paddleocr")
    package_dir = Path(next(iter(spec.submodule_search_locations))).resolve()
    package_dir_str = str(package_dir)
    if package_dir_str not in sys.path:
        sys.path.append(package_dir_str)
    return package_dir


def _model_name_from_url(url: str) -> str:
    name = url.rsplit("/", 1)[-1]
    return name[:-4] if name.endswith(".tar") else name


def _resize_for_ocr(img: np.ndarray) -> np.ndarray:
    """Keep accidental huge selections from making CPU OCR appear hung."""
    h, w = img.shape[:2]
    if h <= 0 or w <= 0:
        return img
    scale = min(1.0, MAX_OCR_SIDE / max(h, w), (MAX_OCR_PIXELS / (h * w)) ** 0.5)
    if scale >= 0.999:
        return img
    import cv2

    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    return cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)


def _format_exc(prefix: str, exc: BaseException) -> str:
    """Build a one-line message that always includes the exception type."""
    import traceback

    traceback.print_exc()
    detail = str(exc).strip()
    type_name = type(exc).__name__
    if detail:
        return f"{prefix}: {type_name}: {detail}"
    return f"{prefix}: {type_name}"


def _start_process_hidden(proc: mp.Process) -> None:
    """Start a multiprocessing child without flashing a console on Windows."""
    if sys.platform != "win32":
        proc.start()
        return

    try:
        import _winapi
        import multiprocessing.popen_spawn_win32 as popen_spawn_win32
        import subprocess
    except ImportError:
        proc.start()
        return

    original_create_process = popen_spawn_win32._winapi.CreateProcess

    def create_process_no_window(
        app_name,
        cmd_line,
        proc_attrs,
        thread_attrs,
        inherit_handles,
        creation_flags,
        env,
        cwd,
        startup_info,
    ):
        if startup_info is None:
            startup_info = subprocess.STARTUPINFO()
        startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup_info.wShowWindow = subprocess.SW_HIDE
        return original_create_process(
            app_name,
            cmd_line,
            proc_attrs,
            thread_attrs,
            inherit_handles,
            creation_flags | _winapi.CREATE_NO_WINDOW,
            env,
            cwd,
            startup_info,
        )

    popen_spawn_win32._winapi.CreateProcess = create_process_no_window
    try:
        proc.start()
    finally:
        popen_spawn_win32._winapi.CreateProcess = original_create_process


def _extract_text(raw) -> str:
    """Flatten PaddleOCR's nested result into a single newline-joined string."""
    if not raw:
        return ""
    # Unwrap batch dimension if present.
    if isinstance(raw, list) and len(raw) == 1 and (raw[0] is None or isinstance(raw[0], list)):
        raw = raw[0]
    if raw is None:
        return ""
    items: list[tuple[float, float, str]] = []
    for entry in raw:
        if entry is None:
            continue
        try:
            bbox, payload = entry[0], entry[1]
            if isinstance(payload, (list, tuple)):
                text = payload[0]
            else:
                text = str(payload)
            if not isinstance(text, str) or not text:
                continue
            ys = [p[1] for p in bbox]
            xs = [p[0] for p in bbox]
            top = float(min(ys))
            left = float(min(xs))
            items.append((top, left, text))
        except (IndexError, TypeError, ValueError):
            continue
    if not items:
        return ""
    items.sort(key=lambda t: (round(t[0] / 8) * 8, t[1]))
    rows: list[list[tuple[float, str]]] = []
    last_band = None
    for top, left, text in items:
        band = round(top / 8) * 8
        if last_band is None or band != last_band:
            rows.append([(left, text)])
            last_band = band
        else:
            rows[-1].append((left, text))
    lines = ["  ".join(t for _, t in sorted(row)) for row in rows]
    return "\n".join(lines)


class OcrService(QObject):
    """Public-facing OCR service. Lives on the GUI thread; owns a worker process."""

    ready = Signal()
    failed = Signal(str)
    resultReady = Signal(str)
    statusChanged = Signal(str)

    def __init__(self, lang: str = "ch", use_angle_cls: bool = True, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._lang = lang
        self._use_angle_cls = use_angle_cls
        self._ctx = mp.get_context("spawn")
        self._in_queue = None
        self._out_queue = None
        self._proc: mp.Process | None = None
        self._ready_emitted = False
        self._worker_failed = False
        self._busy = False
        self._stopping = False
        self._restart_count = 0
        self._max_restarts = 2

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(50)
        self._poll_timer.timeout.connect(self._poll_worker)

    def start(self) -> None:
        if self._proc is not None and self._proc.is_alive():
            log_event("ocr", "start ignored: already alive", pid=self._proc.pid)
            return
        log_event("ocr", "start", lang=self._lang, use_angle_cls=self._use_angle_cls)
        self._stopping = False
        self._ready_emitted = False
        self._worker_failed = False
        self._busy = False
        self._in_queue = self._ctx.Queue(maxsize=1)
        self._out_queue = self._ctx.Queue()
        self._proc = self._ctx.Process(
            target=_ocr_process_main,
            args=(self._in_queue, self._out_queue, self._lang, self._use_angle_cls),
            name="TextRecogOcrWorker",
        )
        self._proc.daemon = True
        _start_process_hidden(self._proc)
        log_event("ocr", "process started", pid=self._proc.pid)
        self._poll_timer.start()

    def stop(self) -> None:
        log_event("ocr", "stop", has_proc=self._proc is not None, alive=(self._proc.is_alive() if self._proc is not None else None))
        self._stopping = True
        self._poll_timer.stop()
        if self._proc is not None and self._proc.is_alive():
            try:
                if self._in_queue is not None:
                    self._in_queue.put(("stop", None), timeout=0.2)
            except Exception:
                pass
            self._proc.join(1.5)
            if self._proc.is_alive():
                log_event("ocr", "terminate process", pid=self._proc.pid)
                self._proc.terminate()
                self._proc.join(1.0)
        self._close_queues()
        self._proc = None
        self._ready_emitted = False
        self._busy = False

    def recognize(self, img: np.ndarray) -> None:
        log_event("ocr", "recognize request", shape=img.shape, busy=self._busy, has_proc=self._proc is not None, alive=(self._proc.is_alive() if self._proc is not None else None))
        if self._proc is None or not self._proc.is_alive() or self._in_queue is None:
            self.failed.emit("OCR worker is not running")
            return
        if self._busy:
            self.failed.emit("OCR worker is busy")
            return

        original_shape = img.shape
        img = _resize_for_ocr(img)
        if img.shape == original_shape:
            self.statusChanged.emit(f"识别中... {img.shape[1]}x{img.shape[0]}")
        else:
            self.statusChanged.emit(
                f"识别中... {original_shape[1]}x{original_shape[0]} -> {img.shape[1]}x{img.shape[0]}"
            )

        try:
            self._busy = True
            self._in_queue.put_nowait(("recognize", img))
            log_event("ocr", "recognize queued", shape=img.shape)
        except queue.Full:
            self._busy = False
            log_event("ocr", "recognize queue full")
            self.failed.emit("OCR worker is busy")

    def _poll_worker(self) -> None:
        out_queue = self._out_queue
        if out_queue is not None:
            while True:
                try:
                    msg = out_queue.get_nowait()
                except queue.Empty:
                    break
                except Exception as exc:
                    # Worker may have crashed mid-write, leaving a partial/corrupt
                    # message in the pipe. Discard and let the process-death check
                    # below handle the failure path.
                    log_exception("ocr", "queue read error", exc)
                    break
                try:
                    self._handle_worker_message(msg)
                except Exception as exc:
                    log_exception("ocr", "message handling error", exc, msg=msg)
                if self._out_queue is not out_queue:
                    break

        proc = self._proc
        if proc is None or proc.is_alive():
            return
        exitcode = proc.exitcode
        log_event("ocr", "process exited", pid=proc.pid, exitcode=exitcode, busy=self._busy, ready=self._ready_emitted, worker_failed=self._worker_failed)
        self._poll_timer.stop()
        self._close_queues()
        self._proc = None
        if not self._worker_failed and (self._busy or not self._ready_emitted or exitcode not in (0, None)):
            self._busy = False
            if not self._stopping and self._restart_count < self._max_restarts:
                self._restart_count += 1
                self.failed.emit(f"OCR 进程异常退出，已自动重启。请重新截图识别。")
                self.statusChanged.emit(f"OCR 进程正在重启 ({self._restart_count}/{self._max_restarts})…")
                self.start()
            else:
                self.failed.emit(f"OCR worker exited unexpectedly (code {exitcode})")

    def _handle_worker_message(self, msg) -> None:
        kind = msg[0]
        log_event("ocr", "worker message", kind=kind)
        if kind == "ready":
            self._ready_emitted = True
            self.ready.emit()
        elif kind == "result":
            _, text, elapsed, w, h = msg
            self._busy = False
            log_event("ocr", "result", w=w, h=h, elapsed=round(elapsed, 3), chars=len(text))
            self.resultReady.emit(text)
        elif kind == "failed":
            self._busy = False
            self._worker_failed = True
            log_event("ocr", "failed message", message=str(msg[1]))
            self.failed.emit(str(msg[1]))

    def _close_queues(self) -> None:
        for q in (self._in_queue, self._out_queue):
            if q is None:
                continue
            try:
                # cancel_join_thread() prevents the GUI thread from blocking on
                # join_thread() when the worker has died mid-write and the feeder
                # thread is stuck trying to flush to a broken pipe.
                q.cancel_join_thread()
                q.close()
            except Exception:
                log_event("ocr", "queue close failed")
                pass
        self._in_queue = None
        self._out_queue = None
