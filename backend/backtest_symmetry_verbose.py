import asyncio
import pandas as pd
import numpy as np
import sys
import os
from datetime import datetime
import logging

# Add current directory to path
sys.path.append(os.getcwd())
sys.path.append(os.path.join(os.getcwd(), 'backend'))

from brain.SymmetryAnalyzer import SymmetryAnalyzer
from core.provider_registry import historical_data_registry, initialize_default_providers
from core.options_manager import options_manager

logging.basicConfig(level=logging.INFO)

async def run_backtest(underlying="NSE:NIFTY", interval='1', count=500):
    print(f"=== Symmetry Strategy Backtest: {underlying} ===", flush=True)
    initialize_default_providers()
    provider = historical_data_registry.get_provider("upstox") or historical_data_registry.get_primary()
    print(f"Using provider: {type(provider).__name__}")

    print(f"Fetching {count} index candles...", flush=True)
    idx_candles = await provider.get_hist_candles(underlying, interval, count)
    if not idx_candles:
        print("Error: Could not fetch index candles.")
        return

    print(f"Index data fetched. Last spot: {idx_candles[-1][4]}")
    last_spot = idx_candles[-1][4]
    strike_interval = 50 if "NIFTY" in underlying and "BANK" not in underlying else 100
    atm_strike = round(last_spot / strike_interval) * strike_interval

    print(f"Refreshing symbols for ATM {atm_strike}...")
    await options_manager._refresh_wss_symbols(underlying)

    ce_sym = options_manager.symbol_map_cache.get(underlying, {}).get(f"{float(atm_strike)}_call") or              options_manager.symbol_map_cache.get(underlying, {}).get(f"{int(atm_strike)}_call")
    pe_sym = options_manager.symbol_map_cache.get(underlying, {}).get(f"{float(atm_strike)}_put") or              options_manager.symbol_map_cache.get(underlying, {}).get(f"{int(atm_strike)}_put")

    if not ce_sym or not pe_sym:
        print(f"Error: ATM symbols for {atm_strike} not found in cache.")
        return

    print(f"Fetching candles for CE={ce_sym} and PE={pe_sym}...")
    ce_candles = await provider.get_hist_candles(ce_sym, interval, count)
    pe_candles = await provider.get_hist_candles(pe_sym, interval, count)

    if not ce_candles or not pe_candles:
        print("Error: Could not fetch option candles.")
        return

    print(f"Running Analyzer for {len(idx_candles)} index candles...")
    analyzer = SymmetryAnalyzer(underlying)
    signals = analyzer.analyze(idx_candles, ce_candles, pe_candles)

    if not signals:
        print("No signals generated in this period.")
        return

    print(f"\n--- Strategy Results ({len(signals)} signals) ---")
    for sig in signals:
        print(f"Signal: {sig['type']} at {datetime.fromtimestamp(sig['time'])} Price: {sig['price']}")

if __name__ == "__main__":
    asyncio.run(run_backtest())
