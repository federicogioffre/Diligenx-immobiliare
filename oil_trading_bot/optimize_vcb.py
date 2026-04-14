"""
optimize_vcb.py — CLI entry point for the VCB strategy grid-search optimizer.

Usage examples
--------------
# Run on real WTI data with default grid (144 combinations):
    python3 optimize_vcb.py --data datasets/wti_5min.csv

# Custom grid — override any dimension:
    python3 optimize_vcb.py \
        --data    datasets/wti_5min.csv \
        --ema     20 50 100 \
        --atr     10 14 \
        --thr     0.6 0.8 1.0 \
        --mult    1.0 1.5 2.0 \
        --output  results/vcb_custom.csv \
        --top     15

# Limit to the most-recent N candles (fast sanity check):
    python3 optimize_vcb.py --data datasets/wti_5min.csv --max-candles 2000

Output
------
  results/vcb_optimization.csv   CSV ranked by total profit
  Stdout                         Formatted top-N table
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure project root is on the Python path when running as a script
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd

from config import Config
from data.data_loader import load_ohlcv
from research.vcb_optimizer import (
    VCBGridSearchOptimizer,
    save_vcb_results,
    print_vcb_top_n,
    EMA_PERIODS,
    ATR_PERIODS,
    COMPRESSION_THRESHOLDS,
    ATR_MULTIPLIERS,
)
from utils.logger import get_logger

log = get_logger("optimize_vcb")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="VCB strategy grid-search optimizer",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # Data
    p.add_argument(
        "--data",
        type=Path,
        default=Path("datasets/wti_5min.csv"),
        help="Path to OHLCV CSV (columns: timestamp, open, high, low, close, volume)",
    )
    p.add_argument(
        "--max-candles",
        type=int,
        default=0,
        metavar="N",
        help="Use only the last N candles (0 = all).  Useful for quick sanity checks.",
    )

    # Output
    p.add_argument(
        "--output",
        type=Path,
        default=Path("results/vcb_optimization.csv"),
        help="Destination CSV for full results",
    )
    p.add_argument(
        "--top",
        type=int,
        default=10,
        metavar="N",
        help="Number of top combinations to print to stdout",
    )

    # Grid dimensions
    p.add_argument(
        "--ema",
        nargs="+",
        type=int,
        default=EMA_PERIODS,
        metavar="N",
        help="EMA period values to test",
    )
    p.add_argument(
        "--atr",
        nargs="+",
        type=int,
        default=ATR_PERIODS,
        metavar="N",
        help="ATR period values to test",
    )
    p.add_argument(
        "--thr",
        nargs="+",
        type=float,
        default=COMPRESSION_THRESHOLDS,
        metavar="F",
        help="Compression threshold values (range < thr × ATR)",
    )
    p.add_argument(
        "--mult",
        nargs="+",
        type=float,
        default=ATR_MULTIPLIERS,
        metavar="F",
        help="ATR SL multiplier values (TP = 2 × SL)",
    )

    # Capital
    p.add_argument(
        "--capital",
        type=float,
        default=100_000.0,
        help="Starting capital for each backtest run",
    )

    return p


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = build_parser().parse_args()

    # ── Load dataset ───────────────────────────────────────────────────
    if not args.data.exists():
        print(f"ERROR: data file not found: {args.data}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading dataset: {args.data}")
    candles_df: pd.DataFrame = load_ohlcv(args.data)

    if args.max_candles and args.max_candles > 0:
        candles_df = candles_df.iloc[-args.max_candles:]
        print(f"Using last {len(candles_df):,} candles")
    else:
        print(f"Loaded {len(candles_df):,} candles")

    date_min = candles_df.index.min()
    date_max = candles_df.index.max()
    print(f"Date range : {date_min}  →  {date_max}")
    print(
        f"Price range: {candles_df['close'].min():.2f}  –  "
        f"{candles_df['close'].max():.2f}"
    )

    # ── Grid summary ───────────────────────────────────────────────────
    n_combos = len(args.ema) * len(args.atr) * len(args.thr) * len(args.mult)
    print(
        f"\nGrid: EMA={args.ema}  ATR={args.atr}  "
        f"thr={args.thr}  mult={args.mult}"
    )
    print(f"Total combinations: {n_combos}")
    print("─" * 60)

    # ── Run optimizer ──────────────────────────────────────────────────
    optimizer = VCBGridSearchOptimizer(
        base_config             = Config(),
        initial_capital         = args.capital,
        ema_periods             = args.ema,
        atr_periods             = args.atr,
        compression_thresholds  = args.thr,
        atr_multipliers         = args.mult,
    )

    results = optimizer.run(candles_df)

    # ── Output ─────────────────────────────────────────────────────────
    save_vcb_results(results, args.output)
    print_vcb_top_n(results, n=args.top)

    # Quick summary line
    best = results[0]
    print(
        f"Best: EMA={best.ema_period}  ATR={best.atr_period}  "
        f"thr={best.compression_threshold:.2f}  mult={best.atr_multiplier:.2f}  "
        f"→  profit=${best.total_profit:,.2f}  "
        f"trades={best.num_trades}  "
        f"WR={best.win_rate * 100:.1f}%"
    )
    print(f"\nFull results saved to: {args.output.resolve()}\n")


if __name__ == "__main__":
    main()
