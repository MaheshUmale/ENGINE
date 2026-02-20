import pandas as pd
import datetime
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

        # Determine range of dates
        date_range = pd.date_range(start=from_date, end=to_date)
        all_combined = []

        for current_date in date_range:
            date_str = current_date.strftime('%Y-%m-%d')
            print(f"Processing date: {date_str}")

            # 1. Fetch historical data for Index to get ATM at market open
            idx_morning = self.data_provider.get_historical_data(INDICES[self.index_name]['index_key'], from_date=date_str, to_date=date_str)

            # If today and empty, try to get LTP for discovery
            if (idx_morning is None or idx_morning.empty) and date_str == datetime.datetime.now().strftime('%Y-%m-%d'):
                print(f"No historical data for today ({date_str}), using live LTP for discovery...")
                quotes = self.data_provider.get_market_quote([INDICES[self.index_name]['index_key']])
                if quotes and INDICES[self.index_name]['index_key'] in quotes:
                    open_price = quotes[INDICES[self.index_name]['index_key']].last_price
                else:
                    continue
            elif idx_morning is not None and not idx_morning.empty:
                # Upstox returns candles sorted DESC usually, let's sort ASC
                idx_morning = idx_morning.sort_values('timestamp')
                open_price = idx_morning.iloc[0]['close']
            else:
                continue

            # We need ATM at open (approx 9:15-9:20)

            # Use morning price to find instruments for the day
            # Mocking ltp for discovery
            original_ltp_method = self.data_provider.get_market_quote
            self.data_provider.get_market_quote = lambda x: {INDICES[self.index_name]['index_key']: type('obj', (object,), {'last_price': open_price})}

            details = await self.data_provider.get_instrument_details(self.index_name)
            self.data_provider.get_market_quote = original_ltp_method # Restore

            if not details:
                continue

            print(f"Instruments for {date_str}: CE={details['ce']}, PE={details['pe']}, ATM={details['strike']}")

            idx_hist = self.data_provider.get_historical_data(details['index'], from_date=date_str, to_date=date_str)
            ce_hist = self.data_provider.get_historical_data(details['ce'], from_date=date_str, to_date=date_str)
            pe_hist = self.data_provider.get_historical_data(details['pe'], from_date=date_str, to_date=date_str)
            fut_hist = self.data_provider.get_historical_data(details['fut'], from_date=date_str, to_date=date_str)

            if idx_hist is None or idx_hist.empty or ce_hist is None or ce_hist.empty or pe_hist is None or pe_hist.empty:
                print(f"Skipping {date_str} due to missing data.")
                continue

            # Align data
            idx_hist = idx_hist.rename(columns={c: f"{c}_idx" for c in idx_hist.columns if c != 'timestamp'})
            ce_hist = ce_hist.rename(columns={c: f"{c}_ce" for c in ce_hist.columns if c != 'timestamp'})
            pe_hist = pe_hist.rename(columns={c: f"{c}_pe" for c in pe_hist.columns if c != 'timestamp'})

            combined = pd.merge(idx_hist, ce_hist, on='timestamp', how='outer')
            combined = pd.merge(combined, pe_hist, on='timestamp', how='outer')

            if fut_hist is not None and not fut_hist.empty:
                fut_hist = fut_hist.rename(columns={c: f"{c}_fut" for c in fut_hist.columns if c != 'timestamp'})
                combined = pd.merge(combined, fut_hist, on='timestamp', how='outer')
            else:
                combined['volume_fut'] = 0

            combined.sort_values('timestamp', inplace=True)
            combined = combined.dropna(subset=['close_idx']).fillna(0)
            combined.sort_values('timestamp', inplace=True)

            # Reset strategy state for new day? (Optional, let's keep levels for now but usually we reset)
            # self.strategy.reference_levels = {'High': None, 'Low': None}

            for i in range(50, len(combined)):
                subset = combined.iloc[:i]
                current = combined.iloc[i]
                current_time = current['timestamp']

                if hasattr(current_time, 'to_pydatetime'):
                    current_time = current_time.to_pydatetime().replace(tzinfo=None)

                # Update strategy
                self.strategy.update_data(details['index'], {
                    'ltp': current['close_idx'],
                    'volume': current.get('volume_fut', 0)
                })
                self.strategy.update_data(details['ce'], {'ltp': current['close_ce'], 'oi_delta': current['oi_ce'] - combined.iloc[i-1]['oi_ce']})
                self.strategy.update_data(details['pe'], {'ltp': current['close_pe'], 'oi_delta': current['oi_pe'] - combined.iloc[i-1]['oi_pe']})

                # Identify Swings
                swing_data = subset.rename(columns={'high_idx': 'high', 'low_idx': 'low', 'close_idx': 'close'})
                swing = self.strategy.identify_swing(swing_data[['high', 'low', 'close']])
                if swing:
                    self.strategy.save_reference_level(
                        swing['type'], current['close_idx'], current['close_ce'], current['close_pe'],
                        details['ce'], details['pe'], timestamp=current_time
                    )

                # Signals
                signal = self.strategy.generate_signals(details)
                if signal:
                    signal.timestamp = current_time
                    if self.index_name not in self.execution.positions:
                        self.execution.execute_signal(signal, timestamp=current_time, index_price=current['close_idx'])
                    session = get_session()
                    session.add(signal)
                    session.commit()
                    session.close()

                # Exits
                if self.index_name in self.execution.positions:
                    pos = self.execution.positions[self.index_name]
                    idx_data = {'ltp': current['close_idx']}
                    ce_data = {'ltp': current['close_ce'], 'oi_delta': current['oi_ce'] - combined.iloc[i-1]['oi_ce']}
                    pe_data = {'ltp': current['close_pe'], 'oi_delta': current['oi_pe'] - combined.iloc[i-1]['oi_pe']}

                    from types import SimpleNamespace
                    if self.strategy.check_exit_condition(SimpleNamespace(**pos), idx_data, ce_data, pe_data):
                        exit_price = current['close_ce'] if pos['side'] == 'BUY_CE' else current['close_pe']
                        self.execution.close_position(self.index_name, exit_price, timestamp=current_time, index_price=current['close_idx'])

            all_combined.append(combined[['timestamp', 'open_idx', 'high_idx', 'low_idx', 'close_idx']])

        if not all_combined:
            print("No data processed for the given date range.")
            return None

        final_df = pd.concat(all_combined).sort_values('timestamp').drop_duplicates('timestamp')
        print(f"Backtest complete for {self.index_name}")
        return final_df
