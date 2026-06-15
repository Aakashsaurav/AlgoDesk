"""
config.py
----------
Central configuration for the AlgoDesk system.

All settings load from the .env file via python-dotenv.
Every other module imports from here — never hardcode paths elsewhere.

Usage:
    from config import config, setup_logging
    from config import IST          # fixed-offset UTC+5:30 (backward compat)
    from config import IST_TZ       # ZoneInfo("Asia/Kolkata") — DST-aware

    setup_logging()
    print(config.TOTAL_CAPITAL)

Note: In the test/workspace environment the .env file may not exist.
All settings fall back to sensible defaults so the system runs without
a live Upstox account (paper-trade / backtest mode).

P2 FIX (2026-04-11) — IST constant extracted here from 6 live_bot modules
==========================================================================
Six modules (engine.py, candle_builder.py, market_feed.py, paper_broker.py,
live_broker.py, risk_guard.py) each defined an identical local copy of:

    IST = timezone(timedelta(hours=5, minutes=30))

This means any future change (e.g. switching to ZoneInfo for proper DST
handling) required editing six files instead of one.

Fix: two module-level constants are now exported from here:

  ``IST``    — ``datetime.timezone(timedelta(hours=5, minutes=30))``
               Fixed UTC+5:30 offset. Identical to the six local definitions
               being replaced. Use this for ``datetime.now(tz=IST)`` calls
               where backward compatibility matters.

  ``IST_TZ`` — ``ZoneInfo("Asia/Kolkata")``
               The IANA timezone for Kolkata. Handles historical DST offsets
               correctly and is the preferred form for new code. Also used
               in broker/upstox/data_manager.py (P0 fix).

All six live_bot modules now do:

    from config import IST          # replaces local IST = timezone(...)

and remove their local definitions.
"""

from __future__ import annotations

import logging
import os
from datetime import timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# ── Optional dotenv loading (non-fatal if not installed) ─────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass  # python-dotenv not required for backtesting

# ── Module-level timezone constants ──────────────────────────────────────────
# P2 FIX: single canonical definition; all live_bot modules import from here.

IST: timezone = timezone(timedelta(hours=5, minutes=30))
"""Fixed UTC+5:30 offset.  Use with ``datetime.now(tz=IST)``.

Drop-in replacement for the six identical local definitions that previously
appeared across the live_bot package. Kept as a plain fixed-offset timezone
for backward compatibility with all existing ``tz=IST`` call sites.
"""

IST_TZ: ZoneInfo = ZoneInfo("Asia/Kolkata")
"""IANA timezone for Kolkata (``ZoneInfo("Asia/Kolkata")``).

Handles historical DST offsets correctly and is the preferred form for new
code and for any context that requires a proper pytz/zoneinfo-compatible
object (e.g. ``pd.Timestamp(..., tz=IST_TZ)``).

Used in ``broker/upstox/data_manager.py`` (P0 fix) and available for use
by any module that performs timezone-aware Pandas operations.
"""

# ── AppConfig ─────────────────────────────────────────────────────────────────

class AppConfig:
    """
    Central config object.  Import the module-level singleton:

        from config import config
        print(config.TOTAL_CAPITAL)
    """
    # ── Token storage ────────────────────────────────────────────────────────
    BASE_DIR: Path = Path(__file__).resolve().parent
    UPSTOX_TOKEN_FILE_PATH: Path = BASE_DIR / os.getenv(
        "TOKEN_FILE_PATH", "broker/upstox/token.json"
    )

    # ── Upstox API Credentials ───────────────────────────────────────────────
    UPSTOX_API_KEY:    str = os.getenv("UPSTOX_API_KEY",    "")
    UPSTOX_API_SECRET: str = os.getenv("UPSTOX_API_SECRET", "")
    UPSTOX_REDIRECT_URI: str = os.getenv(
        "UPSTOX_REDIRECT_URI", "https://127.0.0.1:5000/"
    )
    UPSTOX_REDIRECT_SSL_CERT_FILE: str = os.getenv(
        "UPSTOX_REDIRECT_SSL_CERT_FILE", 
        str(BASE_DIR / "broker" / "upstox" / "cert.pem")
    )
    UPSTOX_REDIRECT_SSL_KEY_FILE: str = os.getenv(
        "UPSTOX_REDIRECT_SSL_KEY_FILE", 
        str(BASE_DIR / "broker" / "upstox" / "key.pem")
    )

    # ── API base URLs ────────────────────────────────────────────────────────
    UPSTOX_BASE_URL:  str = "https://api.upstox.com"
    UPSTOX_AUTH_URL:  str = "https://api.upstox.com/v2/login/authorization/token"
    UPSTOX_AUTH_DIALOG_URL: str = "https://api.upstox.com/v2/login/authorization/dialog"

    # ── Capital & risk ───────────────────────────────────────────────────────
    TOTAL_CAPITAL:          float = float(os.getenv("TOTAL_CAPITAL",          "500000"))
    MAX_PORTFOLIO_DRAWDOWN: float = float(os.getenv("MAX_PORTFOLIO_DRAWDOWN", "20.0"))
    PER_TRADE_RISK_PERCENT: float = float(os.getenv("PER_TRADE_RISK_PERCENT", "1.5"))

    # ── Trading mode ─────────────────────────────────────────────────────────
    PAPER_TRADE: bool = os.getenv("PAPER_TRADE", "True").lower() == "true"

    # ── Market hours (IST) ────────────────────────────────────────────────────
    MARKET_OPEN_TIME:       str = "09:15"
    MARKET_CLOSE_TIME:      str = "15:30"
    INTRADAY_SQUAREOFF_TIME:str = "15:20"

    # ── Data storage paths ───────────────────────────────────────────────────
    DATA_DIR:    Path = BASE_DIR / "data"
    OHLCV_DIR:   Path = DATA_DIR / "ohlcv"
    SQLITE_DIR:  Path = DATA_DIR / "sqlite"
    LIVE_TICK_DIR: Path = DATA_DIR / "live_ticks"
    UNIVERSE_DIR: Path = DATA_DIR / "universes"
    CUSTOM_INDICATOR: Path = BASE_DIR / "indicators" / "custom_indicators.db"

    # ── Screener settings ────────────────────────────────────────────────────
    SCREENER_OUTPUT_DIR: Path = BASE_DIR / "screener" / "output"
    SCREENER_MAX_WORKERS: int = int(os.getenv("SCREENER_MAX_WORKERS", "8"))
    SCREENER_TIMEOUT_PER_SYMBOL: float = float(os.getenv("SCREENER_TIMEOUT_PER_SYMBOL", "30.0"))
    SCREENER_HISTORY_DB: Path = SQLITE_DIR / "screener_history.db"

    # ── Backtester settings ──────────────────────────────────────────────────
    BACKTESTER_OUTPUT_DIR: Path = BASE_DIR / "backtester" / "output"
    BACKTESTER_TRADE_DIR: Path  = BACKTESTER_OUTPUT_DIR / "trade"
    BACKTESTER_CHART_DIR: Path  = BACKTESTER_OUTPUT_DIR / "chart"
    BACKTESTER_REPORT_DIR: Path = BACKTESTER_OUTPUT_DIR / "report"
    BACKTESTER_MAX_WORKERS: int = int(os.getenv("BACKTESTER_MAX_WORKERS", "4"))

    # Legacy flat paths — used by broker/upstox/data_manager.py.
    # New code should use DataManager which builds hierarchical paths:
    #   ohlcv/<exchange>/<instrument_type>/<timeframe>/<symbol>/
    DAILY_DIR:   Path = OHLCV_DIR / "daily"
    MINUTE_DIR:  Path = OHLCV_DIR / "minute"
    WEEKLY_DIR:  Path = OHLCV_DIR / "weekly"

    # ── Data provider settings ───────────────────────────────────────────────
    YFINANCE_RATE_LIMIT_PER_SEC: float = float(
        os.getenv("YFINANCE_RATE_LIMIT_PER_SEC", "2.0")
    )
    YFINANCE_MAX_CONCURRENT: int = int(
        os.getenv("YFINANCE_MAX_CONCURRENT", "3")
    )
    UPSTOX_RATE_LIMIT_PER_SEC: float = float(
        os.getenv("UPSTOX_RATE_LIMIT_PER_SEC", "25.0")
    )
    UPSTOX_RATE_LIMIT_PER_MIN: float = float(
        os.getenv("UPSTOX_RATE_LIMIT_PER_MIN", "500.0")
    )

    # ── Database paths ───────────────────────────────────────────────────────
    METADATA_DB:   Path = SQLITE_DIR / "metadata.db"
    TRADES_DB:     Path = SQLITE_DIR / "trades.db"
    STRATEGIES_DB: Path = SQLITE_DIR / "strategies.db"

    # ── Logging ──────────────────────────────────────────────────────────────
    LOG_LEVEL: str  = os.getenv("LOG_LEVEL", "INFO").upper()
    LOG_FILE:  Path = BASE_DIR / "logs" / "app.log"

    # ── Notifications (optional) ─────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID:   str = os.getenv("TELEGRAM_CHAT_ID",   "")

    # ── Instrument master ────────────────────────────────────────────────────
    INSTRUMENT_KEY_URL: str = (
        "https://assets.upstox.com/market-quote/instruments/"
        "exchange/complete.json.gz"
    )
    INSTRUMENT_KEY_PATH: Path = BASE_DIR / "broker" / "upstox" / "complete_instru_list.json"

    def __init__(self) -> None:
        self._create_directories()

    def _create_directories(self) -> None:
        """Ensure all required directories exist at startup."""
        for d in (
            self.DATA_DIR, self.OHLCV_DIR, self.SQLITE_DIR,
            self.LIVE_TICK_DIR, self.UNIVERSE_DIR,
            self.SCREENER_OUTPUT_DIR,
            self.BACKTESTER_OUTPUT_DIR, self.BACKTESTER_TRADE_DIR,
            self.BACKTESTER_CHART_DIR, self.BACKTESTER_REPORT_DIR,
            self.BASE_DIR / "logs",
        ):
            try:
                d.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass  # non-fatal in read-only test environments

    def display_summary(self) -> None:
        """Print a non-sensitive config summary for startup verification."""
        sep = "=" * 55
        print(sep)
        print("  ALGODESK — CONFIG SUMMARY")
        print(sep)
        mode = "✅ PAPER (safe)" if self.PAPER_TRADE else "🔴 LIVE (real money)"
        print(f"  Paper Trade Mode : {mode}")
        print(f"  Total Capital    : ₹{self.TOTAL_CAPITAL:,.0f}")
        print(f"  Per-Trade Risk   : {self.PER_TRADE_RISK_PERCENT}%")
        print(f"  Max Drawdown     : {self.MAX_PORTFOLIO_DRAWDOWN}%")
        print(f"  Data Directory   : {self.DATA_DIR}")
        print(f"  Log Level        : {self.LOG_LEVEL}")
        print(sep)


# ── setup_logging ─────────────────────────────────────────────────────────────

def setup_logging() -> logging.Logger:
    """
    Configure application-wide logging.

    Outputs to both the console and logs/app.log.
    Safe to call multiple times — duplicate handlers are suppressed.

    Returns the root logger.  Individual modules use:
        import logging
        logger = logging.getLogger(__name__)
    """
    log_dir = Path(__file__).resolve().parent / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    log_level = getattr(
        logging,
        os.getenv("LOG_LEVEL", "INFO").upper(),
        logging.INFO,
    )

    formatter = logging.Formatter(
        fmt     = "%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s",
        datefmt = "%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(log_level)

    # Avoid adding duplicate handlers on repeated calls
    if not root.handlers:
        # Console
        ch = logging.StreamHandler()
        ch.setFormatter(formatter)
        root.addHandler(ch)

        # File (non-fatal if directory is read-only)
        try:
            fh = logging.FileHandler(log_dir / "app.log", encoding="utf-8")
            fh.setFormatter(formatter)
            root.addHandler(fh)
        except (OSError, PermissionError):
            pass

    return root


# ── Module-level singleton ────────────────────────────────────────────────────
# All other modules import this:
#   from config import config
config = AppConfig()
