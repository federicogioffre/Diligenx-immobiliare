"""
run_live.py — Main entry point for paper and live trading.

Usage
-----
  # Paper trading (simulated feed from CSV):
  python run_live.py --mode paper

  # Paper trading with Telegram alerts:
  python run_live.py --mode paper --telegram

  # Live trading via IBKR (TWS/IBG must be running):
  python run_live.py --mode live --ibkr-host 127.0.0.1 --ibkr-port 7496

  # Show dashboard:
  python run_live.py --mode paper --dashboard

  # Kill switch (halt immediately):
  Press Ctrl+C — engine stops gracefully and sends a Telegram alert.

Environment variables (optional)
---------------------------------
  TELEGRAM_TOKEN    — Telegram bot token
  TELEGRAM_CHAT_ID  — Telegram chat ID
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).parent))

from config import Config
from broker.ibkr_connector import IBKRConfig, IBKRConnector
from data.data_loader import load_ohlcv
from data.candle_builder import iter_candles
from data.realtime_feed import RealtimeFeed
from data.websocket_client import SimulatedWebSocketClient
from live_trading.execution_engine import ExecutionEngine, TradeSignal
from live_trading.order_router import OrderRouter, TradingMode
from live_trading.trade_manager import TradeManager
from monitoring.dashboard import Dashboard
from monitoring.telegram_alerts import TelegramAlerter
from paper_trading.paper_broker import ClosedPaperTrade
from paper_trading.paper_engine import PaperEngine
from utils.logger import get_logger

log = get_logger("run_live")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Oil Trading Bot — paper / live trading runner",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--mode", choices=["paper", "live"], default="paper",
        help="Trading mode: 'paper' (simulated) or 'live' (IBKR)",
    )
    p.add_argument(
        "--symbol", default="CL",
        help="Futures symbol (CL = WTI crude oil)",
    )
    p.add_argument(
        "--dataset", default="datasets/example_dataset.csv",
        help="CSV dataset for paper mode simulated feed",
    )
    p.add_argument(
        "--ibkr-host", default="127.0.0.1",
        help="TWS / IB Gateway host",
    )
    p.add_argument(
        "--ibkr-port", type=int, default=7497,
        help="TWS port (7497=paper, 7496=live)",
    )
    p.add_argument(
        "--ibkr-client-id", type=int, default=1,
        help="IBKR client ID (must be unique per connection)",
    )
    p.add_argument(
        "--telegram", action="store_true",
        help="Enable Telegram alerts (requires env vars TELEGRAM_TOKEN + TELEGRAM_CHAT_ID)",
    )
    p.add_argument(
        "--dashboard", action="store_true",
        help="Show live terminal dashboard (requires pip install rich)",
    )
    p.add_argument(
        "--bar-delay", type=float, default=0.05,
        help="Seconds between simulated bars in paper mode (0 = as fast as possible)",
    )
    return p.parse_args()


# ---------------------------------------------------------------------------
# Paper trading runner
# ---------------------------------------------------------------------------

async def run_paper(args: argparse.Namespace, cfg: Config) -> None:
    log.info("Starting PAPER TRADING — dataset=%s", args.dataset)

    # Load historical candles for simulated feed
    df = load_ohlcv(Path(args.dataset))
    candles = list(iter_candles(df))
    log.info("Loaded %d candles for simulation", len(candles))

    feed   = RealtimeFeed(symbol=args.symbol, interval_minutes=5)
    engine = PaperEngine(config=cfg, feed=feed)

    # --- Telegram alerts ---
    alerter = TelegramAlerter() if args.telegram else None

    async def on_trade(trade: ClosedPaperTrade) -> None:
        if alerter:
            side = trade.side.name
            await alerter.trade_closed(
                symbol=args.symbol,
                side=side,
                entry=trade.entry_price,
                exit_price=trade.exit_price,
                pnl=trade.pnl,
                reason=trade.exit_reason,
            )

    engine.on_trade_closed(on_trade)

    # --- Dashboard ---
    dash = Dashboard(refresh_interval=3.0) if args.dashboard else None
    if dash:
        dash.attach(broker=engine.broker, risk=engine.risk, mode="PAPER", symbol=args.symbol)

    # --- Simulated WebSocket client ---
    sim_client = SimulatedWebSocketClient(
        feed=feed,
        candles=candles,
        delay_seconds=args.bar_delay,
    )

    if alerter:
        await alerter.engine_started("PAPER", args.symbol)

    # Start all tasks concurrently
    tasks = [
        asyncio.create_task(engine.run()),
        asyncio.create_task(sim_client.start()),
    ]
    if dash:
        tasks.append(asyncio.create_task(dash.run()))

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        await engine.stop()
        if dash:
            await dash.stop()

    engine.print_summary()

    if alerter:
        await alerter.engine_stopped(
            trades=len(engine.broker.trade_history),
            pnl=engine.broker.daily_pnl,
        )


# ---------------------------------------------------------------------------
# Live trading runner (IBKR)
# ---------------------------------------------------------------------------

async def run_live(args: argparse.Namespace, cfg: Config) -> None:
    log.info("Starting LIVE TRADING — IBKR %s:%d", args.ibkr_host, args.ibkr_port)

    ibkr_cfg = IBKRConfig(
        host=args.ibkr_host,
        port=args.ibkr_port,
        client_id=args.ibkr_client_id,
        symbol=args.symbol,
    )
    connector    = IBKRConnector(ibkr_cfg)
    feed         = RealtimeFeed(symbol=args.symbol, interval_minutes=5)
    trade_mgr    = TradeManager()
    alerter      = TelegramAlerter() if args.telegram else None

    # Wire trade callbacks
    if alerter:
        async def on_live_trade(trade) -> None:
            await alerter.trade_closed(
                symbol=trade.symbol,
                side=trade.side,
                entry=trade.entry_price,
                exit_price=trade.exit_price,
                pnl=trade.pnl,
                reason=trade.exit_reason,
            )
        trade_mgr.on_trade_closed(on_live_trade)

    router  = OrderRouter(
        mode=TradingMode.LIVE,
        broker=connector,
        trade_manager=trade_mgr,
        risk_config=cfg.risk,
    )
    engine  = ExecutionEngine(config=cfg, order_router=router)

    await connector.connect()
    await feed.start()
    await connector.stream_realtime_bars(feed)

    if alerter:
        await alerter.engine_started("LIVE", args.symbol)

    log.info("Live engine running — press Ctrl+C to stop")

    try:
        await engine.run()
    except asyncio.CancelledError:
        pass
    finally:
        log.info("Shutting down live engine...")
        await engine.stop()
        await connector.cancel_all_orders()
        await connector.disconnect()
        await feed.stop()

        if alerter:
            pnl = trade_mgr.get_daily_pnl()
            await alerter.engine_stopped(
                trades=len(trade_mgr.trade_history),
                pnl=pnl,
            )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    args = parse_args()
    cfg  = Config()

    log.info(
        "Oil Trading Bot starting — mode=%s  symbol=%s",
        args.mode.upper(), args.symbol,
    )

    try:
        if args.mode == "paper":
            await run_paper(args, cfg)
        else:
            await run_live(args, cfg)
    except KeyboardInterrupt:
        log.info("Interrupted by user — shutting down")


if __name__ == "__main__":
    asyncio.run(main())
