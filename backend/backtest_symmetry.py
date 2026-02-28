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
with Comprehensive Squeeze Mechanics on historical market data stored in the local DuckDB. 
It simulates trade execution using dynamic exits based on opposite option bounces.

Usage:
    export PYTHONPATH=$PYTHONPATH:$(pwd)/backend
    python backend/backtest_symmetry.py --underlying NSE:NIFTY --count 1000
"""

async def run_backtest(underlying="NSE:NIFTY", interval='1', count=500):
    print(f"=== Symmetry Strategy Backtest: {underlying} ===", flush=True)
    initialize_default_providers()
    # Force Upstox for backtest to avoid TV session issues in headless environment
    provider = historical_data_registry.get_provider("upstox") or historical_data_registry.get_primary()

    # 1. Fetch Index Data
    print(f"Fetching {count} index candles...", flush=True)
    idx_candles = await provider.get_hist_candles(underlying, interval, count)
    if not idx_candles:
        print("Error: Could not fetch index candles.")
        return

    # 2. Discover ATM symbols
    print(f"Index data fetched. Last spot: {idx_candles[-1][4]}")
    last_spot = idx_candles[-1][4]
    strike_interval = 50 if "NIFTY" in underlying and "BANK" not in underlying else 100
    atm_strike = round(last_spot / strike_interval) * strike_interval

    print("Refreshing symbols...")
    await options_manager._refresh_wss_symbols(underlying)
    print("Symbols refreshed.")
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
    # Passing dummy options chain for testing 'Void' capability
    dummy_chain = []
    signals = analyzer.analyze(idx_candles, ce_candles, pe_candles, option_chain=dummy_chain)

    if not signals:
        print("No signals generated in this period.")
        return

    print(f"\n--- Strategy Results ({len(signals)} signals) ---")

    # 5. Simulate Trades with Dynamic Exit Logic
    ce_df = pd.DataFrame(ce_candles, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
    pe_df = pd.DataFrame(pe_candles, columns=['ts', 'o', 'h', 'l', 'c', 'v'])

    results = []
    for sig in signals:
        side = sig['type']
        entry_price = sig['price']
        initial_sl = sig['sl']
        ts = sig['time']

        # The active option is what we bought. The opposite option is what we monitor for exit.
        if side == 'BUY_CE':
            active_df = ce_df[ce_df['ts'] > ts]
            opp_df = pe_df[pe_df['ts'] > ts]
        else:
            active_df = pe_df[pe_df['ts'] > ts]
            opp_df = ce_df[ce_df['ts'] > ts]

        outcome = "OPEN"
        exit_price = entry_price
        exit_time = None

        # Iterate tick by tick in the future
        for i in range(min(len(active_df), len(opp_df))):
            act_row = active_df.iloc[i]
            opp_row = opp_df.iloc[i]
            
            # SL Condition: "Stop Loss: Exit immediately if Symmetry Fails. "
            if act_row['l'] <= initial_sl:
                outcome = "SL"
                exit_price = initial_sl
                exit_time = act_row['ts']
                break
                
            # Dynamic TP Condition: Exit when Opposite Option starts to bounce.
            # "Target: Exit when the Opposite Option starts to bounce... indicates Squeeze has finished first impulse."
            # A bounce is defined as the opposite option making a green candle (C > O) that closes higher than its previous high
            if i > 0:
                opp_prev_row = opp_df.iloc[i-1]
                bouncing = (opp_row['c'] > opp_row['o']) and (opp_row['c'] > opp_prev_row['h'])
                if bouncing:
                    outcome = "DYNAMIC_TP"
                    exit_price = act_row['c'] # Exit active side at market close of this minute
                    exit_time = act_row['ts']
                    break

        if outcome == "OPEN" and not active_df.empty:
            outcome = "EXPIRED"
            exit_price = active_df.iloc[-1]['c']
            exit_time = active_df.iloc[-1]['ts']

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
