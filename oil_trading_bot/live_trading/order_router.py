"""
order_router.py — Routes trade signals to PaperBroker or IBKRConnector.

The ExecutionEngine calls send_order() without knowing which broker
is active; the router handles dispatch and wraps results uniformly.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from live_trading.execution_engine import ExecutionResult, TradeSignal
from strategy.opening_range_breakout import Signal
from utils.logger import get_logger

log = get_logger("order_router")


class TradingMode(Enum):
    PAPER = "paper"
    LIVE  = "live"


class OrderRouter:
    """
    Broker-agnostic order router.

    Parameters
    ----------
    mode : TradingMode
        ``PAPER`` uses PaperBroker; ``LIVE`` uses IBKRConnector.
    broker : PaperBroker | IBKRConnector
        The underlying broker instance.
    trade_manager : TradeManager, optional
        Required for LIVE mode to track positions after fills.
    risk_config : RiskConfig, optional
        Required for LIVE mode to set SL/TP on stop orders.
    """

    def __init__(
        self,
        mode: TradingMode,
        broker,
        trade_manager=None,
        risk_config=None,
    ) -> None:
        self._mode    = mode
        self._broker  = broker
        self._tm      = trade_manager
        self._risk    = risk_config
        log.info("OrderRouter initialised in %s mode", mode.value.upper())

    async def send_order(self, signal: TradeSignal) -> ExecutionResult:
        """
        Dispatch a signal to the configured broker.

        Parameters
        ----------
        signal : TradeSignal

        Returns
        -------
        ExecutionResult
        """
        if self._mode == TradingMode.PAPER:
            return await self._paper(signal)
        return await self._live(signal)

    # ------------------------------------------------------------------
    # Paper routing
    # ------------------------------------------------------------------

    async def _paper(self, signal: TradeSignal) -> ExecutionResult:
        try:
            if signal.direction == Signal.LONG:
                fill = await self._broker.open_long(signal.price, signal.timestamp)
            else:
                fill = await self._broker.open_short(signal.price, signal.timestamp)

            return ExecutionResult(
                accepted=True,
                order_id=id(fill),
                fill_price=fill.fill_price,
                reason="filled",
                timestamp=signal.timestamp,
            )
        except RuntimeError as exc:
            return ExecutionResult(
                accepted=False,
                order_id=None,
                fill_price=None,
                reason=str(exc),
                timestamp=signal.timestamp,
            )

    # ------------------------------------------------------------------
    # Live routing (IBKR)
    # ------------------------------------------------------------------

    async def _live(self, signal: TradeSignal) -> ExecutionResult:
        side = "BUY" if signal.direction == Signal.LONG else "SELL"

        try:
            result = await self._broker.place_market_order(side, 1)

            # Register position with TradeManager
            if self._tm is not None:
                from live_trading.trade_manager import LivePosition
                pos = LivePosition(
                    symbol=signal.symbol,
                    side="LONG" if signal.direction == Signal.LONG else "SHORT",
                    quantity=1,
                    entry_price=result.fill_price,
                    entry_time=signal.timestamp,
                    stop_loss=signal.stop_loss,
                    take_profit=signal.take_profit,
                    order_id=result.order_id,
                )
                self._tm.open_position(pos)

                # Place bracket stop order with IBKR
                close_side = "SELL" if signal.direction == Signal.LONG else "BUY"
                await self._broker.place_stop_order(close_side, 1, signal.stop_loss)

            return ExecutionResult(
                accepted=True,
                order_id=result.order_id,
                fill_price=result.fill_price,
                reason="filled",
                timestamp=signal.timestamp,
            )

        except Exception as exc:
            log.error("Live order failed: %s", exc)
            return ExecutionResult(
                accepted=False,
                order_id=None,
                fill_price=None,
                reason=f"error: {exc}",
                timestamp=signal.timestamp,
            )
