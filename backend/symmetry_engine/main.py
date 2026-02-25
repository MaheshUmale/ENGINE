import asyncio
import datetime
import pandas as pd
from .data_provider import DataProvider
from .strategy import StrategyEngine
from .execution import ExecutionEngine
from .risk_manager import RiskManager
from .alerts import AlertManager
from config import (
    SYMMETRY_INDICES as INDICES,
    UPSTOX_ACCESS_TOKEN as ACCESS_TOKEN,
    SYMMETRY_SWING_WINDOW as SWING_WINDOW,
    SYMMETRY_ENABLE_INDEX_SYNC as ENABLE_INDEX_SYNC
)
from .database import init_db, get_session, RawTick, Candle

class TradingBot:
    def __init__(self, loop=None):
        self.data_provider = DataProvider(ACCESS_TOKEN)
        self.engines = {name: StrategyEngine(name, session_factory=get_session) for name in INDICES}
        self.execution = ExecutionEngine(session_factory=get_session)
        self.risk_manager = RiskManager()
        self.alert_manager = AlertManager()
        self.instruments = {}
        self.candle_buffers = {} # instrument -> interval -> current_candle
        self.candle_buffers_5m = {} # instrument -> current_candle
        self.loop = loop or asyncio.get_event_loop()

    def handle_tick_sync(self, feeds):
        """Bridge for data_engine internal callbacks."""
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.handle_tick(feeds), self.loop)

    async def handle_tick(self, feeds):
        if not isinstance(feeds, dict):
            return

        for key, data in feeds.items():
            ltp = data.get('last_price')
            oi = data.get('oi')
            vtt = data.get('upstox_volume') or data.get('tv_volume') or data.get('ltq', 0)

            if ltp is None: continue

            # Update engine with latest tick data
            for index_name, engine in self.engines.items():
                if key in self.instruments.get(index_name, {}).values():
                    oi_delta = self.data_provider.calculate_oi_delta(key, oi)
                    engine.update_data(key, {
                        'ltp': ltp,
                        'oi': oi,
                        'oi_delta': oi_delta,
                        'bid': data.get('bid'),
                        'ask': data.get('ask')
                    })

                    # Aggregation and Signal Generation
                    await self.aggregate_and_process(index_name, key, ltp, vtt)

    async def aggregate_and_process(self, index_name, key, price, volume):
        engine = self.engines[index_name]
        instruments = self.instruments[index_name]

        # Use UTC for all DB-stored timestamps to ensure alignment with signals/trades
        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        minute = now.replace(second=0, microsecond=0)

        buffer_key = f"{index_name}_{key}"
        if buffer_key not in self.candle_buffers:
            self.candle_buffers[buffer_key] = {'instrument_key': key, 'timestamp': minute, 'open': price, 'high': price, 'low': price, 'close': price, 'volume': 0}

        buffer = self.candle_buffers[buffer_key]
        if minute > buffer['timestamp']:
            # Candle closed
            engine.update_candle(key, buffer.copy())

            if key == instruments['index']:
                # Use a background thread for non-critical DB operations
                def db_ops():
                    session = get_session()
                    try:
                        # Phase I: Identify Swing (Optimized: use internal engine history)
                        history = engine.candle_history.get(key, [])
                        if len(history) >= 5:
                            swing = engine.identify_swing(history)
                            if swing:
                                # Fetch current option prices for reference
                                ce_data = engine.current_data.get(instruments['ce'], {})
                                pe_data = engine.current_data.get(instruments['pe'], {})
                                engine.save_reference_level(
                                    swing['type'],
                                    price,
                                    ce_data.get('ltp', 0),
                                    pe_data.get('ltp', 0),
                                    instruments['ce'],
                                    instruments['pe']
                                )

                        # Save Candle to DB
                        db_candle = Candle(instrument_key=key, interval=1, timestamp=buffer['timestamp'],
                                           open=buffer['open'], high=buffer['high'], low=buffer['low'],
                                           close=buffer['close'], volume=buffer['volume'])
                        session.add(db_candle)
                        session.commit()
                    except Exception as e:
                        print(f"Error in aggregate_and_process DB ops: {e}")
                        session.rollback()
                    finally:
                        session.close()

                asyncio.create_task(asyncio.to_thread(db_ops))

            # 5-minute aggregation
            if buffer_key not in self.candle_buffers_5m:
                self.candle_buffers_5m[buffer_key] = buffer.copy()
                self.candle_buffers_5m[buffer_key]['timestamp'] = minute.replace(minute=minute.minute - (minute.minute % 5))

            buf5 = self.candle_buffers_5m[buffer_key]
            if (minute.minute % 5 == 0) and minute > buf5['timestamp']:
                # 5m candle closed
                engine.update_candle(key, buf5.copy(), interval=5)
                self.candle_buffers_5m[buffer_key] = buffer.copy()
            else:
                buf5['high'] = max(buf5['high'], buffer['high'])
                buf5['low'] = min(buf5['low'], buffer['low'])
                buf5['close'] = buffer['close']
                buf5['volume'] += buffer['volume']

            # Reset buffer
            self.candle_buffers[buffer_key] = {'instrument_key': key, 'timestamp': minute, 'open': price, 'high': price, 'low': price, 'close': price, 'volume': 0}
        else:
            # Update buffer
            buffer['high'] = max(buffer['high'], price)
            buffer['low'] = min(buffer['low'], price)
            buffer['close'] = price
            buffer['volume'] += volume if volume else 0

        # Run strategy signals on every tick if reference levels exist
        signal = engine.generate_signals(instruments)
        if signal:
            signal.timestamp = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

            # Enrich signal with bid/ask for dynamic slippage
            active_opt_key = instruments['ce'] if signal.side == 'BUY_CE' else instruments['pe']
            active_opt_data = engine.current_data.get(active_opt_key, {})
            signal.details['bid'] = active_opt_data.get('bid')
            signal.details['ask'] = active_opt_data.get('ask')

            # Enhancement: Multi-Index Sync Check
            if ENABLE_INDEX_SYNC:
                other_sync = True
                for other_name, other_engine in self.engines.items():
                    if other_name == index_name: continue
                    if not other_engine.get_trend_state(signal.side):
                        other_sync = False
                        print(f"SIGNAL REJECTED: Multi-Index Sync Failed for {index_name} {signal.side}. {other_name} not in sync.")
                        break
                if not other_sync:
                    return

            # Risk Management
            can_trade, reason = self.risk_manager.can_trade(len(self.execution.positions))
            if not can_trade:
                print(f"SIGNAL REJECTED: Risk Manager blocked {index_name} {signal.side}. Reason: {reason}")
                return

            # For live, we can use current index price
            idx_data = engine.current_data.get(instruments['index'], {})
            self.execution.execute_signal(signal, index_price=idx_data.get('ltp'))

            # Send Alert
            asyncio.create_task(self.alert_manager.send_notification(
                f"<b>SIGNAL: {signal.side}</b>\nIndex: {signal.index_name}\nPrice: {signal.index_price}"
            ))

        # Check exits
        if index_name in self.execution.positions:
            pos = self.execution.positions[index_name]
            idx_data = engine.current_data.get(instruments['index'], {})

            # Use the specific strikes from the position, not the current ATM
            # This ensures we check exit conditions on the strike we actually own
            pos_ce_key = pos.get('ce_key')
            pos_pe_key = pos.get('pe_key')

            ce_data = engine.current_data.get(pos_ce_key, {}) if pos_ce_key else engine.current_data.get(instruments['ce'], {})
            pe_data = engine.current_data.get(pos_pe_key, {}) if pos_pe_key else engine.current_data.get(instruments['pe'], {})

            # Sync trailing SL from StrategyEngine to ExecutionEngine/DB
            current_sl = engine.trailing_sl.get(index_name, 0)
            if current_sl != pos.get('trailing_sl', 0):
                self.execution.update_trailing_sl(index_name, current_sl)

            from types import SimpleNamespace
            if engine.check_exit_condition(SimpleNamespace(**pos), idx_data, ce_data, pe_data):
                # Ensure we have a valid price for exit
                active_data = ce_data if pos['side'] == 'BUY_CE' else pe_data
                exit_price = active_data.get('ltp', 0)
                bid = active_data.get('bid', 0)

                if exit_price > 0:
                    trade = self.execution.close_position(index_name, exit_price, index_price=idx_data.get('ltp'), bid=bid)
                    if trade:
                        engine.reset_trailing_sl()
                        self.risk_manager.update_pnl(trade.pnl)
                        asyncio.create_task(self.alert_manager.send_notification(
                            f"<b>TRADE CLOSED</b>\nIndex: {index_name}\nPnL: {trade.pnl:.2f}"
                        ))
                else:
                    print(f"EXIT TRIGGERED but price is 0 for {index_name}. Waiting for valid tick.")

    async def recover_state(self):
        """
        Recovers the complete bot state from database to handle server restarts.
        """
        print("State Recovery: Initializing...")

        # 1. Recover positions and risk metrics
        await asyncio.to_thread(self.execution.recover_positions)
        await asyncio.to_thread(self.risk_manager.recover_pnl)

        # 2. Recover StrategyEngine states (Reference Levels and Instruments)
        session = await asyncio.to_thread(get_session)
        try:
            from .database import ReferenceLevel
            for index_name, engine in self.engines.items():
                # Recover last known High and Low levels for today
                today_sod = datetime.datetime.combine(datetime.date.today(), datetime.time.min)

                for level_type in ['High', 'Low']:
                    last_ref = session.query(ReferenceLevel).filter(
                        ReferenceLevel.index_name == index_name,
                        ReferenceLevel.type == level_type,
                        ReferenceLevel.timestamp >= today_sod
                    ).order_by(ReferenceLevel.timestamp.desc()).first()

                    if last_ref:
                        engine.reference_levels[level_type] = {
                            'index_price': last_ref.index_price,
                            'ce_price': last_ref.ce_price,
                            'pe_price': last_ref.pe_price,
                            'type': last_ref.type
                        }
                        # Also recover the instruments if not already discovered
                        if index_name not in self.instruments:
                            self.instruments[index_name] = {
                                'index': INDICES[index_name]['index_key'],
                                'ce': last_ref.instrument_ce,
                                'pe': last_ref.instrument_pe
                            }
                            print(f"State Recovery: Recovered instruments for {index_name} from RefLevel")

                # 3. Recover active trailing stop losses for restored positions
                if index_name in self.execution.positions:
                    pos = self.execution.positions[index_name]
                    if pos.get('trailing_sl'):
                        engine.trailing_sl[index_name] = pos['trailing_sl']
                        print(f"State Recovery: Recovered trailing SL for {index_name}: {pos['trailing_sl']}")

                    # Parallelize history fetching for position strikes
                    pos_keys = [pos.get(k) for k in ['ce_key', 'pe_key'] if pos.get(k)]
                    if pos_keys:
                        print(f"State Recovery: Fetching history for position strikes {pos_keys}")
                        hist_results = await asyncio.gather(*[self.data_provider.get_historical_data(k, interval=1) for k in pos_keys])
                        for key, hist in zip(pos_keys, hist_results):
                            if hist is not None and not hist.empty:
                                for _, row in hist.tail(20).iterrows():
                                    engine.update_candle(key, {
                                        'open': row['open'], 'high': row['high'],
                                        'low': row['low'], 'close': row['close']
                                    })

            print("State Recovery: Complete.")
        except Exception as e:
            print(f"Error during state recovery: {e}")
        finally:
            session.close()

    async def monitor_index(self, index_name):
        print(f"Starting monitor for {index_name}")
        last_update_price = 0
        while True:
            # Update instruments every 5 minutes or on large price move
            current_price = 0
            idx_key = INDICES[index_name]['index_key']
            if index_name in self.engines and idx_key in self.engines[index_name].current_data:
                current_price = self.engines[index_name].current_data[idx_key].get('ltp', 0)

            threshold = 25 if index_name == 'NIFTY' else 100

            # Only update instruments during market hours or if never updated
            # For simplicity in paper trading, we update anytime price moves significantly
            if abs(current_price - last_update_price) >= threshold or last_update_price == 0:
                old_details = self.instruments.get(index_name)
                details = await self.data_provider.get_instrument_details(index_name)
                if details:
                    self.instruments[index_name] = details
                    last_update_price = details['ltp']
                    print(f"Updated instruments for {index_name} (Price: {last_update_price}): {details}")

                    # Update subscriptions
                    new_keys = [details['ce'], details['pe']]

                    # Protect active position strikes from unsubscription
                    protected_keys = []
                    for pos in self.execution.positions.values():
                        if pos.get('ce_key'): protected_keys.append(pos['ce_key'])
                        if pos.get('pe_key'): protected_keys.append(pos['pe_key'])

                    if old_details:
                        old_keys = [old_details['ce'], old_details['pe']]
                        to_unsubscribe = [k for k in old_keys if k not in new_keys and k not in protected_keys]
                        if to_unsubscribe:
                            self.data_provider.unsubscribe(to_unsubscribe)

                    self.data_provider.subscribe(new_keys)

            await asyncio.sleep(60) # Check every minute

    async def warmup(self):
        print("Performing Strategy Warmup...")
        for name, engine in self.engines.items():
            details = self.instruments.get(name)
            if not details:
                print(f"Warmup Skipped for {name}: Instruments not discovered.")
                continue

            # Fetch last 2 days of data for Index, CE, PE (with retries)
            async def fetch_with_retry(key, retries=3):
                for i in range(retries):
                    try:
                        data = await self.data_provider.get_historical_data(key, interval=1)
                        if data is not None and not data.empty:
                            return data
                    except Exception as e:
                        print(f"Warmup: Attempt {i+1} failed for {key}: {e}")
                    await asyncio.sleep(2)
                return None

            print(f"Warmup: Fetching history for {name}...")
            idx_hist = await fetch_with_retry(details['index'])
            ce_hist = await fetch_with_retry(details['ce'])
            pe_hist = await fetch_with_retry(details['pe'])

            if idx_hist is not None and not idx_hist.empty:
                print(f"Ingesting historical candles for {name} warm-up")

                # Align data
                idx_hist = idx_hist.rename(columns={c: f"{c}_idx" for c in idx_hist.columns if c != 'timestamp'})
                ce_hist = ce_hist.rename(columns={c: f"{c}_ce" for c in ce_hist.columns if c != 'timestamp'}) if ce_hist is not None else None
                pe_hist = pe_hist.rename(columns={c: f"{c}_pe" for c in pe_hist.columns if c != 'timestamp'}) if pe_hist is not None else None

                combined = idx_hist
                if ce_hist is not None: combined = pd.merge(combined, ce_hist, on='timestamp', how='left')
                if pe_hist is not None: combined = pd.merge(combined, pe_hist, on='timestamp', how='left')

                combined = combined.sort_values('timestamp').ffill().fillna(0)

                # 5m aggregation for warmup
                agg_dict = {
                    'open_idx': 'first', 'high_idx': 'max', 'low_idx': 'min', 'close_idx': 'last'
                }
                if 'close_ce' in combined.columns: agg_dict['close_ce'] = 'last'
                if 'close_pe' in combined.columns: agg_dict['close_pe'] = 'last'

                combined_5m = combined.resample('5min', on='timestamp').agg(agg_dict).dropna()

                for _, row in combined_5m.iterrows():
                    engine.update_candle(details['index'], {
                        'open': row['open_idx'], 'high': row['high_idx'],
                        'low': row['low_idx'], 'close': row['close_idx']
                    }, interval=5)

                for i in range(SWING_WINDOW + 2, len(combined)):
                    subset = combined.iloc[:i]
                    current = combined.iloc[i]

                    # Update engine candle history
                    engine.update_candle(details['index'], {
                        'open': current['open_idx'], 'high': current['high_idx'],
                        'low': current['low_idx'], 'close': current['close_idx']
                    })
                    if 'close_ce' in current:
                        engine.update_candle(details['ce'], {
                            'open': current['open_ce'], 'high': current['high_ce'],
                            'low': current['low_ce'], 'close': current['close_ce']
                        })
                    if 'close_pe' in current:
                        engine.update_candle(details['pe'], {
                            'open': current['open_pe'], 'high': current['high_pe'],
                            'low': current['low_pe'], 'close': current['close_pe']
                        })

                    # Identify Swings
                    swing_data = subset.rename(columns={'high_idx': 'high', 'low_idx': 'low', 'close_idx': 'close'})
                    swing = engine.identify_swing(swing_data[['high', 'low', 'close']])
                    if swing:
                        engine.save_reference_level(
                            swing['type'],
                            current['close_idx'],
                            current.get('close_ce', 0),
                            current.get('close_pe', 0),
                            details['ce'], details['pe'],
                            timestamp=current['timestamp'].to_pydatetime()
                        )

                # Save historical candles to DB if not present (Optimized: offload to thread)
                def save_hist():
                    session = get_session()
                    try:
                        for _, row in idx_hist.tail(100).iterrows():
                            exists = session.query(Candle).filter_by(instrument_key=details['index'], timestamp=row['timestamp']).first()
                            if not exists:
                                db_candle = Candle(
                                    instrument_key=details['index'], interval=1, timestamp=row['timestamp'],
                                    open=row['open_idx'], high=row['high_idx'], low=row['low_idx'],
                                    close=row['close_idx'], volume=row['volume_idx']
                                )
                                session.add(db_candle)
                        session.commit()
                    finally:
                        session.close()

                asyncio.create_task(asyncio.to_thread(save_hist))

    async def run(self):
        init_db()
        print("Trading Bot Started")

        # 0. Recover state from previous session
        await self.recover_state()

        # 1. Initial Discovery
        all_keys = []
        for name in INDICES:
            details = await self.data_provider.get_instrument_details(name)
            if details:
                self.instruments[name] = details
                all_keys.extend([details['index'], details['ce'], details['pe'], details['fut']])

        # 2. Warmup strategy with historical data
        await self.warmup()

        # Start monitoring tasks for each index
        monitoring_tasks = [self.monitor_index(name) for name in INDICES]

        # Start the WebSocket stream
        await self.data_provider.start_streaming(all_keys, self.handle_tick)

        await asyncio.gather(*monitoring_tasks)

if __name__ == "__main__":
    bot = TradingBot()
    asyncio.run(bot.run())
