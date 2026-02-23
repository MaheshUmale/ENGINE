"""
DuckDB-based Local Database implementation.
Provides an optimized columnar data store for high-frequency tick data.
"""
import duckdb
import os
import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
import threading
import pandas as pd
from core.utils import safe_int, safe_float

logger = logging.getLogger(__name__)

import numpy as np

class LocalDBJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime): return obj.isoformat()
        if isinstance(obj, (float, np.float64, np.float32)):
            if not np.isfinite(obj): return None
        return super().default(obj)

DB_PATH = os.getenv('DUCKDB_PATH', 'pro_trade.db')

class LocalDB:
    _instance = None
    _singleton_lock = threading.Lock()
    _execute_lock = threading.Lock()
    _batch_count = 0

    def __new__(cls):
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = super(LocalDB, cls).__new__(cls)
                cls._instance._init_db()
        return cls._instance

    def _init_db(self):
        self.conn = duckdb.connect(DB_PATH)
        self.conn.execute("SET memory_limit = '1GB'")
        self.conn.execute("SET threads = 4")
        self.conn.execute("SET TimeZone='UTC'")
        self.conn.execute("SET preserve_insertion_order = false")

        # Check and load extensions to avoid slow INSTALL calls on every boot
        try:
            ext_info = self.conn.execute("SELECT extension_name, installed FROM duckdb_extensions() WHERE extension_name IN ('json', 'icu')").fetchall()
            ext_map = {name: installed for name, installed in ext_info}

            if not ext_map.get('json'):
                logger.info("Installing json extension...")
                self.conn.execute("INSTALL json")
            self.conn.execute("LOAD json")

            if not ext_map.get('icu'):
                logger.info("Installing icu extension...")
                self.conn.execute("INSTALL icu")
            self.conn.execute("LOAD icu")
        except Exception as e:
            logger.warning(f"Error loading extensions: {e}. Attempting direct LOAD...")
            try:
                self.conn.execute("LOAD json")
                self.conn.execute("LOAD icu")
            except:
                logger.error("Failed to load extensions.")

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS ticks (
                date DATE,
                instrumentKey VARCHAR,
                ts_ms BIGINT,
                price DOUBLE,
                qty BIGINT,
                source VARCHAR,
                full_feed JSON
            )
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_ticks_key_ts ON ticks (instrumentKey, ts_ms)")

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS metadata (
                instrument_key VARCHAR PRIMARY KEY,
                hrn VARCHAR,
                meta JSON,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Options data for analysis
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS options_snapshots (
                timestamp TIMESTAMP,
                underlying VARCHAR,
                symbol VARCHAR,
                expiry DATE,
                strike DOUBLE,
                option_type VARCHAR,
                oi BIGINT,
                oi_change BIGINT,
                volume BIGINT,
                ltp DOUBLE,
                iv DOUBLE,
                delta DOUBLE,
                gamma DOUBLE,
                theta DOUBLE,
                vega DOUBLE,
                intrinsic_value DOUBLE,
                time_value DOUBLE,
                source VARCHAR
            )
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_opt_snap_ts ON options_snapshots (timestamp, underlying)")

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS pcr_history (
                timestamp TIMESTAMP,
                underlying VARCHAR,
                pcr_oi DOUBLE,
                pcr_vol DOUBLE,
                pcr_oi_change DOUBLE,
                underlying_price DOUBLE,
                max_pain DOUBLE,
                spot_price DOUBLE,
                total_oi BIGINT,
                total_oi_change BIGINT
            )
        """)

        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_pcr_hist_ts ON pcr_history (timestamp, underlying)")

        self._migrate_db()
        logger.info(f"Local DuckDB initialized at {DB_PATH}")

    def _migrate_db(self):
        """Add missing columns to existing tables."""
        # 1. options_snapshots
        try:
            cols = [c['column_name'] for c in self.get_table_schema('options_snapshots')]
            missing_snapshot_cols = {
                'delta': 'DOUBLE',
                'gamma': 'DOUBLE',
                'theta': 'DOUBLE',
                'vega': 'DOUBLE',
                'intrinsic_value': 'DOUBLE',
                'time_value': 'DOUBLE',
                'source': 'VARCHAR'
            }
            for col, dtype in missing_snapshot_cols.items():
                if col not in cols:
                    logger.info(f"Migrating: Adding {col} to options_snapshots")
                    self.conn.execute(f"ALTER TABLE options_snapshots ADD COLUMN {col} {dtype}")
        except Exception as e:
            logger.error(f"Error migrating options_snapshots: {e}")

        # 2. pcr_history
        try:
            cols = [c['column_name'] for c in self.get_table_schema('pcr_history')]
            missing_pcr_cols = {
                'pcr_oi_change': 'DOUBLE',
                'underlying_price': 'DOUBLE',
                'spot_price': 'DOUBLE',
                'total_oi': 'BIGINT',
                'total_oi_change': 'BIGINT'
            }
            for col, dtype in missing_pcr_cols.items():
                if col not in cols:
                    logger.info(f"Migrating: Adding {col} to pcr_history")
                    self.conn.execute(f"ALTER TABLE pcr_history ADD COLUMN {col} {dtype}")
        except Exception as e:
            logger.error(f"Error migrating pcr_history: {e}")

    def insert_ticks(self, ticks: List[Dict[str, Any]]):
        if not ticks: return
        data = []
        for t in ticks:
            # Robust type casting using shared utilities
            price = safe_float(t.get('last_price'))
            qty = safe_int(t.get('ltq'))
            ts_ms = safe_int(t.get('ts_ms'))

            data.append({
                'date': t.get('date', datetime.now().strftime('%Y-%m-%d')),
                'instrumentKey': t.get('instrumentKey'),
                'ts_ms': ts_ms,
                'price': price,
                'qty': qty,
                'source': t.get('source', 'live'),
                'full_feed': json.dumps(t, cls=LocalDBJSONEncoder)
            })

        df = pd.DataFrame(data)
        with self._execute_lock:
            self.conn.execute("INSERT INTO ticks SELECT * FROM df")
            self._batch_count += 1
            if self._batch_count >= 10:
                self.conn.execute("CHECKPOINT")
                self._batch_count = 0

    def update_metadata(self, instrument_key: str, hrn: str, meta: Dict[str, Any]):
        meta_json = json.dumps(meta)
        with self._execute_lock:
            self.conn.execute("""
                INSERT OR REPLACE INTO metadata (instrument_key, hrn, meta, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            """, (instrument_key, hrn, meta_json))

    def bulk_update_metadata(self, batch: List[Dict[str, Any]]):
        """Bulk updates instrument metadata from a list of dicts."""
        if not batch: return
        try:
            data = []
            for item in batch:
                data.append({
                    'instrument_key': item['instrument_key'],
                    'hrn': item['hrn'],
                    'meta': json.dumps(item['meta'])
                })
            df = pd.DataFrame(data)
            with self._execute_lock:
                self.conn.execute("""
                    INSERT OR REPLACE INTO metadata (instrument_key, hrn, meta, updated_at)
                    SELECT instrument_key, hrn, meta, CURRENT_TIMESTAMP FROM df
                """)
        except Exception as e:
            logger.error(f"Bulk metadata update failed: {e}")

    def get_metadata(self, instrument_key: str) -> Optional[Dict[str, Any]]:
        with self._execute_lock:
            res = self.conn.execute("SELECT hrn, meta FROM metadata WHERE instrument_key = ?", (instrument_key,)).fetchone()
        if res: return {'hrn': res[0], 'metadata': json.loads(res[1])}
        return None

    def execute(self, sql: str, params: tuple = ()):
        with self._execute_lock:
            self.conn.execute(sql, params)

    def query(self, sql: str, params: tuple = (), json_serialize: bool = False) -> List[Dict[str, Any]]:
        with self._execute_lock:
            df = self.conn.execute(sql, params).fetch_df()

        # Ensure all datetime columns are UTC-aware
        for col in df.select_dtypes(include=['datetime64']).columns:
            if df[col].dt.tz is None:
                df[col] = df[col].dt.tz_localize('UTC')
            else:
                df[col] = df[col].dt.tz_convert('UTC')

        if json_serialize:
            # Use pandas to_json to handle NaN/nulls correctly for API consumption
            return json.loads(df.to_json(orient='records', date_format='iso'))

        return df.to_dict('records')

    def get_tables(self) -> List[str]:
        with self._execute_lock:
            df = self.conn.execute("SHOW TABLES").fetch_df()
        return df['name'].tolist() if not df.empty else []

    def get_table_schema(self, table_name: str, json_serialize: bool = False) -> List[Dict[str, Any]]:
        with self._execute_lock:
            # DESCRIBE returns column_name, column_type, null, key, default, extra
            # Wrap table name in double quotes for safety
            df = self.conn.execute(f'DESCRIBE "{table_name}"').fetch_df()

        if json_serialize:
            # Use pandas to_json to handle NaN/nulls correctly for API consumption
            return json.loads(df.to_json(orient='records', date_format='iso'))

        return df.to_dict('records')

    def insert_options_snapshot(self, data: List[Dict[str, Any]]):
        if not data: return
        cols = [
            'timestamp', 'underlying', 'symbol', 'expiry', 'strike', 'option_type',
            'oi', 'oi_change', 'volume', 'ltp', 'iv', 'delta', 'gamma', 'theta',
            'vega', 'intrinsic_value', 'time_value', 'source'
        ]
        # Ensure all columns exist in data and have correct types
        for item in data:
            for c in cols:
                if c not in item:
                    item[c] = None

            # Robust type casting for critical numeric fields to prevent downstream failures
            item['oi'] = safe_int(item.get('oi'))
            item['oi_change'] = safe_int(item.get('oi_change'))
            item['volume'] = safe_int(item.get('volume'))
            item['strike'] = safe_float(item.get('strike'))
            item['ltp'] = safe_float(item.get('ltp'))

        df = pd.DataFrame(data)[cols]
        # Explicitly convert timestamp to naive datetime objects to avoid DuckDB conversion errors
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp']).dt.tz_localize(None)

        with self._execute_lock:
            # Register the dataframe to ensure types are correctly mapped
            self.conn.register('df_view', df)
            self.conn.execute(f"INSERT INTO options_snapshots ({', '.join(cols)}) SELECT * FROM df_view")
            self.conn.unregister('df_view')

    def insert_pcr_history(self, record: Dict[str, Any]):
        cols = ['timestamp', 'underlying', 'pcr_oi', 'pcr_vol', 'pcr_oi_change', 'underlying_price', 'max_pain', 'spot_price', 'total_oi', 'total_oi_change']

        # Ensure all columns exist and use safe casting for numeric fields
        for c in cols:
            if c in ['timestamp', 'underlying']:
                continue
            if 'pcr' in c or 'price' in c or 'pain' in c:
                record[c] = safe_float(record.get(c))
            else:
                record[c] = safe_int(record.get(c))

        df = pd.DataFrame([record])[cols]
        # Explicitly convert timestamp to naive datetime objects to avoid DuckDB conversion errors
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp']).dt.tz_localize(None)

        with self._execute_lock:
            # Register the dataframe to ensure types are correctly mapped
            self.conn.register('df_view_pcr', df)
            self.conn.execute(f"INSERT INTO pcr_history ({', '.join(cols)}) SELECT * FROM df_view_pcr")
            self.conn.unregister('df_view_pcr')

    def cleanup_old_data(self, days: int = 30):
        """Deletes ticks older than X days to keep the DB size manageable."""
        with self._execute_lock:
            try:
                self.conn.execute(f"DELETE FROM ticks WHERE date < CURRENT_DATE - INTERVAL '{days} days'")
                self.conn.execute("CHECKPOINT")
                logger.info(f"Cleaned up ticks older than {days} days")
            except Exception as e:
                logger.error(f"Cleanup error: {e}")

    def optimize_storage(self):
        """Performs a vacuum-like optimization by re-sorting ticks by instrument and timestamp."""
        with self._execute_lock:
            try:
                logger.info("Optimizing data storage for replay...")
                # DuckDB doesn't have CLUSTER, so we recreate the table sorted
                self.conn.execute("CREATE TABLE ticks_new AS SELECT * FROM ticks ORDER BY instrumentKey, ts_ms")
                self.conn.execute("DROP TABLE ticks")
                self.conn.execute("ALTER TABLE ticks_new RENAME TO ticks")
                self.conn.execute("CREATE INDEX IF NOT EXISTS idx_ticks_key_ts ON ticks (instrumentKey, ts_ms)")
                self.conn.execute("CHECKPOINT")
                logger.info("Storage optimization complete.")
            except Exception as e:
                logger.error(f"Optimization error: {e}")

db = LocalDB()
