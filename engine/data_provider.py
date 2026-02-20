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
        self.api_instance = upstox_client.MarketQuoteV3Api(upstox_client.ApiClient(self.configuration))
        self.history_api = upstox_client.HistoryV3Api(upstox_client.ApiClient(self.configuration))
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
            # Using V3 get_ltp
            api_response = self.api_instance.get_ltp(instrument_key=symbol_list)
            # Normalize keys to use | instead of :
            normalized_data = {}
            for k, v in api_response.data.items():
                normalized_key = k.replace(':', '|')
                normalized_data[normalized_key] = v
            return normalized_data
        except Exception as e:
            print(f"Exception when calling MarketQuoteV3Api->get_ltp: {e}")
            return None
        
    def getData(self, instrument_key, interval=1, to_date=None, from_date=None):
        import upstox_client
        configuration = upstox_client.Configuration()
        configuration.access_token = ACCESS_TOKEN
        apiInstance = upstox_client.HistoryV3Api(upstox_client.ApiClient(configuration))
        try:
            response = apiInstance.get_historical_candle_data1(instrument_key, "minutes", "1", to_date, from_date )

            #convert response into DF as timestmap ,o ,h l ,c v, oi 
            df = pd.DataFrame(response.data.candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'oi'])
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            return df 
        # except ApiException as e:
        except Exception as e:
            print("Exception when calling HistoryV3Api->get_historical_candle_data1: %s\n" % e)
            
    def get_historical_data(self, instrument_key, interval=1, to_date=None, from_date=None):
        if to_date is None:
            to_date = datetime.datetime.now().strftime('%Y-%m-%d')
        if from_date is None:
            from_date = (datetime.datetime.now() - datetime.timedelta(days=10)).strftime('%Y-%m-%d')

        # If fetching for today, use intraday API
        today_str = datetime.datetime.now().strftime('%Y-%m-%d')

        # V3 interval is usually passed as string in some examples, let's try string
        try:
            interval_str = str(interval)
            if to_date == today_str:
                api_response = self.history_api.get_intra_day_candle_data(instrument_key, "minutes", interval_str)
            else:
                api_response = self.history_api.get_historical_candle_data1(instrument_key, "minutes", 1, to_date, from_date)
                self.getData(instrument_key, 1, to_date, from_date)
            if api_response.status == 'success':
                df = pd.DataFrame(api_response.data.candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'oi'])
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                return df
            else:
                print(f"HistoryV3Api status error: {api_response}")
            return None
        except Exception as e:
            print(f"Exception when calling HistoryV3Api: {e}")
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
        Starts the Upstox Market Data Streamer V3.
        """
        loop = asyncio.get_event_loop()
        def on_message(message):
            # message is already decoded by the SDK
            asyncio.run_coroutine_threadsafe(callback(message), loop)

        def on_error(error):
            print(f"WebSocket Error: {error}")

        def on_open():
            print("WebSocket Connection Opened")

        try:
            self.streamer = upstox_client.MarketDataStreamerV3(
                upstox_client.ApiClient(self.configuration),
                instrument_keys,
                "full"
            )
            self.streamer.on("message", on_message)
            self.streamer.on("error", on_error)
            self.streamer.on("open", on_open)

            self.streamer.connect()
            self.running = True
        except Exception as e:
            print(f"Failed to start streaming V3: {e}")

    def calculate_oi_delta(self, instrument_key, current_oi):
        # Use in-memory cache for performance
        last_oi = self.oi_cache.get(instrument_key)
        self.oi_cache[instrument_key] = current_oi

        if last_oi is not None:
            return current_oi - last_oi
        return 0
