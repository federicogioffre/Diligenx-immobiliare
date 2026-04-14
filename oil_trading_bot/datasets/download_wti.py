"""
download_wti.py — Downloads real WTI crude oil 5-min data via yfinance.

yfinance provides up to 60 days of 5-minute bars for CL=F (WTI futures
continuous contract). Saves a clean CSV compatible with the backtest engine.

Run: python3 datasets/download_wti.py
"""

import sys
from pathlib import Path

try:
    import yfinance as yf
except ImportError:
    print("ERROR: yfinance not installed. Run: pip install yfinance")
    sys.exit(1)

import pandas as pd

OUT = Path(__file__).parent / "wti_5min.csv"

print("Downloading WTI 5-min data from Yahoo Finance (CL=F, last 60 days)...")
df = yf.download("CL=F", interval="5m", period="60d", auto_adjust=True, progress=False)

if df.empty:
    print("ERROR: no data returned by yfinance.")
    sys.exit(1)

# Flatten MultiIndex columns (yfinance sometimes returns them)
if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.get_level_values(0)

# Rename to match the project's expected column names
df.index.name = "timestamp"
df.rename(columns={
    "Open":   "open",
    "High":   "high",
    "Low":    "low",
    "Close":  "close",
    "Volume": "volume",
}, inplace=True)

# Keep only OHLCV
df = df[["open", "high", "low", "close", "volume"]]

# Drop incomplete rows
df.dropna(inplace=True)
df = df[df["close"] > 0]
df = df[df["volume"] > 0]

# Save
df.to_csv(OUT)

print(f"\nSaved {len(df):,} rows → {OUT}")
print(f"Date range : {df.index[0]}  →  {df.index[-1]}")
print(f"Price range: {df['close'].min():.2f}  –  {df['close'].max():.2f}")
print(f"\nFirst 3 rows:")
print(df.head(3).to_string())
print(f"\nLast 3 rows:")
print(df.tail(3).to_string())
