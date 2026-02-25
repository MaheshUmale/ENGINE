import pandas as pd
import datetime
import asyncio
from .data_provider import DataProvider
from .strategy import StrategyEngine
from .database import get_session, Trade, Signal, ReferenceLevel, Candle, RawTick
from .execution import ExecutionEngine
from .risk_manager import RiskManager
from .config import INDICES, ENABLE_INDEX_SYNC

class Backtester:
    def __init__(self, index_name, db_path=None):
        self.index_name = index_name
        self.data_provider = DataProvider()

        # Use a separate database for backtest results to avoid destroying live data
        from .database import create_engine, sessionmaker, Base
        import os

        self.db_path = db_path or "data/backtest_results.db"
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.engine = create_engine(f'sqlite:///{self.db_path}')
        self.Session = sessionmaker(bind=self.engine)
        Base.metadata.create_all(self.engine)

        def bt_session_factory():
            return self.Session()

        self.engines = {name: StrategyEngine(name, session_factory=bt_session_factory) for name in INDICES}
        self.strategy = self.engines[index_name]

        self.execution = ExecutionEngine(session_factory=bt_session_factory)
        self.risk_manager = RiskManager()
        self.params = {}

    def apply_params(self):
        """Applies dynamic parameters to engines."""
        if not self.params: return

        swing_window = self.params.get('swing_window', 10)
        # Update StrategyEngine logic to use these params
        # Since SWING_WINDOW is currently imported from config, we'll need to override it
        # or update the StrategyEngine to use instance variables.

        # We will dynamically inject these into the strategy instance
        self.strategy.swing_window = swing_window
        self.strategy.confluence_threshold = self.params.get('confluence_threshold', 4)
        self.strategy.atr_multiplier = self.params.get('atr_multiplier', 1.5)
        self.enable_index_sync = self.params.get('enable_index_sync', True)

    def get_backtest_session(self):
        return self.Session()

    def clean_db(self):
        print(f"Cleaning backtest database at {self.db_path}...")
        session = self.get_backtest_session()
        try:
            session.query(Trade).delete()
            session.query(Signal).delete()
            session.query(ReferenceLevel).delete()
            session.query(Candle).delete()
            session.query(RawTick).delete()
            session.commit()
        except Exception as e:
            print(f"Error cleaning backtest DB: {e}")
            session.rollback()
        finally:
            session.close()

    async def run_backtest(self, from_date, to_date):
        self.clean_db()
        self.apply_params()

        enable_sync = getattr(self, 'enable_index_sync', ENABLE_INDEX_SYNC)
        print(f"Starting backtest for {self.index_name} from {from_date} to {to_date} (Index Sync: {enable_sync})")

        # Determine range of dates - include 1 day prior for warm-up
        start_dt = pd.to_datetime(from_date) - datetime.timedelta(days=2) # 2 days to ensure at least 1 trading day
        date_range = pd.date_range(start=start_dt, end=to_date)
        all_combined = []

        for current_date in date_range:
            is_warmup = current_date < pd.to_datetime(from_date)
            date_str = current_date.strftime('%Y-%m-%d')
            print(f"Processing date: {date_str}")

            # 1. Fetch historical data for Index to get ATM at market open
            idx_morning = await self.data_provider.get_historical_data(INDICES[self.index_name]['index_key'], from_date=date_str, to_date=date_str)

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

            idx_hist = await self.data_provider.get_historical_data(details['index'], from_date=date_str, to_date=date_str)

            # Fetch other index data if sync is enabled
            other_indices_hist = {}
            if ENABLE_INDEX_SYNC:
                for name, cfg in INDICES.items():
                    if name != self.index_name:
                        oh = await self.data_provider.get_historical_data(cfg['index_key'], from_date=date_str, to_date=date_str)
                        if oh is not None:
                            other_indices_hist[name] = oh

            # To support dynamic strike updates, we fetch the whole 7-strike chain
            # Also fetch data for any active positions carried over from previous day
            chain_data = {}
            target_keys = set()
            for opt in details['option_chain']:
                target_keys.add(opt['ce'])
                target_keys.add(opt['pe'])

            # Add keys from active positions
            for pos in self.execution.positions.values():
                if pos.get('ce_key'): target_keys.add(pos['ce_key'])
                if pos.get('pe_key'): target_keys.add(pos['pe_key'])

            # Parallelize historical data fetching for efficiency
            keys_list = list(target_keys)
            print(f"Fetching historical data for {len(keys_list)} instruments in parallel...")

            tasks = [self.data_provider.get_historical_data(k, from_date=date_str, to_date=date_str) for k in keys_list]
            # Include Future data in the parallel fetch
            tasks.append(self.data_provider.get_historical_data(details['fut'], from_date=date_str, to_date=date_str))

            results = await asyncio.gather(*tasks)

            # Map results back
            for i, key in enumerate(keys_list):
                if results[i] is not None: chain_data[key] = results[i]

            fut_hist = results[-1]

            if idx_hist is None or idx_hist.empty:
                print(f"Skipping {date_str} due to missing index data.")
                continue

            # Align data
            combined = idx_hist.rename(columns={c: f"{c}_idx" for c in idx_hist.columns if c != 'timestamp'})

            for name, oh in other_indices_hist.items():
                oh = oh.rename(columns={c: f"{c}_{name}" for c in oh.columns if c != 'timestamp'})
                combined = pd.merge(combined, oh, on='timestamp', how='outer')

            for k, df in chain_data.items():
                df = df.rename(columns={c: f"{c}_{k}" for c in df.columns if c != 'timestamp'})
                combined = pd.merge(combined, df, on='timestamp', how='outer')

            if fut_hist is not None and not fut_hist.empty:
                fut_hist = fut_hist.rename(columns={c: f"{c}_fut" for c in fut_hist.columns if c != 'timestamp'})
                combined = pd.merge(combined, fut_hist, on='timestamp', how='outer')
            else:
                combined['volume_fut'] = 0

            # Convert UTC to IST (+5:30) for alignment with market hours
            combined['timestamp'] = combined['timestamp'] + datetime.timedelta(hours=5, minutes=30)

            # Use forward fill for prices and OI to handle missing candles, then fill remaining NaNs with 0
            combined = combined.dropna(subset=['close_idx'])
            combined = combined.sort_values('timestamp').ffill().fillna(0)

            # Pre-calculate 5m candles for backtest
            combined_5m = combined.resample('5min', on='timestamp').agg({
                'open_idx': 'first', 'high_idx': 'max', 'low_idx': 'min', 'close_idx': 'last'
            }).ffill()
            combined_5m.index = combined_5m.index.tz_localize(None)

            other_5m = {}
            for name in other_indices_hist:
                other_5m[name] = combined.resample('5min', on='timestamp').agg({
                    f'open_{name}': 'first', f'high_{name}': 'max', f'low_{name}': 'min', f'close_{name}': 'last'
                }).ffill()
                other_5m[name].index = other_5m[name].index.tz_localize(None)

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

                # Update main strategy engine
                self.strategy.update_data(details['index'], {
                    'ltp': current['close_idx'],
                    'volume': current.get('volume_fut', 0)
                })

                # Update other engines for sync
                for name in other_indices_hist:
                    self.engines[name].update_data(INDICES[name]['index_key'], {'ltp': current[f'close_{name}']})

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
                            self.strategy.update_candle(key, {
                                'open': current[f'open_{key}'], 'high': current[f'high_{key}'],
                                'low': current[f'low_{key}'], 'close': current[f'close_{key}']
                            })

                self.strategy.update_candle(details['index'], {
                    'open': current['open_idx'], 'high': current['high_idx'],
                    'low': current['low_idx'], 'close': current['close_idx']
                })

                for name in other_indices_hist:
                    self.engines[name].update_candle(INDICES[name]['index_key'], {
                        'open': current[f'open_{name}'], 'high': current[f'high_{name}'],
                        'low': current[f'low_{name}'], 'close': current[f'close_{name}']
                    })

                # Update 5m candle if at 5m boundary
                if current_time.minute % 5 == 0:
                    ts = current_time.replace(second=0, microsecond=0)
                    c5 = combined_5m.loc[ts]
                    self.strategy.update_candle(details['index'], {
                        'open': c5['open_idx'], 'high': c5['high_idx'],
                        'low': c5['low_idx'], 'close': c5['close_idx']
                    }, interval=5)

                    for name in other_indices_hist:
                        c5o = other_5m[name].loc[ts]
                        self.engines[name].update_candle(INDICES[name]['index_key'], {
                            'open': c5o[f'open_{name}'], 'high': c5o[f'high_{name}'],
                            'low': c5o[f'low_{name}'], 'close': c5o[f'close_{name}']
                        }, interval=5)

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

                # Signals (Only if not warmup)
                if not is_warmup:
                    # Inject params into generate_signals if needed or use modified StrategyEngine
                    signal = self.strategy.generate_signals(details)
                    if signal:
                        # Enhancement: Multi-Index Sync Check
                        if enable_sync:
                            other_sync = True
                            for other_name, other_engine in self.engines.items():
                                if other_name == self.index_name: continue
                                if not other_engine.get_trend_state(signal.side):
                                    other_sync = False
                                    break
                            if not other_sync:
                                continue

                        signal.timestamp = current_time
                        if self.index_name not in self.execution.positions:
                            # Risk Check
                            can_trade, _ = self.risk_manager.can_trade(len(self.execution.positions), timestamp=current_time)
                            if can_trade:
                                self.execution.execute_signal(signal, timestamp=current_time, index_price=current['close_idx'])

                        session = self.get_backtest_session()
                        session.add(signal)
                        session.commit()
                        session.close()

                # Exits
                if not is_warmup and self.index_name in self.execution.positions:
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

                        if exit_price > 0:
                            trade = self.execution.close_position(self.index_name, exit_price, timestamp=current_time, index_price=current['close_idx'])

                            if trade:
                                self.strategy.reset_trailing_sl()
                                self.risk_manager.update_pnl(trade.pnl)
                        else:
                            # If price is 0 (missing data), don't exit yet to avoid ruined stats
                            pass

            if not is_warmup:
                all_combined.append(combined[['timestamp', 'open_idx', 'high_idx', 'low_idx', 'close_idx']])

        if not all_combined:
            print("No data processed for the given date range.")
            return None

        final_df = pd.concat(all_combined).sort_values('timestamp').drop_duplicates('timestamp')
        print(f"Backtest complete for {self.index_name}")

        # Calculate Performance KPIs
        session = self.get_backtest_session()
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

            # Sharpe Ratio (Daily proxy)
            sharpe = 0
            if len(pnls) > 1:
                std = pd.Series(pnls).std()
                sharpe = (avg_trade / std) * (252**0.5) if std != 0 else 0

            print("\n" + "="*30)
            print(f"PERFORMANCE REPORT: {self.index_name}")
            print("="*30)
            print(f"Total Trades:    {len(pnls)}")
            print(f"Win Rate:        {win_rate:.2f}%")
            print(f"Total PnL (Net): {total_pnl:.2f}")
            print(f"Avg per Trade:   {avg_trade:.2f}")
            print(f"Max Drawdown:    {max_dd:.2f}")
            print(f"Sharpe Ratio:    {sharpe:.2f}")
            print("="*30 + "\n")

        return final_df
