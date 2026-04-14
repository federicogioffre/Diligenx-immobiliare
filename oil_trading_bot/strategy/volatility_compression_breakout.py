"""
volatility_compression_breakout.py — Volatility Compression Breakout (VCB) strategy.

Logic
-----
1. Three streaming indicators are maintained on every bar:

   EMA(ema_period)
       Exponential moving average of close prices.
       Provides the macro trend direction.

   ATR(atr_period)
       Average True Range using EWM smoothing.
       Provides the current volatility baseline.

   Rolling Range(range_period)
       range_high = max(high) over last N bars
       range_low  = min(low)  over last N bars
       range_size = range_high − range_low

2. A *compression episode* begins when the rolling range is unusually
   tight relative to volatility:

       range_size < compression_threshold × ATR

   When the range expands back above the threshold, the episode ends
   and the strategy resets, waiting for the next squeeze.

3. During an active compression episode (first breakout only):

   LONG  entry:  close > range_high  AND  close > EMA
   SHORT entry:  close < range_low   AND  close < EMA

   Volume is NOT required — the squeeze itself acts as the filter.

4. Risk management (computed at entry using the live ATR value):

       stop_loss   = entry ± ATR × atr_sl_multiplier
       take_profit = entry ± ATR × atr_tp_multiplier

   The 1:2 risk-reward default (sl_mult=1.0, tp_mult=2.0) matches the
   project convention and is overridable via VCBConfig.

State machine
-------------
                   ┌────────────────────────────────┐
                   │          SCANNING               │
                   │  watching for squeeze           │
                   └──────────┬─────────────────────┘
                   range<thr×ATR detected
                              │
                              ▼
                   ┌────────────────────────────────┐
                   │       IN COMPRESSION            │
                   │  waiting for breakout           │
                   └──────────┬────────────┬────────┘
                breakout      │            │ range released
                occurs        │            │ (no trade)
                              ▼            ▼
                   ┌──────────────┐   back to SCANNING
                   │  TRADED      │
                   │  (cooldown   │
                   │  until range │
                   │  releases)   │
                   └──────────────┘
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import date
from typing import Optional

from config import VCBConfig
from data.candle_builder import Candle
from strategy.opening_range_breakout import Signal
from utils.logger import get_logger

log = get_logger("vcb_strategy")


# ---------------------------------------------------------------------------
# Streaming indicator helpers
# ---------------------------------------------------------------------------

def _ema_update(prev: Optional[float], value: float, alpha: float) -> float:
    """Single-step EMA update.  First call (prev=None) seeds with *value*."""
    if prev is None:
        return value
    return alpha * value + (1.0 - alpha) * prev


def _true_range(candle: Candle, prev_close: Optional[float]) -> float:
    """Compute True Range for one candle."""
    hl = candle.high - candle.low
    if prev_close is None:
        return hl
    return max(hl, abs(candle.high - prev_close), abs(candle.low - prev_close))


# ---------------------------------------------------------------------------
# Strategy state
# ---------------------------------------------------------------------------

@dataclass
class VCBState:
    """All mutable state for one VCB instance."""
    bars_seen:            int   = 0
    ema_value:            Optional[float] = None
    atr_value:            Optional[float] = None
    prev_close:           Optional[float] = None
    in_compression:       bool  = False
    compression_traded:   bool  = False
    current_date:         Optional[date] = None
    daily_trades:         int   = 0


# ---------------------------------------------------------------------------
# VCB Strategy
# ---------------------------------------------------------------------------

class VCBStrategy:
    """
    Volatility Compression Breakout strategy.

    Parameters
    ----------
    vcb_config : VCBConfig
        Strategy parameters (indicator periods, thresholds, risk multipliers).
    """

    def __init__(self, vcb_config: VCBConfig) -> None:
        self._cfg = vcb_config

        # Pre-compute EWM alphas
        self._ema_alpha: float = 2.0 / (vcb_config.ema_period + 1)
        self._atr_alpha: float = 2.0 / (vcb_config.atr_period + 1)

        # Rolling candle buffer for range calculation
        self._buffer: deque[Candle] = deque(maxlen=vcb_config.range_period)

        # Mutable state
        self._s = VCBState()

        # Minimum bars required before generating signals
        self._warmup_needed: int = max(
            vcb_config.ema_period,
            vcb_config.atr_period,
            vcb_config.range_period,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def on_candle(self, candle: Candle) -> Signal:
        """
        Process the next closed bar and return a trading signal.

        Parameters
        ----------
        candle : Candle
            The latest closed OHLCV bar.

        Returns
        -------
        Signal
            ``Signal.LONG``, ``Signal.SHORT``, or ``Signal.NONE``.
        """
        self._maybe_reset_day(candle)
        self._update_indicators(candle)

        # Snapshot the rolling range from the PRIOR N closed bars, before the
        # current candle enters the buffer.  Appending first would contaminate
        # range_high/low with the current bar's intrabar high/low, which:
        #   (a) makes close > range_high impossible when this bar sets the high;
        #   (b) expands range_size so compression appears released on the very
        #       bar that should generate the breakout signal.
        _buf_full = len(self._buffer) == self._buffer.maxlen
        prior_range_high = max(c.high for c in self._buffer) if _buf_full else 0.0
        prior_range_low  = min(c.low  for c in self._buffer) if _buf_full else 0.0

        # Advance buffer — current candle participates in NEXT bar's range only.
        self._buffer.append(candle)
        self._s.bars_seen += 1

        # Warmup guard — need enough history for all indicators
        if not self.is_warm:
            return Signal.NONE

        # Daily trade limit
        if self._s.daily_trades >= self._cfg.max_trades_per_day:
            return Signal.NONE

        range_high = prior_range_high
        range_low  = prior_range_low
        range_size = range_high - range_low

        atr = self._s.atr_value  # guaranteed non-None here (is_warm)
        ema = self._s.ema_value

        compression_level = self._cfg.compression_threshold * atr
        is_compressed     = range_size < compression_level

        # ── Compression state machine ──────────────────────────────────
        if is_compressed and not self._s.in_compression:
            # Entering a new compression episode
            self._s.in_compression     = True
            self._s.compression_traded = False
            log.info(
                "[%s] Compression ▼  range=%.4f  ATR×%.2f=%.4f  EMA=%.4f",
                candle.timestamp,
                range_size,
                self._cfg.compression_threshold,
                compression_level,
                ema,
            )

        elif not is_compressed and self._s.in_compression:
            # Compression released
            log.debug(
                "[%s] Compression ▲ released (range=%.4f > %.4f)",
                candle.timestamp, range_size, compression_level,
            )
            self._s.in_compression     = False
            self._s.compression_traded = False

        # Only signal when actively compressed and no trade taken yet
        if not self._s.in_compression or self._s.compression_traded:
            return Signal.NONE

        # ── Breakout detection ─────────────────────────────────────────

        # LONG: close pierces above range high AND above EMA
        if candle.close > range_high and candle.close > ema:
            self._s.compression_traded = True
            self._s.daily_trades      += 1
            log.info(
                "[%s] VCB LONG  close=%.4f > range_H=%.4f  EMA=%.4f  ATR=%.4f",
                candle.timestamp, candle.close, range_high, ema, atr,
            )
            return Signal.LONG

        # SHORT: close pierces below range low AND below EMA
        if candle.close < range_low and candle.close < ema:
            self._s.compression_traded = True
            self._s.daily_trades      += 1
            log.info(
                "[%s] VCB SHORT close=%.4f < range_L=%.4f  EMA=%.4f  ATR=%.4f",
                candle.timestamp, candle.close, range_low, ema, atr,
            )
            return Signal.SHORT

        return Signal.NONE

    def reset(self) -> None:
        """Full state reset — useful between sessions in tests."""
        self._buffer.clear()
        self._s = VCBState()

    # ------------------------------------------------------------------
    # Properties (consumed by VCBBacktestEngine at trade open)
    # ------------------------------------------------------------------

    @property
    def is_warm(self) -> bool:
        """True once all indicators have enough history to be reliable."""
        return (
            self._s.bars_seen >= self._warmup_needed
            and self._s.ema_value is not None
            and self._s.atr_value is not None
            and len(self._buffer) == self._buffer.maxlen
        )

    @property
    def current_atr(self) -> float:
        """Latest ATR value; ``nan`` during warmup."""
        return self._s.atr_value if self._s.atr_value is not None else float("nan")

    @property
    def current_ema(self) -> float:
        """Latest EMA value; ``nan`` during warmup."""
        return self._s.ema_value if self._s.ema_value is not None else float("nan")

    @property
    def is_compressed(self) -> bool:
        """True when the strategy is currently inside a compression episode."""
        return self._s.in_compression

    @property
    def daily_trades(self) -> int:
        """Number of trades taken today."""
        return self._s.daily_trades

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _update_indicators(self, candle: Candle) -> None:
        """Update streaming EMA and ATR with one new candle."""
        # EMA of close
        self._s.ema_value = _ema_update(
            self._s.ema_value, candle.close, self._ema_alpha
        )

        # ATR via EWM of True Range
        tr = _true_range(candle, self._s.prev_close)
        self._s.atr_value = _ema_update(
            self._s.atr_value, tr, self._atr_alpha
        )

        self._s.prev_close = candle.close

    def _maybe_reset_day(self, candle: Candle) -> None:
        """Reset per-day trade counter at the start of each calendar session."""
        candle_date = candle.timestamp.date()
        if candle_date != self._s.current_date:
            if self._s.current_date is not None:
                log.debug(
                    "VCB new session %s — resetting daily counter (was %d trades)",
                    candle_date, self._s.daily_trades,
                )
            self._s.current_date  = candle_date
            self._s.daily_trades  = 0
