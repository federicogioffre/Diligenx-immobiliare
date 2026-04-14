"""
dashboard.py — Live terminal dashboard powered by the rich library.

Displays
--------
- Session header (mode, symbol, uptime, timestamp)
- Portfolio stats (equity, daily PnL, trade count, risk status)
- Open position details
- Last 10 closed trades

Install: pip install rich
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich import box as rbox
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

from utils.logger import get_logger

log = get_logger("dashboard")


class Dashboard:
    """
    Refreshes a rich terminal layout every ``refresh_interval`` seconds.

    Usage
    -----
    ::
        dash = Dashboard()
        dash.attach(broker=engine.broker, risk=engine.risk,
                    mode="PAPER", symbol="CL")
        asyncio.create_task(dash.run())

    Parameters
    ----------
    refresh_interval : float
        Seconds between screen refreshes.
    """

    def __init__(self, refresh_interval: float = 5.0) -> None:
        self._interval   = refresh_interval
        self._running    = False
        self._started_at = datetime.now()
        self._console    = Console() if HAS_RICH else None
        self._broker     = None
        self._risk       = None
        self._mode       = "PAPER"
        self._symbol     = "CL"

    def attach(
        self,
        broker,
        risk,
        mode: str = "PAPER",
        symbol: str = "CL",
    ) -> None:
        """Attach the data sources used to render the dashboard."""
        self._broker = broker
        self._risk   = risk
        self._mode   = mode.upper()
        self._symbol = symbol

    async def run(self) -> None:
        """Start the refresh loop."""
        if not HAS_RICH:
            log.warning("Dashboard disabled — install rich: pip install rich")
            return

        self._running = True
        log.info("Dashboard started (%.0fs refresh)", self._interval)

        while self._running:
            self._render()
            await asyncio.sleep(self._interval)

    async def stop(self) -> None:
        self._running = False

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render(self) -> None:
        if self._console is None:
            return
        self._console.clear()
        self._console.print(self._header())
        self._console.print()

        if self._broker is not None:
            self._console.print(self._stats())
            self._console.print()
            self._console.print(self._position())
            self._console.print()
            self._console.print(self._history())
        else:
            self._console.print("[dim]No broker attached.[/dim]")

    def _header(self) -> Panel:
        elapsed = datetime.now() - self._started_at
        h, rem  = divmod(int(elapsed.total_seconds()), 3600)
        m, s    = divmod(rem, 60)
        color   = "green" if self._mode == "PAPER" else "bold red"
        txt = (
            f"[bold]OIL TRADING BOT[/bold]  |  "
            f"[{color}]{self._mode} MODE[/{color}]  |  "
            f"Symbol: [cyan]{self._symbol}[/cyan]  |  "
            f"Uptime: [yellow]{h:02d}:{m:02d}:{s:02d}[/yellow]  |  "
            f"[dim]{datetime.now():%Y-%m-%d %H:%M:%S}[/dim]"
        )
        return Panel(txt, box=rbox.HEAVY_HEAD)

    def _stats(self) -> Panel:
        eq       = getattr(self._broker, "equity",        0.0)
        daily    = getattr(self._broker, "daily_pnl",     0.0)
        trades   = len(getattr(self._broker, "trade_history", []))
        halted   = getattr(self._risk, "is_halted", False) if self._risk else False
        risk_txt = "[red bold]HALTED[/red bold]" if halted else "[green]ACTIVE[/green]"
        pnl_col  = "green" if daily >= 0 else "red"

        txt = (
            f"Equity:    [bold white]{eq:>14,.2f}[/bold white] USD\n"
            f"Daily PnL: [{pnl_col} bold]{daily:>+14.2f}[/{pnl_col} bold] USD\n"
            f"Trades:    [white]{trades:>14}[/white]\n"
            f"Risk:      {risk_txt}"
        )
        return Panel(txt, title="[bold]Portfolio[/bold]", box=rbox.ROUNDED)

    def _position(self) -> Panel:
        pos = getattr(self._broker, "position", None)
        if pos is None:
            body = "[dim]No open position[/dim]"
        else:
            side_name  = pos.side.name if hasattr(pos.side, "name") else str(pos.side)
            side_color = "green" if side_name == "LONG" else "red"
            body = (
                f"Side:   [{side_color}]{side_name}[/{side_color}]\n"
                f"Qty:    {pos.quantity}\n"
                f"Entry:  {pos.entry_price:.3f}\n"
                f"SL:     {pos.stop_loss:.3f}\n"
                f"TP:     {pos.take_profit:.3f}\n"
                f"Since:  {pos.entry_time:%H:%M:%S}"
            )
        return Panel(body, title="[bold]Open Position[/bold]", box=rbox.ROUNDED)

    def _history(self) -> Panel:
        history = list(reversed(getattr(self._broker, "trade_history", [])))[:10]
        tbl = Table(box=rbox.SIMPLE, show_header=True, header_style="bold cyan")
        tbl.add_column("#",      width=4)
        tbl.add_column("Side",   width=6)
        tbl.add_column("Entry",  width=9)
        tbl.add_column("Exit",   width=9)
        tbl.add_column("PnL",    width=9)
        tbl.add_column("Reason", width=12)
        tbl.add_column("Time",   width=9)

        for t in history:
            side_name  = t.side.name if hasattr(t.side, "name") else str(t.side)
            pnl_color  = "green" if t.pnl >= 0 else "red"
            tbl.add_row(
                str(t.trade_id),
                side_name,
                f"{t.entry_price:.3f}",
                f"{t.exit_price:.3f}",
                f"[{pnl_color}]{t.pnl:+.2f}[/{pnl_color}]",
                t.exit_reason,
                f"{t.exit_time:%H:%M:%S}",
            )

        return Panel(tbl, title="[bold]Recent Trades (last 10)[/bold]", box=rbox.ROUNDED)
