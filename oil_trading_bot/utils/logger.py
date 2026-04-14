"""
logger.py — Structured logging configuration for oil_trading_bot.

Creates a consistent log format across all modules:
  [LEVEL] [timestamp] module_name — message

Usage:
    from utils.logger import get_logger
    log = get_logger(__name__)
    log.info("Something happened: %s", value)
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

from config import LOGS_DIR

# Ensure the logs directory exists at import time
LOGS_DIR.mkdir(parents=True, exist_ok=True)

_LOG_FORMAT = "%(asctime)s  %(levelname)-8s  %(name)-24s  %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_root_configured = False


def _configure_root() -> None:
    global _root_configured
    if _root_configured:
        return

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # ── Console handler (INFO and above) ──────────────────────────────
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(_LOG_FORMAT, _DATE_FORMAT))
    root.addHandler(console)

    # ── File handler (DEBUG and above) ────────────────────────────────
    log_file = LOGS_DIR / "backtest.log"
    file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(_LOG_FORMAT, _DATE_FORMAT))
    root.addHandler(file_handler)

    _root_configured = True


def get_logger(name: str, level: Optional[int] = None) -> logging.Logger:
    """
    Return a named logger, configuring the root logger on first call.

    Parameters
    ----------
    name : str
        Module name — pass ``__name__`` from the calling module.
    level : int, optional
        Override log level for this specific logger.

    Returns
    -------
    logging.Logger
    """
    _configure_root()
    logger = logging.getLogger(name)
    if level is not None:
        logger.setLevel(level)
    return logger
