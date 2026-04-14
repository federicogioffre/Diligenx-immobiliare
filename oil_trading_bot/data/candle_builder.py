"""
candle_builder.py — Utilities for working with individual OHLCV candles.

Currently provides:
  - A typed ``Candle`` dataclass used throughout the system.
  - ``iter_candles()`` — iterator that yields Candle objects from a DataFrame.
  - ``session_candles()`` — filter candles for a given trading session date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterator

import pandas as pd


@dataclass(frozen=True, slots=True)
class Candle:
    """Immutable representation of a single OHLCV bar."""
    timestamp: datetime
    open:   float
    high:   float
    low:    float
    close:  float
    volume: float

    # ------------------------------------------------------------------
    # Derived properties
    # ------------------------------------------------------------------
    @property
    def midpoint(self) -> float:
        """Midpoint of the candle's range."""
        return (self.high + self.low) / 2

    @property
    def body_size(self) -> float:
        """Absolute size of the real body."""
        return abs(self.close - self.open)

    @property
    def range_size(self) -> float:
        """High-Low range."""
        return self.high - self.low

    def is_bullish(self) -> bool:
        return self.close >= self.open

    def __str__(self) -> str:
        return (
            f"Candle({self.timestamp:%Y-%m-%d %H:%M}  "
            f"O={self.open:.3f} H={self.high:.3f} "
            f"L={self.low:.3f} C={self.close:.3f}  V={self.volume:.0f})"
        )


# ---------------------------------------------------------------------------
# Iterator helpers
# ---------------------------------------------------------------------------

def iter_candles(df: pd.DataFrame) -> Iterator[Candle]:
    """
    Yield ``Candle`` objects from a OHLCV DataFrame in chronological order.

    Parameters
    ----------
    df : pd.DataFrame
        Indexed by ``timestamp`` (DatetimeIndex). Must contain columns
        open, high, low, close, volume.
    """
    for ts, row in df.iterrows():
        yield Candle(
            timestamp=ts.to_pydatetime(),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
        )


def session_candles(df: pd.DataFrame, session_date: date) -> pd.DataFrame:
    """
    Return all candles belonging to a single trading session date.

    Parameters
    ----------
    df : pd.DataFrame
        Full OHLCV DataFrame.
    session_date : date
        The calendar date to filter on.

    Returns
    -------
    pd.DataFrame
        Subset of ``df`` for that date, preserving original index.
    """
    mask = df.index.date == session_date
    return df.loc[mask]
