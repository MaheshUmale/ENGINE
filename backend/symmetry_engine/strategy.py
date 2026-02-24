import pandas as pd
import datetime
from .database import get_session, ReferenceLevel, Signal, RawTick
from .config import SWING_WINDOW, CONFLUENCE_THRESHOLD

class StrategyEngine:
    def __init__(self, index_name, session_factory=None):
        self.index_name = index_name
        self.get_session = session_factory or get_session
        self.reference_levels = {'High': None, 'Low': None}
        self.positions = []
        self.current_data = {} # instrument_key -> latest_data (tick)
        self.candle_history = {} # instrument_key -> list of last 20 candle dicts
        self.candle_history_5m = {} # instrument_key -> list of last 10 5m candles
        self.trailing_sl = {} # index_name -> current_sl_price

        # Strategy Parameters (can be overridden)
        self.swing_window = SWING_WINDOW
        self.confluence_threshold = CONFLUENCE_THRESHOLD
        self.atr_multiplier = 1.5 # Default multiplier for SL

    def update_data(self, instrument_key, data):
        """Update current tick data."""
        self.current_data[instrument_key] = data

    def update_candle(self, instrument_key, candle, interval=1):
        """Update historical candle data."""
        target_history = self.candle_history if interval == 1 else self.candle_history_5m
        limit = 20 if interval == 1 else 10

        if instrument_key not in target_history:
            target_history[instrument_key] = []

        if isinstance(candle, float):
            candle = {'open': candle, 'high': candle, 'low': candle, 'close': candle}

        if 'instrument_key' not in candle:
            candle['instrument_key'] = instrument_key

        target_history[instrument_key].append(candle)
        if len(target_history[instrument_key]) > limit:
            target_history[instrument_key].pop(0)

    def calculate_atr(self, instrument_key=None, period=14, history=None):
        """Calculate Average True Range."""
        if history is None:
            history = self.candle_history.get(instrument_key, [])

        if not history or len(history) < 2:
            return 0

        # Adjust period if history is short
        effective_period = min(period, len(history) - 1)

        tr_list = []
        for i in range(1, len(history)):
            h = history[i]['high']
            l = history[i]['low']
            pc = history[i-1]['close']
            tr = max(h - l, abs(h - pc), abs(l - pc))
            tr_list.append(tr)

        return sum(tr_list[-effective_period:]) / effective_period

    def calculate_velocity(self, instrument_key):
        """Price Velocity: Rate of change over 3 candles."""
        history = self.candle_history.get(instrument_key, [])
        if len(history) < 4:
            return 0
        return (history[-1]['close'] - history[-4]['close']) / 3

    def calculate_relative_strength(self, option_key, index_key):
        """Relative Strength: (Option % Change) / (Index % Change)."""
        opt_history = self.candle_history.get(option_key, [])
        idx_history = self.candle_history.get(index_key, [])

        if len(opt_history) < 2 or len(idx_history) < 2:
            return 0

        opt_prices = [c['close'] for c in opt_history]
        idx_prices = [c['close'] for c in idx_history]

        opt_change = (opt_prices[-1] - opt_prices[-2]) / opt_prices[-2] if opt_prices[-2] != 0 else 0
        idx_change = (idx_prices[-1] - idx_prices[-2]) / idx_prices[-2] if idx_prices[-2] != 0 else 0

        if idx_change == 0:
            return 0

        return opt_change / idx_change

    def identify_swing(self, candles):
        """
        Identify Significant Swings where a 'Wall' exists.
        Enhanced: Hits a New High/Low and confirms with 2-candle pullback + ATR filter.
        """
        if isinstance(candles, list):
            if len(candles) < 10: return None

            # Use pandas for consistency if window is large or complex logic is needed,
            # but for 20 candles, manual is fine. Let's stick to consistent logic.
            df = pd.DataFrame(candles)
            return self.identify_swing(df)

        if len(candles) < 10:
            return None

        # Calculate ATR for threshold (optional but recommended)
        atr = self.calculate_atr(candles.iloc[0].get('instrument_key', ''))
        atr_threshold = atr * 0.5 if atr > 0 else 0

        # Simple swing detection: local high/low in the window
        last_n = candles.tail(self.swing_window)
        current_high = last_n['high'].max()
        current_low = last_n['low'].min()

        # Check if the move into the high/low was significant relative to ATR
        window_start_price = last_n.iloc[0]['close']
        if abs(current_high - window_start_price) < atr_threshold and abs(current_low - window_start_price) < atr_threshold:
            return None

        # Confirmation logic:
        # High formed: Extreme High at candle i-2, then candle i-1 and i have lower highs
        c = candles.iloc[-1]
        p = candles.iloc[-2]
        pp = candles.iloc[-3]

        # Bullish Wall Identification (Resistance)
        if pp['high'] == current_high:
            if p['high'] < pp['high'] and c['high'] < p['high']:
                # Pullback confirmed by 2 consecutive lower highs
                return {'type': 'High', 'price': current_high}

        # Bearish Wall Identification (Support)
        if pp['low'] == current_low:
            if p['low'] > pp['low'] and c['low'] > p['low']:
                # Pullback confirmed by 2 consecutive higher lows
                return {'type': 'Low', 'price': current_low}

        return None

    def check_decay_filter(self, current_index_price, current_ce_price, ref_level):
        """
        Phase II: The Pullback & Decay Filter (Anti-Theta)
        If Index returns to Ref_Price_Index but Current_Price_CE is higher than Ref_Price_CE
        """
        if not ref_level or ref_level['type'] != 'High':
            return False

        if current_index_price >= ref_level['index_price']:
            if current_ce_price > ref_level['ce_price']:
                return True # Bullish Divergence
        return False

    def generate_signals(self, instruments):
        """
        Phase III: The Symmetry-Panic Trigger
        """
        idx_key = instruments['index']
        ce_key = instruments['ce']
        pe_key = instruments['pe']

        if any(k not in self.current_data for k in [idx_key, ce_key, pe_key]):
            return None

        idx_data = self.current_data[idx_key]
        ce_data = self.current_data[ce_key]
        pe_data = self.current_data[pe_key]

        ref_high = self.reference_levels['High']
        ref_low = self.reference_levels['Low']

        # --- Bullish Trigger (Call Buy) ---
        if ref_high:
            score = 0
            details = {}

            # 1. Index: Crosses above Ref_Price_Index
            if idx_data['ltp'] > ref_high['index_price']:
                score += 1
                details['index_break'] = True

            # 2. Symmetry (CE): Current_Price_CE crosses above Ref_Price_CE
            if ce_data['ltp'] > ref_high['ce_price']:
                score += 1
                details['ce_break'] = True

            # 3. Symmetry (PE Breakdown): Current_Price_PE must break below local support/low
            if pe_data['ltp'] < ref_high['pe_price']:
                score += 1
                details['pe_breakdown'] = True

            # 4. The Panic (OI): ATM Call OI decreasing, ATM Put OI increasing
            details['ce_oi'] = float(ce_data.get('oi', 0))
            details['ce_oi_delta'] = float(ce_data.get('oi_delta', 0))
            details['pe_oi'] = float(pe_data.get('oi', 0))
            details['pe_oi_delta'] = float(pe_data.get('oi_delta', 0))

            if ce_data.get('oi_delta', 0) < 0 and pe_data.get('oi_delta', 0) > 0:
                # Weighted Score: OI Panic is a high-conviction signal
                score += 2
                details['oi_panic'] = True

            # Calculate and log metrics
            details['ce_velocity'] = self.calculate_velocity(ce_key)
            details['ce_rs'] = self.calculate_relative_strength(ce_key, idx_key)

            # Decay Filter Bonus (Anti-Theta)
            if self.check_decay_filter(idx_data['ltp'], ce_data['ltp'], ref_high):
                details['decay_filter'] = True
                # Boost score if decay filter passes even if other conditions are marginal
                score += 1

            # Volume Proxy check (Optional but adds conviction)
            if idx_data.get('volume', 0) > 0:
                details['volume_active'] = True

            if score >= self.confluence_threshold:
                # Log attempt
                print(f"SIGNAL ATTEMPT: Bullish signal for {self.index_name} with score {score}")
                # Check MTF Confirmation
                if not self.check_mtf_confirmation('Bullish', idx_key):
                    print(f"SIGNAL REJECTED: Bullish MTF Confirmation Failed for {self.index_name}")
                    return None

                # Check Guardrails
                if self.check_guardrails('Bullish', idx_data, ce_data, pe_data, ref_high):
                    print(f"SIGNAL REJECTED: Bullish Guardrails (Trap) Detected for {self.index_name}")
                    return None

                self.reset_trailing_sl()
                details['ce_key'] = ce_key
                details['pe_key'] = pe_key
                return Signal(index_name=self.index_name, side='BUY_CE', index_price=idx_data['ltp'],
                                option_price=ce_data['ltp'], confluence_score=score, details=details)

        # --- Bearish Trigger (Put Buy) ---
        if ref_low:
            score = 0
            details = {}

            if idx_data['ltp'] < ref_low['index_price']:
                score += 1
                details['index_break'] = True
            else:
                # Log why score might be low
                pass

            if pe_data['ltp'] > ref_low['pe_price']:
                score += 1
                details['pe_break'] = True

            if ce_data['ltp'] < ref_low['ce_price']:
                score += 1
                details['ce_breakdown'] = True

            details['ce_oi'] = float(ce_data.get('oi', 0))
            details['ce_oi_delta'] = float(ce_data.get('oi_delta', 0))
            details['pe_oi'] = float(pe_data.get('oi', 0))
            details['pe_oi_delta'] = float(pe_data.get('oi_delta', 0))

            if pe_data.get('oi_delta', 0) < 0 and ce_data.get('oi_delta', 0) > 0:
                # Weighted Score
                score += 2
                details['oi_panic'] = True

            # Metrics
            details['pe_velocity'] = self.calculate_velocity(pe_key)
            details['pe_rs'] = self.calculate_relative_strength(pe_key, idx_key)

            if idx_data.get('volume', 0) > 0:
                details['volume_active'] = True

            if score >= self.confluence_threshold:
                # Check MTF Confirmation
                if not self.check_mtf_confirmation('Bearish', idx_key):
                    print(f"SIGNAL REJECTED: Bearish MTF Confirmation Failed for {self.index_name}")
                    return None

                if self.check_guardrails('Bearish', idx_data, ce_data, pe_data, ref_low):
                    print(f"SIGNAL REJECTED: Bearish Guardrails (Trap) Detected for {self.index_name}")
                    return None

                self.reset_trailing_sl()
                details['ce_key'] = ce_key
                details['pe_key'] = pe_key
                return Signal(index_name=self.index_name, side='BUY_PE', index_price=idx_data['ltp'],
                                option_price=pe_data['ltp'], confluence_score=score, details=details)

        return None

    def check_exit_condition(self, position, idx_data, ce_data, pe_data):
        """
        Exit when the Opposite Option stops making new lows and its OI starts falling.
        Includes ATR-based dynamic trailing stop loss.
        """
        from .config import SL_TRAILING
        side = position.side
        active_opt_data = ce_data if side == 'BUY_CE' else pe_data
        opp_opt_data = pe_data if side == 'BUY_CE' else ce_data
        entry_price = getattr(position, 'entry_price', 0)

        # 1. ATR-based Trailing SL
        if SL_TRAILING:
            # Calculate ATR for the active option
            opt_key = getattr(position, 'ce_key' if side == 'BUY_CE' else 'pe_key', None)
            atr = self.calculate_atr(opt_key) if opt_key else 0
            if atr > 0:
                # Initialize or update trailing SL
                if not self.trailing_sl.get(self.index_name):
                    self.trailing_sl[self.index_name] = entry_price - (self.atr_multiplier * atr)
                    print(f"SL INITIALIZED for {self.index_name} at {self.trailing_sl[self.index_name]:.2f} (ATR: {atr:.2f})")

                # Update trailing SL (only moves up)
                new_sl = active_opt_data['ltp'] - (self.atr_multiplier * atr)
                if new_sl > self.trailing_sl[self.index_name]:
                    self.trailing_sl[self.index_name] = new_sl

                # Check SL hit
                if active_opt_data['ltp'] < self.trailing_sl[self.index_name]:
                    return True

                # Profit-Locked Aggressive Trailing
                # If profit > 3x ATR, lock in at least 1x ATR profit
                if active_opt_data['ltp'] > entry_price + (3 * atr):
                    locked_sl = entry_price + (1 * atr)
                    if locked_sl > self.trailing_sl[self.index_name]:
                        self.trailing_sl[self.index_name] = locked_sl

        # 2. Strategy Exits
        # Exit if Opposite Option OI starts falling (sellers finished)
        if opp_opt_data.get('oi_delta', 0) < 0:
                return True

        # 3. Hard Stop (20%) if ATR is not yet calculated
        if active_opt_data['ltp'] < entry_price * 0.8:
            return True

        # 4. SL: Symmetry break
        if side == 'BUY_CE':
            ref_high = self.reference_levels.get('High')
            if ref_high and idx_data['ltp'] > ref_high['index_price'] and ce_data['ltp'] < ref_high['ce_price']:
                return True
        else:
            ref_low = self.reference_levels.get('Low')
            if ref_low and idx_data['ltp'] < ref_low['index_price'] and pe_data['ltp'] < ref_low['pe_price']:
                return True

        return False

    def check_guardrails(self, side, idx_data, ce_data, pe_data, ref_level):
        """
        Phase IV: The 'Trap' Guardrails
        Returns True if a trap is detected (should VOID trade)
        """
        if side == 'Bullish':
            if idx_data['ltp'] > ref_level['index_price'] and ce_data['ltp'] <= ref_level['ce_price']:
                return True
            if ce_data.get('oi_delta', 0) > 0:
                return True
            if pe_data['ltp'] >= ref_level['pe_price']:
                return True
        elif side == 'Bearish':
            if idx_data['ltp'] < ref_level['index_price'] and pe_data['ltp'] <= ref_level['pe_price']:
                return True
            if pe_data.get('oi_delta', 0) > 0:
                return True
            if ce_data['ltp'] >= ref_level['ce_price']:
                return True

        return False

    def reset_trailing_sl(self):
        self.trailing_sl[self.index_name] = 0

    def check_mtf_confirmation(self, side, idx_key):
        """Check if 5m trend confirms the 1m signal."""
        history_5m = self.candle_history_5m.get(idx_key, [])
        if not history_5m:
            return True # Assume OK if no data

        last_5m = history_5m[-1]
        current_price = self.current_data[idx_key]['ltp']

        if side == 'Bullish':
            # Bullish: Current price > 5m Open AND 5m Close > previous 5m High (optional)
            return current_price > last_5m['open']
        elif side == 'Bearish':
            # Bearish: Current price < 5m Open
            return current_price < last_5m['open']

        return True

    def get_trend_state(self, side):
        """
        Returns True if the current index trend is in sync with the requested side.
        Used for Multi-Index Sync enhancement.
        """
        # We need the index key from INDICES, but StrategyEngine doesn't have it directly.
        # However, we can find it in self.current_data if we know the index_name.
        # Actually, let's assume the index key is in current_data.
        # A better way is to pass the index_key or find it.
        from .config import INDICES
        idx_key = INDICES[self.index_name]['index_key']

        if idx_key not in self.current_data:
            return True # Neutral if no data

        ltp = self.current_data[idx_key]['ltp']

        if side == 'BUY_CE':
            ref = self.reference_levels.get('High')
            if ref:
                return ltp > ref['index_price']
            hist = self.candle_history.get(idx_key)
            if hist:
                return ltp > hist[0]['open']
            return True

        elif side == 'BUY_PE':
            ref = self.reference_levels.get('Low')
            if ref:
                return ltp < ref['index_price']
            hist = self.candle_history.get(idx_key)
            if hist:
                return ltp < hist[0]['open']
            return True

        return True

    def save_reference_level(self, level_type, index_price, ce_price, pe_price, ce_key, pe_key, timestamp=None):
        session = self.get_session()
        ref = ReferenceLevel(
            timestamp=timestamp if timestamp else datetime.datetime.utcnow(),
            index_name=self.index_name,
            type=level_type,
            index_price=index_price,
            ce_price=ce_price,
            pe_price=pe_price,
            instrument_ce=ce_key,
            instrument_pe=pe_key
        )
        session.add(ref)
        session.commit()

        # Store as a plain dict to avoid DetachedInstanceError
        self.reference_levels[level_type] = {
            'index_price': index_price,
            'ce_price': ce_price,
            'pe_price': pe_price,
            'type': level_type
        }
        session.close()
