
import logging
import asyncio
import upstox_client
from upstox_client.rest import ApiException
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from config import UPSTOX_ACCESS_TOKEN
from core.symbol_mapper import symbol_mapper

logger = logging.getLogger(__name__)

class UpstoxAPIClient:
    def __init__(self, access_token: str = UPSTOX_ACCESS_TOKEN):
        self.access_token = access_token
        self.configuration = upstox_client.Configuration()
        self.configuration.access_token = access_token
        self.api_client = upstox_client.ApiClient(self.configuration)

    async def get_hist_candles(self, symbol: str, interval: str, count: int) -> List[List]:
        """Fetch historical candles from Upstox with client-side aggregation for unsupported timeframes."""
        supported_intervals = ["1", "30", "1D", "1W", "1M", "D", "W"]

        # If the interval is not natively supported by Upstox, we'll fetch 1-min and aggregate
        needs_aggregation = interval not in supported_intervals and interval.isdigit()
        fetch_interval = "1" if needs_aggregation else interval

        logger.info(f"Upstox fetching historical candles for {symbol} (interval={interval}, count={count})")
        try:
            instrument_key = symbol_mapper.to_upstox_key(symbol)
            history_api = upstox_client.HistoryApi(self.api_client)
            u_interval = "1minute" if interval == "1" else f"{interval}minute" if interval.isdigit() else "day"
            now = datetime.now().strftime("%Y-%m-%d")

            def fetch():
                try:
                    # Map to Upstox specific interval strings
                    upstox_interval = "1minute" if fetch_interval == "1" else \
                                      "30minute" if fetch_interval == "30" else \
                                      "day" if fetch_interval in ["1D", "D"] else \
                                      "week" if fetch_interval in ["1W", "W"] else \
                                      "month" if fetch_interval in ["1M", "M"] else "1minute"

                    # Try intraday first if it's a small interval
                    if upstox_interval in ["1minute", "30minute"]:
                         res = history_api.get_intra_day_candle_data(instrument_key, upstox_interval, "2.0")
                         if res and res.status == "success" and res.data and res.data.candles:
                             return res

                    # Fallback to historical for larger window or if intraday empty
                    days_back = 7 if upstox_interval == "1minute" else 30 if upstox_interval == "30minute" else 365
                    from_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
                    res = history_api.get_historical_candle_data1(instrument_key, upstox_interval, now, from_date, "2.0")
                    return res
                except ApiException as e:
                    logger.error(f"Upstox API Error fetching candles for {symbol}: {e}")
                    return None

            response = await asyncio.to_thread(fetch)
            if response and response.status == "success":
                raw_candles = response.data.candles
                formatted = []
                for c in raw_candles:
                    try:
                        dt = datetime.fromisoformat(c[0].replace('+05:30', ''))
                        ts = int(dt.timestamp())
                        formatted.append([ts, float(c[1]), float(c[2]), float(c[3]), float(c[4]), int(c[5])])
                    except Exception as e:
                        logger.warning(f"Error parsing Upstox candle: {e}")
                formatted.sort(key=lambda x: x[0])

                # Client-side aggregation if needed (e.g. 1m -> 5m)
                if needs_aggregation:
                    try:
                        step = int(interval)
                        agg = []
                        for i in range(0, len(formatted), step):
                            chunk = formatted[i:i+step]
                            if not chunk: continue
                            # [ts, o, h, l, c, v]
                            ts = chunk[0][0]
                            o = chunk[0][1]
                            h = max(c[2] for c in chunk)
                            l = min(c[3] for c in chunk)
                            c = chunk[-1][4]
                            v = sum(c[5] for c in chunk)
                            agg.append([ts, o, h, l, c, v])
                        formatted = agg
                        logger.info(f"Aggregated {len(agg)} candles for interval {interval}")
                    except Exception as e:
                        logger.error(f"Aggregation failed: {e}")

                # Hybrid Volume for Indices: Fetch from TradingView
                is_index = any(idx in symbol.upper() for idx in ["NIFTY", "BANKNIFTY", "FINNIFTY"])
                if is_index:
                    try:
                        from .tv_api import tv_api
                        tv_candles = await asyncio.to_thread(tv_api.get_hist_candles, symbol, interval, count + 50)
                        if tv_candles:
                            # Map TV candles by timestamp
                            tv_map = {c[0]: c[5] for c in tv_candles} # ts -> volume
                            for c in formatted:
                                if c[0] in tv_map:
                                    c[5] = int(tv_map[c[0]])
                            logger.info(f"Merged TradingView volume for index {symbol}")
                    except Exception as e:
                        logger.error(f"Failed to merge TradingView volume: {e}")

                return formatted[-count:]
            return []
        except Exception as e:
            logger.error(f"Error in Upstox get_hist_candles: {e}")
            return []

    async def get_option_chain(self, underlying: str) -> Dict[str, Any]:
        """Fetch option chain for an underlying."""
        try:
            instrument_key = symbol_mapper.to_upstox_key(underlying)
            logger.info(f"Upstox fetching option chain for {underlying} ({instrument_key})")
            options_api = upstox_client.OptionsApi(self.api_client)
            expiries = await self.get_expiry_dates(underlying)
            if not expiries:
                logger.warning(f"No expiries found for {underlying}")
                return {}
            expiry = expiries[0]
            logger.info(f"Using expiry {expiry} for {underlying}")

            # Handle if expiry is already a date/datetime object
            expiry_str = expiry.strftime("%Y-%m-%d") if hasattr(expiry, 'strftime') else str(expiry)
            expiry_ts = int(datetime.strptime(expiry_str, "%Y-%m-%d").timestamp())

            def fetch():
                try:
                    return options_api.get_put_call_option_chain(instrument_key, expiry_str)
                except ApiException as e:
                    logger.error(f"Upstox API Error fetching option chain for {underlying}: {e}")
                    return None

            response = await asyncio.to_thread(fetch)
            if response and response.status == "success":
                logger.info(f"Successfully fetched Upstox option chain for {underlying} with {len(response.data)} strikes")
                standard_data = {"timestamp": datetime.now().isoformat(), "underlying_price": 0, "symbols": []}

                # Get base symbol like NIFTY from NSE:NIFTY
                base_symbol = underlying.split(':')[-1]
                if base_symbol == "CNXFINANCE": base_symbol = "FINNIFTY"

                expiry_dt = datetime.fromtimestamp(expiry_ts)
                yy = expiry_dt.strftime("%y")
                mm = expiry_dt.strftime("%m")
                dd = expiry_dt.strftime("%d")

                for item in response.data:
                    strike = float(item.strike_price)
                    strike_str = str(int(strike)) if strike == int(strike) else str(strike)

                    if item.call_options:
                        co = item.call_options
                        # Construct internal symbol: NSE:NIFTY260224C25700
                        internal_symbol = f"NSE:{base_symbol}{yy}{mm}{dd}C{strike_str}"
                        symbol_mapper.register_mapping(internal_symbol, co.instrument_key)

                        standard_data["symbols"].append({"f": [co.instrument_key, str(strike), "call", 0.0, float(co.market_data.ltp if co.market_data else 0), int(co.market_data.volume if co.market_data else 0), int(co.market_data.oi if co.market_data else 0), 0, expiry_ts, 0.0, 0.0, 0.0, 0.0, 0.0]})

                    if item.put_options:
                        po = item.put_options
                        internal_symbol = f"NSE:{base_symbol}{yy}{mm}{dd}P{strike_str}"
                        symbol_mapper.register_mapping(internal_symbol, po.instrument_key)

                        standard_data["symbols"].append({"f": [po.instrument_key, str(strike), "put", 0.0, float(po.market_data.ltp if po.market_data else 0), int(po.market_data.volume if po.market_data else 0), int(po.market_data.oi if po.market_data else 0), 0, expiry_ts, 0.0, 0.0, 0.0, 0.0, 0.0]})
                return standard_data
            return {}
        except Exception as e:
            logger.error(f"Error in Upstox get_option_chain: {e}")
            return {}

    async def get_oi_data(self, underlying: str, expiry: str) -> Dict[str, Any]:
        """Fetch OI data in the format expected by OptionsManager."""
        try:
            instrument_key = symbol_mapper.to_upstox_key(underlying)
            options_api = upstox_client.OptionsApi(self.api_client)

            def fetch():
                try:
                    return options_api.get_put_call_option_chain(instrument_key, expiry)
                except ApiException as e:
                    logger.error(f"Upstox API Error fetching OI data for {underlying}: {e}")
                    return None

            response = await asyncio.to_thread(fetch)
            if response and response.status == "success":
                oi_data = {}
                for item in response.data:
                    strike = str(float(item.strike_price))
                    oi_data[strike] = {
                        'callOi': int(item.call_options.market_data.oi) if item.call_options and item.call_options.market_data else 0,
                        'callOiChange': 0, # Upstox V3 doesn't provide OI change directly in this endpoint
                        'callVol': int(item.call_options.market_data.volume) if item.call_options and item.call_options.market_data else 0,
                        'callLtp': float(item.call_options.market_data.ltp) if item.call_options and item.call_options.market_data else 0,
                        'putOi': int(item.put_options.market_data.oi) if item.put_options and item.put_options.market_data else 0,
                        'putOiChange': 0,
                        'putVol': int(item.put_options.market_data.volume) if item.put_options and item.put_options.market_data else 0,
                        'putLtp': float(item.put_options.market_data.ltp) if item.put_options and item.put_options.market_data else 0,
                    }
                return {'body': {'oiData': oi_data}, 'head': {'status': '0'}}
            return {}
        except Exception as e:
            logger.error(f"Error in Upstox get_oi_data: {e}")
            return {}

    async def get_expiry_dates(self, underlying: str) -> List[str]:
        """Fetch expiry dates for an underlying."""
        try:
            instrument_key = symbol_mapper.to_upstox_key(underlying)
            options_api = upstox_client.OptionsApi(self.api_client)
            def fetch():
                try:
                    return options_api.get_option_contracts(instrument_key)
                except ApiException as e:
                    logger.error(f"Upstox API Error fetching contracts for {underlying}: {e}")
                    return None
            response = await asyncio.to_thread(fetch)
            if response and response.status == "success":
                # Convert date objects to string if necessary
                dates = []
                for c in response.data:
                    if c.expiry:
                        d = c.expiry.strftime("%Y-%m-%d") if hasattr(c.expiry, 'strftime') else str(c.expiry)
                        dates.append(d)
                return sorted(list(set(dates)))
            return []
        except Exception as e:
            logger.error(f"Error in Upstox get_expiry_dates: {e}")
            return []

upstox_api_client = UpstoxAPIClient()
