import asyncio
import pandas as pd
import numpy as np
import sys
import os
from datetime import datetime

# Add current directory to path
sys.path.append(os.getcwd())
sys.path.append(os.path.join(os.getcwd(), 'backend'))

from brain.SymmetryAnalyzer import SymmetryAnalyzer
from core.provider_registry import historical_data_registry, initialize_default_providers
from core.options_manager import options_manager

"""
Triple-Stream Symmetry & Panic Strategy Backtester.

This utility allows users to evaluate the performance of the Symmetry strategy
on historical market data stored in the local DuckDB. It simulates trade execution,
calculates PnL for each signal, and provides an aggregate performance report.

Usage:
    export PYTHONPATH=$PYTHONPATH:$(pwd)/backend
    python backend/backtest_symmetry.py --underlying NSE:NIFTY --count 1000

Parameters:
    --underlying: The index symbol to test (default: NSE:NIFTY)
    --interval: Data granularity (default: '1')
    --count: Number of historical candles to fetch (default: 500)
"""

async def run_backtest(underlying="NSE:NIFTY", interval='1', count=500):
    print(f"=== Symmetry Strategy Backtest: {underlying} ===")
    initialize_default_providers()
    provider = historical_data_registry.get_primary()

    # 1. Fetch Index Data
    print(f"Fetching {count} index candles...")
    idx_candles = await provider.get_hist_candles(underlying, interval, count)
    if not idx_candles:
        print("Error: Could not fetch index candles.")
        return

    # 2. Discover ATM symbols
    last_spot = idx_candles[-1][4]
    strike_interval = 50 if "NIFTY" in underlying and "BANK" not in underlying else 100
    atm_strike = round(last_spot / strike_interval) * strike_interval

    await options_manager._refresh_wss_symbols(underlying)
    ce_sym = options_manager.symbol_map_cache.get(underlying, {}).get(f"{float(atm_strike)}_call") or \
             options_manager.symbol_map_cache.get(underlying, {}).get(f"{int(atm_strike)}_call")
    pe_sym = options_manager.symbol_map_cache.get(underlying, {}).get(f"{float(atm_strike)}_put") or \
             options_manager.symbol_map_cache.get(underlying, {}).get(f"{int(atm_strike)}_put")

    if not ce_sym or not pe_sym:
        print(f"Error: ATM symbols for {atm_strike} not found in cache.")
        return

    # 3. Fetch Option Data
    print(f"Fetching candles for {ce_sym} and {pe_sym}...")
    ce_candles = await provider.get_hist_candles(ce_sym, interval, count)
    pe_candles = await provider.get_hist_candles(pe_sym, interval, count)

    if not ce_candles or not pe_candles:
        print("Error: Could not fetch option candles.")
        return

    # 4. Run Analyzer
    analyzer = SymmetryAnalyzer(underlying)
    signals = analyzer.analyze(idx_candles, ce_candles, pe_candles)

    if not signals:
        print("No signals generated in this period.")
        return

    print(f"\n--- Strategy Results ({len(signals)} signals) ---")

    # 5. Simulate Trades
    ce_df = pd.DataFrame(ce_candles, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
    pe_df = pd.DataFrame(pe_candles, columns=['ts', 'o', 'h', 'l', 'c', 'v'])

    results = []
    for sig in signals:
        side = sig['type']
        entry_price = sig['price']
        sl = sig['sl']
        tp = sig['tp']
        ts = sig['time']

        # Find subsequent price action
        df = ce_df if side == 'BUY_CE' else pe_df
        future_candles = df[df['ts'] > ts]

        outcome = "OPEN"
        exit_price = entry_price
        exit_time = None

        for _, row in future_candles.iterrows():
            if row['l'] <= sl:
                outcome = "SL"
                exit_price = sl
                exit_time = row['ts']
                break
            if row['h'] >= tp:
                outcome = "TP"
                exit_price = tp
                exit_time = row['ts']
                break

        if outcome == "OPEN" and not future_candles.empty:
            outcome = "EXPIRED"
            exit_price = future_candles.iloc[-1]['c']
            exit_time = future_candles.iloc[-1]['ts']

        pnl = (exit_price - entry_price) / entry_price * 100
        results.append({
            'time': datetime.fromtimestamp(ts).strftime('%H:%M:%S'),
            'type': side,
            'entry': entry_price,
            'exit': exit_price,
            'outcome': outcome,
            'pnl%': pnl
        })

    res_df = pd.DataFrame(results)
    print(res_df.to_string(index=False))

    win_rate = len(res_df[res_df['pnl%'] > 0]) / len(res_df) * 100
    total_pnl = res_df['pnl%'].sum()

    print(f"\nSummary:")
    print(f"Win Rate: {win_rate:.2f}%")
    print(f"Total PnL: {total_pnl:.2f}%")
    print(f"Avg PnL per trade: {res_df['pnl%'].mean():.2f}%")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run Symmetry Strategy Backtest")
    parser.add_argument("--underlying", type=str, default="NSE:NIFTY", help="Index symbol")
    parser.add_argument("--interval", type=str, default="1", help="Timeframe")
    parser.add_argument("--count", type=int, default=500, help="Number of candles")

    args = parser.parse_args()
    asyncio.run(run_backtest(underlying=args.underlying, interval=args.interval, count=args.count))
