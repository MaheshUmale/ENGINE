import sys
import os
sys.path.append(os.path.join(os.getcwd(), 'backend'))
import logging
from db.local_db import LocalDB

# Setup logging to see migration info
logging.basicConfig(level=logging.INFO)

def test_migration():
    print("Testing DB Migration and Insertion...")
    # This will trigger __init__ and _migrate_db
    db = LocalDB()

    # Test insertion with 6 fields
    tick = {
        'last_price': 25000.0,
        'ltq': 100,
        'ts_ms': 1740000000000,
        'instrumentKey': 'NSE:NIFTY',
        'source': 'test'
    }
    db.insert_ticks([tick])

    # Verify insertion
    res = db.query("SELECT * FROM ticks WHERE source = 'test'")
    print(f"Queried ticks: {res}")
    assert len(res) > 0
    assert 'full_feed' not in res[0]
    print("DB Migration and Insertion OK")

if __name__ == "__main__":
    # Remove existing DB to start fresh for this test if needed,
    # but here we want to test migration of existing one.
    test_migration()
