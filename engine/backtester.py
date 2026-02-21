import pandas as pd
import datetime
from .data_provider import DataProvider
from .strategy import StrategyEngine
from .database import get_session, Trade
from .execution import ExecutionEngine
from .risk_manager import RiskManager
from .config import INDICES

class Backtester:
    def __init__(self, index_name):
        self.index_name = index_name
        self.data_provider = DataProvider()
        self.strategy = StrategyEngine(index_name)
        self.execution = ExecutionEngine()
        self.risk_manager = RiskManager()

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

            details = await self.data_provider.get_instrument_details(self.index_name, reference_date=date_str)
            self.data_provider.get_market_quote = original_ltp_method # Restore

            if not details:
                continue

            print(f"Instruments for {date_str}: CE={details['ce']}, PE={details['pe']}, ATM={details['strike']}")

            idx_hist = self.data_provider.get_historical_data(details['index'], from_date=date_str, to_date=date_str)
            # To support dynamic strike updates, we fetch the whole 7-strike chain
            chain_data = {}
            for opt in details['option_chain']:
                ce_d = self.data_provider.get_historical_data(opt['ce'], from_date=date_str, to_date=date_str)
                pe_d = self.data_provider.get_historical_data(opt['pe'], from_date=date_str, to_date=date_str)
                if ce_d is not None: chain_data[opt['ce']] = ce_d
                if pe_d is not None: chain_data[opt['pe']] = pe_d

            fut_hist = self.data_provider.get_historical_data(details['fut'], from_date=date_str, to_date=date_str)

            if idx_hist is None or idx_hist.empty:
                print(f"Skipping {date_str} due to missing index data.")
                continue

            # Align data
            combined = idx_hist.rename(columns={c: f"{c}_idx" for c in idx_hist.columns if c != 'timestamp'})

            for k, df in chain_data.items():
                df = df.rename(columns={c: f"{c}_{k}" for c in df.columns if c != 'timestamp'})
                combined = pd.merge(combined, df, on='timestamp', how='outer')

            if fut_hist is not None and not fut_hist.empty:
                fut_hist = fut_hist.rename(columns={c: f"{c}_fut" for c in fut_hist.columns if c != 'timestamp'})
                combined = pd.merge(combined, fut_hist, on='timestamp', how='outer')
            else:
                combined['volume_fut'] = 0

            combined.sort_values('timestamp', inplace=True)
            # Use forward fill for prices and OI to handle missing candles, then fill remaining NaNs with 0
            combined = combined.dropna(subset=['close_idx'])
            combined = combined.sort_values('timestamp').ffill().fillna(0)

            for i in range(50, len(combined)):
                subset = combined.iloc[:i]
                current = combined.iloc[i]
                current_time = current['timestamp']

                # Dynamic ATM Selection
                current_idx_price = current['close_idx']
                best_strike = min(details['option_chain'], key=lambda x: abs(x['strike'] - current_idx_price))
                details['ce'] = best_strike['ce']
                details['pe'] = best_strike['pe']
                details['strike'] = best_strike['strike']

                if hasattr(current_time, 'to_pydatetime'):
                    current_time = current_time.to_pydatetime().replace(tzinfo=None)

                # Update strategy with all chain data for context, but primary ce/pe for signal
                self.strategy.update_data(details['index'], {
                    'ltp': current['close_idx'],
                    'volume': current.get('volume_fut', 0)
                })

                for opt in details['option_chain']:
                    for side in ['ce', 'pe']:
                        key = opt[side]
                        if f'close_{key}' in current:
                            # Avoid huge OI spikes due to missing data by using current OI if i-1 is missing
                            prev_oi = combined.iloc[i-1].get(f'oi_{key}', current[f'oi_{key}']) if i > 0 else current[f'oi_{key}']
                            self.strategy.update_data(key, {
                                'ltp': current[f'close_{key}'],
                                'oi': current[f'oi_{key}'],
                                'oi_delta': current[f'oi_{key}'] - prev_oi
                            })
                            self.strategy.update_candle(key, current[f'close_{key}'])

                self.strategy.update_candle(details['index'], current['close_idx'])

                # Identify Swings
                swing_data = subset.rename(columns={'high_idx': 'high', 'low_idx': 'low', 'close_idx': 'close'})
                swing = self.strategy.identify_swing(swing_data[['high', 'low', 'close']])
                if swing:
                    ce_key = details['ce']
                    pe_key = details['pe']
                    self.strategy.save_reference_level(
                        swing['type'],
                        current['close_idx'],
                        current.get(f'close_{ce_key}', 0),
                        current.get(f'close_{pe_key}', 0),
                        ce_key, pe_key, timestamp=current_time
                    )

                # Signals
                signal = self.strategy.generate_signals(details)
                if signal:
                    signal.timestamp = current_time
                    if self.index_name not in self.execution.positions:
                        # Risk Check
                        can_trade, _ = self.risk_manager.can_trade(len(self.execution.positions), timestamp=current_time)
                        if can_trade:
                            self.execution.execute_signal(signal, timestamp=current_time, index_price=current['close_idx'])
                    session = get_session()
                    session.add(signal)
                    session.commit()
                    session.close()

                # Exits
                if self.index_name in self.execution.positions:
                    pos = self.execution.positions[self.index_name]
                    # Use the entry strike's data for exit, even if ATM shifted
                    entry_ce_key = pos['ce_key']
                    entry_pe_key = pos['pe_key']

                    idx_data = {'ltp': current['close_idx']}

                    prev_oi_ce = combined.iloc[i-1].get(f'oi_{entry_ce_key}', current.get(f'oi_{entry_ce_key}', 0)) if i > 0 else current.get(f'oi_{entry_ce_key}', 0)
                    prev_oi_pe = combined.iloc[i-1].get(f'oi_{entry_pe_key}', current.get(f'oi_{entry_pe_key}', 0)) if i > 0 else current.get(f'oi_{entry_pe_key}', 0)

                    ce_data = {'ltp': current.get(f'close_{entry_ce_key}', 0),
                               'oi_delta': current.get(f'oi_{entry_ce_key}', 0) - prev_oi_ce}
                    pe_data = {'ltp': current.get(f'close_{entry_pe_key}', 0),
                               'oi_delta': current.get(f'oi_{entry_pe_key}', 0) - prev_oi_pe}

                    from types import SimpleNamespace
                    if self.strategy.check_exit_condition(SimpleNamespace(**pos), idx_data, ce_data, pe_data):
                        exit_price = ce_data['ltp'] if pos['side'] == 'BUY_CE' else pe_data['ltp']
                        trade = self.execution.close_position(self.index_name, exit_price, timestamp=current_time, index_price=current['close_idx'])
                        if trade:
                            self.risk_manager.update_pnl(trade.pnl)

            all_combined.append(combined[['timestamp', 'open_idx', 'high_idx', 'low_idx', 'close_idx']])

        if not all_combined:
            print("No data processed for the given date range.")
            return None

        final_df = pd.concat(all_combined).sort_values('timestamp').drop_duplicates('timestamp')
        print(f"Backtest complete for {self.index_name}")

        # Calculate Performance KPIs
        session = get_session()
        closed_trades = session.query(Trade).filter_by(index_name=self.index_name, status='CLOSED', side='SELL').all()
        session.close()

        if closed_trades:
            pnls = [t.pnl for t in closed_trades]
            total_pnl = sum(pnls)
            wins = [p for p in pnls if p > 0]
            win_rate = (len(wins) / len(pnls)) * 100
            avg_trade = total_pnl / len(pnls)

            # Simplified Drawdown
            cumulative = pd.Series(pnls).cumsum()
            max_pnl = cumulative.expanding().max()
            drawdown = cumulative - max_pnl
            max_dd = drawdown.min()

            print("\n" + "="*30)
            print(f"PERFORMANCE REPORT: {self.index_name}")
            print("="*30)
            print(f"Total Trades:    {len(pnls)}")
            print(f"Win Rate:        {win_rate:.2f}%")
            print(f"Total PnL (Net): {total_pnl:.2f}")
            print(f"Avg per Trade:   {avg_trade:.2f}")
            print(f"Max Drawdown:    {max_dd:.2f}")
            print("="*30 + "\n")

        return final_df
