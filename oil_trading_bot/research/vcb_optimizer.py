"""
vcb_optimizer.py — Grid-search optimizer for the VCB strategy.

What it optimises
-----------------
Four VCBConfig parameters are varied independently:

  ema_period            : trend-filter lookback
  atr_period            : volatility baseline lookback
  compression_threshold : squeeze sensitivity (range < thr × ATR)
  atr_multiplier        : SL distance; TP is fixed at 2 × SL (1:2 R:R)

Default grid
------------
  ema_period            : [20, 50, 100]
  atr_period            : [10, 14, 20]
  compression_threshold : [0.6, 0.8, 1.0, 1.2]
  atr_multiplier        : [0.8, 1.0, 1.5, 2.0]
  Total                 : 3 × 3 × 4 × 4 = 144 combinations

Design
------
Unlike the ORB optimizer (FilteredBacktestEngine) the VCB strategy
computes all its indicators *inline* (streaming, bar-by-bar).  This
means no pre-computation of pandas indicator series is needed — each
run is fully self-contained.  The trade-off is that each of the 144
runs does its own O(N) indicator pass, which is still fast in practice
(~0.01 s per run on typical datasets).

Output
------
  results/vcb_optimization.csv  — all combinations, ranked by profit
  Top-N printed to stdout.
"""

from __future__ import annotations

import copy
import itertools
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from analytics.metrics import compute_metrics
from backtest.vcb_engine import VCBBacktestEngine
from config import Config, VCBConfig
from utils.logger import get_logger

log = get_logger("vcb_optimizer")


# ---------------------------------------------------------------------------
# Default parameter grids
# ---------------------------------------------------------------------------

EMA_PERIODS:             list[int]   = [20, 50, 100]
ATR_PERIODS:             list[int]   = [10, 14, 20]
COMPRESSION_THRESHOLDS:  list[float] = [0.6, 0.8, 1.0, 1.2]
ATR_MULTIPLIERS:         list[float] = [0.8, 1.0, 1.5, 2.0]


# ---------------------------------------------------------------------------
# Parameter / result containers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VCBOptimParams:
    """One grid-search parameter combination."""
    ema_period:            int
    atr_period:            int
    compression_threshold: float
    atr_multiplier:        float   # SL mult; TP = 2 × SL


@dataclass
class VCBOptimResult:
    """Metrics collected from a single VCB backtest run."""
    ema_period:            int
    atr_period:            int
    compression_threshold: float
    atr_multiplier:        float
    num_trades:            int
    total_profit:          float
    max_drawdown:          float
    sharpe_ratio:          float
    profit_factor:         float
    win_rate:              float
    avg_trade:             float
    elapsed_ms:            float

    def as_dict(self) -> dict:
        return {
            "ema_period":            self.ema_period,
            "atr_period":            self.atr_period,
            "compression_threshold": round(self.compression_threshold, 2),
            "atr_multiplier":        round(self.atr_multiplier, 2),
            "num_trades":            self.num_trades,
            "total_profit":          round(self.total_profit, 4),
            "max_drawdown":          round(self.max_drawdown, 4),
            "sharpe_ratio":          round(self.sharpe_ratio, 4),
            "profit_factor":         round(self.profit_factor, 4),
            "win_rate":              round(self.win_rate * 100, 2),
            "avg_trade":             round(self.avg_trade, 4),
            "elapsed_ms":            round(self.elapsed_ms, 1),
        }


# ---------------------------------------------------------------------------
# Optimizer
# ---------------------------------------------------------------------------

class VCBGridSearchOptimizer:
    """
    Grid-search optimizer for the Volatility Compression Breakout strategy.

    Parameters
    ----------
    base_config : Config
        Base configuration object; VCBConfig fields are overridden per run.
        ORBConfig is not used.
    initial_capital : float
        Starting cash for every backtest run.
    ema_periods : list[int]
        EMA lookback values to test.
    atr_periods : list[int]
        ATR lookback values to test.
    compression_thresholds : list[float]
        Squeeze threshold values to test (range < thr × ATR).
    atr_multipliers : list[float]
        ATR SL multipliers to test (TP = 2 × SL).
    """

    def __init__(
        self,
        base_config:             Config,
        initial_capital:         float        = 100_000.0,
        ema_periods:             list[int]    = EMA_PERIODS,
        atr_periods:             list[int]    = ATR_PERIODS,
        compression_thresholds:  list[float]  = COMPRESSION_THRESHOLDS,
        atr_multipliers:         list[float]  = ATR_MULTIPLIERS,
    ) -> None:
        self._cfg                    = base_config
        self._capital                = initial_capital
        self._ema_periods            = ema_periods
        self._atr_periods            = atr_periods
        self._compression_thresholds = compression_thresholds
        self._atr_multipliers        = atr_multipliers

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, candles_df: pd.DataFrame) -> list[VCBOptimResult]:
        """
        Execute the full grid search.

        Parameters
        ----------
        candles_df : pd.DataFrame
            OHLCV dataset (same format as BacktestEngine expects).

        Returns
        -------
        list[VCBOptimResult]
            All results sorted by ``total_profit`` descending.
        """
        combos = list(itertools.product(
            self._ema_periods,
            self._atr_periods,
            self._compression_thresholds,
            self._atr_multipliers,
        ))
        total = len(combos)
        log.info("VCB grid search: %d combinations", total)

        results: list[VCBOptimResult] = []

        for i, (ema_p, atr_p, thr, mult) in enumerate(combos, 1):
            log.info(
                "[%3d/%d]  EMA=%3d  ATR=%2d  thr=%.2f  mult=%.2f",
                i, total, ema_p, atr_p, thr, mult,
            )
            result = self._run_single(candles_df, ema_p, atr_p, thr, mult)
            results.append(result)

        results.sort(key=lambda r: r.total_profit, reverse=True)

        best = results[0]
        log.info(
            "Grid search done — best: EMA=%d ATR=%d thr=%.2f mult=%.2f  "
            "profit=%.2f  trades=%d  WR=%.1f%%",
            best.ema_period, best.atr_period,
            best.compression_threshold, best.atr_multiplier,
            best.total_profit, best.num_trades, best.win_rate * 100,
        )
        return results

    # ------------------------------------------------------------------
    # Single-run helper
    # ------------------------------------------------------------------

    def _run_single(
        self,
        candles_df: pd.DataFrame,
        ema_period:            int,
        atr_period:            int,
        compression_threshold: float,
        atr_multiplier:        float,
    ) -> VCBOptimResult:
        # Deep-copy so each run is fully isolated
        cfg = copy.deepcopy(self._cfg)
        cfg.vcb.ema_period            = ema_period
        cfg.vcb.atr_period            = atr_period
        cfg.vcb.compression_threshold = compression_threshold
        cfg.vcb.atr_sl_multiplier     = atr_multiplier
        cfg.vcb.atr_tp_multiplier     = atr_multiplier * 2.0   # fixed 1:2 R:R

        engine = VCBBacktestEngine(cfg, self._capital)

        t0 = time.perf_counter()
        bt_result = engine.run(candles_df)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        metrics = compute_metrics(
            bt_result.trades,
            bt_result.equity_curve,
            self._capital,
        )

        return VCBOptimResult(
            ema_period            = ema_period,
            atr_period            = atr_period,
            compression_threshold = compression_threshold,
            atr_multiplier        = atr_multiplier,
            num_trades            = metrics.num_trades,
            total_profit          = metrics.total_net_profit,
            max_drawdown          = metrics.max_drawdown,
            sharpe_ratio          = metrics.sharpe_ratio,
            profit_factor         = metrics.profit_factor,
            win_rate              = metrics.win_rate,
            avg_trade             = metrics.avg_trade_pnl,
            elapsed_ms            = elapsed_ms,
        )


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def save_vcb_results(results: list[VCBOptimResult], output_path: Path) -> None:
    """
    Write all results to a ranked CSV file.

    Parameters
    ----------
    results : list[VCBOptimResult]
        Grid-search output (sorted by profit descending).
    output_path : Path
        Destination CSV (parent directory is created if needed).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame([r.as_dict() for r in results])
    df.sort_values("total_profit", ascending=False, inplace=True)
    df.reset_index(drop=True, inplace=True)
    df.index += 1   # 1-based rank column
    df.to_csv(output_path, index_label="rank")
    log.info("VCB results saved → %s", output_path)


def print_vcb_top_n(results: list[VCBOptimResult], n: int = 10) -> None:
    """
    Print the top-N results as a formatted table.

    Parameters
    ----------
    results : list[VCBOptimResult]
        Sorted results (best first).
    n : int
        Rows to display.
    """
    top = results[:n]

    # Column widths
    cw = dict(rank=5, ema=6, atr=5, thr=6, mult=6,
              trades=7, profit=11, dd=11, sharpe=8, pf=7, wr=7)

    header = (
        f"{'#':>{cw['rank']}}  "
        f"{'EMA':>{cw['ema']}}  "
        f"{'ATR':>{cw['atr']}}  "
        f"{'Thr':>{cw['thr']}}  "
        f"{'Mult':>{cw['mult']}}  "
        f"{'Trades':>{cw['trades']}}  "
        f"{'Profit $':>{cw['profit']}}  "
        f"{'MaxDD $':>{cw['dd']}}  "
        f"{'Sharpe':>{cw['sharpe']}}  "
        f"{'PF':>{cw['pf']}}  "
        f"{'WR %':>{cw['wr']}}"
    )
    sep = "─" * len(header)

    print(f"\n{'VCB TOP ' + str(n) + ' PARAMETER COMBINATIONS':^{len(header)}}")
    print(sep)
    print(header)
    print(sep)

    for rank, r in enumerate(top, 1):
        pf_str = f"{r.profit_factor:.2f}" if r.profit_factor != float("inf") else "  inf"
        print(
            f"{rank:>{cw['rank']}}  "
            f"{r.ema_period:>{cw['ema']}}  "
            f"{r.atr_period:>{cw['atr']}}  "
            f"{r.compression_threshold:>{cw['thr']}.2f}  "
            f"{r.atr_multiplier:>{cw['mult']}.2f}  "
            f"{r.num_trades:>{cw['trades']}}  "
            f"{r.total_profit:>{cw['profit']}.2f}  "
            f"{r.max_drawdown:>{cw['dd']}.2f}  "
            f"{r.sharpe_ratio:>{cw['sharpe']}.2f}  "
            f"{pf_str:>{cw['pf']}}  "
            f"{r.win_rate * 100:>{cw['wr']}.1f}"
        )

    print(sep)
    print(f"Full results: results/vcb_optimization.csv\n")
