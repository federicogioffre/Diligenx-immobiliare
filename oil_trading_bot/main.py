"""
main.py — Entry point for the oil_trading_bot backtesting system.

Usage:
    python main.py                        # uses default dataset
    python main.py --data path/to/data.csv
    python main.py --data path/to/data.csv --report-dir reports/
"""

import argparse
import sys
from pathlib import Path

from config import config, DEFAULT_DATASET, REPORTS_DIR
from data.data_loader import load_ohlcv
from backtest.engine import BacktestEngine
from analytics.report import generate_report
from utils.logger import get_logger

log = get_logger("main")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Oil Futures ORB Backtester",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=DEFAULT_DATASET,
        help="Path to OHLCV CSV file",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=REPORTS_DIR,
        help="Directory to write HTML/PNG reports",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # ── 1. Load data ──────────────────────────────────────────────────────
    log.info("Loading data from %s", args.data)
    candles = load_ohlcv(args.data)
    log.info("Loaded %d candles  [%s → %s]",
             len(candles),
             candles.index[0].date(),
             candles.index[-1].date())

    # ── 2. Run backtest ───────────────────────────────────────────────────
    engine = BacktestEngine(config)
    results = engine.run(candles)
    log.info("Backtest complete — %d trades executed", len(results.trades))

    # ── 3. Generate report ────────────────────────────────────────────────
    args.report_dir.mkdir(parents=True, exist_ok=True)
    generate_report(results, output_dir=args.report_dir)
    log.info("Report written to %s", args.report_dir)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.warning("Interrupted by user")
        sys.exit(0)
