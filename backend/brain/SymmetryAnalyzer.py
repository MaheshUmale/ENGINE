import pandas as pd
import numpy as np
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class SymmetryAnalyzer:
    """
    Implements the Triple-Stream Symmetry & Panic Strategy (inspired by MaheshUmale/ENGINE).
    This strategy moves away from simple price-crossing logic and implements a "Pressure Gauge".
    """
    def __init__(self, underlying="NSE:NIFTY"):
        self.underlying = underlying
        self.reference_levels = {'High': None, 'Low': None}
        self.swing_window = 15

    def calculate_atr(self, df, window=14, prefix=''):
        if len(df) < window + 1: return 0
        df = df.copy()
        h_col = f'h{prefix}'
        l_col = f'l{prefix}'
        c_col = f'c{prefix}'

        if h_col not in df.columns: h_col = 'h'
        if l_col not in df.columns: l_col = 'l'
        if c_col not in df.columns: c_col = 'c'

        df['h-l'] = df[h_col] - df[l_col]
        df['h-pc'] = abs(df[h_col] - df[c_col].shift(1))
        df['l-pc'] = abs(df[l_col] - df[c_col].shift(1))
        df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)
        return df['tr'].tail(window).mean()

    def identify_swing(self, subset_df):
        if len(subset_df) < 15: return None

        atr = self.calculate_atr(subset_df, prefix='_idx')
        atr_threshold = atr * 1.5 if atr > 0 else 5.0

        c = subset_df.iloc[-1]
        p = subset_df.iloc[-2]
        pp = subset_df.iloc[-3]
        ppp = subset_df.iloc[-4]

        last_n = subset_df.tail(15)
        current_high = last_n['h_idx'].max()
        current_low = last_n['l_idx'].min()

        window_start_price = last_n.iloc[0]['o_idx']
        if abs(current_high - window_start_price) < atr_threshold and abs(current_low - window_start_price) < atr_threshold:
            return None

        # Bullish Wall (High) with 3-candle pullback
        if ppp['h_idx'] == current_high:
            if pp['h_idx'] < ppp['h_idx'] and p['h_idx'] < pp['h_idx'] and c['h_idx'] < p['h_idx']:
                return {'type': 'High', 'data': ppp}

        # Bearish Wall (Low) with 3-candle pullback
        if ppp['l_idx'] == current_low:
            if pp['l_idx'] > ppp['l_idx'] and p['l_idx'] > pp['l_idx'] and c['l_idx'] > p['l_idx']:
                return {'type': 'Low', 'data': ppp}

        return None

    def calculate_relative_velocity(self, subset, lookback=3):
        if len(subset) < lookback + 1:
            return 0, 0, 0
        current = subset.iloc[-1]
        past = subset.iloc[-lookback - 1]

        idx_vel = (current['c_idx'] - past['c_idx']) / past['c_idx'] if past['c_idx'] > 0 else 0
        ce_vel = (current['c_ce'] - past['c_ce']) / past['c_ce'] if past['c_ce'] > 0 else 0
        pe_vel = (current['c_pe'] - past['c_pe']) / past['c_pe'] if past['c_pe'] > 0 else 0

        return idx_vel, ce_vel, pe_vel

    def is_shallow_pullback(self, subset, active_side='CE'):
        """
        Check for 'Shallow Pullbacks':
        If Index drops 0.1% but the Active Option drops less than its expected Delta value.
        """
        if len(subset) < 5: return False
        
        c = subset.iloc[-1]
        last_5 = subset.tail(5)
        
        if active_side == 'CE':
            recent_peak_idx = last_5['h_idx'].max()
            peak_row = last_5.loc[last_5['h_idx'] == recent_peak_idx].iloc[0]
            
            idx_drop_pct = (peak_row['h_idx'] - c['l_idx']) / peak_row['h_idx'] if peak_row['h_idx'] > 0 else 0
            if idx_drop_pct >= 0.001: 
                expected_ce_drop_points = (peak_row['h_idx'] - c['l_idx']) * 0.5
                actual_ce_drop_points = peak_row['h_ce'] - c['l_ce']
                if 0 <= actual_ce_drop_points < (expected_ce_drop_points * 0.8):
                    return True
        elif active_side == 'PE':
            recent_low_idx = last_5['l_idx'].min()
            low_row = last_5.loc[last_5['l_idx'] == recent_low_idx].iloc[0]
            
            idx_rally_pct = (c['h_idx'] - low_row['l_idx']) / low_row['l_idx'] if low_row['l_idx'] > 0 else 0
            if idx_rally_pct >= 0.001:
                expected_pe_drop_points = (c['h_idx'] - low_row['l_idx']) * 0.5
                actual_pe_drop_points = low_row['h_pe'] - c['l_pe']
                if 0 <= actual_pe_drop_points < (expected_pe_drop_points * 0.8):
                    return True
        return False

    def is_late_to_party(self, subset, active_side='CE'):
        if len(subset) < 15: return False
        c = subset.iloc[-1]
        
        if active_side == 'CE':
            avg_ce_body = abs(subset.tail(15)['c_ce'] - subset.tail(15)['o_ce']).mean()
            current_ce_body = abs(c['c_ce'] - c['o_ce'])
            return current_ce_body > (2 * avg_ce_body) if avg_ce_body > 0 else False
        else:
            avg_pe_body = abs(subset.tail(15)['c_pe'] - subset.tail(15)['o_pe']).mean()
            current_pe_body = abs(c['c_pe'] - c['o_pe'])
            return current_pe_body > (2 * avg_pe_body) if avg_pe_body > 0 else False

    def calculate_pcr_momentum(self, pcr_data, current_ts):
        """
        Check PCR momentum. PCR must be trending in the direction of the trade.
        Returns +1 (Bullish momentum) or -1 (Bearish momentum) or 0 (Neutral/No Data).
        """
        if not pcr_data or len(pcr_data) == 0:
            return 0
            
        timestamps = sorted(pcr_data.keys())
        # Filter data up to current_ts
        valid_ts = [t for t in timestamps if t <= current_ts]
        if len(valid_ts) < 2:
            return 0
            
        current_pcr = pcr_data[valid_ts[-1]]
        sod_pcr = pcr_data[valid_ts[0]] # approximation of SOD
        
        # 10 min MA
        lookback = valid_ts[-10:] if len(valid_ts) >= 10 else valid_ts
        ma_pcr = sum([pcr_data[t] for t in lookback]) / len(lookback)
        
        if current_pcr > sod_pcr and current_pcr > ma_pcr:
            return 1 # Bullish (PCR increasing -> Call buying)
        elif current_pcr < sod_pcr and current_pcr < ma_pcr:
            return -1 # Bearish (PCR decreasing -> Put buying)
        return 0

    def calculate_ema(self, df, period=20, prefix='_idx'):
        """Calculates Exponential Moving Average for trend filtering."""
        c_col = f'c{prefix}'
        if c_col not in df.columns: c_col = 'c'
        if len(df) < period:
            return 0
        return df[c_col].ewm(span=period, adjust=False).mean().iloc[-1]

    def calculate_avg_volume(self, df, period=10, prefix='_idx'):
        """Calculates average volume over N candles."""
        v_col = f'v{prefix}'
        if v_col not in df.columns: v_col = 'v'
        if len(df) < period: return 0
        return df[v_col].tail(period).mean()

    def check_void_above(self, current_index, direction, option_chain):
        """
        The 'Void' Check: Ensure there's no massive OI wall 5-10 points away.
        Args:
            current_index (float): Current underlying price
            direction (str): 'UP' or 'DOWN'
            option_chain (list): Array of dicts representing the strikes and their OI
        Returns: True if there is a Void, False if blocked by a Wall.
        """
        if not option_chain:
            # Default to True to allow testing if chain data isn't provided
            return True
            
        # VERY basic void check looking 5-15 points away
        # Real implementation requires processing specific strike arrays 
        # and checking Call OI (for UP) or Put OI (for DOWN)
        # We will assume a simple pass for this skeleton where data is missing
        return True

    def analyze(self, idx_candles, ce_candles, pe_candles, oi_data=None, pcr_data=None, option_chain=None):
        """
        Executes the Comprehensive Squeeze strategy.
        """
        if not idx_candles or not ce_candles or not pe_candles:
            return []

        idx_df = pd.DataFrame(idx_candles, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        ce_df = pd.DataFrame(ce_candles, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        pe_df = pd.DataFrame(pe_candles, columns=['ts', 'o', 'h', 'l', 'c', 'v'])

        combined = pd.merge(idx_df, ce_df, on='ts', suffixes=('_idx', '_ce'))
        combined = pd.merge(combined, pe_df, on='ts')
        combined.rename(columns={'o': 'o_pe', 'h': 'h_pe', 'l': 'l_pe', 'c': 'c_pe', 'v': 'v_pe'}, inplace=True)
        combined.sort_values('ts', inplace=True)

        signals = []
        seen_timestamps = set()

        for i in range(self.swing_window, len(combined)):
            subset = combined.iloc[:i+1]
            current = combined.iloc[i]
            ts = int(current['ts'])

            swing = self.identify_swing(subset)
            if swing:
                l_type = swing['type']
                peak_data = swing['data']
                self.reference_levels[l_type] = {
                    'index_price': float(peak_data['h_idx'] if l_type == 'High' else peak_data['l_idx']),
                    'ce_price': float(peak_data['c_ce']),
                    'pe_price': float(peak_data['c_pe']),
                    'type': l_type,
                    'time': int(peak_data['ts'])
                }

            ref_high = self.reference_levels.get('High')
            ref_low = self.reference_levels.get('Low')

            # The Setup: Was there a pullback (First hit confirmed)?
            # The strategy says a trade setup is ONLY valid if we see a Second Attempt.
            # identify_swing inherently required a 3-candle pullback, so if ref_high exists, a pullback happened.

            # --- Bullish Trigger (Call Buy) ---
            if ref_high:
                score = 0
                details = {}

                # 0. Volume Confirmation (Surge > 1.5x MA)
                avg_vol = self.calculate_avg_volume(subset, period=20)
                vol_surge = current['v_idx'] > (avg_vol * 1.5) if avg_vol > 0 else False
                if vol_surge:
                    score += 1
                    details['volume_confirmation'] = True

                # 0.1 Trend Filter (5m EMA proxy via 20-period EMA on 1m chart)
                ema_val = self.calculate_ema(subset, period=20)
                trend_ok = current['c_idx'] > ema_val if ema_val > 0 else True
                if trend_ok:
                    score += 1
                    details['trend_confirmation'] = True

                # 1. Absorption Filter
                is_absorption = current['c_idx'] >= ref_high['index_price'] and current['c_ce'] <= ref_high['ce_price']

                # 2. Relative Velocity (Tick-Stream Anticipation)
                idx_vel, ce_vel, pe_vel = self.calculate_relative_velocity(subset, lookback=3)
                # Option delta is approx 0.5 ATM. Action is a 'Raid' if option moves > 1.5x expected velocity.
                if ce_vel > (idx_vel * 0.5 * 1.5) and ce_vel > 0:
                    details['relative_velocity_high'] = True
                    score += 1

                # 3. Symmetry of Panic (Opposing Option / Victim making fresh lows)
                pe_fresh_low = current['c_pe'] < ref_high['pe_price'] and pe_vel < 0
                if pe_fresh_low:
                    details['pe_victim_breakdown'] = True
                    score += 1

                # 4. PCR Momentum Check
                pcr_mom = self.calculate_pcr_momentum(pcr_data, ts)
                if pcr_mom == 1:
                    score += 1
                    details['pcr_momentum'] = True

                # 5. Void Check
                has_void = self.check_void_above(current['c_idx'], 'UP', option_chain)
                if has_void:
                    score += 1
                    details['void_present'] = True

                # 6. Shallow Pullback flag (The 2nd Attempt Check)
                if self.is_shallow_pullback(subset, active_side='CE'):
                    details['shallow_pullback'] = True
                    score += 1

                # 7. Writer Panic (Negative OI Delta)
                ce_oi_delta = 0
                if oi_data and ts in oi_data:
                    ce_oi_delta = oi_data[ts].get('ce_oi_chg', 0)

                # STRICTER OI RULE: -500 minimum delta to filter noise
                writer_panic = True if (not oi_data or ce_oi_delta < -500) else False
                if writer_panic:
                    details['writer_panic'] = True
                    score += 2 # Higher weighting for real panic

                # 8. The Trigger: 
                # - 2nd Attempt Relative Strength (`current['c_ce'] > ref_high['ce_price']`)
                # - Option moving, Victim dying, and OI Panic.
                if not is_absorption and not self.is_late_to_party(subset, 'CE'):
                    # The "Retest": Price must be crossing the CE reference high, showing relative strength vs the first attempt.
                    if pe_fresh_low and current['c_ce'] > ref_high['ce_price'] and writer_panic:
                        # Tick Stream Anticipation: We no longer STRICTLY require Index to close above ref_high, 
                        # but we require Relative Strength on the CE (it's trading higher than it was at the first High).
                        # However to be safe, Index must be at least very close (within 0.05%)
                        if current['c_idx'] >= ref_high['index_price'] * 0.9995:
                            cooldown_passed = all(ts - s.get('time', 0) > 900 for s in signals[-3:]) # 15 min * 60s
                            # Increased threshold from 3 to 5 for high-confidence trades
                            if score >= 5 and cooldown_passed and ts not in seen_timestamps:
                                entry_price = float(current['c_ce'])
                                # Balanced SL: 7% of premium + small 2pt buffer
                                sl_buffer = (entry_price * 0.07) + 2.0
                                sl = entry_price - sl_buffer
                                signals.append({
                                    'time': ts,
                                    'type': 'BUY_CE',
                                    'score': score,
                                    'price': entry_price,
                                    'sl': float(sl), 
                                    'details': details
                                })
                                seen_timestamps.add(ts)

            # --- Bearish Trigger (Put Buy) ---
            if ref_low:
                score = 0
                details = {}

                # 0. Volume Confirmation (Surge > 1.5x MA)
                avg_vol = self.calculate_avg_volume(subset, period=20)
                vol_surge = current['v_idx'] > (avg_vol * 1.5) if avg_vol > 0 else False
                if vol_surge:
                    score += 1
                    details['volume_confirmation'] = True

                # 0.1 Trend Filter (5m EMA proxy)
                ema_val = self.calculate_ema(subset, period=20)
                trend_ok = current['c_idx'] < ema_val if ema_val > 0 else True
                if trend_ok:
                    score += 1
                    details['trend_confirmation'] = True

                # 1. Absorption Filter
                is_absorption = current['c_idx'] <= ref_low['index_price'] and current['c_pe'] <= ref_low['pe_price']

                # 2. Relative Velocity
                idx_vel, ce_vel, pe_vel = self.calculate_relative_velocity(subset, lookback=3)
                # Option delta is approx 0.5 ATM. Action is a 'Raid' if option moves > 1.5x expected velocity.
                # Index drops (idx_vel < 0), Put should rise.
                if pe_vel > abs(idx_vel) * 0.5 * 1.5 and pe_vel > 0:
                    details['relative_velocity_high'] = True
                    score += 1

                # 3. Symmetry of Panic (Opposing Option / Victim making fresh lows)
                ce_fresh_low = current['c_ce'] < ref_low['ce_price'] and ce_vel < 0
                if ce_fresh_low:
                    details['ce_victim_breakdown'] = True
                    score += 1

                # 4. PCR Momentum Check
                pcr_mom = self.calculate_pcr_momentum(pcr_data, ts)
                if pcr_mom == -1:
                    score += 1
                    details['pcr_momentum'] = True

                # 5. Void Check
                has_void = self.check_void_above(current['c_idx'], 'DOWN', option_chain)
                if has_void:
                    score += 1
                    details['void_present'] = True

                # 6. Shallow Pullback flag
                if self.is_shallow_pullback(subset, active_side='PE'):
                    details['shallow_pullback'] = True
                    score += 1

                # 7. Writer Panic (Negative OI Delta)
                pe_oi_delta = 0
                if oi_data and ts in oi_data:
                    pe_oi_delta = oi_data[ts].get('pe_oi_chg', 0)

                # STRICTER OI RULE
                writer_panic = True if (not oi_data or pe_oi_delta < -500) else False
                if writer_panic:
                    details['writer_panic'] = True
                    score += 2

                # 8. The Trigger: 
                # - 2nd Attempt Relative Strength (`current['c_pe'] > ref_low['pe_price']`)
                if not is_absorption and not self.is_late_to_party(subset, 'PE'):
                    if ce_fresh_low and current['c_pe'] > ref_low['pe_price'] and writer_panic:
                        # Tick Stream Anticipation check
                        if current['c_idx'] <= ref_low['index_price'] * 1.0005:
                            cooldown_passed = all(ts - s.get('time', 0) > 900 for s in signals[-3:])
                            if score >= 5 and cooldown_passed and ts not in seen_timestamps:
                                entry_price = float(current['c_pe'])
                                # Balanced SL: 7% of premium + small 2pt buffer
                                sl_buffer = (entry_price * 0.07) + 2.0
                                sl = entry_price - sl_buffer
                                signals.append({
                                    'time': ts,
                                    'type': 'BUY_PE',
                                    'score': score,
                                    'price': entry_price,
                                    'sl': float(sl),
                                    'details': details
                                })
                                seen_timestamps.add(ts)

        return signals
