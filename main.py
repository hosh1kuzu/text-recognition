"""Entry point. Sets DPI awareness BEFORE importing Qt — see plan §3.2."""
import os
import sys
import ctypes


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
    from textrecog.app import main  # noqa: E402

    sys.exit(main())
