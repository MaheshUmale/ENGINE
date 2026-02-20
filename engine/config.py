import os
from dotenv import load_dotenv

load_dotenv()

# Upstox Access Token
ACCESS_TOKEN = os.getenv('UPSTOX_ACCESS_TOKEN')

# Strategy Parameters
TIMEFRAMES = [1, 3, 5]  # In minutes
STRIKE_UPDATE_INTERVAL = 300  # 5 minutes in seconds
STRIKE_UPDATE_THRESHOLD = 25  # Index move in points

# Instruments to monitor
INDICES = {
    'NIFTY': {
        'index_key': 'NSE_INDEX|Nifty 50',
        'fut_key': 'NSE_FO|NIFTY26FEB25FUT',  # Example future key, will be dynamically updated
        'expiry_tag': 'NIFTY26FEB25'
    },
    'BANKNIFTY': {
        'index_key': 'NSE_INDEX|Nifty Bank',
        'fut_key': 'NSE_FO|BANKNIFTY26FEB25FUT',
        'expiry_tag': 'BANKNIFTY26FEB25'
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
