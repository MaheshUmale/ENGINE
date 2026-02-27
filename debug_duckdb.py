
import duckdb
import os

DB_PATH = 'data/pro_trade.db'

if os.path.exists(DB_PATH):
    conn = duckdb.connect(DB_PATH)
    print("Tables:")
    print(conn.execute("SHOW TABLES").fetchall())

    print("\nIndexes:")
    print(conn.execute("SELECT * FROM duckdb_indexes()").fetchall())

    print("\nViews:")
    print(conn.execute("SELECT * FROM duckdb_views()").fetchall())

    try:
        cols = conn.execute("PRAGMA table_info('ticks')").fetchall()
        print("\nTicks columns:")
        for col in cols:
            print(col)

        if any(col[1] == 'full_feed' for col in cols):
            print("\nAttempting to drop 'full_feed'...")
            conn.execute("ALTER TABLE ticks DROP COLUMN full_feed")
            print("Success!")
    except Exception as e:
        print(f"\nError: {e}")
    finally:
        conn.close()
else:
    print(f"Database not found at {DB_PATH}")
