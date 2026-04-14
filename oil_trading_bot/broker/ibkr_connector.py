"""
ibkr_connector.py — Interactive Brokers connector via ib_insync.

Prerequisites
-------------
  pip install ib_insync
  TWS or IB Gateway must be running on host:port before calling connect().

Default ports
-------------
  TWS paper trading : 7497
  TWS live trading  : 7496
  IB Gateway paper  : 4002
  IB Gateway live   : 4001
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

try:
    from ib_insync import IB, Future, MarketOrder, LimitOrder, StopOrder
    HAS_IB_INSYNC = True
except ImportError:
    HAS_IB_INSYNC = False

from data.realtime_feed import RealtimeFeed, Tick
from utils.logger import get_logger

log = get_logger("ibkr_connector")


@dataclass
class IBKRConfig:
    """Connection and instrument parameters."""
    host: str  = "127.0.0.1"
    port: int  = 7497           # 7497 = TWS paper; 7496 = TWS live
    client_id: int = 1
    symbol: str = "CL"          # WTI Crude Oil futures
    exchange: str = "NYMEX"
    currency: str = "USD"
    last_trade_date: str = ""   # e.g. "20241220" — nearest active contract


@dataclass
class OrderResult:
    """Outcome of a placed order."""
    order_id: int
    symbol: str
    side: str           # "BUY" | "SELL"
    quantity: int
    fill_price: float
    status: str
    timestamp: datetime = field(default_factory=datetime.now)


class IBKRConnector:
    """
    Async wrapper around ib_insync for Interactive Brokers.

    Parameters
    ----------
    config : IBKRConfig
        Connection and instrument settings.
    """

    def __init__(self, config: IBKRConfig) -> None:
        if not HAS_IB_INSYNC:
            raise RuntimeError("Install ib_insync: pip install ib_insync")
        self._cfg = config
        self._ib = IB()
        self._contract = None
        self._connected = False

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Connect to TWS / IB Gateway."""
        log.info(
            "Connecting to IBKR at %s:%d (clientId=%d)",
            self._cfg.host, self._cfg.port, self._cfg.client_id,
        )
        await self._ib.connectAsync(
            host=self._cfg.host,
            port=self._cfg.port,
            clientId=self._cfg.client_id,
        )
        self._contract = self._build_contract()
        await self._ib.qualifyContractsAsync(self._contract)
        self._connected = True
        log.info("IBKR connected — contract: %s", self._contract)

    async def disconnect(self) -> None:
        """Disconnect cleanly."""
        if self._connected:
            self._ib.disconnect()
            self._connected = False
            log.info("IBKR disconnected")

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    async def get_market_data(self) -> dict:
        """
        Request a snapshot of bid/ask/last/volume.

        Returns
        -------
        dict
            Keys: ``bid``, ``ask``, ``last``, ``volume``, ``timestamp``.
        """
        self._assert_connected()
        ticker = self._ib.reqMktData(self._contract, "", True, False)
        await asyncio.sleep(1.0)
        result = {
            "bid":       ticker.bid,
            "ask":       ticker.ask,
            "last":      ticker.last,
            "volume":    ticker.volume,
            "timestamp": datetime.now(),
        }
        self._ib.cancelMktData(self._contract)
        return result

    async def stream_realtime_bars(self, feed: RealtimeFeed) -> None:
        """
        Subscribe to 5-second real-time bars and push ticks into a RealtimeFeed.

        IBKR provides 5-second bars via ``reqRealTimeBars``. Each bar's
        close price is pushed as a Tick; the RealtimeFeed aggregates them
        into 5-minute candles.
        """
        self._assert_connected()
        log.info("Subscribing to real-time bars for %s", self._cfg.symbol)
        bars = self._ib.reqRealTimeBars(self._contract, 5, "TRADES", False)

        async def _on_bar(bars, has_new_bar: bool) -> None:
            if has_new_bar:
                bar = bars[-1]
                tick = Tick(
                    symbol=self._cfg.symbol,
                    timestamp=datetime.fromtimestamp(bar.time),
                    price=float(bar.close),
                    volume=float(bar.volume),
                )
                await feed.put_tick(tick)

        bars.updateEvent += _on_bar
        log.info("Real-time bar subscription active")

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    async def place_market_order(self, side: str, quantity: int) -> OrderResult:
        """
        Place a market order and wait for fill (up to 10 s).

        Parameters
        ----------
        side : str
            ``'BUY'`` or ``'SELL'``.
        quantity : int
            Number of contracts.
        """
        self._assert_connected()
        order = MarketOrder(side, quantity)
        trade = self._ib.placeOrder(self._contract, order)

        for _ in range(100):
            await asyncio.sleep(0.1)
            if trade.isDone():
                break

        fill_price = trade.orderStatus.avgFillPrice or 0.0
        log.info(
            "Market order filled: %s %d @ %.3f  status=%s",
            side, quantity, fill_price, trade.orderStatus.status,
        )
        return OrderResult(
            order_id=trade.order.orderId,
            symbol=self._cfg.symbol,
            side=side,
            quantity=quantity,
            fill_price=fill_price,
            status=trade.orderStatus.status,
        )

    async def place_stop_order(self, side: str, quantity: int, stop_price: float) -> OrderResult:
        """Place a stop order at ``stop_price``."""
        self._assert_connected()
        order = StopOrder(side, quantity, stop_price)
        trade = self._ib.placeOrder(self._contract, order)
        log.info("Stop order submitted: %s %d @ %.3f", side, quantity, stop_price)
        return OrderResult(
            order_id=trade.order.orderId,
            symbol=self._cfg.symbol,
            side=side,
            quantity=quantity,
            fill_price=stop_price,
            status="Submitted",
        )

    async def place_limit_order(self, side: str, quantity: int, limit_price: float) -> OrderResult:
        """Place a limit order at ``limit_price``."""
        self._assert_connected()
        order = LimitOrder(side, quantity, limit_price)
        trade = self._ib.placeOrder(self._contract, order)
        log.info("Limit order submitted: %s %d @ %.3f", side, quantity, limit_price)
        return OrderResult(
            order_id=trade.order.orderId,
            symbol=self._cfg.symbol,
            side=side,
            quantity=quantity,
            fill_price=limit_price,
            status="Submitted",
        )

    async def cancel_order(self, order_id: int) -> None:
        """Cancel a specific order by ID."""
        self._assert_connected()
        for trade in self._ib.trades():
            if trade.order.orderId == order_id:
                self._ib.cancelOrder(trade.order)
                log.info("Order %d cancelled", order_id)
                return
        log.warning("Order %d not found", order_id)

    async def cancel_all_orders(self) -> None:
        """Send a global cancel for all open orders."""
        self._assert_connected()
        self._ib.reqGlobalCancel()
        log.warning("Global cancel issued — all open orders cancelled")

    # ------------------------------------------------------------------
    # Portfolio
    # ------------------------------------------------------------------

    async def get_positions(self) -> list[dict]:
        """Return all current open positions."""
        self._assert_connected()
        return [
            {
                "symbol":   p.contract.symbol,
                "quantity": p.position,
                "avg_cost": p.avgCost,
            }
            for p in self._ib.positions()
        ]

    async def get_account_value(self) -> float:
        """Return the account's net liquidation value in USD."""
        self._assert_connected()
        for v in self._ib.accountValues():
            if v.tag == "NetLiquidation" and v.currency == "USD":
                return float(v.value)
        return 0.0

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_contract(self):
        kwargs: dict = dict(
            symbol=self._cfg.symbol,
            exchange=self._cfg.exchange,
            currency=self._cfg.currency,
        )
        if self._cfg.last_trade_date:
            kwargs["lastTradeDateOrContractMonth"] = self._cfg.last_trade_date
        return Future(**kwargs)

    def _assert_connected(self) -> None:
        if not self._connected:
            raise RuntimeError("IBKRConnector not connected. Call await connect() first.")
