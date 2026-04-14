"""
telegram_alerts.py — Telegram notification service for trade events.

Setup
-----
1. Create a bot via @BotFather on Telegram.  Copy the BOT_TOKEN.
2. Send a message to your bot, then visit:
     https://api.telegram.org/bot<TOKEN>/getUpdates
   to find your CHAT_ID.
3. Export the variables before running:
     export TELEGRAM_TOKEN=<your_token>
     export TELEGRAM_CHAT_ID=<your_chat_id>
   Or pass TelegramConfig explicitly.

Install: pip install httpx
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

from utils.logger import get_logger

log = get_logger("telegram_alerts")

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


@dataclass
class TelegramConfig:
    token: str   = ""
    chat_id: str = ""


class TelegramAlerter:
    """
    Sends Markdown-formatted messages to a Telegram chat.

    Parameters
    ----------
    config : TelegramConfig, optional
        Token and chat_id. Falls back to environment variables
        ``TELEGRAM_TOKEN`` and ``TELEGRAM_CHAT_ID`` if not provided.
    """

    def __init__(self, config: Optional[TelegramConfig] = None) -> None:
        cfg = config or TelegramConfig()
        self._token   = cfg.token   or os.getenv("TELEGRAM_TOKEN",   "")
        self._chat_id = cfg.chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
        self._enabled = bool(self._token and self._chat_id)

        if self._enabled:
            log.info("TelegramAlerter ready (chat_id=%s)", self._chat_id)
        else:
            log.warning(
                "TelegramAlerter disabled — set TELEGRAM_TOKEN and TELEGRAM_CHAT_ID"
            )

    # ------------------------------------------------------------------
    # Alert methods
    # ------------------------------------------------------------------

    async def trade_opened(
        self,
        symbol: str,
        side: str,
        price: float,
        sl: float,
        tp: float,
    ) -> None:
        """Alert when a new position is opened."""
        emoji = "🟢" if side == "LONG" else "🔴"
        await self._send(
            f"{emoji} *TRADE OPENED*\n"
            f"Symbol: `{symbol}`\n"
            f"Side:   `{side}`\n"
            f"Entry:  `{price:.3f}`\n"
            f"SL:     `{sl:.3f}`\n"
            f"TP:     `{tp:.3f}`"
        )

    async def trade_closed(
        self,
        symbol: str,
        side: str,
        entry: float,
        exit_price: float,
        pnl: float,
        reason: str,
    ) -> None:
        """Alert when a position is closed."""
        emoji = "✅" if pnl >= 0 else "❌"
        await self._send(
            f"{emoji} *TRADE CLOSED*\n"
            f"Symbol: `{symbol}`\n"
            f"Side:   `{side}`\n"
            f"Entry:  `{entry:.3f}`\n"
            f"Exit:   `{exit_price:.3f}`\n"
            f"PnL:    `{pnl:+.2f}` USD\n"
            f"Reason: `{reason}`"
        )

    async def daily_summary(
        self,
        date_str: str,
        trades: int,
        pnl: float,
        equity: float,
    ) -> None:
        """End-of-session daily summary."""
        emoji = "📈" if pnl >= 0 else "📉"
        await self._send(
            f"{emoji} *DAILY SUMMARY — {date_str}*\n"
            f"Trades:    `{trades}`\n"
            f"Daily PnL: `{pnl:+.2f}` USD\n"
            f"Equity:    `{equity:,.2f}` USD"
        )

    async def kill_switch(self) -> None:
        """Alert when the kill switch is activated."""
        await self._send("🚨 *KILL SWITCH ACTIVATED* — all trading halted immediately.")

    async def risk_halted(self, daily_loss: float, limit: float) -> None:
        """Alert when max daily loss is reached."""
        await self._send(
            f"⛔ *MAX DAILY LOSS REACHED*\n"
            f"Loss: `{daily_loss:+.2f}` USD  |  Limit: `-{limit:.2f}` USD\n"
            f"Trading halted for the remainder of the session."
        )

    async def error(self, message: str) -> None:
        """Alert on system errors."""
        await self._send(f"⚠️ *ERROR*\n`{message}`")

    async def info(self, message: str) -> None:
        """General informational alert."""
        await self._send(f"ℹ️ {message}")

    async def engine_started(self, mode: str, symbol: str) -> None:
        await self._send(
            f"🚀 *ENGINE STARTED*\n"
            f"Mode:   `{mode.upper()}`\n"
            f"Symbol: `{symbol}`"
        )

    async def engine_stopped(self, trades: int, pnl: float) -> None:
        await self._send(
            f"🛑 *ENGINE STOPPED*\n"
            f"Total trades: `{trades}`\n"
            f"Session PnL:  `{pnl:+.2f}` USD"
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _send(self, text: str) -> None:
        if not self._enabled:
            log.debug("Telegram (disabled): %s", text.replace("\n", " | "))
            return

        if not HAS_HTTPX:
            log.error("Telegram requires httpx: pip install httpx")
            return

        url     = _TELEGRAM_API.format(token=self._token)
        payload = {
            "chat_id":    self._chat_id,
            "text":       text,
            "parse_mode": "Markdown",
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code != 200:
                    log.warning(
                        "Telegram API error: %d — %s",
                        resp.status_code, resp.text[:200],
                    )
        except Exception as exc:
            log.error("Telegram send failed: %s", exc)
