import requests
import random
import time
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Module-level session to reuse connections
_SESSION = requests.Session()

def requests_get_with_retry(url, headers=None, cookies=None, max_retries=4, backoff_factor=1.0, timeout=10):
    """GET with retries, exponential backoff and jitter."""
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = _SESSION.get(url, headers=headers, cookies=cookies, timeout=timeout)
            if resp.status_code == 200:
                return resp
            else:
                resp.raise_for_status()
        except Exception as exc:
            last_exc = exc
            sleep_seconds = backoff_factor * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
            logger.warning(f"Request to {url} failed (attempt {attempt}/{max_retries}): {exc}. Retrying in {sleep_seconds:.1f}s")
            time.sleep(sleep_seconds)
            continue
    raise last_exc

def get_nse_cookies():
    baseurl = "https://www.nseindia.com/"
    headers = {
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.149 Safari/537.36',
        'accept-language': 'en,gu;q=0.9,hi;q=0.8',
    }
    try:
        resp = requests_get_with_retry(baseurl, headers=headers, max_retries=3, backoff_factor=0.8, timeout=8)
        return dict(resp.cookies)
    except Exception as e:
        logger.warning(f"Failed to get NSE cookies: {e}")
        return {}

def fetch_nse_oi_data(symbol="NIFTY"):
    """Fetches OI data directly from NSE."""
    try:
        cookies = get_nse_cookies()
        if symbol in ["NIFTY", "BANKNIFTY", "FINNIFTY"]:
            url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
        else:
            url = f"https://www.nseindia.com/api/option-chain-equities?symbol={symbol}"

        headers = {
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.149 Safari/537.36',
            'accept-language': 'en,gu;q=0.9,hi;q=0.8',
            'referer': 'https://www.nseindia.com/market-data/option-chain',
        }

        resp = requests_get_with_retry(url, headers=headers, cookies=cookies, max_retries=4, backoff_factor=0.8, timeout=10)
        return resp.json()
    except Exception as e:
        logger.error(f"Error fetching NSE OI data for {symbol}: {e}")
        return None
