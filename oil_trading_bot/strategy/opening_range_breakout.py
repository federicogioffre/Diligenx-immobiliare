"""
opening_range_breakout.py — Opening Range Breakout (ORB) strategy.

Logic
-----
1. During the *opening range window* (e.g. 15:30–16:00), accumulate bars to
   compute ``opening_range_high``, ``opening_range_low``, and
   ``average_volume``.

2. After the window closes, for each subsequent bar on the same session:
   - LONG  if close > opening_range_high  AND  volume > multiplier * avg_volume
   - SHORT if close < opening_range_low   AND  volume > multiplier * avg_volume
   - At most one trade per direction per session.

3. Resets automatically at the start of each new calendar date.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time
from enum import Enum, auto
from typing import Optional

from data.candle_builder import Candle
from config import ORBConfig
from utils.logger import get_logger

log = get_logger("orb_strategy")


class Signal(Enum):
    NONE  = auto()
    LONG  = auto()
    SHORT = auto()


@dataclass
class OpeningRange:
    """Accumulated statistics for the opening range window."""
    high: float = 0.0
    low: float  = float("inf")
    total_volume: float = 0.0
    bar_count: int = 0

    @property
    def average_volume(self) -> float:
        return self.total_volume / self.bar_count if self.bar_count else 0.0

    def update(self, candle: Candle) -> None:
        self.high = max(self.high, candle.high)
        self.low  = min(self.low,  candle.low)
        self.total_volume += candle.volume
        self.bar_count += 1

    @property
    def is_valid(self) -> bool:
        return self.bar_count > 0


@dataclass
class ORBStrategyState:
    """Mutable per-session state for one ORB instance."""
    session_date:   Optional[date] = None
    opening_range:  OpeningRange   = field(default_factory=OpeningRange)
    range_complete: bool           = False
    long_traded:    bool           = False
    short_traded:   bool           = False


class ORBStrategy:
    """
    Opening Range Breakout strategy.

    Parameters
    ----------
    orb_config : ORBConfig
        Strategy parameters (range window times, volume multiplier, etc.).
    """

    def __init__(self, orb_config: ORBConfig) -> None:
        self._cfg   = orb_config
        self._state = ORBStrategyState()
        self._range_start: time = self._parse_time(orb_config.range_start)
        self._range_end:   time = self._parse_time(orb_config.range_end)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def on_candle(self, candle: Candle) -> Signal:
        """
        Process the next candle and return a trading signal.

        Parameters
        ----------
        candle : Candle
            The latest closed bar.

        Returns
        -------
        Signal
            ``Signal.LONG``, ``Signal.SHORT``, or ``Signal.NONE``.
        """
        self._maybe_reset_session(candle)

        bar_time: time = candle.timestamp.time()

        # ── Phase 1: inside opening range window ──────────────────────
        if self._in_range_window(bar_time):
            self._state.opening_range.update(candle)
            log.debug(
                "[%s] Range bar — H=%.3f L=%.3f AvgVol=%.0f",
                candle.timestamp, self._state.opening_range.high,
                self._state.opening_range.low,
                self._state.opening_range.average_volume,
            )
            return Signal.NONE

        # ── Phase 2: mark range as complete after window passes ────────
        if not self._state.range_complete:
            if self._state.opening_range.is_valid:
                self._state.range_complete = True
                log.info(
                    "[%s] Range locked — High=%.3f  Low=%.3f  AvgVol=%.0f",
                    candle.timestamp.date(),
                    self._state.opening_range.high,
                    self._state.opening_range.low,
                    self._state.opening_range.average_volume,
                )
            else:
                return Signal.NONE

        # ── Phase 3: breakout detection ────────────────────────────────
        return self._evaluate_breakout(candle)

    def reset(self) -> None:
        """Force a full state reset (useful between sessions in tests)."""
        self._state = ORBStrategyState()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _maybe_reset_session(self, candle: Candle) -> None:
        candle_date = candle.timestamp.date()
        if candle_date != self._state.session_date:
            if self._state.session_date is not None:
                log.debug("New session — resetting ORB state (%s)", candle_date)
            self._state = ORBStrategyState(session_date=candle_date)

    def _in_range_window(self, bar_time: time) -> bool:
        return self._range_start <= bar_time < self._range_end

    def _evaluate_breakout(self, candle: Candle) -> Signal:
        orng = self._state.opening_range
        required_volume = self._cfg.volume_multiplier * orng.average_volume

        # ── Long breakout ──────────────────────────────────────────────
        if (
            not self._state.long_traded
            and candle.close > orng.high
            and candle.volume > required_volume
        ):
            self._state.long_traded = True
            log.info(
                "[%s] LONG signal — close=%.3f > range_high=%.3f  vol=%.0f > req=%.0f",
                candle.timestamp, candle.close, orng.high,
                candle.volume, required_volume,
            )
            return Signal.LONG

        # ── Short breakout ─────────────────────────────────────────────
        if (
            not self._state.short_traded
            and candle.close < orng.low
            and candle.volume > required_volume
        ):
            self._state.short_traded = True
            log.info(
                "[%s] SHORT signal — close=%.3f < range_low=%.3f  vol=%.0f > req=%.0f",
                candle.timestamp, candle.close, orng.low,
                candle.volume, required_volume,
            )
            return Signal.SHORT

        return Signal.NONE

    @staticmethod
    def _parse_time(t: str) -> time:
        """Parse ``'HH:MM'`` string into a ``datetime.time``."""
        h, m = map(int, t.split(":"))
        return time(h, m)
