"""
optimize.py — CLI entry point for strategy parameter optimization.

Usage
-----
  # Optimize on the example dataset:
  python3 optimize.py

  # Optimize on a custom dataset:
  python3 optimize.py --data datasets/wti_5min.csv

  # Custom output file:
  python3 optimize.py --data datasets/wti_5min.csv --output results/my_run.csv

  # Custom grid (override defaults):
  python3 optimize.py --ema 20 50 100 --atr 10 14 --mult 1.5 2.0

  # Show more top results:
  python3 optimize.py --top 20

  # Run only first N candles (quick test):
  python3 optimize.py --max-candles 500
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Ensure project root is on sys.path (supports running from any directory)
sys.path.insert(0, str(Path(__file__).parent))

from config import Config
from data.data_loader import load_ohlcv
from research.optimizer import (
    GridSearchOptimizer,
    print_top_n,
    save_results,
)
from utils.logger import get_logger

log = get_logger("optimize")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Oil Trading Bot — strategy parameter grid search",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--data",
        default="datasets/example_dataset.csv",
        help="Path to OHLCV CSV dataset",
    )
    p.add_argument(
        "--output",
        default="results/optimization_results.csv",
        help="Path to save the full results CSV",
    )
    p.add_argument(
        "--ema",
        nargs="+",
        type=int,
        default=[20, 30, 50, 100],
        metavar="N",
        help="EMA period(s) to test",
    )
    p.add_argument(
        "--atr",
        nargs="+",
        type=int,
        default=[10, 14, 20],
        metavar="N",
        help="ATR period(s) to test",
    )
    p.add_argument(
        "--mult",
        nargs="+",
        type=float,
        default=[1.2, 1.5, 1.8, 2.0],
        metavar="M",
        help="ATR multiplier(s) to test (SL = ATR × M,  TP = SL × 2)",
    )
    p.add_argument(
        "--capital",
        type=float,
        default=100_000.0,
        help="Starting capital for each backtest run",
    )
    p.add_argument(
        "--top",
        type=int,
        default=10,
        help="Number of top combinations to display",
    )
    p.add_argument(
        "--max-candles",
        type=int,
        default=0,
        help="Limit dataset to first N candles (0 = no limit; useful for quick tests)",
    )
    return p.parse_args()


def main() -> None:
    args   = parse_args()
    cfg    = Config()
    t_start = time.perf_counter()

    # ── Load data ──────────────────────────────────────────────────────
    data_path = Path(args.data)
    if not data_path.exists():
        log.error("Dataset not found: %s", data_path)
        sys.exit(1)

    log.info("Loading dataset: %s", data_path)
    df = load_ohlcv(data_path)

    if args.max_candles > 0:
        df = df.iloc[: args.max_candles]
        log.info("Limited to first %d candles (--max-candles)", args.max_candles)

    log.info(
        "Dataset: %d candles  [%s → %s]",
        len(df),
        df.index[0].strftime("%Y-%m-%d"),
        df.index[-1].strftime("%Y-%m-%d"),
    )

    # ── Grid ───────────────────────────────────────────────────────────
    total_combos = len(args.ema) * len(args.atr) * len(args.mult)
    log.info(
        "Grid: EMA=%s  ATR=%s  mult=%s  → %d combinations",
        args.ema, args.atr, args.mult, total_combos,
    )

    optimizer = GridSearchOptimizer(
        base_config     = cfg,
        initial_capital = args.capital,
        ema_periods     = args.ema,
        atr_periods     = args.atr,
        atr_multipliers = args.mult,
    )

    # ── Run ────────────────────────────────────────────────────────────
    results = optimizer.run(df)

    elapsed = time.perf_counter() - t_start
    log.info("Optimization complete in %.1f s (%d runs)", elapsed, len(results))

    # ── Save ───────────────────────────────────────────────────────────
    output_path = Path(args.output)
    save_results(results, output_path)

    # ── Print ranking ──────────────────────────────────────────────────
    print_top_n(results, n=min(args.top, len(results)))

    # Exit summary line
    best = results[0]
    print(
        f"Best combination: EMA={best.ema_period}  ATR={best.atr_period}  "
        f"mult={best.atr_multiplier}  →  profit={best.total_profit:+.2f}  "
        f"trades={best.num_trades}  WR={best.win_rate*100:.1f}%"
    )


if __name__ == "__main__":
    main()
