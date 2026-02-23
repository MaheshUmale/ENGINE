import sys
import os
sys.path.append(os.path.join(os.getcwd(), 'backend'))

from brain.VolumeAnalyzer import VolumeAnalyzer
import pandas as pd

def test_volume_analyzer():
    # Create dummy OHLCV data
    candles = []
    import time
    now = int(time.time())
    for i in range(200):
        # Every 50 bars, add a massive volume spike
        vol = 1000 if i % 50 != 0 else 5000
        candles.append([now + i*60, 100, 105, 95, 102, vol])

    analyzer = VolumeAnalyzer()
    result = analyzer.analyze(candles)

    print(f"RVOL length: {len(result['rvol'])}")
    print(f"Markers count: {len(result['markers'])}")
    print(f"Lines count: {len(result['lines'])}")

    if result['markers']:
        print(f"Sample marker: {result['markers'][0]}")
    if result['lines']:
        print(f"Sample line: {result['lines'][0]}")

    # Check RVOL values
    rvol_series = pd.Series(result['rvol'])
    print(f"Max RVOL: {rvol_series.max()}")

if __name__ == "__main__":
    test_volume_analyzer()
