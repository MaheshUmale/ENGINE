import asyncio
from symmetry_engine.backtester import Backtester
import datetime

async def test():
    bt = Backtester("NIFTY")
    # Just run for 1 day to see if it crashes
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    try:
        await bt.run_backtest(today, today)
        print("Backtest ran without NameError")
    except NameError as e:
        print(f"FAILED: {e}")
    except Exception as e:
        print(f"Ran into other error (expected if no data): {e}")

if __name__ == "__main__":
    asyncio.run(test())
