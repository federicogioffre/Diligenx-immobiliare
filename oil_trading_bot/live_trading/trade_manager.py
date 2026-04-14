"""
trade_manager.py — Tracks open positions and closed trade history in live trading.

Responsibilities
----------------
- Register / close live positions
- Monitor SL/TP breaches on each price tick
- Compute unrealised and daily PnL
- Invoke async callbacks on trade close (Telegram, dashboard, etc.)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable, Coroutine, Optional

from utils.logger import get_logger

log = get_logger("trade_manager")


@dataclass
class LivePosition:
    """An open position being tracked."""
    symbol: str
    side: str               # "LONG" | "SHORT"
    quantity: int
    entry_price: float
    entry_time: datetime
    stop_loss: float
    take_profit: float
    order_id: int = 0


@dataclass
class LiveTrade:
    """A completed trade record."""
    trade_id: int
    symbol: str
    side: str
    quantity: int
    entry_price: float
    exit_price: float
    entry_time: datetime
    exit_time: datetime
    pnl: float
    exit_reason: str


TradeClosedCallback = Callable[[LiveTrade], Coroutine]


class TradeManager:
    """
    Manages open positions and trade history for live trading.

    Parameters
    ----------
    on_trade_closed : TradeClosedCallback, optional
        Async callback invoked each time a position closes.
    """

    def __init__(self, on_trade_closed: Optional[TradeClosedCallback] = None) -> None:
        self._positions: dict[str, LivePosition] = {}
        self._history: list[LiveTrade] = []
        self._counter = 0
        self._daily_pnl: dict[date, float] = {}
        self._callbacks: list[TradeClosedCallback] = []
        if on_trade_closed:
            self._callbacks.append(on_trade_closed)

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def on_trade_closed(self, callback: TradeClosedCallback) -> None:
        self._callbacks.append(callback)

    # ------------------------------------------------------------------
    # Position lifecycle
    # ------------------------------------------------------------------

    def open_position(self, position: LivePosition) -> None:
        """Register a new open position."""
        if position.symbol in self._positions:
            log.warning("Position already open for %s — overwriting", position.symbol)
        self._positions[position.symbol] = position
        log.info(
            "Position OPENED: %s %s  qty=%d  entry=%.3f  SL=%.3f  TP=%.3f",
            position.side, position.symbol, position.quantity,
            position.entry_price, position.stop_loss, position.take_profit,
        )

    async def close_position(
        self,
        symbol: str,
        exit_price: float,
        exit_time: datetime,
        reason: str,
    ) -> Optional[LiveTrade]:
        """
        Close a tracked position, compute PnL, and fire callbacks.

        Returns
        -------
        Optional[LiveTrade]
            The completed trade, or ``None`` if no position existed.
        """
        pos = self._positions.pop(symbol, None)
        if pos is None:
            log.warning("close_position: no open position for %s", symbol)
            return None

        gross = (exit_price - pos.entry_price) * pos.quantity
        if pos.side == "SHORT":
            gross = -gross

        self._counter += 1
        trade = LiveTrade(
            trade_id=self._counter,
            symbol=symbol,
            side=pos.side,
            quantity=pos.quantity,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            entry_time=pos.entry_time,
            exit_time=exit_time,
            pnl=gross,
            exit_reason=reason,
        )
        self._history.append(trade)

        day = exit_time.date()
        self._daily_pnl[day] = self._daily_pnl.get(day, 0.0) + gross

        log.info(
            "Trade#%d CLOSED: %s %s  entry=%.3f exit=%.3f  pnl=%+.2f [%s]",
            trade.trade_id, pos.side, symbol,
            pos.entry_price, exit_price, gross, reason,
        )

        for cb in self._callbacks:
            await cb(trade)

        return trade

    # ------------------------------------------------------------------
    # SL/TP monitoring
    # ------------------------------------------------------------------

    def check_triggers(self, symbol: str, current_price: float) -> Optional[str]:
        """
        Check whether SL or TP has been hit for an open position.

        Returns
        -------
        Optional[str]
            ``'stop_loss'``, ``'take_profit'``, or ``None``.
        """
        pos = self._positions.get(symbol)
        if pos is None:
            return None

        if pos.side == "LONG":
            if current_price <= pos.stop_loss:
                return "stop_loss"
            if current_price >= pos.take_profit:
                return "take_profit"
        else:
            if current_price >= pos.stop_loss:
                return "stop_loss"
            if current_price <= pos.take_profit:
                return "take_profit"

        return None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def open_positions(self) -> dict[str, LivePosition]:
        return dict(self._positions)

    @property
    def trade_history(self) -> list[LiveTrade]:
        return list(self._history)

    def get_daily_pnl(self, day: Optional[date] = None) -> float:
        return self._daily_pnl.get(day or date.today(), 0.0)

    def unrealised_pnl(self, symbol: str, current_price: float) -> float:
        pos = self._positions.get(symbol)
        if pos is None:
            return 0.0
        gross = (current_price - pos.entry_price) * pos.quantity
        return gross if pos.side == "LONG" else -gross
