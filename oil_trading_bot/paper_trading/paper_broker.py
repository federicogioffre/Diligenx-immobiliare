"""
paper_broker.py — Simulated broker operating on live/real-time prices.

Unlike the backtest BrokerSimulator (which processes static historical bars),
PaperBroker tracks positions and PnL in an async real-time session.

Features
--------
- Market fills with configurable slippage and commission
- Single open position at a time (one contract)
- Automatic SL/TP check on each price update
- Async callbacks on trade close (for Telegram alerts, dashboards, etc.)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Callable, Coroutine, Optional

from config import BrokerConfig, RiskConfig
from utils.logger import get_logger

log = get_logger("paper_broker")


class OrderSide(Enum):
    BUY  = auto()
    SELL = auto()


class PositionSide(Enum):
    LONG  = auto()
    SHORT = auto()


@dataclass
class PaperFill:
    """Execution record for a simulated fill."""
    side: OrderSide
    quantity: int
    fill_price: float
    commission: float
    slippage: float
    timestamp: datetime


@dataclass
class OpenPaperPosition:
    """A currently open simulated position."""
    side: PositionSide
    quantity: int
    entry_price: float
    entry_time: datetime
    stop_loss: float
    take_profit: float


@dataclass
class ClosedPaperTrade:
    """A completed trade with PnL."""
    trade_id: int
    side: PositionSide
    quantity: int
    entry_price: float
    exit_price: float
    entry_time: datetime
    exit_time: datetime
    pnl: float
    exit_reason: str


TradeCallback = Callable[[ClosedPaperTrade], Coroutine]


class PaperBroker:
    """
    Paper broker: fills at market with slippage/commission, tracks one position.

    Parameters
    ----------
    broker_config : BrokerConfig
        Slippage and commission model.
    risk_config : RiskConfig
        Stop-loss, take-profit, and position size.
    initial_capital : float
        Starting cash balance.
    """

    def __init__(
        self,
        broker_config: BrokerConfig,
        risk_config: RiskConfig,
        initial_capital: float = 100_000.0,
    ) -> None:
        self._broker_cfg = broker_config
        self._risk_cfg   = risk_config
        self._cash       = initial_capital
        self._initial    = initial_capital
        self._position: Optional[OpenPaperPosition] = None
        self._trades: list[ClosedPaperTrade] = []
        self._trade_counter = 0
        self._equity_curve: list[tuple[datetime, float]] = []
        self._callbacks: list[TradeCallback] = []

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def on_trade_closed(self, callback: TradeCallback) -> None:
        """Register an async callback invoked each time a trade closes."""
        self._callbacks.append(callback)

    # ------------------------------------------------------------------
    # Order execution
    # ------------------------------------------------------------------

    async def open_long(self, price: float, timestamp: datetime) -> PaperFill:
        """Open a long position at ``price``."""
        return await self._open(OrderSide.BUY, price, timestamp)

    async def open_short(self, price: float, timestamp: datetime) -> PaperFill:
        """Open a short position at ``price``."""
        return await self._open(OrderSide.SELL, price, timestamp)

    async def close_position(
        self,
        price: float,
        timestamp: datetime,
        reason: str,
    ) -> Optional[ClosedPaperTrade]:
        """
        Close the current open position.

        Returns
        -------
        Optional[ClosedPaperTrade]
            The completed trade, or ``None`` if no position was open.
        """
        if self._position is None:
            return None

        pos = self._position
        close_side = OrderSide.SELL if pos.side == PositionSide.LONG else OrderSide.BUY
        fill = self._make_fill(close_side, price, timestamp)

        gross = (fill.fill_price - pos.entry_price) * pos.quantity
        if pos.side == PositionSide.SHORT:
            gross = -gross
        net_pnl = gross - fill.commission

        self._trade_counter += 1
        trade = ClosedPaperTrade(
            trade_id=self._trade_counter,
            side=pos.side,
            quantity=pos.quantity,
            entry_price=pos.entry_price,
            exit_price=fill.fill_price,
            entry_time=pos.entry_time,
            exit_time=timestamp,
            pnl=net_pnl,
            exit_reason=reason,
        )

        self._cash += net_pnl
        self._position = None
        self._trades.append(trade)
        self._equity_curve.append((timestamp, self._cash))

        log.info(
            "Trade#%d %s  entry=%.3f exit=%.3f  pnl=%+.2f [%s]  equity=%.2f",
            trade.trade_id, pos.side.name,
            pos.entry_price, fill.fill_price,
            net_pnl, reason, self._cash,
        )

        for cb in self._callbacks:
            await cb(trade)

        return trade

    # ------------------------------------------------------------------
    # SL/TP monitoring
    # ------------------------------------------------------------------

    async def check_sl_tp(
        self,
        current_price: float,
        timestamp: datetime,
    ) -> Optional[ClosedPaperTrade]:
        """
        Check whether stop-loss or take-profit has been breached.

        Call this on every new candle close price.
        """
        if self._position is None:
            return None

        pos = self._position
        if pos.side == PositionSide.LONG:
            if current_price <= pos.stop_loss:
                return await self.close_position(pos.stop_loss, timestamp, "stop_loss")
            if current_price >= pos.take_profit:
                return await self.close_position(pos.take_profit, timestamp, "take_profit")
        else:
            if current_price >= pos.stop_loss:
                return await self.close_position(pos.stop_loss, timestamp, "stop_loss")
            if current_price <= pos.take_profit:
                return await self.close_position(pos.take_profit, timestamp, "take_profit")

        return None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def has_position(self) -> bool:
        return self._position is not None

    @property
    def position(self) -> Optional[OpenPaperPosition]:
        return self._position

    @property
    def equity(self) -> float:
        return self._cash

    @property
    def daily_pnl(self) -> float:
        return self._cash - self._initial

    @property
    def trade_history(self) -> list[ClosedPaperTrade]:
        return list(self._trades)

    @property
    def equity_curve(self) -> list[tuple[datetime, float]]:
        return list(self._equity_curve)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _open(
        self,
        side: OrderSide,
        price: float,
        timestamp: datetime,
    ) -> PaperFill:
        if self._position is not None:
            raise RuntimeError("Cannot open position: already in a trade")

        fill = self._make_fill(side, price, timestamp)
        self._cash -= fill.commission  # entry commission

        is_long = side == OrderSide.BUY
        sl = (
            fill.fill_price - self._risk_cfg.stop_loss_dollars
            if is_long else
            fill.fill_price + self._risk_cfg.stop_loss_dollars
        )
        tp = (
            fill.fill_price + self._risk_cfg.take_profit_dollars
            if is_long else
            fill.fill_price - self._risk_cfg.take_profit_dollars
        )

        self._position = OpenPaperPosition(
            side=PositionSide.LONG if is_long else PositionSide.SHORT,
            quantity=self._risk_cfg.position_size,
            entry_price=fill.fill_price,
            entry_time=timestamp,
            stop_loss=sl,
            take_profit=tp,
        )

        log.info(
            "Position OPENED: %s  entry=%.3f  SL=%.3f  TP=%.3f",
            self._position.side.name, fill.fill_price, sl, tp,
        )
        self._equity_curve.append((timestamp, self._cash))
        return fill

    def _make_fill(self, side: OrderSide, price: float, timestamp: datetime) -> PaperFill:
        slip = self._broker_cfg.slippage_per_side
        fill_price = price + slip if side == OrderSide.BUY else price - slip
        return PaperFill(
            side=side,
            quantity=self._risk_cfg.position_size,
            fill_price=fill_price,
            commission=self._broker_cfg.commission_per_side,
            slippage=slip,
            timestamp=timestamp,
        )
