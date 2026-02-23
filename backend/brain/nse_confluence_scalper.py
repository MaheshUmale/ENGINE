import logging
import pandas as pd
import numpy as np
from datetime import datetime
import pytz
import asyncio
import json
import csv
import os
import time
from scipy.signal import find_peaks
from core.options_manager import options_manager
from core.oi_buildup_analyzer import oi_buildup_analyzer
from brain.MarketPsychologyAnalyzer import MarketPsychologyAnalyzer

logger = logging.getLogger(__name__)

class DataStreamer:
    """Handles WSS connections for Underlying, ATM Call, and ATM Put."""
    def __init__(self, scalper):
        self.scalper = scalper
        self.buffers = {
            'underlying': pd.DataFrame(columns=['ts', 'o', 'h', 'l', 'c', 'v']),
            'atm_call': pd.DataFrame(columns=['ts', 'o', 'h', 'l', 'c', 'v']),
            'atm_put': pd.DataFrame(columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        }
        self.tick_buffer = [] # Circular buffer of last 500 ticks
        self.instrument_map = {} # instrumentKey -> 'underlying'|'atm_call'|'atm_put'
        self.symbols = {} # 'underlying'|'atm_call'|'atm_put' -> instrumentKey
        self.cum_vol = {'underlying': 0, 'atm_call': 0, 'atm_put': 0}
        self.cum_pv = {'underlying': 0, 'atm_call': 0, 'atm_put': 0}
        self.vwap = {'underlying': 0, 'atm_call': 0, 'atm_put': 0}

    def on_tick(self, instrument_key, tick_data):
        target = self.instrument_map.get(instrument_key)
        if not target: return

        price = float(tick_data.get('last_price', 0))
        volume = int(tick_data.get('ltq', 0))

        tick = {
            'ts': tick_data.get('ts_ms', time.time()*1000),
            'last_price': price,
            'ltq': volume
        }

        # Calculate VWAP
        if volume > 0:
            self.cum_vol[target] += volume
            self.cum_pv[target] += price * volume
            self.vwap[target] = self.cum_pv[target] / self.cum_vol[target]

        if target == 'underlying':
            self.scalper.current_spot = price
            self.tick_buffer.append(tick)
            if len(self.tick_buffer) > 500: self.tick_buffer.pop(0)

            # Re-calculate HVN every 100 ticks
            if len(self.tick_buffer) % 100 == 0:
                self.scalper.engine.calculate_volume_profile(self.tick_buffer)

        self.scalper.last_ticks[target] = tick

    def on_ohlcv(self, instrument_key, candle_data):
        target = self.instrument_map.get(instrument_key)
        if not target: return

        if not candle_data or 'ohlcv' not in candle_data: return

        new_df = pd.DataFrame(candle_data['ohlcv'], columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        self.buffers[target] = new_df

        # Update levels
        if target == 'underlying':
            self.scalper.engine.find_levels(new_df, 'underlying')
            # Market Psychology Analysis
            try:
                zones, signals = self.scalper.psych_analyzer.analyze(candle_data['ohlcv'])
                self.scalper.psych_data['zones'] = zones
                self.scalper.psych_data['signals'] = signals
            except Exception as e:
                logger.error(f"Psychology analysis error: {e}")
        else:
            self.scalper.engine.update_option_levels(instrument_key, new_df)

    async def subscribe(self, underlying):
        from core.options_manager import options_manager
        from core.provider_registry import live_stream_registry
        from external.tv_api import tv_api

        self.symbols['underlying'] = underlying
        self.instrument_map[underlying] = 'underlying'

        # Find ATM options
        spot = await options_manager.get_spot_price(underlying)
        if spot == 0:
            logger.error(f"Cannot subscribe for {underlying}: Spot price 0")
            return

        self.scalper.current_spot = spot
        # NIFTY uses 50 strike interval, others 100. Let's be smart.
        strike_interval = 50 if "NIFTY" in underlying and "BANK" not in underlying else 100
        atm_strike = round(spot / strike_interval) * strike_interval

        # Ensure symbols are cached
        await options_manager._refresh_wss_symbols(underlying)
        # Find specific ATM Call and Put
        call_sym = options_manager.symbol_map_cache.get(underlying, {}).get(f"{atm_strike}_call")
        put_sym = options_manager.symbol_map_cache.get(underlying, {}).get(f"{atm_strike}_put")

        if not call_sym or not put_sym:
            logger.error(f"ATM symbols not found for {underlying} at {atm_strike}")
            return

        self.symbols['atm_call'] = call_sym
        self.symbols['atm_put'] = put_sym
        self.instrument_map[call_sym] = 'atm_call'
        self.instrument_map[put_sym] = 'atm_put'

        # Fetch Historical Data for Level Hunting
        self.scalper.log(f"Fetching historical data for {underlying} and ATM options...")
        for target, symbol in self.symbols.items():
            try:
                hist = await asyncio.to_thread(tv_api.get_hist_candles, symbol, '1', 1000)
                if hist:
                    self.on_ohlcv(symbol, {'ohlcv': hist})
                    if target == 'underlying':
                        self.scalper.engine.calculate_volume_profile(None, hist)
            except Exception as e:
                logger.error(f"Error fetching historical data for {symbol}: {e}")

        # Use registry for live stream
        provider = live_stream_registry.get_primary()
        provider.set_callback(self.scalper._handle_wss_message)
        provider.start()
        provider.subscribe([underlying, call_sym, put_sym], interval="1")

        self.scalper.log(f"Subscribed via {type(provider).__name__} to {underlying}, {call_sym}, {put_sym}")

class ConfluenceEngine:
    """Identifies Zones of Interest."""
    def __init__(self, scalper):
        self.scalper = scalper
        self.underlying_levels = [] # List of prices
        self.hvn_levels = []
        self.option_levels = {} # {symbol: {'orb_h':, 'orb_l':, 'prev_15_h':, 'prev_15_l':}}
        self.pcr_history = []

    def find_levels(self, df, symbol_type='underlying'):
        """Identify Swing Highs/Lows using find_peaks."""
        if df.empty or len(df) < 20: return []

        # Highs
        highs, _ = find_peaks(df['h'].values, distance=5)
        # Lows (negative peaks)
        lows, _ = find_peaks(-df['l'].values, distance=5)

        levels = sorted(list(set(df['h'].iloc[highs].tolist() + df['l'].iloc[lows].tolist())))
        if symbol_type == 'underlying':
            self.underlying_levels = levels
        return levels

    def calculate_volume_profile(self, ticks=None, candles=None):
        """Calculate High Volume Nodes (HVN) for current and previous day."""
        if not ticks and not candles: return []

        if candles:
            # columns=['ts', 'o', 'h', 'l', 'c', 'v']
            df = pd.DataFrame(candles, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
            # For candles, we can use 'c' as price and 'v' as volume
            vp = df.groupby('c')['v'].sum().sort_values(ascending=False)
        else:
            df = pd.DataFrame(ticks)
            if 'last_price' not in df.columns or 'ltq' not in df.columns:
                return []
            vp = df.groupby('last_price')['ltq'].sum().sort_values(ascending=False)

        # Top 5 HVNs for better confluence
        self.hvn_levels = vp.head(5).index.tolist()
        return self.hvn_levels

    def update_option_levels(self, symbol, df_1m):
        """Track ORB and Previous 15-min High/Low."""
        if df_1m.empty: return

        # ORB (First 15 mins of day)
        orb_df = df_1m.iloc[:15]
        orb_h = orb_df['h'].max()
        orb_l = orb_df['l'].min()

        # Prev 15 min
        prev_15 = df_1m.iloc[-16:-1] if len(df_1m) > 16 else df_1m
        p15_h = prev_15['h'].max()
        p15_l = prev_15['l'].min()

        self.option_levels[symbol] = {
            'orb_h': orb_h, 'orb_l': orb_l,
            'p15_h': p15_h, 'p15_l': p15_l,
            'last_swing_h': df_1m['h'].iloc[-5:].max(),
            'last_swing_l': df_1m['l'].iloc[-5:].min()
        }

    def is_in_signal_zone(self, price):
        """Underlying within 0.05% of a major level."""
        psych_levels = [z['price'] for z in self.scalper.psych_data.get('zones', [])]
        major_levels = self.underlying_levels + self.hvn_levels + psych_levels
        for level in major_levels:
            if abs(price - level) / level <= 0.0005:
                return True, level
        return False, None

    def calculate_pcr(self, chain_data):
        """Calculate live PCR based on the total OI of the nearest 5 strikes."""
        if not chain_data: return 0

        spot = self.scalper.current_spot
        chain_data.sort(key=lambda x: abs(x['strike'] - spot))

        nearest_5 = chain_data[:10] # 5 strikes * 2 (call/put)
        call_oi = sum(x['oi'] for x in nearest_5 if x['option_type'] == 'call')
        put_oi = sum(x['oi'] for x in nearest_5 if x['option_type'] == 'put')

        pcr = put_oi / call_oi if call_oi > 0 else 0
        self.pcr_history.append(pcr)
        if len(self.pcr_history) > 60: self.pcr_history.pop(0)
        return pcr

    def get_oi_spurt(self, current_chain, prev_chain):
        """Monitor Change in OI for spurts."""
        spurts = {'call': 0, 'put': 0}
        for curr in current_chain:
            prev = next((x for x in prev_chain if x['strike'] == curr['strike'] and x['option_type'] == curr['option_type']), None)
            if prev:
                change = curr['oi'] - prev['oi']
                spurts[curr['option_type']] += change
        return spurts

    def get_buildup_status(self, price_change, oi_change):
        """Identify buildup type based on price and OI correlation."""
        if price_change > 0 and oi_change > 0: return "LONG_BUILDUP"
        if price_change > 0 and oi_change < 0: return "SHORT_COVERING"
        if price_change < 0 and oi_change > 0: return "SHORT_BUILDUP"
        if price_change < 0 and oi_change < 0: return "LONG_UNWINDING"
        return "NEUTRAL"

class SignalGenerator:
    """Orchestrates signal detection logic."""
    def __init__(self, scalper):
        self.scalper = scalper

    def check_signals(self):
        spot = self.scalper.current_spot
        in_zone, level = self.scalper.engine.is_in_signal_zone(spot)

        oi_levels = options_manager.get_support_resistance(self.scalper.underlying)
        sup_oi = [x['strike'] for x in oi_levels.get('support_levels', [])]
        res_oi = [x['strike'] for x in oi_levels.get('resistance_levels', [])]

        chain_res = options_manager.get_chain_with_greeks(self.scalper.underlying)
        chain_data = chain_res.get('chain', [])
        if spot == 0: spot = chain_res.get('spot_price', 0)

        pcr = 0
        if chain_data:
            pcr = self.scalper.engine.calculate_pcr(chain_data)

        spurts = {'call': 0, 'put': 0}
        if chain_data and self.scalper.prev_chain:
            spurts = self.scalper.engine.get_oi_spurt(chain_data, self.scalper.prev_chain)
        if chain_data:
            self.scalper.prev_chain = chain_data

        pcr_rising = False
        if len(self.scalper.engine.pcr_history) >= 2:
            pcr_rising = self.scalper.engine.pcr_history[-1] > self.scalper.engine.pcr_history[-2]

        price_chg = 0
        if len(self.scalper.streamer.tick_buffer) >= 2:
            price_chg = self.scalper.streamer.tick_buffer[-1]['last_price'] - self.scalper.streamer.tick_buffer[-2]['last_price']

        net_spurt = spurts['put'] - spurts['call']
        oi_status = self.scalper.engine.get_buildup_status(price_chg, net_spurt)

        # Trend indicators
        bullish_oi = (pcr_rising and spurts['put'] > spurts['call']) or (oi_status in ["LONG_BUILDUP", "SHORT_COVERING"])
        bearish_oi = (not pcr_rising and spurts['call'] > spurts['put']) or (oi_status in ["SHORT_BUILDUP", "LONG_UNWINDING"])

        # Psychology Signals Integration
        psych_signals = self.scalper.psych_data.get('signals', {})
        latest_psych = None
        if psych_signals:
            latest_ts = max(psych_signals.keys())
            # Convert to seconds if it is a datetime object
            ts_seconds = latest_ts.timestamp() if isinstance(latest_ts, datetime) else latest_ts
            if (time.time() - ts_seconds) < 300: # Last 5 mins
                latest_psych = psych_signals[latest_ts]

        if latest_psych == "SHORT_TRAP": bullish_oi = True
        if latest_psych == "LONG_TRAP": bearish_oi = True

        # Option Data
        call_sym = self.scalper.streamer.symbols.get('atm_call')
        put_sym = self.scalper.streamer.symbols.get('atm_put')
        call_levels = self.scalper.engine.option_levels.get(call_sym, {})
        put_levels = self.scalper.engine.option_levels.get(put_sym, {})
        call_tick = self.scalper.last_ticks.get('atm_call')
        put_tick = self.scalper.last_ticks.get('atm_put')
        call_vwap = self.scalper.streamer.vwap.get('atm_call', 0)
        put_vwap = self.scalper.streamer.vwap.get('atm_put', 0)

        # Confluence bits
        call_brk = call_tick['last_price'] > max(call_levels.get('last_swing_h', 0), call_vwap, call_levels.get('p15_h', 0), call_levels.get('orb_h', 0)) if call_tick and call_levels else False
        put_brk_dwn = put_tick['last_price'] < min(put_levels.get('last_swing_l', 999999), put_levels.get('p15_l', 999999), put_levels.get('orb_l', 999999)) if put_tick and put_levels else False
        put_brk = put_tick['last_price'] > max(put_levels.get('last_swing_h', 0), put_vwap, put_levels.get('p15_h', 0), put_levels.get('orb_h', 0)) if put_tick and put_levels else False
        call_brk_dwn = call_tick['last_price'] < min(call_levels.get('last_swing_l', 999999), call_levels.get('p15_l', 999999), call_levels.get('orb_l', 999999)) if call_tick and call_levels else False

        oi_conf = "BULLISH" if bullish_oi else "BEARISH" if bearish_oi else "NEUTRAL"
        if latest_psych: oi_conf += f" ({latest_psych})"

        # Confluence metrics for UI
        if self.scalper.sio and self.scalper.loop:
            oi_power = "STRONG" if abs(net_spurt) > 500000 else "MODERATE" if abs(net_spurt) > 100000 else "WEAK"

            asyncio.run_coroutine_threadsafe(
                self.scalper.sio.emit('scalper_metrics', {
                    'pcr': round(pcr, 2),
                    'oi_power': oi_power,
                    'oi_sentiment': oi_conf,
                    'oi_status': oi_status,
                    'underlying_level': level or (sup_oi[0] if sup_oi else 0),
                    'vwap': {'call': round(call_vwap, 2), 'put': round(put_vwap, 2)},
                    'oi_levels': {'support': sup_oi[:2], 'resistance': res_oi[:2]},
                    'confluence': {
                        'lvl': in_zone,
                        'pcr': pcr_rising,
                        'oi': bullish_oi or bearish_oi,
                        'opt_brk': call_brk if bullish_oi else put_brk if bearish_oi else False,
                        'inv_dwn': put_brk_dwn if bullish_oi else call_brk_dwn if bearish_oi else False
                    }
                }),
                self.scalper.loop
            )

        # Actual trade logic
        if len(self.scalper.order_manager.active_trades) > 0: return
        if not call_tick or not put_tick or not call_levels or not put_levels: return

        is_at_support = (in_zone and spot <= level * 1.0005) or any(abs(spot-s)/s < 0.0005 for s in sup_oi)
        is_brk_resistance = (in_zone and spot >= level * 0.9995) or any(abs(spot-r)/r < 0.0005 for r in res_oi)

        # Bullish Signal
        if (is_at_support or is_brk_resistance or latest_psych == "SHORT_TRAP") and bullish_oi:
            if call_brk and put_brk_dwn:
                inv_status = "PUT_BREAKDOWN"
                msg = f"[SIGNAL: CALL_BUY] [LVL: {level or spot}] [OI: {oi_conf}] [INV: {inv_status}]"
                self.scalper.log(msg)

                if self.scalper.sio and self.scalper.loop:
                    asyncio.run_coroutine_threadsafe(
                        self.scalper.sio.emit('scalper_log', {
                            'time': datetime.now().strftime('%H:%M:%S'),
                            'signal': 'CALL BUY',
                            'underlying_level': round(level or spot, 2),
                            'oi_confirmation': oi_conf,
                            'inverse_status': inv_status
                        }),
                        self.scalper.loop
                    )

                self.scalper.order_manager.execute_buy(call_sym, 'CALL', call_tick['last_price'], call_levels['last_swing_l'])

        # Bearish Signal
        elif (is_at_support or is_brk_resistance or latest_psych == "LONG_TRAP") and bearish_oi:
            if put_brk and call_brk_dwn:
                inv_status = "CALL_BREAKDOWN"
                msg = f"[SIGNAL: PUT_BUY] [LVL: {level or spot}] [OI: {oi_conf}] [INV: {inv_status}]"
                self.scalper.log(msg)

                if self.scalper.sio and self.scalper.loop:
                    asyncio.run_coroutine_threadsafe(
                        self.scalper.sio.emit('scalper_log', {
                            'time': datetime.now().strftime('%H:%M:%S'),
                            'signal': 'PUT BUY',
                            'underlying_level': round(level or spot, 2),
                            'oi_confirmation': oi_conf,
                            'inverse_status': inv_status
                        }),
                        self.scalper.loop
                    )

                self.scalper.order_manager.execute_buy(put_sym, 'PUT', put_tick['last_price'], put_levels['last_swing_l'])

class OrderManager:
    """Handles order execution and risk management."""
    def __init__(self, scalper):
        self.scalper = scalper
        self.active_trades = []
        self.trades_file = "trades.csv"
        self.risk_per_trade = 2000

    def execute_buy(self, symbol, side, entry_price, sl_level):
        jumper = 0.50
        limit_price = entry_price + jumper

        # Hard SL at 15% or Confluence Level (whichever is closer/safer)
        hard_sl = entry_price * 0.85
        final_sl = max(sl_level, hard_sl) # Don't risk more than 15%

        risk_amount = abs(entry_price - final_sl)
        if risk_amount == 0: risk_amount = entry_price * 0.10 # fallback

        quantity = int(self.risk_per_trade / risk_amount)
        if quantity == 0: quantity = 1

        trade = {
            'symbol': symbol, 'side': side, 'entry_price': entry_price,
            'limit_price': limit_price, 'sl': final_sl,
            'tp': entry_price + (risk_amount * 2.5),
            'quantity': quantity, 'entry_time': datetime.now(),
            'last_price': entry_price, 'max_price': entry_price,
            'status': 'OPEN', 'be_moved': False, 'underlying_entry': self.scalper.current_spot
        }
        self.active_trades.append(trade)
        self.scalper.log(f"ORDER SENT: BUY {side} @ {limit_price} | SL: {trade['sl']} | TP: {trade['tp']}")
        return trade

    def manage_risk(self):
        for trade in self.active_trades[:]:
            current_tick = self.scalper.last_ticks.get('atm_call' if trade['side'] == 'CALL' else 'atm_put')
            if not current_tick: continue

            price = current_tick['last_price']
            trade['last_price'] = price
            trade['max_price'] = max(trade['max_price'], price)

            if price >= trade['tp']: self._close_trade(trade, "TARGET HIT")
            elif price <= trade['sl']: self._close_trade(trade, "SL HIT")
            elif not trade['be_moved'] and (price - trade['entry_price']) / trade['entry_price'] >= 0.10:
                trade['sl'] = trade['entry_price']
                trade['be_moved'] = True
                self.scalper.log(f"RiskMgmt: Trailing SL moved to BE for {trade['side']}")

            elapsed = (datetime.now() - trade['entry_time']).total_seconds()
            if elapsed > 180:
                underlying_in_favor = (self.scalper.current_spot > trade['underlying_entry']) if trade['side'] == 'CALL' else (self.scalper.current_spot < trade['underlying_entry'])
                if underlying_in_favor and (price - trade['entry_price']) / trade['entry_price'] < 0.01:
                    self._close_trade(trade, "THETA PROTECTION")

    def _close_trade(self, trade, reason):
        trade['status'] = 'CLOSED'
        trade['exit_price'] = trade['last_price']
        trade['exit_time'] = datetime.now()
        trade['pnl'] = (trade['exit_price'] - trade['entry_price']) * trade['quantity']
        self.scalper.log(f"TRADE CLOSED: {trade['side']} @ {trade['exit_price']} | Reason: {reason} | PnL: {trade['pnl']}")
        self.log_trade(trade)
        self.active_trades.remove(trade)

    def log_trade(self, trade):
        file_exists = os.path.isfile(self.trades_file)
        try:
            with open(self.trades_file, 'a', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=[
                    'symbol', 'side', 'entry_price', 'limit_price', 'sl', 'tp',
                    'quantity', 'entry_time', 'exit_price', 'exit_time', 'status', 'pnl'
                ])
                if not file_exists: writer.writeheader()
                log_data = {k: trade.get(k) for k in writer.fieldnames}
                writer.writerow(log_data)
        except Exception as e: logger.error(f"Error logging trade: {e}")

class NSEConfluenceScalper:
    def __init__(self, underlying="NSE:NIFTY"):
        self.underlying = underlying
        self.is_running = False
        self.streamer = DataStreamer(self)
        self.engine = ConfluenceEngine(self)
        self.signal_generator = SignalGenerator(self)
        self.order_manager = OrderManager(self)
        self.psych_analyzer = MarketPsychologyAnalyzer()
        self.psych_data = {"zones": [], "signals": {}}
        self.sio = None
        self.loop = None
        self.current_spot = 0
        self.last_ticks = {}
        self.prev_chain = []

    def set_socketio(self, sio, loop):
        self.sio = sio
        self.loop = loop

    def log(self, message):
        ist = pytz.timezone('Asia/Kolkata')
        timestamp = datetime.now(ist).strftime("%H:%M:%S")
        formatted_msg = f"[{timestamp}] {message}"
        logger.info(formatted_msg)
        if self.sio and self.loop:
            asyncio.run_coroutine_threadsafe(self.sio.emit('scalper_log', {'message': formatted_msg}), self.loop)

    async def start(self):
        if self.is_running: return
        self.is_running = True
        self.log(f"Scalper Starting: {self.underlying}")
        await self.streamer.subscribe(self.underlying)
        asyncio.create_task(self._main_loop())
        asyncio.create_task(self._atm_tracking_loop())

    async def _atm_tracking_loop(self):
        """Periodically updates ATM option subscriptions."""
        while self.is_running:
            try:
                if self.current_spot > 0:
                    spot = self.current_spot
                    atm_strike = round(spot / 50) * 50
                    if "BANKNIFTY" in self.underlying:
                        atm_strike = round(spot / 100) * 100

                    # Ensure symbols are cached
                    await options_manager._refresh_wss_symbols(self.underlying)
                    call_sym = options_manager.symbol_map_cache.get(self.underlying, {}).get(f"{atm_strike}_call")
                    put_sym = options_manager.symbol_map_cache.get(self.underlying, {}).get(f"{atm_strike}_put")

                    if call_sym and put_sym:
                        current_ce = self.streamer.symbols.get('atm_call')
                        current_pe = self.streamer.symbols.get('atm_put')

                        if call_sym != current_ce or put_sym != current_pe:
                            from core.provider_registry import live_stream_registry
                            provider = live_stream_registry.get_primary()

                            # Unsubscribe old
                            to_unsub = []
                            if current_ce: to_unsub.append(current_ce)
                            if current_pe: to_unsub.append(current_pe)
                            if to_unsub: provider.unsubscribe_instrument(to_unsub, "scalper")

                            # Update map
                            if current_ce: self.streamer.instrument_map.pop(current_ce, None)
                            if current_pe: self.streamer.instrument_map.pop(current_pe, None)

                            self.streamer.symbols['atm_call'] = call_sym
                            self.streamer.symbols['atm_put'] = put_sym
                            self.streamer.instrument_map[call_sym] = 'atm_call'
                            self.streamer.instrument_map[put_sym] = 'atm_put'

                            # Subscribe new
                            provider.subscribe([call_sym, put_sym], interval="1")
                            self.log(f"ATM Switched to {atm_strike}: {call_sym}, {put_sym}")

                await asyncio.sleep(60)
            except Exception as e:
                logger.error(f"ATM tracking error: {e}")
                await asyncio.sleep(10)

    def _handle_wss_message(self, data):
        if data.get('type') == 'live_feed':
            for inst_key, tick in data.get('feeds', {}).items(): self.streamer.on_tick(inst_key, tick)
        elif data.get('type') == 'chart_update':
            self.streamer.on_ohlcv(data.get('instrumentKey'), data.get('data'))

    async def stop(self): self.is_running = False

    async def _main_loop(self):
        while self.is_running:
            try:
                self.signal_generator.check_signals()
                self.order_manager.manage_risk()
            except Exception as e: logger.error(f"Scalper Loop Error: {e}")
            await asyncio.sleep(0.5)

scalper = NSEConfluenceScalper()
