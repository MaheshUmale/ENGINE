import httpx
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

class TrendlyneAPI:
    FALLBACK_IDS = {
        'NIFTY': 1887,
        'NIFTY 50': 1887,
        'BANKNIFTY': 1898,
        'BANK NIFTY': 1898,
        'FINNIFTY': 1900,
        'FIN NIFTY': 1900
    }

    def __init__(self):
        self.base_url = "https://smartoptions.trendlyne.com/phoenix/api"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        self.stock_id_cache = {}

    async def get_stock_id(self, symbol: str) -> Optional[int]:
        # Clean symbol for lookup
        clean_symbol = symbol.upper().replace("NSE:", "").strip()

        if clean_symbol in self.FALLBACK_IDS:
            return self.FALLBACK_IDS[clean_symbol]

        if symbol in self.stock_id_cache:
            return self.stock_id_cache[symbol]

        url = f"{self.base_url}/search-contract-stock/"
        params = {'query': symbol.lower()}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params, headers=self.headers, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    logger.debug(f"Trendlyne Search Response for {symbol}: {data}")
                    if data and 'body' in data and 'data' in data['body']:
                        stock_id = None
                        for item in data['body']['data']:
                            if item.get('stock_code', '').lower() == symbol.lower():
                                stock_id = item['stock_id']
                                break

                        # Fallback to first if no exact match (optional, but user requested exact)
                        if not stock_id and len(data['body']['data']) > 0:
                             # Just in case, let's log what we found
                             logger.warning(f"No exact stock_code match for {symbol}, found codes: {[i.get('stock_code') for i in data['body']['data']]}")

                        if stock_id:
                            self.stock_id_cache[symbol] = stock_id
                            return stock_id
        except Exception as e:
            logger.error(f"Error looking up stock ID for {symbol}: {e}")
        return None

    async def get_expiry_dates(self, stock_id: int) -> List[str]:
        url = f"{self.base_url}/search-contract-expiry-dates/"
        params = {'stock_pk': stock_id}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params, headers=self.headers, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    # Structure in reference repo: body.data.all_exp_list
                    if data and 'body' in data and 'data' in data['body']:
                        return data['body']['data'].get('all_exp_list', [])
        except Exception as e:
            logger.error(f"Error getting expiry dates for stock_id {stock_id}: {e}")
        return []

    async def get_oi_data(self, stock_id: int, expiry: str, max_time: str) -> Optional[Dict[str, Any]]:
        """
        Fetch OI data snapshot.
        max_time: HH:MM
        """
        url = f"{self.base_url}/live-oi-data/"
        params = {
            'stockId': stock_id,
            'expDateList': expiry,
            'minTime': "09:15",
            'maxTime': max_time,
            'format': 'json'
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params, headers=self.headers, timeout=15)
                if response.status_code == 200:
                    data = response.json()
                    logger.debug(f"Trendlyne OI Response for stock_id {stock_id}: {data}")
                    return data
        except Exception as e:
            logger.error(f"Error fetching OI data from Trendlyne: {e}")
        return None

trendlyne_api = TrendlyneAPI()
