"""
risk_manager.py — Daily risk gate for the backtesting system.

Responsibilities:
  - Track daily realised PnL.
  - Block new trades once ``max_daily_loss`` is breached.
  - Reset state at the start of each new session.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from config import RiskConfig
from utils.logger import get_logger

log = get_logger("risk_manager")


class RiskManager:
    """
    Stateful daily risk manager.

    Parameters
    ----------
    risk_config : RiskConfig
        Stop-loss, take-profit, and max-daily-loss parameters.
    """

    def __init__(self, risk_config: RiskConfig) -> None:
        self._cfg = risk_config
        self._current_date:  Optional[date] = None
        self._daily_pnl:     float          = 0.0
        self._trading_halted: bool          = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reset_daily(self, session_date: date) -> None:
        """
        Reset daily counters for a new session.

        Called by the engine at the start of each calendar date.
        """
        if session_date != self._current_date:
            log.debug("Risk reset for session %s  (prev P&L: %.2f)", session_date, self._daily_pnl)
            self._current_date   = session_date
            self._daily_pnl      = 0.0
            self._trading_halted = False

    def can_trade(self, session_date: date) -> bool:
        """
        Return ``True`` if new trades are allowed for this session.

        Trading is blocked when cumulative daily losses exceed
        ``max_daily_loss``.
        """
        if self._trading_halted:
            log.debug("[%s] Trading halted — daily loss limit reached", session_date)
            return False
        return True

    def record_trade(self, session_date: date, pnl: float) -> None:
        """
        Update daily PnL after a trade closes and check the loss limit.

        Parameters
        ----------
        session_date : date
            The date on which the trade closed.
        pnl : float
            Net PnL of the completed trade (positive = profit).
        """
        self._daily_pnl += pnl

        log.info(
            "[%s] Trade PnL: %+.2f  | Daily cumulative: %+.2f  | Limit: -%.2f",
            session_date, pnl, self._daily_pnl, self._cfg.max_daily_loss,
        )

        if self._daily_pnl <= -self._cfg.max_daily_loss:
            self._trading_halted = True
            log.warning(
                "[%s] MAX DAILY LOSS REACHED (%.2f). "
                "Trading halted for the remainder of the session.",
                session_date, self._daily_pnl,
            )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def daily_pnl(self) -> float:
        return self._daily_pnl

    @property
    def is_halted(self) -> bool:
        return self._trading_halted
