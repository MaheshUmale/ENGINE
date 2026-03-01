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
            "level": "WARNING"
        },
        "file": {
            "class": "logging.FileHandler",
            "filename": "logs/protrade.log",
            "formatter": "default",
            "level": "DEBUG"
        }
    },
    "root": {
        "level": "WARNING",
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
UPSTOX_ACCESS_TOKEN = os.getenv("UPSTOX_ACCESS_TOKEN", "eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiI3NkFGMzUiLCJqdGkiOiI2OWEzYWMxNDU3NDY0OTRiNzVjMDExNWEiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlhdCI6MTc3MjMzNDEwMCwiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxNzcyNDAyNDAwfQ.rLX_N6O-YexrShbTI0GqPJY0oN2aQVu61ehUbW6XeAc")
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
    "backfill_interval_minutes": 5,  # 5-minute intervals for backfill
    "enable_tv_volume_merge": False  # Disabled to speed up backtesting and avoid TV hangs
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

# ==============================================================================
# SYMMETRY ENGINE CONFIGURATION
# ==============================================================================

# Strategy Parameters
SYMMETRY_TIMEFRAMES = [1, 3, 5]  # In minutes
SYMMETRY_STRIKE_UPDATE_INTERVAL = 300  # 5 minutes in seconds
SYMMETRY_STRIKE_UPDATE_THRESHOLD = 25  # Index move in points

# Instruments to monitor
SYMMETRY_INDICES = {
    'NIFTY': {
        'index_key': 'NSE_INDEX|Nifty 50',
        'lot_size': 75
    },
    'BANKNIFTY': {
        'index_key': 'NSE_INDEX|Nifty Bank',
        'lot_size': 15
    }
}

# Database Config for Symmetry Engine
SYMMETRY_DB_PATH = os.path.join('data', 'trading_engine.db')

# Strategy Specifics
SYMMETRY_SWING_WINDOW = 15  # 15 minutes rolling swing
SYMMETRY_CONFLUENCE_THRESHOLD = 4  # All 4 conditions must be met

# Paper Trading Config
SYMMETRY_INITIAL_BALANCE = 1000000
SYMMETRY_SL_TRAILING = True

# Enhancement: Multi-Index Sync
SYMMETRY_ENABLE_INDEX_SYNC = True
