"""
engine.py — Sequential backtest engine.

Iterates over OHLCV candles, feeds them through the strategy, applies
risk rules, submits orders to the broker simulator, and updates the
portfolio.

The engine also handles stop-loss and take-profit checks on each bar
using the high/low of the candle (intra-bar fill simulation).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

import pandas as pd

from backtest.broker_simulator import BrokerSimulator, Order, OrderSide, OrderType
from backtest.portfolio import Portfolio, PositionSide
from config import Config
from data.candle_builder import Candle, iter_candles
from risk.risk_manager import RiskManager
from strategy.opening_range_breakout import ORBStrategy, Signal
from utils.logger import get_logger

log = get_logger("engine")


@dataclass
class BacktestResults:
    """Container for all backtest output data."""
    trades:       list
    equity_curve: list[tuple]
    config:       Config
    candle_count: int


class BacktestEngine:
    """
    Sequential backtesting engine for the ORB strategy.

    Parameters
    ----------
    config : Config
        Full configuration object.
    initial_capital : float
        Starting portfolio cash.
    """

    def __init__(
        self,
        config: Config,
        initial_capital: float = 100_000.0,
    ) -> None:
        self._cfg      = config
        self._broker   = BrokerSimulator(config.broker)
        self._portfolio = Portfolio(initial_capital)
        self._strategy  = ORBStrategy(config.orb)
        self._risk      = RiskManager(config.risk)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, candles_df: pd.DataFrame) -> BacktestResults:
        """
        Execute the backtest over the full candle DataFrame.

        Parameters
        ----------
        candles_df : pd.DataFrame
            OHLCV data indexed by ``timestamp``.

        Returns
        -------
        BacktestResults
        """
        current_session: Optional[date] = None
        candle_count = 0

        for candle in iter_candles(candles_df):
            candle_count += 1

            # ── Session boundary ───────────────────────────────────────
            session_date = candle.timestamp.date()
            if session_date != current_session:
                self._on_new_session(session_date, candle)
                current_session = session_date

            # ── Check SL/TP on open position ───────────────────────────
            if self._portfolio.has_open_position:
                self._check_sl_tp(candle)

            # ── Strategy signal ────────────────────────────────────────
            signal = self._strategy.on_candle(candle)

            # ── Risk gate ──────────────────────────────────────────────
            if signal != Signal.NONE and not self._portfolio.has_open_position:
                if self._risk.can_trade(session_date):
                    self._open_trade(signal, candle)
                else:
                    log.warning("[%s] Risk gate blocked signal %s", candle.timestamp, signal.name)

            # ── Mark-to-market equity update ───────────────────────────
            self._portfolio.update_equity(candle.timestamp, candle.close)

        # ── Force-close any remaining position at end of data ─────────
        if self._portfolio.has_open_position:
            self._force_close(candles_df.index[-1].to_pydatetime(),
                              float(candles_df["close"].iloc[-1]))

        log.info("Engine finished: %d candles, %d trades",
                 candle_count, len(self._portfolio.trades))

        return BacktestResults(
            trades=self._portfolio.trades,
            equity_curve=self._portfolio.equity_curve,
            config=self._cfg,
            candle_count=candle_count,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _on_new_session(self, session_date: date, candle: Candle) -> None:
        """Handle start of a new trading session."""
        log.debug("New session: %s", session_date)
        self._risk.reset_daily(session_date)

    def _open_trade(self, signal: Signal, candle: Candle) -> None:
        """Submit entry order and open portfolio position."""
        side = OrderSide.BUY if signal == Signal.LONG else OrderSide.SELL
        order = Order(
            side=side,
            quantity=self._cfg.risk.position_size,
            order_type=OrderType.MARKET,
        )
        fill = self._broker.execute(order, candle.close, candle.timestamp)

        sl_distance = self._cfg.risk.stop_loss_dollars
        tp_distance = self._cfg.risk.take_profit_dollars

        if signal == Signal.LONG:
            stop_loss   = fill.fill_price - sl_distance
            take_profit = fill.fill_price + tp_distance
        else:
            stop_loss   = fill.fill_price + sl_distance
            take_profit = fill.fill_price - tp_distance

        self._portfolio.open_position_from_fill(fill, stop_loss, take_profit)

    def _check_sl_tp(self, candle: Candle) -> None:
        """
        Check whether the current bar triggers a stop-loss or take-profit.

        Uses intra-bar simulation: if the bar's range touches either level,
        we assume the closer level is hit first.
        """
        pos = self._portfolio.open_position
        if pos is None:
            return

        hit_sl = hit_tp = False

        if pos.side == PositionSide.LONG:
            hit_sl = candle.low  <= pos.stop_loss
            hit_tp = candle.high >= pos.take_profit
        else:  # SHORT
            hit_sl = candle.high >= pos.stop_loss
            hit_tp = candle.low  <= pos.take_profit

        # If both hit in same bar, assume closer one fires first
        if hit_sl and hit_tp:
            # Use distance from open to decide
            sl_dist = abs(candle.open - pos.stop_loss)
            tp_dist = abs(candle.open - pos.take_profit)
            if sl_dist <= tp_dist:
                hit_tp = False
            else:
                hit_sl = False

        if hit_sl:
            self._close_position(pos.stop_loss, candle, "stop_loss")
        elif hit_tp:
            self._close_position(pos.take_profit, candle, "take_profit")

    def _close_position(self, price: float, candle: Candle, reason: str) -> None:
        pos = self._portfolio.open_position
        if pos is None:
            return

        exit_side = OrderSide.SELL if pos.side == PositionSide.LONG else OrderSide.BUY
        order = Order(
            side=exit_side,
            quantity=pos.quantity,
            order_type=OrderType.MARKET,
            tag=reason,
        )
        fill = self._broker.execute(order, price, candle.timestamp)
        trade = self._portfolio.close_position_from_fill(fill, reason)
        self._risk.record_trade(candle.timestamp.date(), trade.pnl)

    def _force_close(self, timestamp, price: float) -> None:
        """Close open position at end of dataset."""
        from datetime import datetime
        if not isinstance(timestamp, datetime):
            from data.candle_builder import Candle as _C
            pass

        pos = self._portfolio.open_position
        if pos is None:
            return

        exit_side = OrderSide.SELL if pos.side == PositionSide.LONG else OrderSide.BUY
        order = Order(
            side=exit_side,
            quantity=pos.quantity,
            order_type=OrderType.MARKET,
            tag="end_of_data",
        )
        fill = self._broker.execute(order, price, timestamp)
        trade = self._portfolio.close_position_from_fill(fill, "end_of_data")
        self._risk.record_trade(timestamp.date(), trade.pnl)
