import asyncio
import sys
import os
sys.path.append(os.path.join(os.getcwd(), 'backend'))

from external.upstox_api import upstox_api_client

async def test():
    print("Testing Upstox API...")
    try:
        expiries = await upstox_api_client.get_expiry_dates("NSE:NIFTY")
        print(f"Expiries: {expiries}")
        if expiries:
            chain = await upstox_api_client.get_option_chain("NSE:NIFTY")
            print(f"Chain strikes: {len(chain.get('symbols', []))}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test())
