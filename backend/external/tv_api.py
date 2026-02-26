import logging
try:
    from tvDatafeed import TvDatafeed, Interval
except ImportError:
    TvDatafeed = None
    Interval = None
from tradingview_scraper.symbols.stream import Streamer
import logging
import os
import contextlib
import io
import time
from datetime import datetime
import re
import inspect
from config import TV_COOKIE

logger = logging.getLogger(__name__)

class TradingViewAPI:
    def __init__(self):
        username = os.getenv('TV_USERNAME')
        password = os.getenv('TV_PASSWORD')
        if TvDatafeed:
            # Safely initialize TvDatafeed based on supported arguments
            try:
                sig = inspect.signature(TvDatafeed.__init__)
                if 'cookies' in sig.parameters and TV_COOKIE:
                    self.tv = TvDatafeed(username, password) if username and password else TvDatafeed(cookies=TV_COOKIE)
                    logger.info("TradingViewAPI initialized with tvDatafeed (using cookies)")
                else:
                    self.tv = TvDatafeed(username, password)
                    logger.info("TradingViewAPI initialized with tvDatafeed")
            except Exception as e:
                logger.warning(f"TvDatafeed init failed, falling back to basic: {e}")
                self.tv = TvDatafeed(username, password)
        else:
            self.tv = None
            logger.warning("tvDatafeed not installed, falling back to Streamer only")

        self._init_streamer()

    def _init_streamer(self):
        try:
            self.streamer = Streamer(export_result=False)
        except Exception as e:
            logger.error(f"Failed to initialize TV Streamer: {e}")
            self.streamer = None

    def get_hist_candles(self, symbol_or_hrn, interval_min='1', n_bars=5000):
        try:
            from core.symbol_mapper import symbol_mapper
            logger.info(f"Fetching historical candles for {symbol_or_hrn} (bars={n_bars})")
            if not symbol_or_hrn: return None

            # Centralized mapping to TV symbol (e.g. NSE:NIFTY)
            tv_full_symbol = symbol_mapper.to_tv_symbol(symbol_or_hrn)

            if ':' in tv_full_symbol:
                parts = tv_full_symbol.split(':')
                tv_exchange = parts[0]
                tv_symbol = parts[1]
            else:
                tv_exchange = 'NSE'
                tv_symbol = tv_full_symbol

            logger.info(f"Mapped {symbol_or_hrn} -> {tv_exchange}:{tv_symbol}")

            # 1. Try tvDatafeed first for historical data (more stable for one-offs)
            if self.tv:
                try:
                    tv_interval = Interval.in_1_minute
                    if interval_min == '3': tv_interval = Interval.in_3_minute
                    elif interval_min == '5': tv_interval = Interval.in_5_minute
                    elif interval_min == '15': tv_interval = Interval.in_15_minute
                    elif interval_min == '30': tv_interval = Interval.in_30_minute
                    elif interval_min == '45': tv_interval = Interval.in_45_minute
                    elif interval_min == '60': tv_interval = Interval.in_1_hour
                    elif interval_min == '120': tv_interval = Interval.in_2_hour
                    elif interval_min == '240': tv_interval = Interval.in_4_hour
                    elif interval_min == 'D' or interval_min == '1d': tv_interval = Interval.in_daily
                    elif interval_min == 'W' or interval_min == '1w': tv_interval = Interval.in_weekly

                    # tvDatafeed can be sensitive to case and exchange
                    df = self.tv.get_hist(symbol=tv_symbol, exchange=tv_exchange, interval=tv_interval, n_bars=n_bars)
                    if df is not None and not df.empty:
                        candles = []
                        import pytz
                        ist = pytz.timezone('Asia/Kolkata')
                        for ts, row in df.iterrows():
                            try:
                                ts_ist = ist.localize(ts) if ts.tzinfo is None else ts.astimezone(ist)
                                unix_ts = int(ts_ist.timestamp())
                            except:
                                unix_ts = int(ts.timestamp())

                            candles.append([
                                unix_ts,
                                float(row['open']), float(row['high']), float(row['low']), float(row['close']),
                                float(row['volume'])
                            ])
                        logger.info(f"Retrieved {len(candles)} candles via tvDatafeed for {tv_exchange}:{tv_symbol}")
                        return candles[::-1] # Newest first
                except Exception as tv_e:
                    logger.warning(f"tvDatafeed failed for {tv_symbol}: {tv_e}")

            # 2. Fallback to Streamer
            try:
                tf = f"{interval_min}m"
                if interval_min == 'D': tf = '1d'
                elif interval_min == 'W': tf = '1w'
                elif interval_min == '60': tf = '1h'
                elif interval_min == '120': tf = '2h'
                elif interval_min == '240': tf = '4h'

                logger.info(f"Using timeframe {tf} for Streamer fallback (interval_min={interval_min})")
                if not self.streamer: self._init_streamer()

                with contextlib.redirect_stdout(io.StringIO()):
                    stream = self.streamer.stream(
                        exchange=tv_exchange,
                        symbol=tv_symbol,
                        timeframe=tf,
                        numb_price_candles=n_bars
                    )

                data = None
                for item in stream:
                    if 'ohlc' in item:
                        data = item
                        break

                if data and 'ohlc' in data:
                    candles = []
                    import pytz
                    ist = pytz.timezone('Asia/Kolkata')
                    for row in data['ohlc']:
                        ts = row.get('timestamp') or row.get('datetime')
                        if not isinstance(ts, (int, float)):
                            try:
                                # TradingView Scraper often returns timestamps in local exchange time
                                # if they are string-formatted without offset.
                                # For NSE, it's usually IST.
                                dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                                if 'Z' not in ts and '+' not in ts:
                                    # Assume it was IST if no offset provided
                                    dt = ist.localize(dt.replace(tzinfo=None))
                                ts = int(dt.timestamp())
                            except Exception as e:
                                logger.debug(f"TV Streamer timestamp parse error: {e}")

                        candles.append([
                            int(ts),
                            float(row['open']), float(row['high']), float(row['low']), float(row['close']),
                            float(row['volume'])
                        ])
                    logger.info(f"Retrieved {len(candles)} candles via Streamer")
                    return candles[::-1] # Newest first
            except Exception as e:
                logger.warning(f"Streamer failed for {tv_symbol}: {e}")

            # 3. Final Fallback to Local DB (for Replay support or when TV is down)
            try:
                from db.local_db import db
                orig_key = symbol_or_hrn
                # Try with multiple variations for matching
                possible_keys = [orig_key, f"{tv_exchange}:{tv_symbol}", tv_symbol, f"{tv_exchange}|{tv_symbol}"]
                # Also try Upstox mapped key
                up_key = symbol_mapper.to_upstox_key(orig_key)
                if up_key not in possible_keys: possible_keys.append(up_key)

                res = None
                for k in possible_keys:
                    logger.info(f"Falling back to local DB for {k}")
                    interval_map = {'1': 60, '5': 300, '15': 900, '30': 1800, '60': 3600, 'D': 86400}
                    duration = interval_map.get(interval_min, 60)

                    res = db.query(f"""
                        SELECT
                            (ts_ms / 1000 / {duration}) * {duration} as bucket,
                            arg_min(price, ts_ms) as o,
                            MAX(price) as h,
                            MIN(price) as l,
                            arg_max(price, ts_ms) as c,
                            SUM(qty) as v
                        FROM ticks
                        WHERE instrumentKey = ?
                        GROUP BY bucket
                        ORDER BY bucket DESC
                        LIMIT ?
                    """, (k, n_bars))
                    if res: break

                if res:
                    candles = [[int(r['bucket']), float(r['o']), float(r['h']), float(r['l']), float(r['c']), float(r['v'])] for r in res]
                    logger.info(f"Retrieved {len(candles)} candles via local DB")
                    return candles # Already newest first from query
            except Exception as db_e:
                logger.warning(f"Local DB fallback failed: {db_e}")

            return None
        except Exception as e:
            logger.error(f"Error fetching TradingView data: {e}")
            return None

tv_api = TradingViewAPI()
