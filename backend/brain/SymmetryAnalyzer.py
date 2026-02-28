import pandas as pd
import numpy as np
from datetime import datetime
import logging
from core.utils import safe_int, safe_float

logger = logging.getLogger(__name__)

class SymmetryAnalyzer:
    """
    Implements the Triple-Stream Symmetry & Panic Strategy (inspired by MaheshUmale/ENGINE).

    This strategy monitors three data streams concurrently on a 1-minute timeframe:
    1. Primary: Index Spot (e.g., NIFTY 50)
    2. Secondary A: ATM Call (CE)
    3. Secondary B: ATM Put (PE)

    The core logic focuses on the shift from a 'Wall' (Seller Resistance/Support)
    to a 'Void' (Short Covering) by using the Index as the map and the Options as the truth.

    Phases:
    - Phase I: Structural Identification - Identify swing highs/lows in the Index.
    - Phase II: Pullback & Decay Filter - Monitor for bullish divergence in option prices.
    - Phase III: Triple-Symmetry Execution - Trigger BUY when Index, CE, and PE align.
    - Phase IV: Guardrails - Prevent entry during absorption or fake breakouts.
    """
    def __init__(self, underlying="NSE:NIFTY"):
        """
        Initialize the analyzer for a specific underlying.

        Args:
            underlying (str): The symbol of the index (e.g., 'NSE:NIFTY').
        """
        self.underlying = underlying
        self.reference_levels = {'High': None, 'Low': None}
        self.swing_window = 15
        self.confluence_threshold = 3

    def identify_swing(self, subset_df):
        """
        Identify Significant Swings (Walls) where the market pivoted.

        A 'Wall' is a structural support or resistance level identified after
        a move and a subsequent pullback. This forms the baseline for symmetry detection.
        We look for a local peak (High) or trough (Low) and ensure there is a
        pullback confirmation from the subsequent candle.

        Args:
            subset_df (pd.DataFrame): DataFrame containing 'h_idx' (high), 'l_idx' (low),
                                      'c_ce' (call close), 'c_pe' (put close), and 'ts' (timestamp).

        Returns:
            dict: {type: 'High'|'Low', data: Series} representing the peak/trough candle, or None.
        """
        if len(subset_df) < 3:
            return None

        # Simple swing detection: local high/low in the window
        last_n = subset_df.tail(self.swing_window)

        # We look for a peak that is NOT the very last candle (because we need a pullback)
        # Peak is at index -2
        last_candle = subset_df.iloc[-1]
        prev_candle = subset_df.iloc[-2]
        prev_prev = subset_df.iloc[-3]

        # Bullish Wall (High)
        if prev_candle['h_idx'] > prev_prev['h_idx'] and prev_candle['h_idx'] > last_candle['h_idx']:
            return {'type': 'High', 'data': prev_candle}

        # Bearish Wall (Low)
        if prev_candle['l_idx'] < prev_prev['l_idx'] and prev_candle['l_idx'] < last_candle['l_idx']:
            return {'type': 'Low', 'data': prev_candle}

        return None

    def check_decay_filter(self, current_index_price, current_opt_price, ref_level):
        """
        Phase II: Pullback & Decay Filter (Anti-Theta).

        Determines if the Option (CE or PE) is showing 'Relative Strength' despite time decay.
        If the Index returns to a previous Reference Level (High or Low), but the corresponding
        Option price is now higher than it was at that peak/trough, it indicates
        aggressive institutional buying.

        Args:
            current_index_price (float): Current Index Spot price.
            current_opt_price (float): Current ATM Option price (CE or PE).
            ref_level (dict): The active Reference level (High or Low).

        Returns:
            bool: True if Symmetry Panic Divergence is detected.
        """
        if not ref_level:
            return False

        if ref_level['type'] == 'High':
            # Bullish Case (BUY_CE): Index near high, CE should be higher than before
            if current_index_price >= ref_level['index_price'] - 2:
                if current_opt_price > ref_level['ce_price']:
                    return True
        elif ref_level['type'] == 'Low':
            # Bearish Case (BUY_PE): Index near low, PE should be higher than before
            if current_index_price <= ref_level['index_price'] + 2:
                if current_opt_price > ref_level['pe_price']:
                    return True
        return False

    def analyze(self, idx_candles, ce_candles, pe_candles, oi_data=None):
        """
        Main analysis loop that processes historical candles to generate backtest signals.
        Implements Phase III (Execution) and Phase IV (Guardrails) of the strategy.

        Execution Logic (Triple-Stream Symmetry):

        The strategy enters a trade when three independent data streams (Index, CE, PE)
        confirm the exhaustion of the 'Wall' and the formation of a 'Void'.

        BUY_CE (Bullish Entry):
            - Index Break: Spot price exceeds the previous significant high.
            - Active Break: Call option price exceeds its value at the previous index high.
            - Opposite Breakdown: Put option price falls below its value at the previous index high.
            - OI Panic: Significant drop in CE OI (Short Covering) + rise in PE OI (Writing).
            - Decay Divergence: CE price stays high or rises even if the Index pulls back slightly.
            - Absorption Guardrail: Ensures the Call option is actually following the Index move.

        BUY_PE (Bearish Entry):
            - Index Breakdown: Spot price falls below the previous significant low.
            - Active Breakout: Put option price exceeds its value at the previous index low.
            - Opposite Breakdown: Call option price falls below its value at the previous index low.
            - OI Panic: Significant drop in PE OI (Short Covering) + rise in CE OI (Writing).
            - Decay Divergence: PE price stays high or rises even if the Index pulls back slightly.
            - Absorption Guardrail: Ensures the Put option is actually following the Index move.

        Args:
            idx_candles (list): List of Index candles [ts, o, h, l, c, v].
            ce_candles (list): List of ATM Call candles.
            pe_candles (list): List of ATM Put candles.
            oi_data (dict, optional): Mapping of timestamp to {'ce_oi_chg', 'pe_oi_chg'}.

        Returns:
            list: Generated signals with entry, SL, TP, and confluence details.
        """
        if not idx_candles or not ce_candles or not pe_candles:
            return []

        # Convert to DataFrames
        idx_df = pd.DataFrame(idx_candles, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        ce_df = pd.DataFrame(ce_candles, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        pe_df = pd.DataFrame(pe_candles, columns=['ts', 'o', 'h', 'l', 'c', 'v'])

        # Align by timestamp
        combined = pd.merge(idx_df, ce_df, on='ts', suffixes=('_idx', '_ce'))
        combined = pd.merge(combined, pe_df, on='ts')
        combined.rename(columns={'o': 'o_pe', 'h': 'h_pe', 'l': 'l_pe', 'c': 'c_pe', 'v': 'v_pe'}, inplace=True)
        combined.sort_values('ts', inplace=True)

        signals = []
        # Keep track of signals to avoid duplicates at same timestamp
        seen_timestamps = set()

        for i in range(self.swing_window, len(combined)):
            subset = combined.iloc[:i+1] # Include current to see if previous was a peak
            current = combined.iloc[i]
            prev = combined.iloc[i-1]
            ts = int(current['ts'])

            # 1. Update Reference Levels
            swing = self.identify_swing(subset)
            if swing:
                l_type = swing['type']
                peak_data = swing['data']
                # Record prices of all three at the exact moment of peak
                self.reference_levels[l_type] = {
                    'index_price': float(peak_data['h_idx'] if l_type == 'High' else peak_data['l_idx']),
                    'ce_price': float(peak_data['c_ce']),
                    'pe_price': float(peak_data['c_pe']),
                    'type': l_type,
                    'time': int(peak_data['ts'])
                }
                logger.info(f"New Reference {l_type} set at {peak_data['ts']}: Index={self.reference_levels[l_type]['index_price']}")

            # 2. Check for Signals
            ref_high = self.reference_levels.get('High')
            ref_low = self.reference_levels.get('Low')

            # --- Bullish Trigger (Call Buy) ---
            if ref_high:
                score = 0
                details = {}

                # 1. Index: Crosses above Ref_High_Index
                if current['c_idx'] > ref_high['index_price']:
                    score += 1
                    details['index_break'] = True

                # 2. CE Symmetry: ATM Call breaks above Ref_High_CE
                if current['c_ce'] > ref_high['ce_price']:
                    score += 1
                    details['ce_break'] = True

                # 3. PE Symmetry: ATM Put breaks below its own local low at peak
                if current['c_pe'] < ref_high['pe_price']:
                    score += 1
                    details['pe_breakdown'] = True

                # 4. OI Panic (if available)
                if oi_data and ts in oi_data:
                    d = oi_data[ts]
                    if d.get('ce_oi_chg', 0) < 0 and d.get('pe_oi_chg', 0) > 0:
                        score += 1
                        details['oi_panic'] = True

                # 5. Decay Filter
                if self.check_decay_filter(current['c_idx'], current['c_ce'], ref_high):
                    score += 1
                    details['decay_divergence'] = True

                if score >= self.confluence_threshold and ts not in seen_timestamps:
                    # Guardrail: Absorption check (Index high but CE rejected)
                    if not (current['c_idx'] > prev['c_idx'] and current['c_ce'] <= prev['c_ce']):
                        signals.append({
                            'time': ts,
                            'type': 'BUY_CE',
                            'score': score,
                            'price': float(current['c_ce']),
                            'sl': float(ref_high['ce_price'] * 0.90), # 10% hard SL
                            'tp': float(current['c_ce'] + (current['c_ce'] - ref_high['ce_price']) * 2.5),
                            'details': details
                        })
                        seen_timestamps.add(ts)

            # --- Bearish Trigger (Put Buy) ---
            if ref_low:
                score = 0
                details = {}

                # 1. Index: Crosses below Ref_Low_Index
                if current['c_idx'] < ref_low['index_price']:
                    score += 1
                    details['index_break'] = True

                # 2. PE Symmetry: ATM Put breaks above Ref_High_PE (which was local high at support)
                if current['c_pe'] > ref_low['pe_price']:
                    score += 1
                    details['pe_break'] = True

                # 3. CE Symmetry: ATM Call breaks below Ref_Low_CE
                if current['c_ce'] < ref_low['ce_price']:
                    score += 1
                    details['ce_breakdown'] = True

                # 4. OI Panic (if available)
                if oi_data and ts in oi_data:
                    d = oi_data[ts]
                    # PE Sellers exiting (Panic/Short Covering) and CE Buyers entering (Opposite Writing)
                    if d.get('pe_oi_chg', 0) < 0 and d.get('ce_oi_chg', 0) > 0:
                        score += 1
                        details['oi_panic'] = True

                # 5. Decay Filter
                if self.check_decay_filter(current['c_idx'], current['c_pe'], ref_low):
                    score += 1
                    details['decay_divergence'] = True

                if score >= self.confluence_threshold and ts not in seen_timestamps:
                    # Guardrail: Absorption check (Index low but PE rejected)
                    if not (current['c_idx'] < prev['c_idx'] and current['c_pe'] <= prev['c_pe']):
                        signals.append({
                            'time': ts,
                            'type': 'BUY_PE',
                            'score': score,
                            'price': float(current['c_pe']),
                            'sl': float(ref_low['pe_price'] * 0.90),
                            'tp': float(current['c_pe'] + (current['c_pe'] - ref_low['pe_price']) * 2.5),
                            'details': details
                        })
                        seen_timestamps.add(ts)

        return signals
