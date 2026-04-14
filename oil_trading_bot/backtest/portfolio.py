"""
portfolio.py — Portfolio and position tracking.

Tracks open positions, trade history, PnL per trade, and the running
equity curve throughout the backtest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Optional

from backtest.broker_simulator import Fill, OrderSide
from utils.logger import get_logger

log = get_logger("portfolio")


class PositionSide(Enum):
    LONG  = auto()
    SHORT = auto()


@dataclass
class Trade:
    """Completed round-trip trade record."""
    trade_id:    int
    side:        PositionSide
    quantity:    int
    entry_price: float
    exit_price:  float
    entry_time:  datetime
    exit_time:   datetime
    pnl:         float          # net PnL after commissions
    commissions: float
    exit_reason: str            # "take_profit", "stop_loss", "end_of_day", etc.

    @property
    def gross_pnl(self) -> float:
        if self.side == PositionSide.LONG:
            return (self.exit_price - self.entry_price) * self.quantity
        else:
            return (self.entry_price - self.exit_price) * self.quantity

    def __str__(self) -> str:
        return (
            f"Trade#{self.trade_id}  {self.side.name}  "
            f"entry={self.entry_price:.3f}  exit={self.exit_price:.3f}  "
            f"pnl={self.pnl:+.2f}  [{self.exit_reason}]"
        )


@dataclass
class OpenPosition:
    """An active (not yet closed) position."""
    side:         PositionSide
    quantity:     int
    entry_price:  float
    entry_time:   datetime
    stop_loss:    float
    take_profit:  float
    entry_fill:   Fill

    def unrealised_pnl(self, current_price: float) -> float:
        if self.side == PositionSide.LONG:
            return (current_price - self.entry_price) * self.quantity
        else:
            return (self.entry_price - current_price) * self.quantity


class Portfolio:
    """
    Tracks positions, trades, PnL, and the equity curve.

    Parameters
    ----------
    initial_capital : float
        Starting cash balance.
    """

    def __init__(self, initial_capital: float = 100_000.0) -> None:
        self._initial_capital: float  = initial_capital
        self._cash:            float  = initial_capital
        self._trade_counter:   int    = 0
        self._open_position:   Optional[OpenPosition] = None
        self.trades:           list[Trade]            = []
        self.equity_curve:     list[tuple[datetime, float]] = []

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def cash(self) -> float:
        return self._cash

    @property
    def has_open_position(self) -> bool:
        return self._open_position is not None

    @property
    def open_position(self) -> Optional[OpenPosition]:
        return self._open_position

    @property
    def total_equity(self) -> float:
        return self._cash

    @property
    def total_pnl(self) -> float:
        return self._cash - self._initial_capital

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def open_position_from_fill(
        self,
        fill: Fill,
        stop_loss: float,
        take_profit: float,
    ) -> None:
        """Record a new open position from a broker fill."""
        if self._open_position is not None:
            log.warning("Attempting to open a second position — ignored.")
            return

        side = PositionSide.LONG if fill.order.side == OrderSide.BUY else PositionSide.SHORT

        self._open_position = OpenPosition(
            side=side,
            quantity=fill.order.quantity,
            entry_price=fill.fill_price,
            entry_time=fill.timestamp,
            stop_loss=stop_loss,
            take_profit=take_profit,
            entry_fill=fill,
        )

        # Deduct entry commission
        self._cash -= fill.commission / 2  # half on entry, half on exit

        log.info(
            "Position OPENED: %s  qty=%d  entry=%.3f  SL=%.3f  TP=%.3f",
            side.name, fill.order.quantity, fill.fill_price, stop_loss, take_profit,
        )
        self._record_equity(fill.timestamp)

    def close_position_from_fill(
        self,
        fill: Fill,
        exit_reason: str,
    ) -> Trade:
        """
        Close the current open position and record the completed trade.

        Returns
        -------
        Trade
            The closed trade with net PnL.
        """
        if self._open_position is None:
            raise RuntimeError("close_position called with no open position")

        pos = self._open_position
        self._trade_counter += 1

        gross = pos.unrealised_pnl(fill.fill_price)
        exit_commission = fill.commission / 2
        net_pnl = gross - exit_commission

        trade = Trade(
            trade_id=self._trade_counter,
            side=pos.side,
            quantity=pos.quantity,
            entry_price=pos.entry_price,
            exit_price=fill.fill_price,
            entry_time=pos.entry_time,
            exit_time=fill.timestamp,
            pnl=net_pnl,
            commissions=pos.entry_fill.commission / 2 + exit_commission,
            exit_reason=exit_reason,
        )

        self._cash += net_pnl
        self._open_position = None
        self.trades.append(trade)

        log.info("%s  net_pnl=%+.2f  equity=%.2f", trade, net_pnl, self._cash)
        self._record_equity(fill.timestamp)
        return trade

    def update_equity(self, timestamp: datetime, current_price: float) -> None:
        """Record current mark-to-market equity (called each bar)."""
        mtm = self._cash
        if self._open_position:
            mtm += self._open_position.unrealised_pnl(current_price)
        self.equity_curve.append((timestamp, mtm))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _record_equity(self, timestamp: datetime) -> None:
        self.equity_curve.append((timestamp, self._cash))

    def summary(self) -> dict:
        return {
            "initial_capital": self._initial_capital,
            "final_equity":    self._cash,
            "total_pnl":       self.total_pnl,
            "num_trades":      len(self.trades),
        }
