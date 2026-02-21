import pandas as pd
import datetime
from .database import get_session, ReferenceLevel, Signal, RawTick
from .config import SWING_WINDOW, CONFLUENCE_THRESHOLD

class StrategyEngine:
    def __init__(self, index_name):
        self.index_name = index_name
        self.reference_levels = {'High': None, 'Low': None}
        self.positions = []
        self.current_data = {} # instrument_key -> latest_data (tick)
        self.candle_history = {} # instrument_key -> list of last 5 candle closes

    def update_data(self, instrument_key, data):
        """Update current tick data."""
        self.current_data[instrument_key] = data

    def update_candle(self, instrument_key, candle_close):
        """Update historical candle close data for velocity and RS."""
        if instrument_key not in self.candle_history:
            self.candle_history[instrument_key] = []

        self.candle_history[instrument_key].append(candle_close)
        if len(self.candle_history[instrument_key]) > 5:
            self.candle_history[instrument_key].pop(0)

    def calculate_velocity(self, instrument_key):
        """Price Velocity: Rate of change over 3 candles."""
        prices = self.candle_history.get(instrument_key, [])
        if len(prices) < 4:
            return 0
        return (prices[-1] - prices[-4]) / 3

    def calculate_relative_strength(self, option_key, index_key):
        """Relative Strength: (Option % Change) / (Index % Change)."""
        opt_prices = self.candle_history.get(option_key, [])
        idx_prices = self.candle_history.get(index_key, [])

        if len(opt_prices) < 2 or len(idx_prices) < 2:
            return 0

        opt_change = (opt_prices[-1] - opt_prices[-2]) / opt_prices[-2] if opt_prices[-2] != 0 else 0
        idx_change = (idx_prices[-1] - idx_prices[-2]) / idx_prices[-2] if idx_prices[-2] != 0 else 0

        if idx_change == 0:
            return 0

        return opt_change / idx_change

    def identify_swing(self, candles):
        """
        Identify Significant Swings where a 'Wall' exists.
        Advanced: Hits a New High/Low and confirms with 2-candle pullback.
        """
        if len(candles) < 5:
            return None

        # Simple swing detection: local high/low in the window
        last_n = candles.tail(SWING_WINDOW)
        current_high = last_n['high'].max()
        current_low = last_n['low'].min()

        # Confirmation logic:
        # High formed: Extreme High at candle i-2, then candle i-1 and i have lower highs
        # Low formed: Extreme Low at candle i-2, then candle i-1 and i have higher lows
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
                score += 1
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

            if score >= CONFLUENCE_THRESHOLD:
                # Check Guardrails
                if not self.check_guardrails('Bullish', idx_data, ce_data, pe_data, ref_high):
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
                score += 1
                details['oi_panic'] = True

            # Metrics
            details['pe_velocity'] = self.calculate_velocity(pe_key)
            details['pe_rs'] = self.calculate_relative_strength(pe_key, idx_key)

            if idx_data.get('volume', 0) > 0:
                details['volume_active'] = True

            if score >= CONFLUENCE_THRESHOLD:
                if not self.check_guardrails('Bearish', idx_data, ce_data, pe_data, ref_low):
                    details['ce_key'] = ce_key
                    details['pe_key'] = pe_key
                    return Signal(index_name=self.index_name, side='BUY_PE', index_price=idx_data['ltp'],
                                  option_price=pe_data['ltp'], confluence_score=score, details=details)

        return None

    def check_exit_condition(self, position, idx_data, ce_data, pe_data):
        """
        Exit when the Opposite Option stops making new lows and its OI starts falling.
        """
        if position.side == 'BUY_CE':
            # Exit if PE OI starts falling (sellers finished)
            if pe_data.get('oi_delta', 0) < 0:
                 return True
            # Exit if CE price drops 20% (Hard SL)
            entry_price = getattr(position, 'entry_price', 0)
            if ce_data['ltp'] < entry_price * 0.8:
                return True
            # SL: Symmetry break
            ref_high = self.reference_levels.get('High')
            if ref_high and idx_data['ltp'] > ref_high['index_price'] and ce_data['ltp'] < ref_high['ce_price']:
                return True

        elif position.side == 'BUY_PE':
            if ce_data.get('oi_delta', 0) < 0:
                return True
            entry_price = getattr(position, 'entry_price', 0)
            if pe_data['ltp'] < entry_price * 0.8:
                return True
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

    def save_reference_level(self, level_type, index_price, ce_price, pe_price, ce_key, pe_key, timestamp=None):
        session = get_session()
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
