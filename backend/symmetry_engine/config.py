import os
from dotenv import load_dotenv

load_dotenv()

# Upstox Access Token
# ACCESS_TOKEN = os.getenv("UPSTOX_ACCESS_TOKEN", "")
UPSTOX_ACCESS_TOKEN ='eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiI3NkFGMzUiLCJqdGkiOiI2OTllNzU5ZTBlYWIzMzMxMDM0MDg4MmUiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlhdCI6MTc3MTk5MjQ3OCwiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxNzcyMDU2ODAwfQ.C3NczS3N3g-jw0ySiBu4oAO4OuP4y94tw5KFDM4yS-M'
ACCESS_TOKEN=UPSTOX_ACCESS_TOKEN


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
# Resolve absolute path relative to project root
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(BASE_DIR, 'data', 'trading_engine.db')

# Strategy Specifics
SWING_WINDOW = 15  # 15 minutes rolling swing
CONFLUENCE_THRESHOLD = 4  # All 4 conditions must be met

# Paper Trading Config
INITIAL_BALANCE = 1000000
SL_TRAILING = True

# Enhancement: Multi-Index Sync
ENABLE_INDEX_SYNC = True
