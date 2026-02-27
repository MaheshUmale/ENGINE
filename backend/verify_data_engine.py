
import sys
import os
import json
import logging
from unittest.mock import MagicMock, patch

# Add backend to path
sys.path.append(os.path.join(os.getcwd(), 'backend'))

# Mock LocalDBJSONEncoder to avoid json.dumps issues in test
class MockEncoder(json.JSONEncoder):
    def default(self, obj): return str(obj)

# Patch sys.modules to avoid real DB and other imports
sys.modules['db'] = MagicMock()
sys.modules['db.local_db'] = MagicMock(db=MagicMock(), LocalDBJSONEncoder=MockEncoder)
sys.modules['core.provider_registry'] = MagicMock()

# Configure logging
logging.basicConfig(level=logging.INFO)

def test_data_engine_logic():
    # Import after mocking
    from core.data_engine import on_message, set_socketio, emit_event, subscribe_instrument
    from core.symbol_mapper import symbol_mapper

    # Mock SocketIO and loop
    mock_sio = MagicMock()
    mock_loop = MagicMock()
    mock_loop.is_running.return_value = True
    set_socketio(mock_sio, mock_loop)

    # Setup mapping mocks
    inst_key = "NSE_FO|54902"
    hrn = "NIFTY 27 FEB 2025 CALL 23500"
    canonical = "NSE:NIFTY2522723500CE"

    symbol_mapper.get_hrn = MagicMock(return_value=hrn)
    symbol_mapper.from_upstox_key = MagicMock(return_value=canonical)
    symbol_mapper.resolve_to_key = MagicMock(return_value=inst_key)

    # Test 1: emit_event logging
    print("\n--- Test 1: emit_event logging ---")
    emit_event("test_event", {"data": 1}, room=inst_key, hrn=hrn)

    # Test 2: on_message multi-room emission
    print("\n--- Test 2: on_message multi-room emission ---")
    tick_msg = {
        "feeds": {
            inst_key: {
                "last_price": 150.5,
                "tv_volume": 1000,
                "ts_ms": 1740643200000,
                "source": "upstox_wss"
            }
        }
    }

    # Patch time.time to bypass throttling
    with patch('time.time', return_value=2000000000.0), \
         patch('core.data_engine.emit_event') as mock_emit:
        on_message(json.dumps(tick_msg))

        print(f"Total emit_event calls: {mock_emit.call_count}")
        for i, call in enumerate(mock_emit.call_args_list):
            args, kwargs = call
            print(f"Call {i+1}: Event={args[0]}, Room={kwargs.get('room')}, HRN={kwargs.get('hrn')}")

    # Test 3: subscribe_instrument resolution
    print("\n--- Test 3: subscribe_instrument resolution ---")
    with patch('core.data_engine.live_stream_registry.get_all', return_value=[]):
        subscribe_instrument(hrn, "sid_123")

if __name__ == "__main__":
    test_data_engine_logic()
