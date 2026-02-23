import logging
import httpx
import gzip
import io
import pandas as pd
from datetime import datetime
from db.local_db import db
from core.symbol_mapper import symbol_mapper

logger = logging.getLogger(__name__)

class InstrumentManager:
    EXCHANGES = ["NSE", "NFO", "BSE", "BFO"]
    BASE_URL = "https://assets.upstox.com/market-quote/instruments/exchange/{}.json.gz"

    async def fetch_and_store_instruments(self, force=False):
        """Downloads instrument files from Upstox and stores them in metadata table."""
        if not force:
            # Check if already synced today
            try:
                res = db.query("SELECT MAX(updated_at) as last_sync FROM metadata")
                if res and res[0]['last_sync']:
                    last_sync = res[0]['last_sync']
                    if not isinstance(last_sync, datetime):
                        # Handle string if necessary
                        from pandas import Timestamp
                        if isinstance(last_sync, Timestamp):
                            last_sync = last_sync.to_pydatetime()
                        else:
                            last_sync = datetime.fromisoformat(str(last_sync))

                    if last_sync.date() == datetime.now().date():
                        logger.info("Upstox instrument master already synced today. Skipping.")
                        return
            except Exception as e:
                logger.warning(f"Failed to check last sync date: {e}")

        logger.info("Starting Upstox instrument master sync...")
        total_count = 0

        async with httpx.AsyncClient() as client:
            for exchange in self.EXCHANGES:
                try:
                    url = self.BASE_URL.format(exchange)
                    logger.info(f"Fetching instruments for {exchange} from {url}")
                    response = await client.get(url, timeout=60.0)
                    if response.status_code != 200:
                        logger.warning(f"Failed to fetch instruments for {exchange}: {response.status_code}")
                        continue

                    with gzip.GzipFile(fileobj=io.BytesIO(response.content)) as f:
                        df = pd.read_json(f)

                    if df.empty:
                        logger.info(f"No instruments found for {exchange}")
                        continue

                    count = self._process_df(df)
                    total_count += count
                    logger.info(f"Successfully loaded {count} instruments for {exchange}")

                except Exception as e:
                    logger.error(f"Error syncing instruments for {exchange}: {e}")

        logger.info(f"Instrument master sync complete. Total instruments: {total_count}")

    def _process_df(self, df: pd.DataFrame) -> int:
        """Processes the dataframe and updates metadata table in bulk."""
        count = 0

        # Optimize by converting to dict records first
        records = df.to_dict('records')
        batch = []

        for row in records:
            ikey = row.get('instrument_key')
            if not ikey: continue

            # Format expiry correctly
            expiry = row.get('expiry')
            if expiry and not pd.isna(expiry):
                try:
                    if isinstance(expiry, (int, float)):
                        expiry = datetime.fromtimestamp(expiry / 1000).strftime('%Y-%m-%d')
                    else:
                        expiry = str(expiry).split('T')[0]
                except:
                    pass

            meta = {
                'symbol': row.get('name'),
                'trading_symbol': row.get('trading_symbol'),
                'type': row.get('instrument_type'),
                'expiry': expiry,
                'strike': row.get('strike_price'),
                'lot_size': row.get('lot_size'),
                'tick_size': row.get('tick_size'),
                'exchange': row.get('exchange'),
                'segment': row.get('segment')
            }

            # Use SymbolMapper to generate HRN
            hrn = symbol_mapper._generate_hrn(ikey, meta)

            batch.append({
                'instrument_key': ikey,
                'hrn': hrn,
                'meta': meta
            })

            if len(batch) >= 2000: # Slightly larger batch for better perf
                db.bulk_update_metadata(batch)
                count += len(batch)
                batch = []

        if batch:
            db.bulk_update_metadata(batch)
            count += len(batch)

        return count

instrument_manager = InstrumentManager()
