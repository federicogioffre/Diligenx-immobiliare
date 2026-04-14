"""
websocket_client.py — Generic async WebSocket client for market data.

Architecture
------------
``BaseWebSocketClient`` defines the connection/reconnect loop.
Subclasses override ``_parse_message()`` to handle provider-specific JSON.
``SimulatedWebSocketClient`` replays a CSV dataset in real time for testing.

Install: pip install websockets
"""

from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional

try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False

from data.realtime_feed import RealtimeFeed, Tick
from data.candle_builder import Candle
from utils.logger import get_logger

log = get_logger("websocket_client")


class BaseWebSocketClient(ABC):
    """
    Abstract WebSocket client with automatic reconnection.

    Parameters
    ----------
    url : str
        WebSocket endpoint URL.
    feed : RealtimeFeed
        The feed to push parsed ticks into.
    reconnect_delay : float
        Seconds to wait before reconnecting after an error.
    """

    def __init__(self, url: str, feed: RealtimeFeed, reconnect_delay: float = 5.0) -> None:
        self._url = url
        self._feed = feed
        self._reconnect_delay = reconnect_delay
        self._running = False

    async def start(self) -> None:
        """Start the client. Reconnects automatically on failure."""
        self._running = True
        while self._running:
            try:
                await self._connect_and_listen()
            except Exception as exc:
                if self._running:
                    log.error("WebSocket error: %s — reconnecting in %.0fs", exc, self._reconnect_delay)
                    await asyncio.sleep(self._reconnect_delay)

    async def stop(self) -> None:
        """Stop the client."""
        self._running = False
        log.info("WebSocket client stopped")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _connect_and_listen(self) -> None:
        if not HAS_WEBSOCKETS:
            raise RuntimeError("Install websockets: pip install websockets")

        log.info("Connecting to %s", self._url)
        async with websockets.connect(self._url) as ws:
            log.info("WebSocket connected to %s", self._url)
            await self._on_connect(ws)
            async for raw in ws:
                if not self._running:
                    break
                try:
                    msg = json.loads(raw)
                    tick = self._parse_message(msg)
                    if tick is not None:
                        await self._feed.put_tick(tick)
                except Exception as exc:
                    log.warning("Failed to parse message: %s | raw=%s", exc, str(raw)[:120])

    async def _on_connect(self, ws: Any) -> None:
        """Override to send subscription/auth messages after connect."""
        pass

    @abstractmethod
    def _parse_message(self, msg: dict) -> Optional[Tick]:
        """Parse a JSON message into a Tick. Return ``None`` to skip."""
        ...


class SimulatedWebSocketClient(BaseWebSocketClient):
    """
    Simulated WebSocket client that replays a list of Candles as ticks.

    Emits one tick per candle (using the candle's close price), paced at
    ``delay_seconds`` per bar. Used to test the paper trading engine
    without a live data connection.

    Parameters
    ----------
    feed : RealtimeFeed
        Target feed.
    candles : list[Candle]
        Historical candles to replay.
    delay_seconds : float
        Wall-clock delay between bars (default: 0.1s ≈ fast replay).
    """

    def __init__(self, feed: RealtimeFeed, candles: list[Candle], delay_seconds: float = 0.1) -> None:
        super().__init__("simulated://local", feed)
        self._candles = candles
        self._delay = delay_seconds

    async def start(self) -> None:
        self._running = True
        log.info(
            "SimulatedWebSocketClient: replaying %d candles (%.2fs/bar)",
            len(self._candles), self._delay,
        )
        for candle in self._candles:
            if not self._running:
                break
            tick = Tick(
                symbol=self._feed.symbol,
                timestamp=candle.timestamp,
                price=candle.close,
                volume=candle.volume,
            )
            await self._feed.put_tick(tick)
            if self._delay > 0:
                await asyncio.sleep(self._delay)
        log.info("SimulatedWebSocketClient: replay complete")
        self._running = False

    def _parse_message(self, msg: dict) -> Optional[Tick]:
        # Not used for simulated client
        return None
