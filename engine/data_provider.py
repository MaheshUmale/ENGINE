import upstox_client
from upstox_client.rest import ApiException
import pandas as pd
import datetime
import json
import asyncio
import ssl
import requests
import gzip
import io
from .config import ACCESS_TOKEN, INDICES
from .database import get_session, RawTick, Candle

class DataProvider:
    def __init__(self, access_token=ACCESS_TOKEN):
        self.configuration = upstox_client.Configuration()
        self.configuration.access_token = access_token
        self.api_instance = upstox_client.MarketQuoteApi(upstox_client.ApiClient(self.configuration))
        self.history_api = upstox_client.HistoryApi(upstox_client.ApiClient(self.configuration))
        self.options_api = upstox_client.OptionsApi(upstox_client.ApiClient(self.configuration))
        self.instruments = {} # Store current instruments for each index
        self.running = False
        self.oi_cache = {} # instrument_key -> last_oi
        self.instrument_df = None
        self.last_master_update = None

    def get_market_quote(self, symbol_list):
        if isinstance(symbol_list, list):
            symbol_list = ",".join(symbol_list)
        try:
            api_response = self.api_instance.get_full_market_quote(symbol_list, '2.0')
            # Normalize keys to use | instead of :
            normalized_data = {}
            for k, v in api_response.data.items():
                normalized_key = k.replace(':', '|')
                normalized_data[normalized_key] = v
            return normalized_data
        except ApiException as e:
            print(f"Exception when calling MarketQuoteApi->get_full_market_quote: {e}")
            return None

    def get_historical_data(self, instrument_key, interval='1minute', to_date=None, from_date=None):
        if to_date is None:
            to_date = datetime.datetime.now().strftime('%Y-%m-%d')
        if from_date is None:
            from_date = (datetime.datetime.now() - datetime.timedelta(days=10)).strftime('%Y-%m-%d')

        # If fetching for today, use intraday API
        today_str = datetime.datetime.now().strftime('%Y-%m-%d')

        try:
            if to_date == today_str:
                api_response = self.history_api.get_intra_day_candle_data(instrument_key, interval, '2.0')
            else:
                api_response = self.history_api.get_historical_candle_data1(instrument_key, interval, to_date, from_date, '2.0')

            if api_response.status == 'success':
                df = pd.DataFrame(api_response.data.candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'oi'])
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                return df
            return None
        except ApiException as e:
            print(f"Exception when calling HistoryApi: {e}")
            return None

    def fetch_instrument_master(self):
        # Only download if not already downloaded today
        today = datetime.date.today()
        if self.instrument_df is not None and self.last_master_update == today:
            return self.instrument_df

        print("Downloading Upstox Instrument Master...")
        url = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
        response = requests.get(url)
        if response.status_code == 200:
            with gzip.GzipFile(fileobj=io.BytesIO(response.content)) as f:
                self.instrument_df = pd.read_json(f)
                self.last_master_update = today
                return self.instrument_df
        return None

    async def get_instrument_details(self, index_name):
        """
        Dynamically discovers ATM options and nearest expiry for the given index using Instrument Master.
        """
        index_key = INDICES[index_name]['index_key']
        quotes = self.get_market_quote([index_key])
        if not quotes:
            return None

        ltp = quotes[index_key].last_price
        df = self.fetch_instrument_master()
        if df is None: return None

        try:
            # For FO instruments, name is just NIFTY/BANKNIFTY
            fo_name = index_name

            # --- 1. Current Month Future ---
            fut_df = df[(df['name'] == fo_name) & (df['instrument_type'] == 'FUT')].sort_values(by='expiry')

            if fut_df.empty: return None
            current_fut_key = fut_df.iloc[0]['instrument_key']

            # --- 2. Nearest Expiry Options ---
            opt_df = df[(df['name'] == fo_name) & (df['instrument_type'].isin(['CE', 'PE']))].copy()

            if opt_df.empty: return None

            # Expiry is in ms
            opt_df['expiry_dt'] = pd.to_datetime(opt_df['expiry'], unit='ms')
            nearest_expiry = opt_df['expiry_dt'].min()
            near_opt_df = opt_df[opt_df['expiry_dt'] == nearest_expiry]

            # --- 3. Identify ATM Strike ---
            unique_strikes = sorted(near_opt_df['strike_price'].unique())
            atm_strike = min(unique_strikes, key=lambda x: abs(x - ltp))

            ce_row = near_opt_df[(near_opt_df['strike_price'] == atm_strike) & (near_opt_df['instrument_type'] == 'CE')]
            pe_row = near_opt_df[(near_opt_df['strike_price'] == atm_strike) & (near_opt_df['instrument_type'] == 'PE')]

            if ce_row.empty or pe_row.empty: return None

            return {
                'index': index_key,
                'ce': ce_row.iloc[0]['instrument_key'],
                'pe': pe_row.iloc[0]['instrument_key'],
                'fut': current_fut_key,
                'ltp': ltp,
                'strike': float(atm_strike),
                'expiry': nearest_expiry.strftime('%Y-%m-%d')
            }
        except Exception as e:
            print(f"Discovery Error: {e}")
            return None

    async def start_streaming(self, instrument_keys, callback):
        """
        Starts the Upstox Market Data Feed using the SDK's built-in Feeder.
        """
        def on_message(message):
            # message is already decoded by the SDK
            asyncio.run_coroutine_threadsafe(callback(message), asyncio.get_event_loop())

        def on_error(error):
            print(f"WebSocket Error: {error}")

        def on_open():
            print("WebSocket Connection Opened")
            # Subscribe
            feeder.subscribe(instrument_keys, "full")

        def on_close(close_status_code, close_msg):
            print(f"WebSocket Closed: {close_status_code} - {close_msg}")

        try:
            feeder = upstox_client.MarketDataFeed(
                upstox_client.ApiClient(self.configuration),
                on_message=on_message,
                on_error=on_error,
                on_open=on_open,
                on_close=on_close
            )
            feeder.connect()
            self.running = True
        except Exception as e:
            print(f"Failed to start streaming: {e}")

    def calculate_oi_delta(self, instrument_key, current_oi):
        # Use in-memory cache for performance
        last_oi = self.oi_cache.get(instrument_key)
        self.oi_cache[instrument_key] = current_oi

        if last_oi is not None:
            return current_oi - last_oi
        return 0
