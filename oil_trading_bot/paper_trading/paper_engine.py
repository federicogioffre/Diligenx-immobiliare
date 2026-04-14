"""
paper_engine.py — Real-time paper trading engine.

Connects the pipeline:
  RealtimeFeed → ORBStrategy → RiskManager → PaperBroker

Runs asynchronously, processing 5-minute candles as they arrive from
the feed (live or simulated).
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

from config import Config
from data.realtime_feed import RealtimeFeed
from paper_trading.paper_broker import ClosedPaperTrade, PaperBroker
from risk.risk_manager import RiskManager
from strategy.opening_range_breakout import ORBStrategy, Signal
from utils.logger import get_logger

log = get_logger("paper_engine")


class PaperEngine:
    """
    Async paper trading engine.

    Listens to a RealtimeFeed, evaluates the ORB strategy on each candle,
    enforces risk rules, and delegates execution to PaperBroker.

    Parameters
    ----------
    config : Config
        Full trading configuration.
    feed : RealtimeFeed
        Source of real-time (or simulated) 5-minute candles.
    """

    def __init__(self, config: Config, feed: RealtimeFeed) -> None:
        self._cfg      = config
        self._feed     = feed
        self._strategy = ORBStrategy(config.orb)
        self._risk     = RiskManager(config.risk)
        self._broker   = PaperBroker(config.broker, config.risk)
        self._running  = False
        self._candles_processed = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def broker(self) -> PaperBroker:
        """Access the underlying PaperBroker (for dashboard / alerts)."""
        return self._broker

    @property
    def risk(self) -> RiskManager:
        return self._risk

    def on_trade_closed(self, callback) -> None:
        """Register an async callback invoked each time a trade closes."""
        self._broker.on_trade_closed(callback)

    async def run(self) -> None:
        """
        Start the paper trading loop.

        Blocks until ``stop()`` is called or the feed is exhausted.
        """
        self._running = True
        await self._feed.start()
        log.info("PaperEngine started — symbol=%s", self._feed.symbol)

        async for candle in self._feed.candles():
            if not self._running:
                break

            self._candles_processed += 1
            today = candle.timestamp.date()

            # Daily risk reset
            self._risk.reset_daily(today)

            # Check SL/TP on new price
            trade = await self._broker.check_sl_tp(candle.close, candle.timestamp)
            if trade is not None:
                self._risk.record_trade(today, trade.pnl)

            # Evaluate strategy
            signal = self._strategy.on_candle(candle)

            # Skip if position open or risk halted
            if self._broker.has_position:
                continue
            if not self._risk.can_trade(today):
                continue

            # Execute signal
            if signal == Signal.LONG:
                try:
                    await self._broker.open_long(candle.close, candle.timestamp)
                except RuntimeError as exc:
                    log.warning("Could not open LONG: %s", exc)

            elif signal == Signal.SHORT:
                try:
                    await self._broker.open_short(candle.close, candle.timestamp)
                except RuntimeError as exc:
                    log.warning("Could not open SHORT: %s", exc)

        log.info(
            "PaperEngine finished — %d candles, %d trades, equity=%.2f",
            self._candles_processed,
            len(self._broker.trade_history),
            self._broker.equity,
        )

    async def stop(self) -> None:
        """Stop the engine and the underlying feed."""
        self._running = False
        await self._feed.stop()
        log.info("PaperEngine stopped")

    def print_summary(self) -> None:
        """Print a brief performance summary to stdout."""
        trades = self._broker.trade_history
        n = len(trades)
        if n == 0:
            print("No trades executed.")
            return

        wins   = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]
        net    = sum(t.pnl for t in trades)
        win_rate = len(wins) / n * 100

        print("\n" + "─" * 44)
        print(" PAPER TRADING SUMMARY")
        print("─" * 44)
        print(f"  Trades          {n:>8}")
        print(f"  Wins            {len(wins):>8}")
        print(f"  Losses          {len(losses):>8}")
        print(f"  Win Rate (%)    {win_rate:>8.1f}")
        print(f"  Net PnL ($)     {net:>+8.2f}")
        print(f"  Final Equity    {self._broker.equity:>8.2f}")
        print("─" * 44 + "\n")
