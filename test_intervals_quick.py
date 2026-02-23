import asyncio
import logging
import sys
import os

# Add backend to sys.path
sys.path.append(os.path.join(os.getcwd(), 'backend'))

from external.tv_api import tv_api

logging.basicConfig(level=logging.INFO)

async def test_intervals():
    symbol = "NSE:NIFTY"
    intervals = ["3", "120", "D"]

    for interval in intervals:
        print(f"Testing interval: {interval}")
        try:
            # Set a timeout for the call
            candles = await asyncio.wait_for(
                asyncio.to_thread(tv_api.get_hist_candles, symbol, interval, 5),
                timeout=30
            )
            if candles and len(candles) > 0:
                print(f"SUCCESS: Received {len(candles)} candles for interval {interval}")
            else:
                print(f"FAILED: No candles for interval {interval}")
        except Exception as e:
            print(f"ERROR for interval {interval}: {e}")

if __name__ == "__main__":
    asyncio.run(test_intervals())
