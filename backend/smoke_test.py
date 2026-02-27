
import asyncio
import sys
import os

# Add backend to path
sys.path.append(os.path.join(os.getcwd(), 'backend'))

from symmetry_engine.strategy import StrategyEngine
from core.options_manager import options_manager
from core.greeks_calculator import greeks_calculator

async def test_components():
    print("Testing Greeks Calculator...")
    greeks = greeks_calculator.calculate_all_greeks(25000, 25000, 0.01, 0.20, 'call', 200)
    print(f"Greeks: {greeks}")
    assert greeks['delta'] > 0

    print("\nTesting StrategyEngine Initialization...")
    engine = StrategyEngine(index_name="NIFTY")
    print("StrategyEngine initialized.")

    print("\nTesting OptionsManager API placeholders...")
    # Just checking if methods exist and don't crash on basic access
    assert hasattr(options_manager, 'get_chain_with_greeks')
    assert hasattr(options_manager, 'get_genie_insights')
    print("OptionsManager methods verified.")

    print("\nSmoke test passed!")

if __name__ == "__main__":
    asyncio.run(test_components())
