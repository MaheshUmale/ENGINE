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
import os
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

    def get_historical_data(self, instrument_key, interval=1, to_date=None, from_date=None):
        if to_date is None:
            to_date = datetime.datetime.now().strftime('%Y-%m-%d')
        if from_date is None:
            from_date = (datetime.datetime.now() - datetime.timedelta(days=10)).strftime('%Y-%m-%d')

        try:
            all_candles = []
            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'Authorization': f'Bearer {self.configuration.access_token}'
            }
            # V3 API expects the pipe character in the instrument key

            # 1. Historical Data
            v3_url_hist = f"https://api.upstox.com/v3/historical-candle/{instrument_key}/minutes/{interval}/{to_date}/{from_date}"
            resp = requests.get(v3_url_hist, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('status') == 'success' and 'candles' in data.get('data', {}):
                    all_candles.extend(data['data']['candles'])

            # 2. Intraday Data (if range includes today)
            today_str = datetime.datetime.now().strftime('%Y-%m-%d')
            # If to_date is today or after today
            if to_date >= today_str:
                v3_url_intra = f"https://api.upstox.com/v3/historical-candle/intraday/{instrument_key}/minutes/{interval}"
                resp_intra = requests.get(v3_url_intra, headers=headers)
                if resp_intra.status_code == 200:
                    data_intra = resp_intra.json()
                    if data_intra.get('status') == 'success' and 'candles' in data_intra.get('data', {}):
                        existing_ts = {c[0] for c in all_candles}
                        for c in data_intra['data']['candles']:
                            if c[0] not in existing_ts:
                                all_candles.append(c)

            if all_candles:
                df = pd.DataFrame(all_candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'oi'])
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                df = df.sort_values('timestamp').drop_duplicates('timestamp')
                return df
            else:
                print(f"No candles found for {instrument_key} using V3 APIs")
            return None
        except Exception as e:
            print(f"Exception when fetching V3 historical: {e}")
            return None

    def fetch_instrument_master(self):
        # Local cache file
        cache_file = "nse_instruments.json"
        today = datetime.date.today()

        # Only download if not already downloaded today
        if self.instrument_df is not None and self.last_master_update == today:
            return self.instrument_df

        # Check for local file
        if os.path.exists(cache_file):
            mtime = datetime.date.fromtimestamp(os.path.getmtime(cache_file))
            if mtime == today:
                print("Loading Upstox Instrument Master from local cache...")
                self.instrument_df = pd.read_json(cache_file)
                self.last_master_update = today
                return self.instrument_df

        print("Downloading Upstox Instrument Master...")
        url = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
        try:
            response = requests.get(url, timeout=30)
            if response.status_code == 200:
                with gzip.GzipFile(fileobj=io.BytesIO(response.content)) as f:
                    self.instrument_df = pd.read_json(f)
                    self.last_master_update = today
                    # Save to local cache
                    self.instrument_df.to_json(cache_file)
                    return self.instrument_df
        except Exception as e:
            print(f"Error downloading master: {e}")
            if os.path.exists(cache_file):
                print("Fallback to old cache...")
                self.instrument_df = pd.read_json(cache_file)
                return self.instrument_df
        return None

    async def get_instrument_details(self, index_name, reference_date=None):
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

            # Use current LTP date if possible to find future expiry
            # During backtest, we might be on an older date
            # Let's find the minimum expiry that is >= today or >= a provided reference date
            # For simplicity here, we'll find expiries >= the latest candle timestamp we might have
            # But wait, we just want the absolute nearest one available in the master for that name.

            # Find the closest expiry to the reference date
            if reference_date:
                ref_dt = pd.to_datetime(reference_date)
                future_expiries = [e for e in opt_df['expiry_dt'].unique() if e >= ref_dt]
                if future_expiries:
                    nearest_expiry = min(future_expiries)
                else:
                    nearest_expiry = opt_df['expiry_dt'].min() # Fallback
            else:
                nearest_expiry = opt_df['expiry_dt'].min()

            near_opt_df = opt_df[opt_df['expiry_dt'] == nearest_expiry]

            # --- 3. Identify ATM Strike ---
            unique_strikes = sorted(near_opt_df['strike_price'].unique())
            atm_strike = min(unique_strikes, key=lambda x: abs(x - ltp))

            # --- 3. Identify the 7 Strikes (3 OTM, 1 ATM, 3 ITM) ---
            atm_index = unique_strikes.index(atm_strike)
            start_idx = max(0, atm_index - 3)
            end_idx = min(len(unique_strikes), atm_index + 4)
            selected_strikes = unique_strikes[start_idx : end_idx]

            option_keys = []
            for strike in selected_strikes:
                ce_rows = near_opt_df[(near_opt_df['strike_price'] == strike) & (near_opt_df['instrument_type'] == 'CE')]
                pe_rows = near_opt_df[(near_opt_df['strike_price'] == strike) & (near_opt_df['instrument_type'] == 'PE')]

                if ce_rows.empty or pe_rows.empty: continue

                option_keys.append({
                    "strike": float(strike),
                    "ce": ce_rows.iloc[0]['instrument_key'],
                    "ce_symbol": ce_rows.iloc[0]['trading_symbol'],
                    "pe": pe_rows.iloc[0]['instrument_key'],
                    "pe_symbol": pe_rows.iloc[0]['trading_symbol']
                })

            # Primary ATM CE/PE for strategy
            atm_info = next(o for o in option_keys if o['strike'] == float(atm_strike))

            return {
                'index': index_key,
                'ce': atm_info['ce'],
                'pe': atm_info['pe'],
                'fut': current_fut_key,
                'ltp': ltp,
                'strike': float(atm_strike),
                'expiry': nearest_expiry.strftime('%Y-%m-%d'),
                'option_chain': option_keys # 7 strikes
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

            # Enable auto-reconnect
            self.streamer.auto_reconnect(True, interval=1, retry_count=10)

            self.streamer.connect()
            self.running = True
        except Exception as e:
            print(f"Failed to start streaming V3: {e}")

    def subscribe(self, instrument_keys, mode="full"):
        """
        Subscribes to more instrument keys.
        """
        if self.running and self.streamer:
            try:
                self.streamer.subscribe(instrument_keys, mode)
                print(f"Subscribed to: {instrument_keys}")
            except Exception as e:
                print(f"Failed to subscribe: {e}")

    def unsubscribe(self, instrument_keys):
        """
        Unsubscribes from instrument keys.
        """
        if self.running and self.streamer:
            try:
                self.streamer.unsubscribe(instrument_keys)
                print(f"Unsubscribed from: {instrument_keys}")
            except Exception as e:
                print(f"Failed to unsubscribe: {e}")

    def calculate_oi_delta(self, instrument_key, current_oi):
        # Use in-memory cache for performance
        last_oi = self.oi_cache.get(instrument_key)
        self.oi_cache[instrument_key] = current_oi

        if last_oi is not None:
            return current_oi - last_oi
        return 0
