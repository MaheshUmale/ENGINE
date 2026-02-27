
import duckdb
import os

DB_TEST = 'test_dependency_fix.db'
if os.path.exists(DB_TEST): os.remove(DB_TEST)

conn = duckdb.connect(DB_TEST)
conn.execute("""
    CREATE TABLE ticks (
        date DATE,
        instrumentKey VARCHAR,
        ts_ms BIGINT,
        price DOUBLE,
        qty BIGINT,
        source VARCHAR,
        full_feed JSON
    )
""")
conn.execute("CREATE INDEX idx_ticks_date_key_ts ON ticks (date, instrumentKey, ts_ms)")

print("Attempting to drop full_feed with the fix (drop index first)...")
try:
    conn.execute("DROP INDEX IF EXISTS idx_ticks_date_key_ts")
    conn.execute("ALTER TABLE ticks DROP COLUMN full_feed")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ticks_date_key_ts ON ticks (date, instrumentKey, ts_ms)")
    print("Success!")

    cols = conn.execute("PRAGMA table_info('ticks')").fetchall()
    print("Remaining columns:", [col[1] for col in cols])
except Exception as e:
    print(f"Failed: {e}")

conn.close()
if os.path.exists(DB_TEST): os.remove(DB_TEST)
