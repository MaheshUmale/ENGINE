import asyncio
import logging
from external.tv_api import tv_api

logging.basicConfig(level=logging.INFO)

async def test_intervals():
    symbol = "NSE:NIFTY"
    intervals = ["1", "3", "5", "15", "30", "60", "120", "240", "D", "W"]

    for interval in intervals:
        print(f"Testing interval: {interval}")
        candles = await asyncio.to_thread(tv_api.get_hist_candles, symbol, interval, 10)
        if candles and len(candles) > 0:
            print(f"SUCCESS: Received {len(candles)} candles for interval {interval}")
            print(f"First candle: {candles[0]}")
        else:
            print(f"FAILED: No candles for interval {interval}")

if __name__ == "__main__":
    asyncio.run(test_intervals())
