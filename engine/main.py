import asyncio
import datetime
import pandas as pd
from .data_provider import DataProvider
from .strategy import StrategyEngine
from .execution import ExecutionEngine
from .risk_manager import RiskManager
from .alerts import AlertManager
from .config import INDICES, ACCESS_TOKEN, SWING_WINDOW, ENABLE_INDEX_SYNC
from .database import init_db, get_session, RawTick, Candle

class TradingBot:
    def __init__(self):
        self.data_provider = DataProvider(ACCESS_TOKEN)
        self.engines = {name: StrategyEngine(name) for name in INDICES}
        self.execution = ExecutionEngine()
        self.risk_manager = RiskManager()
        self.alert_manager = AlertManager()
        self.instruments = {}
        self.candle_buffers = {} # instrument -> interval -> current_candle
        self.candle_buffers_5m = {} # instrument -> current_candle
        self.tick_batch = []
        self.last_batch_save = datetime.datetime.now()

    async def handle_tick(self, message):
        if not isinstance(message, dict):
            return

        feeds = message.get('feeds', {})
        for key, data in feeds.items():
            full_feed = data.get('fullFeed', {})
            ltp, oi, vtt = None, None, None

            if 'indexFF' in full_feed:
                ltp = full_feed['indexFF'].get('ltpc', {}).get('ltp')
            elif 'marketFF' in full_feed:
                mff = full_feed['marketFF']
                ltp = mff.get('ltpc', {}).get('ltp')
                oi = mff.get('oi')
                vtt = mff.get('vtt')
                if vtt: vtt = float(vtt) # vtt is string in V3

            if ltp is None: continue

            # Batch raw tick for better performance
            self.tick_batch.append(RawTick(instrument_key=key, ltp=ltp, volume=vtt, oi=oi))
            if len(self.tick_batch) >= 100 or (datetime.datetime.now() - self.last_batch_save).seconds > 5:
                await self.save_tick_batch()

            # Update engine with latest tick data
            for index_name, engine in self.engines.items():
                if key in self.instruments.get(index_name, {}).values():
                    oi_delta = self.data_provider.calculate_oi_delta(key, oi)
                    engine.update_data(key, {'ltp': ltp, 'oi': oi, 'oi_delta': oi_delta})

                    # Aggregation and Signal Generation
                    await self.aggregate_and_process(index_name, key, ltp, vtt)

    async def aggregate_and_process(self, index_name, key, price, volume):
        engine = self.engines[index_name]
        instruments = self.instruments[index_name]

        now = datetime.datetime.now()
        minute = now.replace(second=0, microsecond=0)

        buffer_key = f"{index_name}_{key}"
        if buffer_key not in self.candle_buffers:
            self.candle_buffers[buffer_key] = {'timestamp': minute, 'open': price, 'high': price, 'low': price, 'close': price, 'volume': 0}

        buffer = self.candle_buffers[buffer_key]
        if minute > buffer['timestamp']:
            # Candle closed
            engine.update_candle(key, buffer.copy())

            if key == instruments['index']:
                candle_df = pd.DataFrame([buffer])

                # Use a single session for all operations
                session = get_session()
                try:
                    # Phase I: Identify Swing
                    last_candles = session.query(Candle).filter_by(instrument_key=key).order_by(Candle.timestamp.desc()).limit(20).all()

                    if last_candles:
                        df = pd.DataFrame([c.__dict__ for c in last_candles])
                        df = pd.concat([df, candle_df], ignore_index=True)
                        swing = engine.identify_swing(df)
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
            self.candle_buffers[buffer_key] = {'timestamp': minute, 'open': price, 'high': price, 'low': price, 'close': price, 'volume': 0}
        else:
            # Update buffer
            buffer['high'] = max(buffer['high'], price)
            buffer['low'] = min(buffer['low'], price)
            buffer['close'] = price
            buffer['volume'] += volume if volume else 0

        # Run strategy signals on every tick if reference levels exist
        signal = engine.generate_signals(instruments)
        if signal:
            # Enhancement: Multi-Index Sync Check
            if ENABLE_INDEX_SYNC:
                other_sync = True
                for other_name, other_engine in self.engines.items():
                    if other_name == index_name: continue
                    if not other_engine.get_trend_state(signal.side):
                        other_sync = False
                        break
                if not other_sync:
                    # Optional: Log that sync failed
                    return

            # Risk Management
            can_trade, reason = self.risk_manager.can_trade(len(self.execution.positions))
            if not can_trade:
                print(f"Trade blocked by Risk Manager: {reason}")
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
            ce_data = engine.current_data.get(instruments['ce'], {})
            pe_data = engine.current_data.get(instruments['pe'], {})

            from types import SimpleNamespace
            if engine.check_exit_condition(SimpleNamespace(**pos), idx_data, ce_data, pe_data):
                exit_price = ce_data.get('ltp') if pos['side'] == 'BUY_CE' else pe_data.get('ltp')
                trade = self.execution.close_position(index_name, exit_price, index_price=idx_data.get('ltp'))
                if trade:
                    engine.reset_trailing_sl()
                    self.risk_manager.update_pnl(trade.pnl)
                    asyncio.create_task(self.alert_manager.send_notification(
                        f"<b>TRADE CLOSED</b>\nIndex: {index_name}\nPnL: {trade.pnl:.2f}"
                    ))

    async def save_tick_batch(self):
        if not self.tick_batch: return
        try:
            session = get_session()
            session.add_all(self.tick_batch)
            session.commit()
            session.close()
            self.tick_batch = []
            self.last_batch_save = datetime.datetime.now()
        except Exception as e:
            print(f"Error saving tick batch: {e}")

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

            if abs(current_price - last_update_price) >= threshold or last_update_price == 0:
                old_details = self.instruments.get(index_name)
                details = await self.data_provider.get_instrument_details(index_name)
                if details:
                    self.instruments[index_name] = details
                    last_update_price = details['ltp']
                    print(f"Updated instruments for {index_name} (Price: {last_update_price}): {details}")

                    # Update subscriptions
                    new_keys = [details['ce'], details['pe']]
                    if old_details:
                        old_keys = [old_details['ce'], old_details['pe']]
                        to_unsubscribe = [k for k in old_keys if k not in new_keys]
                        if to_unsubscribe:
                            self.data_provider.unsubscribe(to_unsubscribe)

                    self.data_provider.subscribe(new_keys)

            await asyncio.sleep(60) # Check every minute

    async def warmup(self):
        print("Performing Strategy Warmup...")
        for name, engine in self.engines.items():
            details = self.instruments.get(name)
            if not details: continue

            # Fetch last 2 days of data for Index, CE, PE
            idx_hist = self.data_provider.get_historical_data(details['index'], interval=1)
            ce_hist = self.data_provider.get_historical_data(details['ce'], interval=1)
            pe_hist = self.data_provider.get_historical_data(details['pe'], interval=1)

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
                combined_5m = combined.resample('5min', on='timestamp').agg({
                    'open_idx': 'first', 'high_idx': 'max', 'low_idx': 'min', 'close_idx': 'last',
                    'close_ce': 'last', 'close_pe': 'last'
                }).dropna()

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

                # Save historical candles to DB if not present
                session = get_session()
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
                session.close()

    async def run(self):
        init_db()
        print("Trading Bot Started")

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
