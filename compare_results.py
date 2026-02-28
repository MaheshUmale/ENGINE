import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def generate_market_scenario(days=1, trades_per_day=5):
    np.random.seed(42)
    data = []
    base_idx = 22000
    current_idx = base_idx
    ts_start = datetime(2024, 1, 1, 9, 15)
    for i in range(500):
        ts = int((ts_start + timedelta(minutes=i)).timestamp())
        idx_move = np.random.normal(0, 2)
        current_idx += idx_move
        ce_price = 150 + (current_idx - base_idx) * 0.5 + np.random.normal(0, 0.5)
        pe_price = 150 - (current_idx - base_idx) * 0.4 + np.random.normal(0, 0.5)
        if 100 <= i <= 110:
            current_idx += 5
            ce_price += 15
        if 200 <= i <= 210:
             if i == 200: current_idx += 20
             if 201 <= i <= 205: current_idx -= 5
             if i > 205: current_idx += 15
        if 300 <= i <= 310:
             current_idx += 10
             ce_price -= 2
        data.append({
            'ts': ts,
            'o_idx': current_idx - 2, 'h_idx': current_idx + 2, 'l_idx': current_idx - 2, 'c_idx': current_idx, 'v_idx': 1000,
            'c_ce': ce_price, 'h_ce': ce_price + 1, 'l_ce': ce_price - 1,
            'c_pe': pe_price, 'h_pe': pe_price + 1, 'l_pe': pe_price - 1
        })
    return pd.DataFrame(data)

def run_comparison():
    from backend.brain.SymmetryAnalyzer import SymmetryAnalyzer
    df = generate_market_scenario()
    analyzer = SymmetryAnalyzer("NSE:NIFTY")
    idx_candles = df[['ts', 'o_idx', 'h_idx', 'l_idx', 'c_idx', 'v_idx']].values.tolist()
    ce_candles = df[['ts', 'c_ce', 'h_ce', 'l_ce', 'c_ce', 'v_idx']].values.tolist()
    pe_candles = df[['ts', 'c_pe', 'h_pe', 'l_pe', 'c_pe', 'v_idx']].values.tolist()
    oi_data = {c[0]: {'ce_oi_chg': -100, 'pe_oi_chg': 100} for c in idx_candles}
    signals = analyzer.analyze(idx_candles, ce_candles, pe_candles, oi_data=oi_data)
    results = []
    for sig in signals:
        entry_p = sig['price']
        sl = sig['sl']
        tp = sig['tp']
        ts = sig['time']
        future = df[df['ts'] > ts]
        outcome = "EXPIRED"
        exit_p = entry_p
        for _, row in future.iterrows():
            if row['l_ce'] <= sl:
                outcome = "SL"
                exit_p = sl
                break
            if row['h_ce'] >= tp:
                outcome = "TP"
                exit_p = tp
                break
        pnl = (exit_p - entry_p) / entry_p * 100
        results.append({'pnl': pnl, 'outcome': outcome, 'type': sig['type']})
    res_df = pd.DataFrame(results)
    print("==============================")
    print("STABILITY CHECK (OPTIMIZED STRATEGY V2)")
    print("==============================")
    if not res_df.empty:
        win_rate = len(res_df[res_df['pnl'] > 0]) / len(res_df) * 100
        print(f"Total Trades:    {len(res_df)}")
        print(f"Win Rate:        {win_rate:.2f}%")
        print(f"Total PnL (%):   {res_df['pnl'].sum():.2f}%")
    else:
        print("No signals generated.")
    print("==============================\n")

if __name__ == "__main__":
    import sys
    import os
    sys.path.append(os.path.join(os.getcwd(), 'backend'))
    run_comparison()
