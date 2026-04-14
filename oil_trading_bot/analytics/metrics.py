"""
metrics.py — Performance metrics for backtesting results.

Computed metrics:
  - Total Net Profit
  - Max Drawdown (dollar and %)
  - Profit Factor
  - Win Rate
  - Average Trade PnL
  - Sharpe Ratio (annualised)
  - Expectancy
  - Number of Trades
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import pandas as pd

from backtest.portfolio import Trade
from config import RISK_FREE_RATE_ANNUAL, TRADING_DAYS_PER_YEAR


@dataclass
class PerformanceMetrics:
    """Aggregated performance statistics for a backtest run."""
    num_trades:        int
    total_net_profit:  float
    win_rate:          float    # 0–1
    profit_factor:     float    # gross_profit / gross_loss; inf if no losses
    avg_trade_pnl:     float
    max_drawdown:      float    # peak-to-trough in dollars
    max_drawdown_pct:  float    # peak-to-trough as % of peak equity
    sharpe_ratio:      float    # annualised
    expectancy:        float    # avg $ per trade weighted by probability
    gross_profit:      float
    gross_loss:        float    # always ≥ 0
    num_winners:       int
    num_losers:        int

    def as_dict(self) -> dict:
        return {
            "Trades":           self.num_trades,
            "Net Profit ($)":   f"{self.total_net_profit:+.2f}",
            "Win Rate (%)":     f"{self.win_rate * 100:.1f}",
            "Profit Factor":    f"{self.profit_factor:.2f}",
            "Avg Trade ($)":    f"{self.avg_trade_pnl:+.2f}",
            "Max Drawdown ($)": f"{self.max_drawdown:.2f}",
            "Max DD (%)":       f"{self.max_drawdown_pct:.1f}",
            "Sharpe Ratio":     f"{self.sharpe_ratio:.2f}",
            "Expectancy ($)":   f"{self.expectancy:+.2f}",
            "Gross Profit ($)": f"{self.gross_profit:.2f}",
            "Gross Loss ($)":   f"{self.gross_loss:.2f}",
        }

    def __str__(self) -> str:
        lines = ["─" * 42, " PERFORMANCE METRICS", "─" * 42]
        for k, v in self.as_dict().items():
            lines.append(f"  {k:<22} {v:>12}")
        lines.append("─" * 42)
        return "\n".join(lines)


def compute_metrics(
    trades: Sequence[Trade],
    equity_curve: Sequence[tuple],
    initial_capital: float = 100_000.0,
) -> PerformanceMetrics:
    """
    Compute all performance metrics from a list of trades and equity curve.

    Parameters
    ----------
    trades : sequence of Trade
        Completed round-trip trades.
    equity_curve : sequence of (datetime, float) tuples
        Running equity values recorded during the backtest.
    initial_capital : float
        Starting capital (used for drawdown %).

    Returns
    -------
    PerformanceMetrics
    """
    if not trades:
        return PerformanceMetrics(
            num_trades=0, total_net_profit=0, win_rate=0, profit_factor=0,
            avg_trade_pnl=0, max_drawdown=0, max_drawdown_pct=0,
            sharpe_ratio=0, expectancy=0, gross_profit=0, gross_loss=0,
            num_winners=0, num_losers=0,
        )

    pnls = [t.pnl for t in trades]
    winners = [p for p in pnls if p > 0]
    losers  = [p for p in pnls if p <= 0]

    gross_profit = sum(winners) if winners else 0.0
    gross_loss   = abs(sum(losers)) if losers else 0.0

    num_trades   = len(trades)
    num_winners  = len(winners)
    num_losers   = len(losers)
    win_rate     = num_winners / num_trades
    total_pnl    = sum(pnls)
    avg_trade    = total_pnl / num_trades

    profit_factor = (
        gross_profit / gross_loss if gross_loss > 0 else float("inf")
    )

    # Expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)
    avg_win  = sum(winners) / len(winners) if winners else 0.0
    avg_loss = sum(losers)  / len(losers)  if losers  else 0.0
    expectancy = win_rate * avg_win + (1 - win_rate) * avg_loss

    # ── Max Drawdown from equity curve ────────────────────────────────
    equity_values = [eq for _, eq in equity_curve]
    max_dd, max_dd_pct = _max_drawdown(equity_values, initial_capital)

    # ── Sharpe Ratio ──────────────────────────────────────────────────
    sharpe = _sharpe_ratio(pnls, initial_capital)

    return PerformanceMetrics(
        num_trades=num_trades,
        total_net_profit=total_pnl,
        win_rate=win_rate,
        profit_factor=profit_factor,
        avg_trade_pnl=avg_trade,
        max_drawdown=max_dd,
        max_drawdown_pct=max_dd_pct,
        sharpe_ratio=sharpe,
        expectancy=expectancy,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        num_winners=num_winners,
        num_losers=num_losers,
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _max_drawdown(equity: list[float], initial_capital: float) -> tuple[float, float]:
    """Return (max_drawdown_dollars, max_drawdown_pct)."""
    if not equity:
        return 0.0, 0.0

    peak = initial_capital
    max_dd = 0.0

    for val in equity:
        if val > peak:
            peak = val
        drawdown = peak - val
        if drawdown > max_dd:
            max_dd = drawdown

    max_dd_pct = (max_dd / peak * 100) if peak > 0 else 0.0
    return max_dd, max_dd_pct


def _sharpe_ratio(
    pnls: list[float],
    initial_capital: float,
) -> float:
    """
    Annualised Sharpe ratio calculated from per-trade returns.

    Uses daily-trade frequency assumption for annualisation.
    """
    if len(pnls) < 2:
        return 0.0

    returns = [p / initial_capital for p in pnls]
    mean_r  = sum(returns) / len(returns)
    variance = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
    std_r   = math.sqrt(variance) if variance > 0 else 0.0

    if std_r == 0:
        return 0.0

    daily_rf = RISK_FREE_RATE_ANNUAL / TRADING_DAYS_PER_YEAR
    sharpe   = (mean_r - daily_rf) / std_r * math.sqrt(TRADING_DAYS_PER_YEAR)
    return sharpe
