"""
report.py — Visual and tabular reporting for backtest results.

Generates:
  1. Equity curve plot (PNG)
  2. PnL per trade bar chart (PNG)
  3. Summary metrics table (printed to console and saved as TXT)
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import matplotlib
matplotlib.use("Agg")  # non-interactive backend — safe in headless environments
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

from analytics.metrics import compute_metrics, PerformanceMetrics
from backtest.engine import BacktestResults
from utils.logger import get_logger

log = get_logger("report")


def generate_report(
    results: BacktestResults,
    output_dir: Path,
    initial_capital: float = 100_000.0,
) -> None:
    """
    Generate the full backtest report and save artefacts to ``output_dir``.

    Files created:
      - ``equity_curve.png``
      - ``pnl_per_trade.png``
      - ``summary.txt``

    Parameters
    ----------
    results : BacktestResults
        Output from ``BacktestEngine.run()``.
    output_dir : Path
        Directory where report files are saved (created if absent).
    initial_capital : float
        Starting capital for drawdown % calculation.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    metrics = compute_metrics(results.trades, results.equity_curve, initial_capital)

    # ── 1. Console summary ─────────────────────────────────────────────
    print(metrics)

    # ── 2. Save summary TXT ────────────────────────────────────────────
    summary_path = output_dir / "summary.txt"
    summary_path.write_text(str(metrics), encoding="utf-8")
    log.info("Summary written: %s", summary_path)

    # ── 3. Equity curve plot ───────────────────────────────────────────
    _plot_equity_curve(results, metrics, output_dir / "equity_curve.png", initial_capital)

    # ── 4. PnL per trade bar chart ─────────────────────────────────────
    _plot_pnl_per_trade(results, output_dir / "pnl_per_trade.png")


# ---------------------------------------------------------------------------
# Plot helpers
# ---------------------------------------------------------------------------

def _plot_equity_curve(
    results: BacktestResults,
    metrics: PerformanceMetrics,
    path: Path,
    initial_capital: float,
) -> None:
    """Save the equity curve as a PNG."""
    if not results.equity_curve:
        log.warning("No equity curve data — skipping plot.")
        return

    timestamps, values = zip(*results.equity_curve)

    fig, ax = plt.subplots(figsize=(14, 5))
    ax.plot(timestamps, values, linewidth=1.5, color="#1f77b4", label="Equity")
    ax.axhline(initial_capital, color="grey", linestyle="--", linewidth=0.8, label="Initial Capital")

    # Shade drawdown regions
    peak = initial_capital
    prev_ts = timestamps[0]
    dd_start = None
    for ts, val in zip(timestamps, values):
        if val > peak:
            if dd_start is not None:
                ax.axvspan(dd_start, prev_ts, alpha=0.12, color="red")
                dd_start = None
            peak = val
        elif val < peak and dd_start is None:
            dd_start = ts
        prev_ts = ts
    if dd_start is not None:
        ax.axvspan(dd_start, timestamps[-1], alpha=0.12, color="red")

    final = values[-1]
    colour = "#2ca02c" if final >= initial_capital else "#d62728"
    ax.annotate(
        f"Final: ${final:,.0f}",
        xy=(timestamps[-1], final),
        xytext=(-80, 15),
        textcoords="offset points",
        arrowprops=dict(arrowstyle="->", color=colour),
        color=colour,
        fontsize=9,
    )

    ax.set_title("Equity Curve", fontsize=13, fontweight="bold")
    ax.set_xlabel("Date")
    ax.set_ylabel("Portfolio Value ($)")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(True, alpha=0.3)

    stats_text = (
        f"Trades: {metrics.num_trades}  |  "
        f"Net P&L: ${metrics.total_net_profit:+,.0f}  |  "
        f"Max DD: ${metrics.max_drawdown:,.0f} ({metrics.max_drawdown_pct:.1f}%)  |  "
        f"Sharpe: {metrics.sharpe_ratio:.2f}  |  "
        f"Win Rate: {metrics.win_rate*100:.0f}%"
    )
    fig.text(0.5, 0.01, stats_text, ha="center", fontsize=8, color="dimgrey")

    fig.tight_layout(rect=[0, 0.04, 1, 1])
    fig.savefig(path, dpi=150)
    plt.close(fig)
    log.info("Equity curve saved: %s", path)


def _plot_pnl_per_trade(results: BacktestResults, path: Path) -> None:
    """Save a per-trade PnL bar chart."""
    if not results.trades:
        log.warning("No trades — skipping PnL per trade plot.")
        return

    pnls   = [t.pnl for t in results.trades]
    labels = [f"#{t.trade_id}" for t in results.trades]
    colours = ["#2ca02c" if p >= 0 else "#d62728" for p in pnls]

    fig, ax = plt.subplots(figsize=(max(8, len(pnls) * 0.6), 4))
    bars = ax.bar(labels, pnls, color=colours, edgecolor="white", linewidth=0.5)

    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_title("PnL per Trade", fontsize=12, fontweight="bold")
    ax.set_xlabel("Trade")
    ax.set_ylabel("Net PnL ($)")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x:+,.0f}"))

    # Annotate each bar with its value
    for bar, val in zip(bars, pnls):
        y_pos = bar.get_height() + (2 if val >= 0 else -8)
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            y_pos,
            f"{val:+.0f}",
            ha="center", va="bottom", fontsize=7,
        )

    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    log.info("PnL per trade saved: %s", path)
