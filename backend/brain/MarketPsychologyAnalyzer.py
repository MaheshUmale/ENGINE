import numpy as np
import pandas as pd
from datetime import datetime

class MarketPsychologyAnalyzer:
    def __init__(self, vol_lookback=20, atr_lookback=20):
        self.vol_lookback = vol_lookback
        self.atr_lookback = atr_lookback
        self.active_zones = []
        self.confirmed_signals = {} # {timestamp: signal_type}

    def _calculate_metrics(self, df):
        df = df.copy()
        df['vol_sma'] = df['volume'].rolling(window=self.vol_lookback).mean()
        df['r_vol'] = df['volume'] / df['vol_sma']
        df['tr'] = np.maximum(df['high'] - df['low'], np.abs(df['high'] - df['close'].shift(1)))
        df['atr'] = df['tr'].rolling(window=self.atr_lookback).mean()
        df['eff'] = (df['tr'] / df['atr']) / df['r_vol'].replace(0, 1)
        df['ema'] = df['close'].ewm(span=50, adjust=False).mean()
        return df

    def build_global_map(self, df):
        zones = []
        for i in range(self.vol_lookback, len(df) - 1):
            row = df.iloc[i]
            # Create a zone if we see massive absorption (High volume, low price progress)
            if row['r_vol'] > 2.5 and row['eff'] < 0.6:
                price = row['high'] if row['close'] < row['open'] else row['low']
                zones.append({'price': float(price), 'type': 'BATTLE_ZONE', 'time': df.index[i]})
        self.active_zones = zones

    def run_state_machine(self, df):
        self.confirmed_signals = {}
        for i in range(50, len(df)):
            row = df.iloc[i]
            # Check proximity to any global zone
            is_near_zone = any(abs(row['close'] - z['price'])/row['close'] < 0.0015 for z in self.active_zones)

            if is_near_zone and row['r_vol'] > 2.2 and row['eff'] < 0.65:
                # Identification of a Trap
                if row['close'] < row['ema'] and row['close'] < row['open']:
                    self.confirmed_signals[df.index[i]] = "SHORT_TRAP"
                elif row['close'] > row['ema'] and row['close'] > row['open']:
                    self.confirmed_signals[df.index[i]] = "LONG_TRAP"

    def analyze(self, ohlcv_data):
        """
        Input: List of [timestamp, open, high, low, close, volume]
        Output: Tuple of (zones, signals)
        """
        if not ohlcv_data or len(ohlcv_data) < 50:
            return [], {}

        df = pd.DataFrame(ohlcv_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='s')
        df.set_index('datetime', inplace=True)

        full_df = self._calculate_metrics(df)
        self.build_global_map(full_df)
        self.run_state_machine(full_df)

        return self.active_zones, self.confirmed_signals
