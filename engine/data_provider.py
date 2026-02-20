import upstox_client
from upstox_client.rest import ApiException
import pandas as pd
import datetime
import json
import asyncio
import ssl
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

    async def get_instrument_details(self, index_name):
        """
        Dynamically discovers ATM options and nearest expiry for the given index using Option Chain API.
        """
        index_key = INDICES[index_name]['index_key']
        quotes = self.get_market_quote([index_key])
        if not quotes:
            return None

        ltp = quotes[index_key].last_price

        try:
            # Get nearest expiry dates
            contract_res = self.options_api.get_option_contracts(index_key)
            if contract_res.status != 'success' or not contract_res.data:
                return None

            # Sort expiries
            expiries = sorted(list(set([c.expiry for c in contract_res.data])))
            nearest_expiry = expiries[0]

            # Get Option Chain for nearest expiry
            chain_res = self.options_api.get_put_call_option_chain(index_key, nearest_expiry)
            if chain_res.status != 'success' or not chain_res.data:
                return None

            # Find ATM strikes
            # Sort by absolute difference from LTP
            atm_contracts = sorted(chain_res.data, key=lambda x: abs(x.strike_price - ltp))
            atm = atm_contracts[0]

            ce_key = atm.call_options.instrument_key
            pe_key = atm.put_options.instrument_key

            # For Future, we still need to guess or use another discovery
            # But we have CE/PE!
            # Let's use the year and month from the expiry for the Future
            if isinstance(nearest_expiry, str):
                expiry_date = datetime.datetime.strptime(nearest_expiry, '%Y-%m-%d')
            else:
                expiry_date = nearest_expiry
            fut_key = f"NSE_FO|{index_name}{expiry_date.strftime('%y%b').upper()}FUT"

            return {
                'index': index_key,
                'ce': ce_key,
                'pe': pe_key,
                'fut': fut_key,
                'ltp': ltp,
                'strike': atm.strike_price,
                'expiry': nearest_expiry
            }
        except Exception as e:
            print(f"Discovery Error: {e}")
            return None

    def discover_nearest_expiry(self, index_name):
        # Placeholder for expiry discovery. In practice, this would parse the instrument master CSV.
        # For now, we'll return a date that represents the next Thursday (common for NIFTY/BANKNIFTY)
        today = datetime.date.today()
        days_ahead = 3 - today.weekday() # Thursday is 3
        if days_ahead <= 0: days_ahead += 7
        return today + datetime.timedelta(days_ahead)

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
