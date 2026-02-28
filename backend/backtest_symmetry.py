import asyncio
import pandas as pd
import numpy as np
import sys
import os
from datetime import datetime
import plotly.graph_objects as go
from plotly.subplots import make_subplots

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
It also generates an interactive HTML chart (backtest_chart.html) for visual inspection.

Usage:
    export PYTHONPATH=$PYTHONPATH:$(pwd)/backend
    python backend/backtest_symmetry.py --underlying NSE:NIFTY --count 2625
"""

async def run_backtest(underlying="NSE:NIFTY", interval='1', count=500, return_json=False):
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

    idx_df = pd.DataFrame(idx_candles, columns=['ts', 'o', 'h', 'l', 'c', 'v'])

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
        atr_val = sig.get('atr', 20.0) # Assume 20pt ATR if missing
        # The active option is what we bought. The opposite option is what we monitor for exit.
        if side == 'BUY_CE':
            active_df = ce_df[ce_df['ts'] > ts]
            opp_df = pe_df[pe_df['ts'] > ts]
        else:
            active_df = pe_df[pe_df['ts'] > ts]
            opp_df = ce_df[ce_df['ts'] > ts]
            
        future_idx_df = idx_df[idx_df['ts'] > ts]

        outcome = "OPEN"
        exit_price = entry_price
        exit_time = None
        
        entry_idx_candle = idx_df[idx_df['ts'] == ts]
        entry_opt_candle = ce_df[ce_df['ts'] == ts] if side == 'BUY_CE' else pe_df[pe_df['ts'] == ts]
        
        entry_idx_high = float(entry_idx_candle['h'].iloc[0]) if not entry_idx_candle.empty else 0
        entry_opt_high = float(entry_opt_candle['h'].iloc[0]) if not entry_opt_candle.empty else entry_price

        asym_trap_count = 0

        # Iterate tick by tick in the future
        for i in range(min(len(active_df), len(opp_df), len(future_idx_df))):
            act_row = active_df.iloc[i]
            opp_row = opp_df.iloc[i]
            idx_row = future_idx_df.iloc[i]
            
            # SL Condition: "Stop Loss: Exit immediately if Symmetry Fails. "
            if act_row['l'] <= initial_sl:
                outcome = "SL"
                exit_price = initial_sl
                exit_time = act_row['ts']
                break
                
            # Time-Based SL: Removed rigid 3-min rule. Added 15-min stagnation exit (PnL < -2%).
            current_pnl_pct = (act_row['c'] - entry_price) / entry_price * 100
            if i >= 15 and current_pnl_pct < -2.0:
                outcome = "TIME_SL"
                exit_price = act_row['c']
                exit_time = act_row['ts']
                break
                
            # Asymmetry Absorption Exit: Relaxed to 5 minutes of trap
            if idx_row['h'] > entry_idx_high and act_row['h'] < entry_opt_high:
                asym_trap_count += 1
            else:
                asym_trap_count = max(0, asym_trap_count - 1) # decay the count
                
            if asym_trap_count >= 5:
                outcome = "ASYMMETRY_EXIT"
                exit_price = act_row['c']
                exit_time = act_row['ts']
                break
                
            # Dynamic TP Condition: Exit when Opposite Option starts to bounce.
            if i > 2: # Require at least 3 minutes
                opp_prev_row = opp_df.iloc[i-1]
                opp_prev_2_row = opp_df.iloc[i-2]
                
                # Stronger bounce required: 2 consecutive higher highs and higher closes
                bouncing = (opp_row['c'] > opp_row['o']) and \
                           (opp_row['c'] > opp_prev_row['h']) and \
                           (opp_prev_row['c'] > opp_prev_2_row['h'])
                           
                if bouncing and current_pnl_pct > 2.0: # Ensure we are in profit or flat before taking dynamic TP
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
            'ts': ts,
            'exit_ts': exit_time if exit_time else ts,
            'type': side,
            'entry': entry_price,
            'exit': exit_price,
            'outcome': outcome,
            'pnl%': pnl
        })

    res_df = pd.DataFrame(results)
    print(res_df.drop(columns=['ts', 'exit_ts']).to_string(index=False))

    win_rate = len(res_df[res_df['pnl%'] > 0]) / len(res_df) * 100 if not res_df.empty else 0
    total_pnl = res_df['pnl%'].sum() if not res_df.empty else 0

    print(f"\nSummary:")
    print(f"Win Rate: {win_rate:.2f}%")
    print(f"Total PnL: {total_pnl:.2f}%")
    print(f"Avg PnL per trade: {res_df['pnl%'].mean() if not res_df.empty else 0:.2f}%")

    # --- 6. Return JSON for API if requested ---
    if return_json:
        # Pre-format candles for TV Lightweight Charts: [time, open, high, low, close]
        candles_fmt = []
        for c in idx_candles:
            # TV expects seconds
            candles_fmt.append([int(c[0]), c[1], c[2], c[3], c[4]])
            
        # Format trades to match old backend GUI expectations
        formatted_results = []
        for r in results:
            formatted_results.append({
                "timestamp": int(r['ts']),
                "exit_timestamp": int(r['exit_ts']),
                "index": underlying,
                "instrument": "CE" if r['type'] == 'BUY_CE' else "PE",
                "price": r['entry'],
                "exit_price": r['exit'],
                "pnl": r['pnl%']
            })
            
        return {
            "total_pnl": total_pnl,
            "win_rate": win_rate,
            "results": formatted_results,
            "candles": candles_fmt
        }

    # --- 7. Generate Visualization ---
    print("\nGenerating Interactive Plotly Chart (backtest_chart.html)...")
    idx_df = pd.DataFrame(idx_candles, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
    
    # Convert TS to IST (UTC + 5:30)
    idx_df['dt'] = pd.to_datetime(idx_df['ts'], unit='s', utc=True).dt.tz_convert('Asia/Kolkata')
    ce_df['dt'] = pd.to_datetime(ce_df['ts'], unit='s', utc=True).dt.tz_convert('Asia/Kolkata')
    pe_df['dt'] = pd.to_datetime(pe_df['ts'], unit='s', utc=True).dt.tz_convert('Asia/Kolkata')

    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, 
                        subplot_titles=("Index Price", f"Call Option ({ce_sym})", f"Put Option ({pe_sym})"),
                        vertical_spacing=0.08)

    # Base line charts -> Changed to Candlesticks
    fig.add_trace(go.Candlestick(x=idx_df['dt'], open=idx_df['o'], high=idx_df['h'], low=idx_df['l'], close=idx_df['c'], name='Index Close'), row=1, col=1)
    fig.add_trace(go.Candlestick(x=ce_df['dt'], open=ce_df['o'], high=ce_df['h'], low=ce_df['l'], close=ce_df['c'], name='CE Close'), row=2, col=1)
    fig.add_trace(go.Candlestick(x=pe_df['dt'], open=pe_df['o'], high=pe_df['h'], low=pe_df['l'], close=pe_df['c'], name='PE Close'), row=3, col=1)

    # Plot markers for entries and exits
    for res in results:
        entry_dt = pd.to_datetime(res['ts'], unit='s', utc=True).tz_convert('Asia/Kolkata')
        exit_dt = pd.to_datetime(res['exit_ts'], unit='s', utc=True).tz_convert('Asia/Kolkata')
        
        target_row = 2 if res['type'] == 'BUY_CE' else 3
        color = 'blue' if res['pnl%'] > 0 else 'orange'
        
        # Entry Maker
        fig.add_trace(go.Scatter(x=[entry_dt], y=[res['entry']], mode='markers', 
                                 marker=dict(symbol='triangle-up', size=12, color='blue'),
                                 name=f"Entry {res['type']}"), row=target_row, col=1)
                                 
        # Exit Marker
        fig.add_trace(go.Scatter(x=[exit_dt], y=[res['exit']], mode='markers', 
                                 marker=dict(symbol='x', size=10, color=color),
                                 name=f"Exit ({res['outcome']}) {res['pnl%']:.2f}%"), row=target_row, col=1)

    fig.update_layout(
        height=1000, 
        title_text=f"Symmetry Strategy Backtest: {underlying}",
        hovermode="x unified",
        xaxis_rangeslider_visible=False,
        xaxis2_rangeslider_visible=False,
        xaxis3_rangeslider_visible=False
    )
    
    # Remove gaps (Weekends and Outside 09:15-15:30 IST)
    fig.update_xaxes(
        rangebreaks=[
            dict(bounds=["sat", "mon"]), # hide weekends
            dict(bounds=[15.5, 9.25], pattern="hour"),  # hide 3:30 PM to 9:15 AM
        ]
    )
    
    fig.write_html("backtest_chart.html")
    print("Chart saved to 'd:\\ENGINE\\backtest_chart.html'")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run Symmetry Strategy Backtest")
    parser.add_argument("--underlying", type=str, default="NSE:NIFTY", help="Index symbol")
    parser.add_argument("--interval", type=str, default="1", help="Timeframe")
    parser.add_argument("--count", type=int, default=500, help="Number of candles")

    args = parser.parse_args()
    asyncio.run(run_backtest(underlying=args.underlying, interval=args.interval, count=args.count))
