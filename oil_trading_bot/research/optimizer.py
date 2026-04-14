"""
optimizer.py — Grid-search optimizer for the ORB strategy.

What it optimises
-----------------
Two filter/sizing layers are added on top of the plain ORB strategy:

  EMA trend filter
    Only take LONG signals when the candle close is above the EMA.
    Only take SHORT signals when the candle close is below the EMA.
    Keeps the strategy aligned with the prevailing trend.

  ATR-based stop-loss and take-profit
    SL distance = ATR(candle) * atr_multiplier
    TP distance = ATR(candle) * atr_multiplier * 2   (fixed 1:2 R:R)
    Replaces the fixed-dollar SL/TP in RiskConfig.

Grid
----
  ema_period    : [20, 30, 50, 100]
  atr_period    : [10, 14, 20]
  atr_multiplier: [1.2, 1.5, 1.8, 2.0]
  Total         : 4 × 3 × 4 = 48 combinations

Architecture
------------
FilteredBacktestEngine subclasses BacktestEngine and overrides _open_trade()
and _check_sl_tp() so that it injects the EMA/ATR logic without modifying
any existing module.

Output
------
  results/optimization_results.csv   — all 48 rows
  Ranked top-10 printed to stdout.
"""

from __future__ import annotations

import copy
import itertools
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import pandas as pd

from analytics.metrics import PerformanceMetrics, compute_metrics
from backtest.broker_simulator import Order, OrderSide, OrderType
from backtest.engine import BacktestEngine, BacktestResults
from backtest.portfolio import PositionSide
from config import Config, ORBConfig, RiskConfig
from data.candle_builder import Candle, iter_candles
from utils.logger import get_logger

log = get_logger("optimizer")


# ---------------------------------------------------------------------------
# Indicator helpers (pure pandas, no extra dependencies)
# ---------------------------------------------------------------------------

def compute_ema(series: pd.Series, period: int) -> pd.Series:
    """
    Exponential Moving Average.

    Parameters
    ----------
    series : pd.Series
        Close prices indexed by timestamp.
    period : int
        EMA lookback period (span).

    Returns
    -------
    pd.Series
        EMA values aligned with the input index.
    """
    return series.ewm(span=period, adjust=False).mean()


def compute_atr(df: pd.DataFrame, period: int) -> pd.Series:
    """
    Average True Range.

    True Range = max(H-L, |H-prev_C|, |L-prev_C|)
    ATR        = EMA(TR, period)

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV DataFrame indexed by timestamp.
    period : int
        ATR lookback period.

    Returns
    -------
    pd.Series
        ATR values aligned with the input index.
    """
    high  = df["high"]
    low   = df["low"]
    close = df["close"]

    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low  - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    return tr.ewm(span=period, adjust=False).mean()


# ---------------------------------------------------------------------------
# Parameter set
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OptimParams:
    """A single grid-search parameter combination."""
    ema_period:     int
    atr_period:     int
    atr_multiplier: float


@dataclass
class OptimResult:
    """Metrics collected from one backtest run."""
    ema_period:     int
    atr_period:     int
    atr_multiplier: float
    num_trades:     int
    total_profit:   float
    max_drawdown:   float
    sharpe_ratio:   float
    profit_factor:  float
    win_rate:       float
    avg_trade:      float
    elapsed_ms:     float   # wall-clock time for this run

    def as_dict(self) -> dict:
        return {
            "ema_period":     self.ema_period,
            "atr_period":     self.atr_period,
            "atr_multiplier": self.atr_multiplier,
            "num_trades":     self.num_trades,
            "total_profit":   round(self.total_profit, 4),
            "max_drawdown":   round(self.max_drawdown, 4),
            "sharpe_ratio":   round(self.sharpe_ratio, 4),
            "profit_factor":  round(self.profit_factor, 4),
            "win_rate":       round(self.win_rate * 100, 2),
            "avg_trade":      round(self.avg_trade, 4),
            "elapsed_ms":     round(self.elapsed_ms, 1),
        }


# ---------------------------------------------------------------------------
# Filtered backtest engine
# ---------------------------------------------------------------------------

class FilteredBacktestEngine(BacktestEngine):
    """
    BacktestEngine extended with EMA trend filter and ATR-based SL/TP.

    This subclass does NOT modify any existing module — it only overrides
    ``_open_trade()`` and ``_check_sl_tp()`` to inject the new logic.

    Parameters
    ----------
    config : Config
        Base configuration (SL/TP values will be overridden per-bar by ATR).
    ema : pd.Series
        Pre-computed EMA indexed by timestamp.
    atr : pd.Series
        Pre-computed ATR indexed by timestamp.
    atr_multiplier : float
        ATR multiplier for SL distance.  TP = SL * 2 (1:2 risk-reward).
    initial_capital : float
        Starting cash balance.
    """

    def __init__(
        self,
        config: Config,
        ema: pd.Series,
        atr: pd.Series,
        atr_multiplier: float,
        initial_capital: float = 100_000.0,
    ) -> None:
        super().__init__(config, initial_capital)
        self._ema            = ema
        self._atr            = atr
        self._atr_multiplier = atr_multiplier
        # current-bar ATR/EMA cached during run()
        self._current_ema: float = float("nan")
        self._current_atr: float = float("nan")

    # ------------------------------------------------------------------
    # Override: cache EMA/ATR for the current candle before strategy step
    # ------------------------------------------------------------------

    def run(self, candles_df: pd.DataFrame) -> BacktestResults:
        """
        Identical to BacktestEngine.run() but updates EMA/ATR cache
        on every candle before delegating to the parent's candle loop.
        """
        from datetime import date as _date
        current_session = None
        candle_count = 0

        for candle in iter_candles(candles_df):
            candle_count += 1

            # Cache indicators for this timestamp
            ts = candle.timestamp
            if ts in self._ema.index:
                self._current_ema = float(self._ema.loc[ts])
                self._current_atr = float(self._atr.loc[ts])
            else:
                # Interpolate nearest prior value (forward-fill)
                try:
                    idx = self._ema.index.get_indexer([ts], method="ffill")[0]
                    self._current_ema = float(self._ema.iloc[idx]) if idx >= 0 else float("nan")
                    self._current_atr = float(self._atr.iloc[idx]) if idx >= 0 else float("nan")
                except Exception:
                    self._current_ema = float("nan")
                    self._current_atr = float("nan")

            # Session boundary
            session_date = candle.timestamp.date()
            if session_date != current_session:
                self._on_new_session(session_date, candle)
                current_session = session_date

            # Check SL/TP
            if self._portfolio.has_open_position:
                self._check_sl_tp(candle)

            # Strategy signal
            signal = self._strategy.on_candle(candle)

            # Risk gate + EMA filter
            if signal.name != "NONE" and not self._portfolio.has_open_position:
                if self._risk.can_trade(session_date):
                    if self._passes_ema_filter(signal.name, candle.close):
                        self._open_trade(signal, candle)

            self._portfolio.update_equity(candle.timestamp, candle.close)

        # Force-close any remaining position
        if self._portfolio.has_open_position:
            self._force_close(
                candles_df.index[-1].to_pydatetime(),
                float(candles_df["close"].iloc[-1]),
            )

        log.debug(
            "FilteredEngine: %d candles, %d trades",
            candle_count, len(self._portfolio.trades),
        )

        return BacktestResults(
            trades=self._portfolio.trades,
            equity_curve=self._portfolio.equity_curve,
            config=self._cfg,
            candle_count=candle_count,
        )

    # ------------------------------------------------------------------
    # EMA filter
    # ------------------------------------------------------------------

    def _passes_ema_filter(self, direction: str, close: float) -> bool:
        """Return True if direction aligns with EMA trend (or EMA unavailable)."""
        ema = self._current_ema
        if ema != ema:   # NaN check
            return True  # no filter if indicator not yet warm
        if direction == "LONG"  and close < ema:
            return False
        if direction == "SHORT" and close > ema:
            return False
        return True

    # ------------------------------------------------------------------
    # Override: ATR-based SL/TP
    # ------------------------------------------------------------------

    def _open_trade(self, signal, candle: Candle) -> None:
        """Open trade with ATR-based stop and target."""
        from strategy.opening_range_breakout import Signal
        side = OrderSide.BUY if signal == Signal.LONG else OrderSide.SELL
        order = Order(side=side, quantity=self._cfg.risk.position_size, order_type=OrderType.MARKET)
        fill  = self._broker.execute(order, candle.close, candle.timestamp)

        atr = self._current_atr
        if atr != atr or atr <= 0:                    # NaN or zero → fallback
            atr = self._cfg.risk.stop_loss_dollars / self._atr_multiplier

        sl_dist = atr * self._atr_multiplier
        tp_dist = sl_dist * 2                         # fixed 1:2 risk-reward

        if signal == Signal.LONG:
            stop_loss   = fill.fill_price - sl_dist
            take_profit = fill.fill_price + tp_dist
        else:
            stop_loss   = fill.fill_price + sl_dist
            take_profit = fill.fill_price - tp_dist

        self._portfolio.open_position_from_fill(fill, stop_loss, take_profit)


# ---------------------------------------------------------------------------
# Grid-search optimizer
# ---------------------------------------------------------------------------

# Default parameter grid
EMA_PERIODS     = [20, 30, 50, 100]
ATR_PERIODS     = [10, 14, 20]
ATR_MULTIPLIERS = [1.2, 1.5, 1.8, 2.0]


class GridSearchOptimizer:
    """
    Runs a full grid search over (ema_period, atr_period, atr_multiplier).

    Parameters
    ----------
    base_config : Config
        Base configuration shared across all runs (SL/TP overridden by ATR).
    initial_capital : float
        Starting cash for each backtest run.
    ema_periods : list[int]
        EMA lookback values to test.
    atr_periods : list[int]
        ATR lookback values to test.
    atr_multipliers : list[float]
        ATR multiplier values to test.
    """

    def __init__(
        self,
        base_config: Config,
        initial_capital: float = 100_000.0,
        ema_periods:     list[int]   = EMA_PERIODS,
        atr_periods:     list[int]   = ATR_PERIODS,
        atr_multipliers: list[float] = ATR_MULTIPLIERS,
    ) -> None:
        self._cfg        = base_config
        self._capital    = initial_capital
        self._ema_periods    = ema_periods
        self._atr_periods    = atr_periods
        self._atr_multipliers = atr_multipliers

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, candles_df: pd.DataFrame) -> list[OptimResult]:
        """
        Execute the grid search.

        Parameters
        ----------
        candles_df : pd.DataFrame
            Full OHLCV dataset (same format as used by BacktestEngine).

        Returns
        -------
        list[OptimResult]
            One result per parameter combination, sorted by total_profit desc.
        """
        combinations = list(itertools.product(
            self._ema_periods,
            self._atr_periods,
            self._atr_multipliers,
        ))
        total = len(combinations)
        log.info("Grid search: %d combinations to evaluate", total)

        # Pre-compute all indicator series (avoid redundant calculations)
        ema_cache: dict[int, pd.Series] = {}
        atr_cache: dict[int, pd.Series] = {}

        log.info("Pre-computing indicators...")
        for p in self._ema_periods:
            ema_cache[p] = compute_ema(candles_df["close"], p)
        for p in self._atr_periods:
            atr_cache[p] = compute_atr(candles_df, p)

        results: list[OptimResult] = []

        for i, (ema_p, atr_p, atr_mult) in enumerate(combinations, 1):
            log.info(
                "[%3d/%d] EMA=%3d  ATR=%2d  mult=%.1f",
                i, total, ema_p, atr_p, atr_mult,
            )
            result = self._run_single(
                candles_df   = candles_df,
                ema          = ema_cache[ema_p],
                atr          = atr_cache[atr_p],
                ema_period   = ema_p,
                atr_period   = atr_p,
                atr_mult     = atr_mult,
            )
            results.append(result)

        results.sort(key=lambda r: r.total_profit, reverse=True)
        log.info("Grid search complete — best: EMA=%d ATR=%d mult=%.1f  profit=%.2f",
                 results[0].ema_period, results[0].atr_period,
                 results[0].atr_multiplier, results[0].total_profit)
        return results

    # ------------------------------------------------------------------
    # Single-run helper
    # ------------------------------------------------------------------

    def _run_single(
        self,
        candles_df: pd.DataFrame,
        ema: pd.Series,
        atr: pd.Series,
        ema_period: int,
        atr_period: int,
        atr_mult: float,
    ) -> OptimResult:
        # Deep-copy config so each run is fully independent
        cfg = copy.deepcopy(self._cfg)

        engine = FilteredBacktestEngine(
            config=cfg,
            ema=ema,
            atr=atr,
            atr_multiplier=atr_mult,
            initial_capital=self._capital,
        )

        t0 = time.perf_counter()
        bt_result = engine.run(candles_df)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        metrics = compute_metrics(
            bt_result.trades,
            bt_result.equity_curve,
            self._capital,
        )

        return OptimResult(
            ema_period     = ema_period,
            atr_period     = atr_period,
            atr_multiplier = atr_mult,
            num_trades     = metrics.num_trades,
            total_profit   = metrics.total_net_profit,
            max_drawdown   = metrics.max_drawdown,
            sharpe_ratio   = metrics.sharpe_ratio,
            profit_factor  = metrics.profit_factor,
            win_rate       = metrics.win_rate,
            avg_trade      = metrics.avg_trade_pnl,
            elapsed_ms     = elapsed_ms,
        )


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def save_results(results: list[OptimResult], output_path: Path) -> None:
    """
    Save all results to a CSV file.

    Parameters
    ----------
    results : list[OptimResult]
        Full list of grid-search results.
    output_path : Path
        Destination CSV file (parent directory created if needed).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame([r.as_dict() for r in results])

    # Sort by total_profit descending for readability
    df.sort_values("total_profit", ascending=False, inplace=True)
    df.reset_index(drop=True, inplace=True)
    df.index += 1     # 1-based rank

    df.to_csv(output_path, index_label="rank")
    log.info("Results saved to %s", output_path)


def print_top_n(results: list[OptimResult], n: int = 10) -> None:
    """
    Print the top-N ranked parameter combinations to stdout.

    Parameters
    ----------
    results : list[OptimResult]
        Results sorted by total_profit descending.
    n : int
        How many to show.
    """
    top = results[:n]
    col_w = {
        "rank": 5, "ema": 6, "atr": 5, "mult": 6,
        "trades": 7, "profit": 10, "dd": 10,
        "sharpe": 8, "pf": 7, "wr": 7,
    }
    header = (
        f"{'#':>{col_w['rank']}}  "
        f"{'EMA':>{col_w['ema']}}  "
        f"{'ATR':>{col_w['atr']}}  "
        f"{'Mult':>{col_w['mult']}}  "
        f"{'Trades':>{col_w['trades']}}  "
        f"{'Profit $':>{col_w['profit']}}  "
        f"{'MaxDD $':>{col_w['dd']}}  "
        f"{'Sharpe':>{col_w['sharpe']}}  "
        f"{'PF':>{col_w['pf']}}  "
        f"{'WR %':>{col_w['wr']}}"
    )
    sep = "─" * len(header)

    print(f"\n{'TOP ' + str(n) + ' PARAMETER COMBINATIONS':^{len(header)}}")
    print(sep)
    print(header)
    print(sep)

    for rank, r in enumerate(top, 1):
        pf_str = f"{r.profit_factor:.2f}" if r.profit_factor != float("inf") else "  inf"
        print(
            f"{rank:>{col_w['rank']}}  "
            f"{r.ema_period:>{col_w['ema']}}  "
            f"{r.atr_period:>{col_w['atr']}}  "
            f"{r.atr_multiplier:>{col_w['mult']}.1f}  "
            f"{r.num_trades:>{col_w['trades']}}  "
            f"{r.total_profit:>{col_w['profit']:}.2f}  "
            f"{r.max_drawdown:>{col_w['dd']}.2f}  "
            f"{r.sharpe_ratio:>{col_w['sharpe']}.2f}  "
            f"{pf_str:>{col_w['pf']}}  "
            f"{r.win_rate * 100:>{col_w['wr']}.1f}"
        )

    print(sep)
    print(f"Full results: results/optimization_results.csv\n")
