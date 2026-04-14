"""
generate_example.py — Synthetic OHLCV dataset generator.

Generates realistic-looking crude oil futures 5-minute candles for
backtesting purposes.  The synthetic price walk includes:
  - Gaussian random walk for price
  - Intraday opening-range behaviour (higher volatility at open)
  - Trending days (random direction per session)
  - Volume patterns (higher at open/close)

Usage:
    python datasets/generate_example.py
    python datasets/generate_example.py --days 60 --out datasets/my_data.csv
"""

from __future__ import annotations

import argparse
import math
import random
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd


def _trading_minutes(session_date: date) -> list[datetime]:
    """Return 5-minute bar timestamps for a session (09:30–16:00 ET)."""
    start = datetime(session_date.year, session_date.month, session_date.day, 9, 30)
    end   = datetime(session_date.year, session_date.month, session_date.day, 16, 0)
    times = []
    current = start
    while current < end:
        times.append(current)
        current += timedelta(minutes=5)
    return times


def _generate_session(
    session_date: date,
    prev_close: float,
    seed: int,
) -> list[dict]:
    """Generate one day of 5-minute OHLCV bars."""
    rng = random.Random(seed)
    bars: list[dict] = []

    # Session-level trend
    trend = rng.gauss(0, 0.002)          # slight daily drift
    base_vol = rng.uniform(800, 2000)    # average volume per bar

    price = prev_close * (1 + rng.gauss(0, 0.002))  # gap open

    times = _trading_minutes(session_date)
    total_bars = len(times)

    # Pre-select a few bars in the post-range period for volume spikes (breakout simulation)
    spike_bars = set(rng.sample(range(7, total_bars), k=min(4, total_bars - 7)))

    for i, ts in enumerate(times):
        position = i / total_bars

        # Volatility: higher at open (first 6 bars = range window) and close
        vol_mult = 1.2 if position < 0.1 else (1.4 if position > 0.85 else 1.0)

        # Volume spikes outside the opening range simulate breakout volume surges
        if i in spike_bars:
            vol_mult = rng.uniform(1.8, 3.0)

        # Price move
        sigma  = 0.0015 * vol_mult
        move   = rng.gauss(trend, sigma)
        open_  = price
        close  = price * (1 + move)

        # High / Low around open-close range
        spread = abs(close - open_) + price * 0.0005 * vol_mult
        high   = max(open_, close) + abs(rng.gauss(0, spread * 0.5))
        low    = min(open_, close) - abs(rng.gauss(0, spread * 0.5))

        # Volume
        volume = max(10, rng.gauss(base_vol * vol_mult, base_vol * 0.3))

        bars.append({
            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "open":   round(open_, 3),
            "high":   round(high, 3),
            "low":    round(low, 3),
            "close":  round(close, 3),
            "volume": int(volume),
        })

        price = close

    return bars


def generate_dataset(
    num_days: int = 30,
    start_date: date | None = None,
    initial_price: float = 75.0,
    output_path: Path | None = None,
) -> pd.DataFrame:
    """
    Generate a synthetic OHLCV dataset.

    Parameters
    ----------
    num_days : int
        Number of trading days to simulate.
    start_date : date, optional
        First trading session date.  Defaults to today minus ``num_days``.
    initial_price : float
        Starting price for the random walk.
    output_path : Path, optional
        If provided, saves the CSV to this path.

    Returns
    -------
    pd.DataFrame
        OHLCV DataFrame indexed by ``timestamp``.
    """
    if start_date is None:
        start_date = date.today() - timedelta(days=num_days + 10)

    all_bars: list[dict] = []
    price = initial_price
    current = start_date
    sessions = 0

    while sessions < num_days:
        if current.weekday() < 5:  # skip weekends
            session_bars = _generate_session(current, price, seed=sessions * 7 + 42)
            if session_bars:
                all_bars.extend(session_bars)
                price = session_bars[-1]["close"]
            sessions += 1
        current += timedelta(days=1)

    df = pd.DataFrame(all_bars)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df.set_index("timestamp", inplace=True)

    if output_path:
        df.to_csv(output_path)
        print(f"Dataset saved: {output_path}  ({len(df)} rows, {num_days} sessions)")

    return df


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate synthetic OHLCV dataset")
    parser.add_argument("--days",  type=int,   default=30,   help="Number of trading days")
    parser.add_argument("--price", type=float, default=75.0, help="Initial WTI price")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).parent / "example_dataset.csv",
        help="Output CSV path",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    generate_dataset(
        num_days=args.days,
        initial_price=args.price,
        output_path=args.out,
    )
