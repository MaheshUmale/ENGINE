import pandas as pd
from .data_provider import DataProvider
from .strategy import StrategyEngine
from .database import get_session
from .execution import ExecutionEngine
from .config import INDICES

class Backtester:
    def __init__(self, index_name):
        self.index_name = index_name
        self.data_provider = DataProvider()
        self.strategy = StrategyEngine(index_name)
        self.execution = ExecutionEngine()

    async def run_backtest(self, from_date, to_date):
        print(f"Starting backtest for {self.index_name} from {from_date} to {to_date}")

        # 1. Fetch historical data for Index, CE, PE, and Futures
        # (This is a simplified backtest using available data)
        details = await self.data_provider.get_instrument_details(self.index_name)
        if not details:
            return
        print(details)
        idx_hist = self.data_provider.getData(details['index'], from_date=from_date, to_date=to_date)
        ce_hist = self.data_provider.getData(details['ce'], from_date=from_date, to_date=to_date)
        pe_hist = self.data_provider.getData(details['pe'], from_date=from_date, to_date=to_date)
        fut_hist = self.data_provider.getData(details['fut'], from_date=from_date, to_date=to_date)
        
        if idx_hist is None or ce_hist is None or pe_hist is None:
            print("Missing historical data for backtest.")
            return

        # Align data
        # first rename column open_interest as oi 
        # idx_hist = idx_hist.rename(columns={'open_interest': 'oi'})
        # ce_hist = ce_hist.rename(columns={'open_interest': 'oi'})
        # pe_hist = pe_hist.rename(columns={'open_interest': 'oi'})

        idx_hist = idx_hist.rename(columns={c: f"{c}_idx" for c in idx_hist.columns if c != 'timestamp'})
        ce_hist = ce_hist.rename(columns={c: f"{c}_ce" for c in ce_hist.columns if c != 'timestamp'})
        pe_hist = pe_hist.rename(columns={c: f"{c}_pe" for c in pe_hist.columns if c != 'timestamp'})
        
        print(ce_hist.head())
        print(pe_hist.head())
        print(fut_hist.head())

        if fut_hist is not None:
            fut_hist = fut_hist.rename(columns={c: f"{c}_fut" for c in fut_hist.columns if c != 'timestamp'})

        combined = pd.merge(idx_hist, ce_hist, on='timestamp')
        combined = pd.merge(combined, pe_hist, on='timestamp')
        if fut_hist is not None and not fut_hist.empty:
            combined = pd.merge(combined, fut_hist, on='timestamp')
        else:
            print("Future data missing, skipping volume proxy.")
            # Add dummy volume_fut
            combined['volume_fut'] = 0
        combined.sort_values('timestamp', inplace=True)

        for i in range(50, len(combined)):
            subset = combined.iloc[:i]
            current = combined.iloc[i]
            current_time = current['timestamp']

            # Ensure timestamp is naïve for DB if needed, but SQLAlchemy usually handles timezone-aware if configured.
            # Upstox returns timezone-aware. Let's make it naïve for SQLite just in case.
            if hasattr(current_time, 'to_pydatetime'):
                current_time = current_time.to_pydatetime().replace(tzinfo=None)

            # Update strategy with current prices
            self.strategy.update_data(details['index'], {'ltp': current['close_idx']})
            self.strategy.update_data(details['ce'], {'ltp': current['close_ce'], 'oi_delta': current['oi_ce'] - combined.iloc[i-1]['oi_ce']})
            self.strategy.update_data(details['pe'], {'ltp': current['close_pe'], 'oi_delta': current['oi_pe'] - combined.iloc[i-1]['oi_pe']})

            # Identify Swings
            swing_data = subset.rename(columns={'high_idx': 'high', 'low_idx': 'low', 'close_idx': 'close'})
            swing = self.strategy.identify_swing(swing_data[['high', 'low', 'close']])
            if swing:
                # Save as reference level
                self.strategy.save_reference_level(
                    swing['type'],
                    current['close_idx'],
                    current['close_ce'],
                    current['close_pe'],
                    details['ce'],
                    details['pe'],
                    timestamp=current_time
                )

            # Check for Signals
            signal = self.strategy.generate_signals(details)
            if signal:
                signal.timestamp = current_time
                # Check if we already have an open position to avoid duplicate trades
                if self.index_name not in self.execution.positions:
                    # Execute first, then save to avoid DetachedInstanceError during execution
                    self.execution.execute_signal(signal, timestamp=current_time, index_price=current['close_idx'])
                session = get_session()
                session.add(signal)
                session.commit()
                session.close()

            # Check for Exits
            if self.index_name in self.execution.positions:
                pos = self.execution.positions[self.index_name]
                # Simulating exit check
                idx_data = {'ltp': current['close_idx']}
                ce_data = {'ltp': current['close_ce'], 'oi_delta': current['oi_ce'] - combined.iloc[i-1]['oi_ce']}
                pe_data = {'ltp': current['close_pe'], 'oi_delta': current['oi_pe'] - combined.iloc[i-1]['oi_pe']}

                if self.strategy.check_exit_condition(
                    pd.Series({'side': pos['side']}),
                    idx_data,
                    ce_data,
                    pe_data
                ):
                    exit_price = current['close_ce'] if pos['side'] == 'BUY_CE' else current['close_pe']
                    self.execution.close_position(self.index_name, exit_price, timestamp=current_time, index_price=current['close_idx'])

        print(f"Backtest complete for {self.index_name}")
        return combined[['timestamp', 'open_idx', 'high_idx', 'low_idx', 'close_idx']]
