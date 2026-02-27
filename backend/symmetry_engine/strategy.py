import pandas as pd
import datetime
from .database import get_session, ReferenceLevel, Signal
from config import (
    SYMMETRY_SWING_WINDOW as SWING_WINDOW,
    SYMMETRY_CONFLUENCE_THRESHOLD as CONFLUENCE_THRESHOLD,
    SYMMETRY_INDICES as INDICES,
    SYMMETRY_SL_TRAILING as SL_TRAILING
)

class StrategyEngine:
    """
    Core engine for the 'Symmetry Panic' strategy.

    This engine implements a multi-stream analysis (Index + Call Option + Put Option)
    to identify high-probability scalping opportunities based on market structural
    failures and rapid shifts in Open Interest (OI).

    The strategy consists of 4 main phases:
    1. Structural Identification: Finding a 'Wall' (Swing High/Low).
    2. Decay Filter: Detecting divergence between Option price and Index price.
    3. Confluence Trigger: The Triple-Stream Symmetry and OI Panic verification.
    4. Guardrails: Protecting against traps and liquidity gaps.
    """
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
            return 1.0

        opt_prices = [c['close'] for c in opt_history]
        idx_prices = [c['close'] for c in idx_history]

        # Magnitude of move
        opt_change = abs(opt_prices[-1] - opt_prices[-2]) / opt_prices[-2] if opt_prices[-2] != 0 else 0
        idx_change = abs(idx_prices[-1] - idx_prices[-2]) / idx_prices[-2] if idx_prices[-2] != 0 else 0

        if idx_change < 0.00005: # Near zero index change
            return 1.2 if opt_change > 0.001 else 1.0

        return opt_change / idx_change

    def identify_swing(self, candles):
        """
        Identify Significant Swings where a 'Wall' exists.

        The 'Wall' is a structural support or resistance level identified after
        a significant move and a subsequent pullback. This forms the baseline
        for symmetry detection.

        Expert Optimization:
        1. Uses a custom window (default 15) for structural relevance.
        2. Requires move magnitude > 1.2 * ATR to filter noise and focus on intent.
        3. Requires 3-candle pullback for stronger confirmation that the peak/trough
           is indeed a 'Wall' and not just a minor pause.
        """
        window = getattr(self, 'swing_window', 15)
        if isinstance(candles, list):
            if len(candles) < window: return None
            df = pd.DataFrame(candles)
            return self.identify_swing(df)

        if len(candles) < window:
            return None

        # Calculate ATR for the index
        atr = self.calculate_atr(history=candles.to_dict('records'))
        # High threshold for 'Expert' scalping: Move must be significant
        atr_threshold = atr * 1.2 if atr > 0 else 5.0

        # Structural high/low in the custom window
        last_n = candles.tail(window)
        current_high = last_n['high'].max()
        current_low = last_n['low'].min()

        # Phase I Filter: Magnitude check
        window_start_price = last_n.iloc[0]['open']
        if abs(current_high - window_start_price) < atr_threshold and abs(current_low - window_start_price) < atr_threshold:
            return None

        # Phase II Filter: Confirmation logic (3-candle pullback)
        c = candles.iloc[-1]
        p = candles.iloc[-2]
        pp = candles.iloc[-3]
        ppp = candles.iloc[-4]

        # Bullish Wall Identification (Resistance)
        # We look for a high followed by 3 lower highs.
        # The peak is expected at ppp (4th last candle).
        if ppp['high'] == current_high:
            # Check if the subsequent 3 candles (pp, p, c) all have lower highs
            if p['high'] < ppp['high'] and c['high'] < p['high'] and pp['high'] < ppp['high']:
                return {'type': 'High', 'price': current_high}

        # Bearish Wall Identification (Support)
        # We look for a low followed by 3 higher lows.
        # The trough is expected at ppp (4th last candle).
        if ppp['low'] == current_low:
            # Check if the subsequent 3 candles (pp, p, c) all have higher lows
            if p['low'] > ppp['low'] and c['low'] > p['low'] and pp['low'] > ppp['low']:
                return {'type': 'Low', 'price': current_low}

        return None

    def check_decay_filter(self, current_index_price, current_option_price, ref_level):
        """
        Phase II: The Pullback & Decay Filter (Anti-Theta)
        Symmetry Panic: If Index returns to Ref_Price but Option price is BETTER than at Ref_Price.
        """
        if not ref_level:
            return False

        if ref_level['type'] == 'High':
            # Bullish: Index back near high, CE should be higher than it was at high
            if current_index_price >= ref_level['index_price'] - 2:
                if current_option_price > ref_level['ce_price']:
                    return True
        elif ref_level['type'] == 'Low':
            # Bearish: Index back near low, PE should be higher than it was at low
            if current_index_price <= ref_level['index_price'] + 2:
                if current_option_price > ref_level['pe_price']:
                    return True
        return False

    def calculate_ema(self, instrument_key, period=20, interval=5):
        """Calculates Exponential Moving Average for trend filtering."""
        history = self.candle_history_5m.get(instrument_key, []) if interval == 5 else self.candle_history.get(instrument_key, [])
        if len(history) < period:
            return 0

        prices = [c['close'] for c in history]
        return pd.Series(prices).ewm(span=period, adjust=False).mean().iloc[-1]

    def generate_signals(self, instruments):
        """
        Phase III: The Symmetry-Panic Trigger (Expert Optimized)
        Optimizations:
        1. 5m EMA 20 Trend Filter: Only Buy CE if Price > 5m EMA.
        2. Relative Strength Filter: Options must be outperforming the index.
        3. Panic Weighting: OI Panic is mandatory for high-probability scalps.
        """
        idx_key = instruments['index']
        ce_key = instruments['ce']
        pe_key = instruments['pe']

        if any(k not in self.current_data for k in [idx_key, ce_key, pe_key]):
            return None

        idx_data = self.current_data[idx_key]
        ce_data = self.current_data[ce_key]
        pe_data = self.current_data[pe_key]
        current_idx_price = idx_data['ltp']

        # --- TREND FILTER ---
        ema_5m = self.calculate_ema(idx_key, period=20, interval=5)

        # Check Bullish Signal
        bull_sig = self._process_signal_side('Bullish', instruments, idx_data, ce_data, pe_data, ema_5m)
        if bull_sig: return bull_sig

        # Check Bearish Signal
        bear_sig = self._process_signal_side('Bearish', instruments, idx_data, ce_data, pe_data, ema_5m)
        if bear_sig: return bear_sig

        return None

    def _process_signal_side(self, side, instruments, idx_data, ce_data, pe_data, ema_5m):
        """
        Helper to process signal logic for a specific side (Bullish/Bearish).

        This method implements the core 'Triple-Stream Symmetry' logic:
        1. Multi-Timeframe Trend Filter (5m EMA)
        2. Reference Level (The Wall) Breakout/Breakdown
        3. Option Price Symmetry (CE vs PE price action)
        4. Relative Strength Analysis
        5. OI Panic detection (Short Covering)
        6. Decay Divergence Filter
        7. Trap Guardrails

        Args:
            side: 'Bullish' or 'Bearish'
            instruments: Dict of instrument keys (index, ce, pe)
            idx_data: Latest tick data for index
            ce_data: Latest tick data for CE
            pe_data: Latest tick data for PE
            ema_5m: Current 5m EMA value for the index

        Returns:
            Signal object if all conditions are met, else None
        """
        is_bull = side == 'Bullish'
        ref_level = self.reference_levels['High'] if is_bull else self.reference_levels['Low']
        if not ref_level: return None

        current_idx_price = idx_data['ltp']
        active_opt_key = instruments['ce'] if is_bull else instruments['pe']
        opp_opt_key = instruments['pe'] if is_bull else instruments['ce']
        active_opt_data = ce_data if is_bull else pe_data
        opp_opt_data = pe_data if is_bull else ce_data

        # Trend Alignment: Only Buy CE if in 5m uptrend, PE if in 5m downtrend
        if ema_5m > 0:
            if is_bull and current_idx_price < ema_5m: return None
            if not is_bull and current_idx_price > ema_5m: return None

        score = 0
        details = {}

        # 1. Index Breakout/Breakdown
        if (is_bull and current_idx_price > ref_level['index_price']) or \
           (not is_bull and current_idx_price < ref_level['index_price']):
            score += 1
            details['index_break'] = True

        # 2. Symmetry (Active Option Breakout)
        ref_opt_price = ref_level['ce_price'] if is_bull else ref_level['pe_price']
        if active_opt_data['ltp'] > ref_opt_price:
            score += 1
            details['active_opt_break'] = True

        # 3. Symmetry (Opposite Option Breakdown)
        ref_opp_price = ref_level['pe_price'] if is_bull else ref_level['ce_price']
        if opp_opt_data['ltp'] < ref_opp_price:
            score += 1
            details['opp_opt_breakdown'] = True

        # 4. Mandatory Metric: Relative Strength
        rs = self.calculate_relative_strength(active_opt_key, instruments['index'])
        details['rs'] = rs
        if rs > 1.2:
            score += 1
            details['strong_rs'] = True

        # 5. The Panic (OI) - CRITICAL WEIGHTING
        active_oi_delta = float(active_opt_data.get('oi_delta', 0))
        opp_oi_delta = float(opp_opt_data.get('oi_delta', 0))

        if active_oi_delta < 0: # Sellers exiting (Short Covering in CE or Long Unwinding in PE)
            score += 2
            details['oi_panic'] = True

        if opp_oi_delta > 0: # Buyers entering opposite side
            score += 1
            details['opposite_writing'] = True

        # 6. Decay Filter
        if self.check_decay_filter(current_idx_price, active_opt_data['ltp'], ref_level):
            score += 1
            details['decay_filter'] = True

        # Confluence Logic
        has_oi_data = float(active_opt_data.get('oi', 0)) > 0 or abs(active_oi_delta) > 0
        threshold = self.confluence_threshold
        is_valid = (score >= threshold and details.get('oi_panic')) if has_oi_data else (score >= threshold - 1)

        if is_valid:
            if self.check_guardrails(side, idx_data, ce_data, pe_data, ref_level):
                return None

            details['ce_key'] = instruments['ce']
            details['pe_key'] = instruments['pe']
            return Signal(index_name=self.index_name, side='BUY_CE' if is_bull else 'BUY_PE',
                          index_price=current_idx_price, option_price=active_opt_data['ltp'],
                          confluence_score=score, details=details)
        return None

    def check_exit_condition(self, position, idx_data, ce_data, pe_data):
        """
        Exit when the Opposite Option stops making new lows and its OI starts falling.
        Includes ATR-based dynamic trailing stop loss.
        """
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
                current_sl = self.trailing_sl.get(self.index_name)
                if current_sl is None or current_sl == 0:
                    self.trailing_sl[self.index_name] = entry_price - (self.atr_multiplier * atr)
                    print(f"SL INITIALIZED for {self.index_name} at {self.trailing_sl[self.index_name]:.2f} (ATR: {atr:.2f})")
                    current_sl = self.trailing_sl[self.index_name]

                # Update trailing SL (only moves up)
                new_sl = active_opt_data['ltp'] - (self.atr_multiplier * atr)
                if new_sl > current_sl:
                    self.trailing_sl[self.index_name] = new_sl
                    current_sl = new_sl

                # Check SL hit
                if active_opt_data['ltp'] < current_sl:
                    return True

                # Profit-Locked Aggressive Trailing
                # If profit > 3x ATR, lock in at least 1x ATR profit
                if active_opt_data['ltp'] > entry_price + (3 * atr):
                    locked_sl = entry_price + (1 * atr)
                    if locked_sl > current_sl:
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
        self.trailing_sl[self.index_name] = None

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
            timestamp=timestamp if timestamp else datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None),
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
