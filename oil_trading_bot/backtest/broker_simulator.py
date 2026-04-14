"""
broker_simulator.py — Simulated broker with slippage and commissions.

The broker receives an ``Order`` and returns a ``Fill`` (executed trade
record) with the actual execution price adjusted for slippage and the
total round-trip cost adjusted for commissions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from typing import Optional

from config import BrokerConfig
from utils.logger import get_logger

log = get_logger("broker_simulator")


class OrderSide(Enum):
    BUY  = auto()
    SELL = auto()


class OrderType(Enum):
    MARKET = auto()
    LIMIT  = auto()     # reserved for future use


@dataclass
class Order:
    """Represents a trade request submitted to the broker."""
    side:       OrderSide
    quantity:   int                   # number of contracts (positive integer)
    order_type: OrderType = OrderType.MARKET
    limit_price: Optional[float] = None
    tag:        str = ""              # optional label (e.g. "stop_loss", "take_profit")


@dataclass
class Fill:
    """Represents a successfully executed order."""
    order:           Order
    requested_price: float            # mid-market price at submission
    fill_price:      float            # price after slippage
    commission:      float            # total commission (both sides combined)
    timestamp:       datetime
    slippage:        float            # per-side slippage applied

    @property
    def total_cost(self) -> float:
        """Round-trip commission cost."""
        return self.commission

    def __str__(self) -> str:
        return (
            f"Fill({self.order.side.name} {self.order.quantity}  "
            f"fill={self.fill_price:.3f}  slip={self.slippage:.3f}  "
            f"comm={self.commission:.2f}  @ {self.timestamp:%H:%M:%S})"
        )


class BrokerSimulator:
    """
    Simulated broker that introduces slippage and charges commissions.

    Parameters
    ----------
    broker_config : BrokerConfig
        Slippage and commission parameters.
    """

    def __init__(self, broker_config: BrokerConfig) -> None:
        self._cfg = broker_config

    def execute(
        self,
        order: Order,
        market_price: float,
        timestamp: datetime,
    ) -> Fill:
        """
        Simulate order execution at ``market_price``.

        Slippage is applied *against* the trader:
          - BUY  orders are filled slightly *above* market.
          - SELL orders are filled slightly *below* market.

        Parameters
        ----------
        order : Order
            The order to execute.
        market_price : float
            The current mid/close price used as the reference.
        timestamp : datetime
            Bar timestamp at execution.

        Returns
        -------
        Fill
            Executed fill record.
        """
        slip = self._cfg.slippage_per_side

        if order.side == OrderSide.BUY:
            fill_price = market_price + slip
        else:  # SELL
            fill_price = market_price - slip

        commission = self._cfg.commission_per_side * 2 * order.quantity  # round-trip

        fill = Fill(
            order=order,
            requested_price=market_price,
            fill_price=fill_price,
            commission=commission,
            timestamp=timestamp,
            slippage=slip,
        )

        log.info("Broker: %s", fill)
        return fill
