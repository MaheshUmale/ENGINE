import pandas as pd
import datetime
from .database import get_session, ReferenceLevel, Signal, RawTick
from .config import SWING_WINDOW, CONFLUENCE_THRESHOLD

class StrategyEngine:
    def __init__(self, index_name):
        self.index_name = index_name
        self.reference_levels = {'High': None, 'Low': None}
        self.positions = []
        self.current_data = {} # instrument_key -> latest_data

    def update_data(self, instrument_key, data):
        self.current_data[instrument_key] = data

    def identify_swing(self, candles):
        """
        Identify Significant Swings where a 'Wall' exists.
        Index hits a New High (or Low) and pulls back.
        """
        if len(candles) < 3:
            return None

        # Simple swing detection: local high/low in the window
        last_n = candles.tail(SWING_WINDOW)
        current_high = last_n['high'].max()
        current_low = last_n['low'].min()

        # If current candle is a pullback from the high
        last_candle = candles.iloc[-1]

        # Bullish Wall Identification
        if last_candle['high'] < current_high and candles.iloc[-2]['high'] == current_high:
            return {'type': 'High', 'price': current_high}

        # Bearish Wall Identification
        if last_candle['low'] > current_low and candles.iloc[-2]['low'] == current_low:
            return {'type': 'Low', 'price': current_low}

        return None

    def check_decay_filter(self, current_index_price, current_ce_price, ref_level):
        """
        Phase II: The Pullback & Decay Filter (Anti-Theta)
        If Index returns to Ref_Price_Index but Current_Price_CE is higher than Ref_Price_CE
        """
        if not ref_level or ref_level.type != 'High':
            return False

        if current_index_price >= ref_level.index_price:
            if current_ce_price > ref_level.ce_price:
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
            if idx_data['ltp'] > ref_high.index_price:
                score += 1
                details['index_break'] = True

            # 2. Symmetry (CE): Current_Price_CE crosses above Ref_Price_CE
            if ce_data['ltp'] > ref_high.ce_price:
                score += 1
                details['ce_break'] = True

            # 3. Symmetry (PE Breakdown): Current_Price_PE must break below local support/low
            if pe_data['ltp'] < ref_high.pe_price:
                score += 1
                details['pe_breakdown'] = True

            # 4. The Panic (OI): ATM Call OI decreasing, ATM Put OI increasing
            # This requires historical OI change, which we should get from data_provider or ticks
            # For now, let's assume we have it in the data dictionary
            if ce_data.get('oi_delta', 0) < 0 and pe_data.get('oi_delta', 0) > 0:
                score += 1
                details['oi_panic'] = True

            # Decay Filter Bonus
            if self.check_decay_filter(idx_data['ltp'], ce_data['ltp'], ref_high):
                details['decay_filter'] = True
                # Could increase conviction score or position size

            if score >= CONFLUENCE_THRESHOLD:
                # Check Guardrails
                if not self.check_guardrails('Bullish', idx_data, ce_data, pe_data, ref_high):
                    return Signal(index_name=self.index_name, side='BUY_CE', index_price=idx_data['ltp'],
                                  option_price=ce_data['ltp'], confluence_score=score, details=details)

        # --- Bearish Trigger (Put Buy) ---
        if ref_low:
            score = 0
            details = {}

            if idx_data['ltp'] < ref_low.index_price:
                score += 1
                details['index_break'] = True

            if pe_data['ltp'] > ref_low.pe_price:
                score += 1
                details['pe_break'] = True

            if ce_data['ltp'] < ref_low.ce_price:
                score += 1
                details['ce_breakdown'] = True

            if pe_data.get('oi_delta', 0) < 0 and ce_data.get('oi_delta', 0) > 0:
                score += 1
                details['oi_panic'] = True

            if score >= CONFLUENCE_THRESHOLD:
                if not self.check_guardrails('Bearish', idx_data, ce_data, pe_data, ref_low):
                    return Signal(index_name=self.index_name, side='BUY_PE', index_price=idx_data['ltp'],
                                  option_price=pe_data['ltp'], confluence_score=score, details=details)

        return None

    def check_exit_condition(self, position, idx_data, ce_data, pe_data):
        """
        Exit when the Opposite Option stops making new lows and its OI starts falling.
        """
        if position.side == 'BUY_CE':
            # In a Call, exit when the Put (PE) stops falling and starts making a "Higher High"
            # and PE OI starts falling (sellers of PE are finished)
            if pe_data['ltp'] > pe_data.get('low_so_far', 0) and pe_data.get('oi_delta', 0) < 0:
                return True
            # Symmetry break: Index high but CE starts falling
            if idx_data['ltp'] >= idx_data.get('high_so_far', 0) and ce_data['ltp'] < ce_data.get('prev_2m_low', 0):
                return True

        elif position.side == 'BUY_PE':
            if ce_data['ltp'] > ce_data.get('low_so_far', 0) and ce_data.get('oi_delta', 0) < 0:
                return True
            if idx_data['ltp'] <= idx_data.get('low_so_far', 0) and pe_data['ltp'] < pe_data.get('prev_2m_low', 0):
                return True

        return False

    def check_guardrails(self, side, idx_data, ce_data, pe_data, ref_level):
        """
        Phase IV: The 'Trap' Guardrails
        Returns True if a trap is detected (should VOID trade)
        """
        if side == 'Bullish':
            if idx_data['ltp'] > ref_level.index_price and ce_data['ltp'] <= ref_level.ce_price:
                return True
            if ce_data.get('oi_delta', 0) > 0:
                return True
            if pe_data['ltp'] >= ref_level.pe_price:
                return True
        elif side == 'Bearish':
            if idx_data['ltp'] < ref_level.index_price and pe_data['ltp'] <= ref_level.pe_price:
                return True
            if pe_data.get('oi_delta', 0) > 0:
                return True
            if ce_data['ltp'] >= ref_level.ce_price:
                return True

        return False

    def save_reference_level(self, level_type, index_price, ce_price, pe_price, ce_key, pe_key):
        session = get_session()
        ref = ReferenceLevel(
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
        self.reference_levels[level_type] = ref
        session.close()
