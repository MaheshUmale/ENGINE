"""
Configuration for ProTrade Enhanced Options Trading Platform
"""

import os
from typing import List, Dict, Any

# Server Configuration
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "3000"))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# Logging Configuration
LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "level": "INFO"
        },
        "file": {
            "class": "logging.FileHandler",
            "filename": "logs/protrade.log",
            "formatter": "default",
            "level": "DEBUG"
        }
    },
    "root": {
        "level": "INFO",
        "handlers": ["console", "file"]
    }
}

# Options Configuration
OPTIONS_UNDERLYINGS: List[str] = [
    "NSE:NIFTY",
    "NSE:BANKNIFTY"
]

# Initial instruments for WebSocket feed
INITIAL_INSTRUMENTS: List[str] = [
    "NSE:NIFTY",
    "NSE:BANKNIFTY"
]

# Greeks Calculator Configuration
GREEKS_CONFIG = {
    "risk_free_rate": 0.10,  # 10% annual risk-free rate for India
    "default_volatility": 0.20,  # 20% default IV
    "min_time_to_expiry": 0.0001  # Minimum time to prevent division by zero
}

# IV Analyzer Configuration
IV_ANALYZER_CONFIG = {
    "lookback_days": 252,  # 1 year of IV history
    "high_iv_threshold": 70,  # IV Rank above this is high
    "low_iv_threshold": 30,   # IV Rank below this is low
    "spike_threshold": 2.0    # Standard deviations for spike detection
}

# OI Buildup Analyzer Configuration
OI_BUILDUP_CONFIG = {
    "oi_change_threshold": 2.0,      # 2% OI change for pattern detection
    "price_change_threshold": 0.5,   # 0.5% price change threshold
    "strong_buildup_oi_pct": 10,     # 10% OI change = strong
    "strong_buildup_price_pct": 2,   # 2% price change = strong
    "moderate_buildup_oi_pct": 5,    # 5% OI change = moderate
    "moderate_buildup_price_pct": 1  # 1% price change = moderate
}

# Alert System Configuration
ALERT_CONFIG = {
    "default_cooldown_minutes": 15,
    "max_alerts_per_user": 50,
    "cleanup_interval_hours": 24
}

# Strategy Builder Configuration
STRATEGY_CONFIG = {
    "max_legs": 8,  # Maximum legs in a custom strategy
    "default_quantity": 1,
    "supported_strategies": [
        "LONG_CALL",
        "LONG_PUT",
        "SHORT_CALL",
        "SHORT_PUT",
        "BULL_CALL_SPREAD",
        "BEAR_PUT_SPREAD",
        "BULL_PUT_SPREAD",
        "BEAR_CALL_SPREAD",
        "IRON_CONDOR",
        "IRON_BUTTERFLY",
        "LONG_STRADDLE",
        "SHORT_STRADDLE",
        "LONG_STRANGLE",
        "SHORT_STRANGLE",
        "CALL_CALENDAR",
        "PUT_CALENDAR"
    ]
}

# Upstox Configuration
UPSTOX_ACCESS_TOKEN = 'eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiI3NkFGMzUiLCJqdGkiOiI2OTlkMTZlY2YxODdhOTZmZWIwNjQ3NmUiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlhdCI6MTc3MTkwMjcwMCwiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxNzcxOTcwNDAwfQ.ACiFI05Qa-_rGJJc6jqiHzK60FZfpttbreFjwNVqQJ8' 
#os.getenv("UPSTOX_ACCESS_TOKEN", "")

UPSTOX_INDEX_MAP = {
    "NSE:NIFTY": "NSE_INDEX|Nifty 50",
    "NSE:BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "BSE:SENSEX": "BSE_INDEX|SENSEX",
    "BSE:BANKEX": "BSE_INDEX|BANKEX",
}

# TradingView Cookie (Optional)
TV_COOKIE = os.getenv("TV_COOKIE", "")
try:
    import rookiepy
    # Retrieve Brave cookies for TradingView
    TV_COOKIE = rookiepy.to_cookiejar(rookiepy.brave(['.tradingview.com']))
    print("TradingView cookies loaded via rookiepy (Brave)")
except Exception as e:
    # Fallback to env var string if rookiepy fails or isn't needed
    pass

TV_STUDY_ID = os.getenv("TV_STUDY_ID", "USER:f9c7fa68b382417ba34df4122c632dcf")

# Database Configuration
DATABASE_CONFIG = {
    "path": "data/protrade.db",
    "backup_interval_hours": 24,
    "retention_days": 30
}

# TradingView API Configuration
TV_CONFIG = {
    "ws_url": "wss://data.tradingview.com/socket.io/websocket",
    "api_url": "https://www.tradingview.com",
    "timeout_seconds": 30,
    "reconnect_attempts": 5
}

# NSE API Configuration
NSE_CONFIG = {
    "base_url": "https://www.nseindia.com",
    "option_chain_url": "https://www.nseindia.com/api/option-chain-indices",
    "timeout_seconds": 30,
    "rate_limit_per_second": 1
}

# Trendlyne API Configuration
TRENDLYNE_CONFIG = {
    "base_url": "https://trendlyne.com",
    "timeout_seconds": 30
}

# Market Hours (IST)
MARKET_HOURS = {
    "open": "09:15",
    "close": "15:30",
    "pre_market": "09:00",
    "post_market": "15:45"
}

# Snapshot Configuration
SNAPSHOT_CONFIG = {
    "interval_seconds": 180,  # 3 minutes between snapshots
    "backfill_interval_minutes": 5  # 5-minute intervals for backfill
}

# Feature Flags
FEATURES = {
    "greeks_calculation": True,
    "iv_analysis": True,
    "oi_buildup_analysis": True,
    "strategy_builder": True,
    "alert_system": True,
    "paper_trading": False,  # Coming in future release
    "backtesting": False     # Coming in future release
}

# UI Configuration
UI_CONFIG = {
    "default_underlying": "NSE:NIFTY",
    "refresh_interval_seconds": 5,
    "chart_history_days": 30,
    "max_strikes_displayed": 50
}
