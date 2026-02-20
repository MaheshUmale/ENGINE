import asyncio
import argparse
from engine.main import TradingBot
from engine.backtester import Backtester

async def main():
    parser = argparse.ArgumentParser(description='Triple-Stream Symmetry & Unwinding Trading Engine')
    parser.add_argument('--mode', choices=['live', 'backtest'], default='live', help='Run mode')
    parser.add_argument('--index', choices=['NIFTY', 'BANKNIFTY'], default='NIFTY', help='Index for backtest')
    parser.add_argument('--days', type=int, default=5, help='Number of days for backtest')

    args = parser.parse_args()

    # Initialize DB
    from engine.database import init_db
    init_db()

    if args.mode == 'live':
        bot = TradingBot()
        await bot.run()
    else:
        backtester = Backtester(args.index)
        # Simplified date range
        import datetime
        to_date = datetime.datetime.now().strftime('%Y-%m-%d')
        from_date = (datetime.datetime.now() - datetime.timedelta(days=args.days)).strftime('%Y-%m-%d')
        candles = await backtester.run_backtest(from_date, to_date)

        if candles is not None:
            from engine.visualizer import Visualizer
            vis = Visualizer(args.index)
            # Rename columns to standard for visualizer
            candles = candles.rename(columns={
                'open_idx': 'open', 'high_idx': 'high', 'low_idx': 'low', 'close_idx': 'close'
            })
            vis.generate_chart(candles)

if __name__ == "__main__":
    asyncio.run(main())
