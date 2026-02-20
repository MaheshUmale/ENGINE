import os
import asyncio
from engine.data_provider import DataProvider
import datetime

async def check():
    token = os.getenv('UPSTOX_ACCESS_TOKEN')
    dp = DataProvider(token)

    # Get an ATM CE for yesterday
    yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
    # NIFTY was around 25571, so 25550 or 25600
    inst = 'NSE_FO|64854' # This was the CE from previous discovery

    print(f"Fetching historical for {inst} on {yesterday}...")
    df = dp.get_historical_data(inst, to_date=yesterday, from_date=yesterday)
    if df is not None and not df.empty:
        print(f"Fetched {len(df)} candles.")
        print(df[['timestamp', 'close', 'oi']].head())
        print(f"Non-zero OI count: {(df['oi'] > 0).sum()}")
    else:
        print("Failed.")

if __name__ == "__main__":
    asyncio.run(check())
