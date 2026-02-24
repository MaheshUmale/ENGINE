import sqlite3
import pandas as pd

def detailed_report():
    conn = sqlite3.connect('data/backtest_7day.db')
    trades = pd.read_sql_query("SELECT * FROM trades WHERE side='BUY' AND status='CLOSED'", conn)

    # Daily breakdown
    trades['date'] = pd.to_datetime(trades['timestamp']).dt.date
    daily = trades.groupby('date')['pnl'].agg(['sum', 'count']).reset_index()
    daily.columns = ['Date', 'Total PnL', 'Trade Count']

    print("### 7-Day NIFTY Backtest Detailed Report")
    print(f"**Period:** 2026-02-18 to 2026-02-24")
    print(f"**Total PnL:** {trades['pnl'].sum():.2f}")
    print(f"**Win Rate:** {(len(trades[trades['pnl'] > 0]) / len(trades) * 100):.2f}%")
    print(f"**Total Trades:** {len(trades)}")

    print("\n#### Daily Breakdown")
    print(daily.to_string(index=False))

    print("\n#### Trade Log (Latest 15)")
    log = trades[['timestamp', 'instrument_key', 'price', 'exit_price', 'pnl']].tail(15)
    print(log.to_string(index=False))

    conn.close()

if __name__ == "__main__":
    detailed_report()
