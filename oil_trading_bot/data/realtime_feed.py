"""
realtime_feed.py — Aggregates streaming tick data into fixed-interval OHLCV candles.

Flow
----
  tick arrives → CandleAggregator → completed Candle → asyncio.Queue → strategy
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import AsyncIterator, Optional

from data.candle_builder import Candle
from utils.logger import get_logger

log = get_logger("realtime_feed")


@dataclass
class Tick:
    """A single price/volume event from the market."""
    symbol: str
    timestamp: datetime
    price: float
    volume: float


class CandleAggregator:
    """
    Aggregates ticks into fixed-interval OHLCV candles.

    A new candle is emitted whenever a tick arrives in a later time bucket
    than the current open candle.

    Parameters
    ----------
    interval_minutes : int
        Duration of each candle in minutes.
    """

    def __init__(self, interval_minutes: int = 5) -> None:
        self._interval = timedelta(minutes=interval_minutes)
        self._buckets: dict[str, dict] = {}

    def _bucket_start(self, ts: datetime) -> datetime:
        """Floor a timestamp to the nearest candle boundary."""
        epoch = datetime(ts.year, ts.month, ts.day)
        elapsed_sec = (ts - epoch).total_seconds()
        interval_sec = self._interval.total_seconds()
        floored_sec = int(elapsed_sec // interval_sec) * interval_sec
        return epoch + timedelta(seconds=floored_sec)

    def update(self, tick: Tick) -> Optional[Candle]:
        """
        Feed a tick into the aggregator.

        Returns
        -------
        Optional[Candle]
            A completed candle when the bucket rolls over, else ``None``.
        """
        bucket = self._bucket_start(tick.timestamp)
        key = tick.symbol
        completed: Optional[Candle] = None

        # Bucket rolled over — emit the previous candle
        if key in self._buckets and self._buckets[key]["bucket"] != bucket:
            old = self._buckets.pop(key)
            completed = Candle(
                timestamp=old["bucket"],
                open=old["open"],
                high=old["high"],
                low=old["low"],
                close=old["close"],
                volume=old["volume"],
            )
            log.debug(
                "Candle closed [%s] O=%.3f H=%.3f L=%.3f C=%.3f V=%.0f",
                completed.timestamp, completed.open, completed.high,
                completed.low, completed.close, completed.volume,
            )

        # Initialise or update current bucket
        if key not in self._buckets:
            self._buckets[key] = {
                "bucket": bucket,
                "open":   tick.price,
                "high":   tick.price,
                "low":    tick.price,
                "close":  tick.price,
                "volume": tick.volume,
            }
        else:
            b = self._buckets[key]
            b["high"]   = max(b["high"],  tick.price)
            b["low"]    = min(b["low"],   tick.price)
            b["close"]  = tick.price
            b["volume"] += tick.volume

        return completed

    def flush(self, symbol: str) -> Optional[Candle]:
        """Force-emit the current open candle (call at session end)."""
        b = self._buckets.pop(symbol, None)
        if b is None:
            return None
        return Candle(
            timestamp=b["bucket"],
            open=b["open"],
            high=b["high"],
            low=b["low"],
            close=b["close"],
            volume=b["volume"],
        )


class RealtimeFeed:
    """
    Async real-time market data feed.

    Consumes ticks from an input queue, builds candles via ``CandleAggregator``,
    and publishes completed candles to an output queue consumed by the strategy.

    Parameters
    ----------
    symbol : str
        Instrument symbol (e.g. ``'CL'`` for WTI crude oil futures).
    interval_minutes : int
        Candle duration in minutes.
    maxsize : int
        Maximum depth of the internal queues.
    """

    def __init__(
        self,
        symbol: str = "CL",
        interval_minutes: int = 5,
        maxsize: int = 100,
    ) -> None:
        self.symbol = symbol
        self._aggregator = CandleAggregator(interval_minutes)
        self._tick_queue: asyncio.Queue[Tick] = asyncio.Queue(maxsize=maxsize)
        self._candle_queue: asyncio.Queue[Candle] = asyncio.Queue(maxsize=maxsize)
        self._running = False
        self._task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def put_tick(self, tick: Tick) -> None:
        """Push a tick into the feed (called by data source)."""
        await self._tick_queue.put(tick)

    async def get_candle(self) -> Candle:
        """Block until the next completed candle is available."""
        return await self._candle_queue.get()

    async def candles(self) -> AsyncIterator[Candle]:
        """Async iterator that yields candles as they complete."""
        while self._running:
            try:
                candle = await asyncio.wait_for(self._candle_queue.get(), timeout=1.0)
                yield candle
            except asyncio.TimeoutError:
                continue

    async def start(self) -> None:
        """Start the internal aggregation loop."""
        self._running = True
        self._task = asyncio.create_task(self._aggregation_loop())
        log.info("RealtimeFeed started — symbol=%s", self.symbol)

    async def stop(self) -> None:
        """Stop the feed and flush any open candle."""
        self._running = False
        if self._task:
            await asyncio.gather(self._task, return_exceptions=True)
        candle = self._aggregator.flush(self.symbol)
        if candle:
            await self._candle_queue.put(candle)
        log.info("RealtimeFeed stopped — symbol=%s", self.symbol)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _aggregation_loop(self) -> None:
        while self._running:
            try:
                tick = await asyncio.wait_for(self._tick_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            candle = self._aggregator.update(tick)
            if candle is not None:
                await self._candle_queue.put(candle)
