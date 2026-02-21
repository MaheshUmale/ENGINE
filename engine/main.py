import asyncio
import datetime
from .data_provider import DataProvider
from .strategy import StrategyEngine
from .execution import ExecutionEngine
from .config import INDICES, ACCESS_TOKEN
from .database import init_db, get_session, RawTick, Candle

class TradingBot:
    def __init__(self):
        self.data_provider = DataProvider(ACCESS_TOKEN)
        self.engines = {name: StrategyEngine(name) for name in INDICES}
        self.execution = ExecutionEngine()
        self.instruments = {}
        self.candle_buffers = {} # instrument -> interval -> current_candle

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

            # Persist raw tick
            session = get_session()
            tick = RawTick(instrument_key=key, ltp=ltp, volume=vtt, oi=oi)
            session.add(tick)
            session.commit()
            session.close()

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

        # We only need candles for the Index to identify swings
        if key == instruments['index']:
            # Simplified aggregation for 1m candles
            now = datetime.datetime.now()
            minute = now.replace(second=0, microsecond=0)

            if index_name not in self.candle_buffers:
                self.candle_buffers[index_name] = {'timestamp': minute, 'open': price, 'high': price, 'low': price, 'close': price, 'volume': 0}

            buffer = self.candle_buffers[index_name]
            if minute > buffer['timestamp']:
                # Candle closed
                candle_df = pd.DataFrame([buffer])

                # Phase I: Identify Swing
                # In real scenario, we'd fetch last N candles from DB
                session = get_session()
                last_candles = session.query(Candle).filter_by(instrument_key=key).order_by(Candle.timestamp.desc()).limit(20).all()
                session.close()

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
                session = get_session()
                db_candle = Candle(instrument_key=key, interval=1, timestamp=buffer['timestamp'],
                                   open=buffer['open'], high=buffer['high'], low=buffer['low'],
                                   close=buffer['close'], volume=buffer['volume'])
                session.add(db_candle)
                session.commit()
                session.close()

                # Reset buffer
                self.candle_buffers[index_name] = {'timestamp': minute, 'open': price, 'high': price, 'low': price, 'close': price, 'volume': 0}
            else:
                # Update buffer
                buffer['high'] = max(buffer['high'], price)
                buffer['low'] = min(buffer['low'], price)
                buffer['close'] = price
                buffer['volume'] += volume if volume else 0

        # Run strategy signals on every tick if reference levels exist
        signal = engine.generate_signals(instruments)
        if signal:
            # For live, we can use current index price
            idx_data = engine.current_data.get(instruments['index'], {})
            self.execution.execute_signal(signal, index_price=idx_data.get('ltp'))

        # Check exits
        if index_name in self.execution.positions:
            pos = self.execution.positions[index_name]
            idx_data = engine.current_data.get(instruments['index'], {})
            ce_data = engine.current_data.get(instruments['ce'], {})
            pe_data = engine.current_data.get(instruments['pe'], {})

            if engine.check_exit_condition(pd.Series({'side': pos['side']}), idx_data, ce_data, pe_data):
                exit_price = ce_data.get('ltp') if pos['side'] == 'BUY_CE' else pe_data.get('ltp')
                self.execution.close_position(index_name, exit_price, index_price=idx_data.get('ltp'))

    async def monitor_index(self, index_name):
        print(f"Starting monitor for {index_name}")
        while True:
            # Update instruments every 5 minutes
            details = await self.data_provider.get_instrument_details(index_name)
            if details:
                self.instruments[index_name] = details
                print(f"Updated instruments for {index_name}: {details}")

            await asyncio.sleep(300) # 5 minutes

    async def run(self):
        init_db()
        print("Trading Bot Started")

        # Start monitoring tasks for each index
        monitoring_tasks = [self.monitor_index(name) for name in INDICES]

        # Start streaming (this would block or run in background)
        # For the purpose of this task, we'll simulate the start
        all_keys = []
        for name in INDICES:
            details = await self.data_provider.get_instrument_details(name)
            if details:
                self.instruments[name] = details
                all_keys.extend([details['index'], details['ce'], details['pe'], details['fut']])

        # Start the WebSocket stream
        await self.data_provider.start_streaming(all_keys, self.handle_tick)

        await asyncio.gather(*monitoring_tasks)

if __name__ == "__main__":
    bot = TradingBot()
    asyncio.run(bot.run())
