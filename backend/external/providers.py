import asyncio
import logging
from typing import Dict, Any, List, Optional, Callable
from core.interfaces import ILiveStreamProvider, IOptionsDataProvider, IHistoricalDataProvider
from external.tv_live_wss import TradingViewWSS
from external.tv_options_scanner import fetch_option_chain
from external.trendlyne_api import trendlyne_api
from external.nse_api import fetch_nse_oi_data
from external.tv_api import tv_api
from external.upstox_api import upstox_api_client
from external.upstox_wss import UpstoxWSS

logger = logging.getLogger(__name__)

class TradingViewLiveStreamProvider(ILiveStreamProvider):
    """TradingView WebSocket Implementation."""
    def __init__(self, callback: Callable = None):
        self.callbacks = []
        if callback: self.callbacks.append(callback)
        self.wss = TradingViewWSS(self._distribute_callback)

    def _distribute_callback(self, data):
        for cb in self.callbacks:
            try:
                cb(data)
            except Exception as e:
                logger.error(f"Error in TradingViewLiveStreamProvider callback: {e}")

    def subscribe(self, symbols: List[str], interval: str = "1"):
        self.wss.subscribe(symbols, interval)

    def unsubscribe(self, symbol: str, interval: str = "1"):
        self.wss.unsubscribe(symbol, interval)

    def add_symbols(self, symbols: List[str]):
        """Alias for subscribe to match OptionsWSS interface."""
        self.subscribe(symbols)

    def set_callback(self, callback: Callable):
        if callback not in self.callbacks:
            self.callbacks.append(callback)

    def start(self):
        self.wss.start()

    def stop(self):
        self.wss.stop()

    def is_connected(self) -> bool:
        return self.wss.ws and self.wss.ws.sock and self.wss.ws.sock.connected


class TrendlyneOptionsProvider(IOptionsDataProvider):
    """Trendlyne API Implementation for Options data."""
    def __init__(self):
        self.symbol_map = {
            "NSE:NIFTY": "NIFTY 50",
            "NSE:BANKNIFTY": "BANKNIFTY",
            "NSE:FINNIFTY": "FINNIFTY"
        }

    async def get_option_chain(self, underlying: str) -> Dict[str, Any]:
        # Trendlyne uses OI data for chain, but let's use TV for the full chain structure if needed
        # Or implement a hybrid if Trendlyne provides it. For now, focus on OI.
        return await fetch_option_chain(underlying)

    async def get_expiry_dates(self, underlying: str) -> List[str]:
        tl_symbol = self.symbol_map.get(underlying, underlying.split(':')[-1])
        stock_id = await trendlyne_api.get_stock_id(tl_symbol)
        if stock_id:
            return await trendlyne_api.get_expiry_dates(stock_id)
        return []

    async def get_oi_data(self, underlying: str, expiry: str, time_str: str) -> Dict[str, Any]:
        tl_symbol = self.symbol_map.get(underlying, underlying.split(':')[-1])
        stock_id = await trendlyne_api.get_stock_id(tl_symbol)
        if stock_id:
            return await trendlyne_api.get_oi_data(stock_id, expiry, time_str)
        return {}


class NSEOptionsProvider(IOptionsDataProvider):
    """NSE India Direct Implementation for Options data."""
    async def get_option_chain(self, underlying: str) -> Dict[str, Any]:
        symbol = underlying.split(':')[-1]
        if symbol == "CNXFINANCE": symbol = "FINNIFTY"
        data = await asyncio.to_thread(fetch_nse_oi_data, symbol)
        # Transform NSE format to a unified format if necessary
        return data

    async def get_expiry_dates(self, underlying: str) -> List[str]:
        data = await self.get_option_chain(underlying)
        if data and 'records' in data:
            raw_dates = data['records'].get('expiryDates', [])
            # Standardize to YYYY-MM-DD
            standard_dates = []
            for d in raw_dates:
                try:
                    # Parse DD-MMM-YYYY
                    dt = datetime.strptime(d, "%d-%b-%Y")
                    standard_dates.append(dt.strftime("%Y-%m-%d"))
                except:
                    standard_dates.append(d)
            return standard_dates
        return []

    async def get_oi_data(self, underlying: str, expiry: str, time_str: str) -> Dict[str, Any]:
        data = await self.get_option_chain(underlying)
        # NSE Direct doesn't usually support historical time snapshots via public API
        # but we can return the latest filtered by expiry.
        if not data: return {}

        oi_data = {}
        for item in data.get('filtered', {}).get('data', []):
            raw_exp = item.get('expiryDate')
            std_exp = raw_exp
            try:
                std_exp = datetime.strptime(raw_exp, "%d-%b-%Y").strftime("%Y-%m-%d")
            except:
                pass

            if std_exp == expiry:
                strike = str(item['strikePrice'])
                oi_data[strike] = {
                    'callOi': item.get('CE', {}).get('openInterest', 0),
                    'callOiChange': item.get('CE', {}).get('changeinOpenInterest', 0),
                    'callVol': item.get('CE', {}).get('totalTradedVolume', 0),
                    'callLtp': item.get('CE', {}).get('lastPrice', 0),
                    'putOi': item.get('PE', {}).get('openInterest', 0),
                    'putOiChange': item.get('PE', {}).get('changeinOpenInterest', 0),
                    'putVol': item.get('PE', {}).get('totalTradedVolume', 0),
                    'putLtp': item.get('PE', {}).get('lastPrice', 0),
                }
        return {'body': {'oiData': oi_data}, 'head': {'status': '0'}}


class TradingViewHistoricalProvider(IHistoricalDataProvider):
    """TradingView Historical Data Implementation."""
    async def get_hist_candles(self, symbol: str, interval: str, count: int) -> List[List]:
        return await asyncio.to_thread(tv_api.get_hist_candles, symbol, interval, count)


class UpstoxLiveStreamProvider(ILiveStreamProvider):
    """Upstox WebSocket Implementation."""
    def __init__(self, callback: Callable = None):
        self.callbacks = []
        if callback: self.callbacks.append(callback)
        self.wss = UpstoxWSS(self._distribute_callback)

    def _distribute_callback(self, data):
        for cb in self.callbacks:
            try:
                cb(data)
            except Exception as e:
                logger.error(f"Error in UpstoxLiveStreamProvider callback: {e}")

    def subscribe(self, symbols: List[str], interval: str = "1"):
        self.wss.subscribe(symbols, interval)

    def unsubscribe(self, symbol: str, interval: str = "1"):
        self.wss.unsubscribe(symbol, interval)

    def add_symbols(self, symbols: List[str]):
        """Alias for subscribe to match OptionsWSS interface."""
        self.subscribe(symbols)

    def set_callback(self, callback: Callable):
        if callback not in self.callbacks:
            self.callbacks.append(callback)

    def start(self):
        self.wss.start()

    def stop(self):
        self.wss.stop()

    def is_connected(self) -> bool:
        return self.wss.is_running


class UpstoxOptionsProvider(IOptionsDataProvider):
    """Upstox API Implementation for Options data."""
    async def get_option_chain(self, underlying: str) -> Dict[str, Any]:
        return await upstox_api_client.get_option_chain(underlying)

    async def get_expiry_dates(self, underlying: str) -> List[str]:
        return await upstox_api_client.get_expiry_dates(underlying)

    async def get_oi_data(self, underlying: str, expiry: str, time_str: str) -> Dict[str, Any]:
        return await upstox_api_client.get_oi_data(underlying, expiry)


class UpstoxHistoricalProvider(IHistoricalDataProvider):
    """Upstox Historical Data Implementation."""
    async def get_hist_candles(self, symbol: str, interval: str, count: int) -> List[List]:
        return await upstox_api_client.get_hist_candles(symbol, interval, count)
