import os
from dotenv import load_dotenv

load_dotenv()

# Upstox Access Token# Upstox Access Token
ACCESS_TOKEN = 'eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiI3NkFGMzUiLCJqdGkiOiI2OTliY2JkODdmODBmOTFjMDgxNWJlYzUiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlhdCI6MTc3MTgxNzk0NCwiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxNzcxODg0MDAwfQ.CvOrpuM3kC6w_qd7U6lXIUSN0yDMmLdZWw2VNN5ie2A'


# Strategy Parameters
TIMEFRAMES = [1, 3, 5]  # In minutes
STRIKE_UPDATE_INTERVAL = 300  # 5 minutes in seconds
STRIKE_UPDATE_THRESHOLD = 25  # Index move in points

# Instruments to monitor
INDICES = {
    'NIFTY': {
        'index_key': 'NSE_INDEX|Nifty 50',
        'lot_size': 75
    },
    'BANKNIFTY': {
        'index_key': 'NSE_INDEX|Nifty Bank',
        'lot_size': 15
    }
}

# Database Config
DB_PATH = 'trading_engine.db'

# Strategy Specifics
SWING_WINDOW = 15  # 15 minutes rolling swing
CONFLUENCE_THRESHOLD = 4  # All 4 conditions must be met

# Paper Trading Config
INITIAL_BALANCE = 1000000
SL_TRAILING = True

# Enhancement: Multi-Index Sync
ENABLE_INDEX_SYNC = True
