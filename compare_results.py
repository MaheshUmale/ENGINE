
import sqlite3
import pandas as pd

def get_stats(db_path):
    conn = sqlite3.connect(db_path)
    try:
        trades = pd.read_sql("SELECT * FROM trades", conn)
        if trades.empty:
            return 0, 0, 0
        win_rate = (trades['pnl'] > 0).mean() * 100
        total_pnl = trades['pnl'].sum()
        return len(trades), win_rate, total_pnl
    finally:
        conn.close()

base_trades, base_wr, base_pnl = get_stats('data/backtest_7day.db')
opt_trades, opt_wr, opt_pnl = get_stats('data/backtest_7day_optimized.db')

print("==========================================")
print("   STRATEGY COMPARISON (7-DAY NIFTY)     ")
print("==========================================")
print(f"Metric        | Base Strategy | Expert Opt")
print(f"------------------------------------------")
print(f"Total Trades  | {base_trades:<13} | {opt_trades:<10}")
print(f"Win Rate      | {base_wr:>5.2f}%       | {opt_wr:>5.2f}%")
print(f"Total PnL     | {base_pnl:>8.2f}      | {opt_pnl:>8.2f}")
print("==========================================")
