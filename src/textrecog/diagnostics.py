"""Small file-based diagnostics for packaged runs."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import threading
import traceback


_LOGGER_NAME = "textrecog"
_LOG_MAX_BYTES = 1_000_000
_LOG_BACKUP_COUNT = 3
_configured = False
_lock = threading.Lock()


def log_path() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        root = Path(base)
    else:
        root = Path.home() / "AppData" / "Roaming"
    return root / "TextRecog" / "logs" / "textrecog.log"


def setup_logging() -> Path:
    global _configured
    path = log_path()
    with _lock:
        if _configured:
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        logger = logging.getLogger(_LOGGER_NAME)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        handler = RotatingFileHandler(
            path,
            maxBytes=_LOG_MAX_BYTES,
            backupCount=_LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s.%(msecs)03d %(levelname)s "
                "pid=%(process)d thread=%(threadName)s %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.handlers.clear()
        logger.addHandler(handler)
        _configured = True
    return path


def log_event(area: str, message: str, **fields) -> None:
    setup_logging()
    suffix = ""
    if fields:
        parts = [f"{key}={value!r}" for key, value in fields.items()]
        suffix = " " + " ".join(parts)
    logging.getLogger(_LOGGER_NAME).info("[%s] %s%s", area, message, suffix)


def log_exception(area: str, message: str, exc: BaseException | None = None, **fields) -> None:
    setup_logging()
    if exc is not None:
        fields = {**fields, "exception": f"{type(exc).__name__}: {exc}"}
    suffix = ""
    if fields:
        parts = [f"{key}={value!r}" for key, value in fields.items()]
        suffix = " " + " ".join(parts)
    logging.getLogger(_LOGGER_NAME).error("[%s] %s%s", area, message, suffix)
    logging.getLogger(_LOGGER_NAME).error("".join(traceback.format_exc()))


def install_excepthook() -> None:
    setup_logging()
    original = sys.excepthook

    def hook(exc_type, exc, tb):
        logging.getLogger(_LOGGER_NAME).critical(
            "[app] unhandled exception",
            exc_info=(exc_type, exc, tb),
        )
        original(exc_type, exc, tb)

    sys.excepthook = hook
