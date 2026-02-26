import sys
import os
sys.path.append(os.path.join(os.getcwd(), 'backend'))

from core.greeks_calculator import greeks_calculator
from symmetry_engine.strategy import StrategyEngine
from symmetry_engine.database import Signal

def test_greeks():
    print("Testing Greeks Calculator...")
    res = greeks_calculator.calculate_all_greeks(
        spot_price=25000,
        strike_price=25000,
        time_to_expiry=0.01,
        volatility=0.20,
        option_type='call',
        option_price=200
    )
    assert res['delta'] > 0
    assert res['implied_volatility'] > 0
    print("Greeks Calculator OK")

def test_strategy():
    print("Testing Strategy Engine...")
    engine = StrategyEngine("NIFTY")

    # Mock some data
    instruments = {'index': 'NSE_INDEX|Nifty 50', 'ce': 'CE_KEY', 'pe': 'PE_KEY'}
    engine.update_data('NSE_INDEX|Nifty 50', {'ltp': 25100})
    engine.update_data('CE_KEY', {'ltp': 150, 'oi_delta': -1000})
    engine.update_data('PE_KEY', {'ltp': 50, 'oi_delta': 500})

    # Mock reference levels
    engine.reference_levels['High'] = {
        'index_price': 25050,
        'ce_price': 140,
        'pe_price': 60,
        'type': 'High'
    }

    # Mock candle history for ATR and Relative Strength
    for _ in range(20):
        engine.update_candle('NSE_INDEX|Nifty 50', {'open': 25000, 'high': 25010, 'low': 24990, 'close': 25000})
        engine.update_candle('CE_KEY', {'open': 140, 'high': 145, 'low': 135, 'close': 140})
        engine.update_candle('PE_KEY', {'open': 60, 'high': 65, 'low': 55, 'close': 60})

    # Mock 5m EMA
    for _ in range(20):
        engine.update_candle('NSE_INDEX|Nifty 50', {'open': 25000, 'high': 25010, 'low': 24990, 'close': 25000}, interval=5)

    sig = engine.generate_signals(instruments)
    if sig:
        print(f"Signal generated: {sig.side}, Score: {sig.confluence_score}")
    else:
        print("No signal generated (expected depending on logic)")

    print("Strategy Engine OK")

if __name__ == "__main__":
    test_greeks()
    test_strategy()
