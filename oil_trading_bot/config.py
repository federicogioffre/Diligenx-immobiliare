"""
config.py — Central configuration for oil_trading_bot.

All tuneable parameters live here. Import this module anywhere you need
a setting; never hard-code values elsewhere.
"""

from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT_DIR: Path = Path(__file__).parent
DATASETS_DIR: Path = ROOT_DIR / "datasets"
REPORTS_DIR: Path = ROOT_DIR / "reports"
LOGS_DIR: Path = ROOT_DIR / "logs"

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
DEFAULT_DATASET: Path = DATASETS_DIR / "example_dataset.csv"
TIMESTAMP_COL: str = "timestamp"
CANDLE_INTERVAL_MINUTES: int = 5          # expected bar frequency

# ---------------------------------------------------------------------------
# Strategy — Opening Range Breakout
# ---------------------------------------------------------------------------
@dataclass
class ORBConfig:
    """Parameters for the Opening Range Breakout strategy."""
    # Opening range window (24-hour HH:MM strings, UTC or exchange local)
    range_start: str = "09:30"
    range_end:   str = "10:00"

    # Volume multiplier required to confirm a breakout
    volume_multiplier: float = 0.5

    # Maximum trades per direction per session (long / short)
    max_trades_per_direction: int = 1


# ---------------------------------------------------------------------------
# Strategy — Volatility Compression Breakout
# ---------------------------------------------------------------------------
@dataclass
class VCBConfig:
    """
    Parameters for the Volatility Compression Breakout strategy.

    The strategy waits for the market to enter a *squeeze* — a period where
    the N-bar rolling range is unusually narrow relative to the ATR — then
    trades the first decisive breakout in the direction of the EMA trend.

    Indicator periods
    -----------------
    ema_period : int
        Lookback for the exponential moving average (trend filter).
    atr_period : int
        Lookback for the Average True Range (volatility baseline).
    range_period : int
        Number of bars used to compute the rolling high/low range.

    Compression
    -----------
    compression_threshold : float
        A bar is *compressed* when:
            (range_high − range_low) < compression_threshold × ATR
        Lower values = stricter squeeze required before signalling.

    Risk management
    ---------------
    atr_sl_multiplier : float
        stop_loss distance = ATR × atr_sl_multiplier
    atr_tp_multiplier : float
        take_profit distance = ATR × atr_tp_multiplier
        Default 2.0 → 1:2 risk-reward ratio.

    max_trades_per_day : int
        Hard cap on signals per calendar session (all directions combined).
    """
    ema_period:             int   = 50
    atr_period:             int   = 14
    range_period:           int   = 20
    compression_threshold:  float = 0.8   # range < threshold × ATR → squeeze
    atr_sl_multiplier:      float = 1.0   # SL = 1 × ATR
    atr_tp_multiplier:      float = 2.0   # TP = 2 × ATR  (1:2 R:R)
    max_trades_per_day:     int   = 3


# ---------------------------------------------------------------------------
# Risk Management
# ---------------------------------------------------------------------------
@dataclass
class RiskConfig:
    """Position-sizing and loss-limit parameters."""
    stop_loss_dollars: float  = 1.20    # distance from entry to stop (per contract)
    take_profit_dollars: float = 2.40   # distance from entry to take-profit
    max_daily_loss: float     = 500.0   # shut down trading for the session beyond this
    position_size: int        = 1       # contracts per trade


# ---------------------------------------------------------------------------
# Broker Simulator
# ---------------------------------------------------------------------------
@dataclass
class BrokerConfig:
    """Slippage and commission model."""
    slippage_per_side: float  = 0.05    # dollars per contract per side
    commission_per_side: float = 0.50   # dollars per contract per side


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------
RISK_FREE_RATE_ANNUAL: float = 0.05     # annualised, used in Sharpe calculation
TRADING_DAYS_PER_YEAR: int  = 252


# ---------------------------------------------------------------------------
# Convenience: single top-level config object
# ---------------------------------------------------------------------------
@dataclass
class Config:
    orb: ORBConfig       = field(default_factory=ORBConfig)
    vcb: VCBConfig       = field(default_factory=VCBConfig)
    risk: RiskConfig     = field(default_factory=RiskConfig)
    broker: BrokerConfig = field(default_factory=BrokerConfig)


# Singleton used by the rest of the codebase
config = Config()
