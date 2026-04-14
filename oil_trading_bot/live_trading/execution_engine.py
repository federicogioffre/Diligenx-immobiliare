"""
execution_engine.py — Async execution engine for live and paper trading.

Receives TradeSignals from strategies, validates them against the
RiskManager, and dispatches to an OrderRouter.

Features
--------
- Async signal queue (non-blocking for strategy)
- Kill switch (halts all new orders instantly)
- Per-signal risk validation
- Extensible via signal callbacks
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Coroutine, Optional

from config import Config
from risk.risk_manager import RiskManager
from strategy.opening_range_breakout import Signal
from utils.logger import get_logger

log = get_logger("execution_engine")


@dataclass
class TradeSignal:
    """A trading signal produced by a strategy."""
    symbol: str
    direction: Signal       # Signal.LONG | Signal.SHORT
    price: float            # reference price at signal time
    timestamp: datetime
    stop_loss: float
    take_profit: float


@dataclass
class ExecutionResult:
    """Result of an order dispatch attempt."""
    accepted: bool
    order_id: Optional[int]
    fill_price: Optional[float]
    reason: str             # "filled" | "rejected_risk" | "kill_switch" | "error:..."
    timestamp: datetime = field(default_factory=datetime.now)


class ExecutionEngine:
    """
    Routes validated signals to an OrderRouter.

    Parameters
    ----------
    config : Config
        Trading configuration (risk params used for daily reset).
    order_router : OrderRouter
        Broker-agnostic router (paper or live).
    """

    def __init__(self, config: Config, order_router) -> None:
        self._cfg    = config
        self._router = order_router
        self._risk   = RiskManager(config.risk)
        self._queue: asyncio.Queue[TradeSignal] = asyncio.Queue()
        self._running     = False
        self._kill_switch = False
        self._result_callbacks: list[Callable[[ExecutionResult], Coroutine]] = []

    # ------------------------------------------------------------------
    # Kill switch
    # ------------------------------------------------------------------

    def activate_kill_switch(self) -> None:
        """Immediately halt all new order submissions."""
        self._kill_switch = True
        log.critical("KILL SWITCH ACTIVATED — all new orders blocked")

    def deactivate_kill_switch(self) -> None:
        """Re-enable order submission."""
        self._kill_switch = False
        log.info("Kill switch deactivated")

    @property
    def kill_switch_active(self) -> bool:
        return self._kill_switch

    # ------------------------------------------------------------------
    # Signal ingestion
    # ------------------------------------------------------------------

    async def submit(self, signal: TradeSignal) -> None:
        """
        Enqueue a signal for execution (non-blocking for the caller).

        Parameters
        ----------
        signal : TradeSignal
            Signal to be validated and routed.
        """
        await self._queue.put(signal)

    def on_result(self, callback: Callable[[ExecutionResult], Coroutine]) -> None:
        """Register an async callback called after each execution attempt."""
        self._result_callbacks.append(callback)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Process signals from the queue. Runs until stop() is called."""
        self._running = True
        log.info("ExecutionEngine started")

        while self._running:
            try:
                signal = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            result = await self._process(signal)

            log.info(
                "Signal %s %s → %s  fill=%.3f  reason=%s",
                signal.direction.name,
                signal.symbol,
                "ACCEPTED" if result.accepted else "REJECTED",
                result.fill_price or 0.0,
                result.reason,
            )

            for cb in self._result_callbacks:
                await cb(result)

    async def stop(self) -> None:
        """Stop the execution loop."""
        self._running = False
        log.info("ExecutionEngine stopped")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _process(self, signal: TradeSignal) -> ExecutionResult:
        now   = signal.timestamp
        today = now.date()
        self._risk.reset_daily(today)

        if self._kill_switch:
            return ExecutionResult(False, None, None, "kill_switch", now)

        if signal.direction == Signal.NONE:
            return ExecutionResult(False, None, None, "no_signal", now)

        if not self._risk.can_trade(today):
            return ExecutionResult(False, None, None, "rejected_risk", now)

        try:
            return await self._router.send_order(signal)
        except Exception as exc:
            log.error("Order routing error: %s", exc)
            return ExecutionResult(False, None, None, f"error: {exc}", now)
