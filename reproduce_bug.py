
import duckdb
import os

DB_TEST = 'test_dependency.db'
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

print("Attempting to drop full_feed while index exists...")
try:
    conn.execute("ALTER TABLE ticks DROP COLUMN full_feed")
    print("Success!")
except Exception as e:
    print(f"Failed: {e}")

conn.close()
if os.path.exists(DB_TEST): os.remove(DB_TEST)
