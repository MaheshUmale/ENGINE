import numpy as np
import pandas as pd
from datetime import datetime
from core.utils import safe_int, safe_float

class VolumeAnalyzer:
    def __init__(self, rvol_len=20, bubble_long_len=100, bubble_short_len=10, node_std_len=48):
        self.rvol_len = rvol_len
        self.bubble_long_len = bubble_long_len
        self.bubble_short_len = bubble_short_len
        self.node_std_len = node_std_len

        # Thresholds from Pine Script
        self.BUBBLE_THRESHOLD = 2.5
        self.BUBBLE_DELTA = 0.75
        self.RAY_WICK_RATIO = 1.5
        self.MAX_RAYS = 50

    def analyze(self, candles, settings=None):
        """
        candles: list of [ts, o, h, l, c, v]
        settings: dict containing overrides for lengths and thresholds
        Returns: {
            'rvol': [float], # same length as candles
            'markers': [],   # list of marker objects
            'lines': [],      # High Volume Nodes
            'volume_rays': [] # NEW: Requested Ray Levels
        }
        """
        # Apply setting overrides
        s = settings or {}

        rvol_len = safe_int(s.get('rvol_len'), self.rvol_len)
        bubble_long_len = safe_int(s.get('bubble_long_len'), self.bubble_long_len)
        bubble_short_len = safe_int(s.get('bubble_short_len'), self.bubble_short_len)
        node_std_len = safe_int(s.get('node_std_len'), self.node_std_len)
        bubble_threshold = safe_float(s.get('bubble_threshold'), self.BUBBLE_THRESHOLD)
        ray_wick_ratio = safe_float(s.get('ray_wick_ratio'), self.RAY_WICK_RATIO)
        max_rays = safe_int(s.get('max_rays'), self.MAX_RAYS)
        rvol_threshold = safe_float(s.get('rvol_threshold'), 2.0)

        if len(candles) < max(rvol_len, bubble_long_len, node_std_len):
            return {'rvol': [1.0] * len(candles), 'markers': [], 'lines': [], 'volume_rays': []}

        df = pd.DataFrame(candles, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        df['hlcc4'] = (df['h'] + df['l'] + df['c'] + df['c']) / 4

        # 1. RVOL Calculation
        df['v_sma20'] = df['v'].rolling(window=rvol_len).mean()
        df['rvol'] = df['v'] / df['v_sma20'].replace(0, 1)

        # 2. Bubble & Ray Calculation
        df['v_sma100'] = df['v'].rolling(window=bubble_long_len).mean()
        df['v_sma10'] = df['v'].rolling(window=bubble_short_len).mean()
        df['v_avg_bubble'] = (df['v_sma100'] + df['v_sma10']) / 2
        df['bubble_ratio'] = df['v'] / df['v_avg_bubble'].replace(0, 1)

        # 3. Normalized Volume (for High Volume Nodes / Bubble Lines)
        df['bubble_ratio'] = df['bubble_ratio'].fillna(0.0)
        df['v_sma48'] = df['v'].rolling(window=node_std_len).mean()
        df['v_std48'] = df['v'].rolling(window=node_std_len).std()
        df['v_norm'] = (df['v'] - df['v_sma48']) / df['v_std48'].replace(0, 1)

        markers = []
        lines = []
        volume_rays = []

        show_bubbles = s.get('show_bubbles', True)
        show_rays = s.get('show_rays', True)

        for i in range(len(df)):
            row = df.iloc[i]
            ratio = row['bubble_ratio']
            rvol = row['rvol']
            v_norm = row['v_norm']

            # Identify high volume candle for Ray/Level logic
            if (ratio > bubble_threshold or rvol > rvol_threshold) and show_rays:
                # Starting point logic
                o, h, l, c = row['o'], row['h'], row['l'], row['c']
                uw = h - max(o, c)
                lw = min(o, c) - l

                # Use settings for ratio threshold
                if uw > ray_wick_ratio * lw:
                    start_price = h
                    level_type = "Resistance"
                elif lw > ray_wick_ratio * uw:
                    start_price = l
                    level_type = "Support"
                else:
                    start_price = c
                    level_type = "Pivot"

                is_up = c > o
                color = "rgba(34, 197, 94, 0.6)" if level_type == "Support" else "rgba(239, 68, 68, 0.6)" if level_type == "Resistance" else "rgba(59, 130, 246, 0.6)"

                volume_rays.append({
                    "price": float(start_price),
                    "color": color,
                    "width": 2,
                    "title": f"V-Ray ({level_type})",
                    "time": int(row['ts'])
                })

            # Add bubble marker
            if (ratio > bubble_threshold or rvol > rvol_threshold) and show_bubbles:
                is_up = row['c'] > row['o']
                markers.append({
                    "time": int(row['ts']),
                    "position": "belowBar" if is_up else "aboveBar",
                    "color": "rgba(34, 197, 94, 0.3)" if is_up else "rgba(239, 68, 68, 0.3)",
                    "shape": "circle",
                    "text": f"V:{ratio:.1f}x",
                    "id": f"bubble_{i}"
                })

            # High Volume Nodes (Aligned with Pine Script v_norm logic)
            # step = (v_norm - BubbleSize) / BubbleSizeDelta; if step >= 4
            bubble_delta = 0.75 # Default from Pine
            step = (v_norm - bubble_threshold) / bubble_delta
            if step >= 4:
                # Use hlcc4 from Pine Script for standard bubble lines
                lines.append({
                    "price": float(row['hlcc4']),
                    "color": "rgba(0, 255, 255, 0.5)" if row['c'] > row['o'] else "rgba(255, 165, 0, 0.5)",
                    "width": 3 if step >= 6 else 2,
                    "time": int(row['ts'])
                })

        # Limit rays
        volume_rays = sorted(volume_rays, key=lambda x: x['time'])[-max_rays:]

        # 4. EVWMA Calculation
        evma_res = []
        if s.get('show_evwma', True):
            evma_len = int(s.get('evwma_len', 5))
            df['shares_sum'] = df['v'].rolling(window=evma_len).sum()
            evma = [np.nan] * len(df)
            for i in range(1, len(df)):
                shares = df['shares_sum'].iloc[i]
                vol = df['v'].iloc[i]
                price = df['c'].iloc[i]
                prev_val = evma[i-1] if i > 0 and not np.isnan(evma[i-1]) else price
                if shares > 0:
                    evma[i] = (prev_val * (shares - vol) / shares) + (vol * price / shares)
                else:
                    evma[i] = prev_val
            evma_res = [{"time": int(ts), "value": float(v)} for ts, v in zip(df['ts'], evma) if np.isfinite(v) and v > 0]

        # 5. Dynamic Pivot Calculation
        dyn_p_res = []
        if s.get('show_dyn_pivot', True):
            force_len = int(s.get('pivot_force_len', 20))
            pivot_len = int(s.get('pivot_len', 10))
            df['pC'] = df['c'] - df['o']
            df['mB'] = df['pC'].abs().rolling(window=force_len).max()
            df['sc'] = df['pC'].abs() / df['mB'].replace(0, 1)
            df['netF'] = (df['pC'] * df['v'] * df['sc']).rolling(window=force_len).mean()
            df['baseP'] = df.apply(lambda r: r['h'] if r['pC'] > 0 else r['l'], axis=1).rolling(window=pivot_len).mean()
            df['fS'] = (df['c'].diff().abs() / df['c']).rolling(window=pivot_len).mean()
            df['hN'] = df['netF'].abs().rolling(window=pivot_len).max()
            df['fA'] = df['netF'] / df['hN'].replace(0, 1)
            df['dynP'] = df['baseP'] + (df['fA'] * df['c'] * df['fS'].fillna(0))
            dyn_p_res = [{"time": int(ts), "value": float(v)} for ts, v in zip(df['ts'], df['dynP']) if np.isfinite(v) and v > 0]

        return {
            'rvol': [float(v) if np.isfinite(v) else 1.0 for v in df['rvol'].fillna(1.0)],
            'markers': markers,
            'lines': lines,
            'volume_rays': volume_rays,
            'evwma': evma_res,
            'dyn_pivot': dyn_p_res
        }
