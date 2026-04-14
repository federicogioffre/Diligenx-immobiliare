"""
data_loader.py — Reads raw OHLCV CSV data into a clean pandas DataFrame.

Expected CSV columns:
    timestamp, open, high, low, close, volume

Timestamps are parsed as UTC-aware datetimes (or naïve if the source has
no timezone info).
"""

from pathlib import Path

import pandas as pd

from utils.logger import get_logger

log = get_logger("data_loader")

REQUIRED_COLUMNS = {"timestamp", "open", "high", "low", "close", "volume"}


def load_ohlcv(path: Path | str) -> pd.DataFrame:
    """
    Load an OHLCV CSV file and return a cleaned, indexed DataFrame.

    Parameters
    ----------
    path : Path or str
        Location of the CSV file.

    Returns
    -------
    pd.DataFrame
        DataFrame indexed by ``timestamp`` (DatetimeIndex), sorted ascending.
        Columns: open, high, low, close, volume — all numeric.

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    ValueError
        If required columns are missing.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")

    log.debug("Reading CSV: %s", path)
    df = pd.read_csv(path, parse_dates=["timestamp"])

    # ── Validate columns ──────────────────────────────────────────────────
    missing = REQUIRED_COLUMNS - set(df.columns.str.lower())
    if missing:
        raise ValueError(f"CSV is missing required columns: {missing}")

    df.columns = df.columns.str.lower()

    # ── Type coercion ─────────────────────────────────────────────────────
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df.dropna(subset=["timestamp", "open", "high", "low", "close"], inplace=True)

    # ── Index & sort ──────────────────────────────────────────────────────
    df.set_index("timestamp", inplace=True)
    df.sort_index(inplace=True)

    log.info("Loaded %d rows, date range %s → %s",
             len(df), df.index[0], df.index[-1])
    return df
