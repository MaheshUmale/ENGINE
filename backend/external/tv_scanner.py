import httpx
import logging

logger = logging.getLogger(__name__)

async def search_options(underlying: str):
    url = "https://scanner.tradingview.com/options/scan2?label-product=options-symbol-search"

    # Standardize underlying for TradingView (usually NSE:NIFTY)
    # Default to NSE for Indian markets if no exchange specified
    if ":" not in underlying:
        tv_underlying = f"NSE:{underlying}"
    else:
        tv_underlying = underlying

    root = tv_underlying.split(":")[-1]

    payload = {
        "columns": ["option-type", "strike"],
        "filter": [
            {"left": "type", "operation": "equal", "right": "option"},
            {"left": "root", "operation": "equal", "right": root}
        ],
        "ignore_unknown_fields": False,
        "sort": {"sortBy": "name", "sortOrder": "asc"},
        "index_filters": [
            {"name": "underlying_symbol", "values": [tv_underlying]}
        ]
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/json",
        "Referer": "https://www.tradingview.com/",
        "Origin": "https://www.tradingview.com"
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers, timeout=15.0)
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Options scanner failed: {response.status_code} {response.text}")
                return None
    except Exception as e:
        logger.error(f"Error calling options scanner: {e}")
        return None
