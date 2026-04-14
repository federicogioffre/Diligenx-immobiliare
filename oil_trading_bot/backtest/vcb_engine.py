"""
vcb_engine.py — Backtest engine wired to the VCB strategy.

Architecture
------------
VCBBacktestEngine subclasses BacktestEngine and makes two minimal changes:

1. Replaces ``self._strategy`` (ORBStrategy) with ``VCBStrategy``.
2. Overrides ``_open_trade()`` to use the live ATR value exposed by
   the strategy for dynamic stop-loss and take-profit distances,
   rather than the fixed-dollar values in RiskConfig.

Everything else — session handling, SL/TP checks, portfolio updates,
the risk gate, and force-close at end of data — is inherited unchanged.

Usage
-----
    from backtest.vcb_engine import VCBBacktestEngine
    from config import Config

    engine = VCBBacktestEngine(Config(), initial_capital=100_000)
    results = engine.run(candles_df)
"""

from __future__ import annotations

from config import Config
from backtest.broker_simulator import Order, OrderSide, OrderType
from backtest.engine import BacktestEngine
from data.candle_builder import Candle
from strategy.opening_range_breakout import Signal
from strategy.volatility_compression_breakout import VCBStrategy
from utils.logger import get_logger

log = get_logger("vcb_engine")


class VCBBacktestEngine(BacktestEngine):
    """
    Sequential backtesting engine for the Volatility Compression Breakout
    strategy.

    Parameters
    ----------
    config : Config
        Full configuration object.  ``config.vcb`` controls VCB parameters;
        ``config.risk`` provides ``position_size`` and ``max_daily_loss``;
        ``config.broker`` provides slippage/commission.
    initial_capital : float
        Starting portfolio cash.
    """

    def __init__(
        self,
        config: Config,
        initial_capital: float = 100_000.0,
    ) -> None:
        # Initialise parent (creates broker, portfolio, risk manager).
        # Parent also creates an ORBStrategy — we immediately replace it.
        super().__init__(config, initial_capital)

        # Swap ORB for VCB strategy
        self._strategy = VCBStrategy(config.vcb)
        log.debug(
            "VCBBacktestEngine ready — EMA=%d  ATR=%d  range=%d  thr=%.2f"
            "  sl_mult=%.2f  tp_mult=%.2f",
            config.vcb.ema_period,
            config.vcb.atr_period,
            config.vcb.range_period,
            config.vcb.compression_threshold,
            config.vcb.atr_sl_multiplier,
            config.vcb.atr_tp_multiplier,
        )

    # ------------------------------------------------------------------
    # Override: ATR-dynamic stop-loss and take-profit
    # ------------------------------------------------------------------

    def _open_trade(self, signal: Signal, candle: Candle) -> None:
        """
        Submit an entry order and open a portfolio position.

        Stop-loss and take-profit are derived from the *live ATR* at the
        moment of entry, using multipliers from ``config.vcb``.

        Fallback: if ATR is unavailable (NaN) or zero — which only happens
        at the very start of data before the indicator warms up — the fixed
        RiskConfig values are used instead.
        """
        side = OrderSide.BUY if signal == Signal.LONG else OrderSide.SELL
        order = Order(
            side=side,
            quantity=self._cfg.risk.position_size,
            order_type=OrderType.MARKET,
        )
        fill = self._broker.execute(order, candle.close, candle.timestamp)

        # Use live ATR from the strategy for dynamic SL/TP
        atr = self._strategy.current_atr   # type: ignore[attr-defined]

        if atr != atr or atr <= 0.0:
            # Fallback to fixed-dollar values (should not happen after warmup)
            log.warning(
                "[%s] ATR unavailable (%.4f) — falling back to fixed SL/TP",
                candle.timestamp, atr,
            )
            sl_dist = self._cfg.risk.stop_loss_dollars
            tp_dist = self._cfg.risk.take_profit_dollars
        else:
            sl_dist = atr * self._cfg.vcb.atr_sl_multiplier
            tp_dist = atr * self._cfg.vcb.atr_tp_multiplier

        if signal == Signal.LONG:
            stop_loss   = fill.fill_price - sl_dist
            take_profit = fill.fill_price + tp_dist
        else:
            stop_loss   = fill.fill_price + sl_dist
            take_profit = fill.fill_price - tp_dist

        log.debug(
            "[%s] VCB %s entry=%.4f  SL=%.4f  TP=%.4f  ATR=%.4f",
            candle.timestamp,
            signal.name,
            fill.fill_price,
            stop_loss,
            take_profit,
            atr,
        )

        self._portfolio.open_position_from_fill(fill, stop_loss, take_profit)
