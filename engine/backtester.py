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

        idx_hist = self.data_provider.get_historical_data(details['index'], from_date=from_date, to_date=to_date)
        ce_hist = self.data_provider.get_historical_data(details['ce'], from_date=from_date, to_date=to_date)
        pe_hist = self.data_provider.get_historical_data(details['pe'], from_date=from_date, to_date=to_date)
        fut_hist = self.data_provider.get_historical_data(details['fut'], from_date=from_date, to_date=to_date)

        if idx_hist is None or ce_hist is None or pe_hist is None:
            print("Missing historical data for backtest.")
            return

        # Align data
        idx_hist = idx_hist.rename(columns={c: f"{c}_idx" for c in idx_hist.columns if c != 'timestamp'})
        ce_hist = ce_hist.rename(columns={c: f"{c}_ce" for c in ce_hist.columns if c != 'timestamp'})
        pe_hist = pe_hist.rename(columns={c: f"{c}_pe" for c in pe_hist.columns if c != 'timestamp'})
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
                    details['pe']
                )

            # Check for Signals
            signal = self.strategy.generate_signals(details)
            if signal:
                # Execute first, then save to avoid DetachedInstanceError during execution
                self.execution.execute_signal(signal)
                session = get_session()
                session.add(signal)
                session.commit()
                session.close()

            # Check for Exits
            if self.index_name in self.execution.positions:
                pos = self.execution.positions[self.index_name]
                # Simulating exit check
                if self.strategy.check_exit_condition(
                    pd.Series({'side': pos['side']}),
                    {'ltp': current['close_idx']},
                    {'ltp': current['close_ce']},
                    {'ltp': current['close_pe']}
                ):
                    exit_price = current['close_ce'] if pos['side'] == 'BUY_CE' else current['close_pe']
                    self.execution.close_position(self.index_name, exit_price)

        print(f"Backtest complete for {self.index_name}")
