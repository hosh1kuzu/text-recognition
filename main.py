"""Entry point. Sets DPI awareness BEFORE importing Qt — see plan §3.2."""
import os
import sys
import ctypes


_SINGLE_INSTANCE_MUTEX = None
_ERROR_ALREADY_EXISTS = 183


def _enable_per_monitor_v2_dpi_awareness() -> None:
    # Must run before any Qt import. Without this, mss returns logically-sized
    # (scaled-down) pixels on monitors at >100% scaling, breaking the rect→image
    # mapping. SetProcessDpiAwarenessContext is the modern API; fall back through
    # SetProcessDpiAwareness → SetProcessDPIAware for older Windows builds.
    try:
        ctx_per_monitor_v2 = ctypes.c_void_p(-4)
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctx_per_monitor_v2):
            return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


def _acquire_single_instance_lock() -> bool:
    """Return False when another GUI instance is already running.

    This is intentionally called after multiprocessing.freeze_support() so the
    packaged OCR child process is not blocked by the GUI singleton mutex.
    """
    if sys.platform != "win32":
        return True
    global _SINGLE_INSTANCE_MUTEX
    try:
        ctypes.windll.kernel32.CreateMutexW.argtypes = (
            ctypes.c_void_p,
            ctypes.c_bool,
            ctypes.c_wchar_p,
        )
        ctypes.windll.kernel32.CreateMutexW.restype = ctypes.c_void_p
        ctypes.windll.kernel32.GetLastError.restype = ctypes.c_ulong
        ctypes.windll.kernel32.SetLastError(0)
        handle = ctypes.windll.kernel32.CreateMutexW(
            None,
            False,
            "Local\\TextRecog.SingleInstance",
        )
        if not handle:
            return True
        _SINGLE_INSTANCE_MUTEX = handle
        return ctypes.windll.kernel32.GetLastError() != _ERROR_ALREADY_EXISTS
    except (AttributeError, OSError):
        return True


if sys.platform == "win32":
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
    _enable_per_monitor_v2_dpi_awareness()


# Ensure src/ is importable when running `python main.py` from a checkout.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_HERE, "src")
if os.path.isdir(_SRC) and _SRC not in sys.path:
    sys.path.insert(0, _SRC)

if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    if not _acquire_single_instance_lock():
        sys.exit(0)

    from textrecog.app import main  # noqa: E402

    sys.exit(main())
