"""
ProTrade Data Engine
Manages real-time data ingestion and OHLC aggregation.
"""
import asyncio
import json
import logging
import threading
import time
from datetime import datetime
from typing import Dict, Any, List, Optional, Union
from db.local_db import db, LocalDBJSONEncoder
from core.symbol_mapper import symbol_mapper
from core.utils import safe_int, safe_float
from core.provider_registry import live_stream_registry

logger = logging.getLogger(__name__)

# Configuration
try:
    from config import INITIAL_INSTRUMENTS, UPSTOX_INDEX_MAP
except ImportError:
    INITIAL_INSTRUMENTS = ["NSE:NIFTY"]
    UPSTOX_INDEX_MAP = {}

socketio_instance = None
main_event_loop = None
latest_total_volumes = {}
# Track subscribers per (instrumentKey, interval)
room_subscribers = {} # (instrumentKey, interval) -> set of sids
internal_tick_callbacks = []

def register_tick_callback(callback):
    if callback not in internal_tick_callbacks:
        internal_tick_callbacks.append(callback)

def get_primary_interval(instrument_key: str) -> str:
    """Find the smallest active interval for an instrument to act as the primary tick source."""
    instrument_key = instrument_key.upper()
    active = []
    for (ik, interval) in room_subscribers.keys():
        if ik == instrument_key:
            if interval.isdigit():
                active.append(int(interval))
            elif interval == 'D':
                active.append(1440)
    if not active: return "1"
    return str(min(active))

# Track last processed state to avoid redundant ticks
last_processed_tick = {} # instrumentKey -> {ts_ms, price, volume}

TICK_BATCH_SIZE = 100
tick_buffer = []
buffer_lock = threading.Lock()

def set_socketio(sio, loop=None):
    global socketio_instance, main_event_loop
    socketio_instance = sio
    main_event_loop = loop

def emit_event(event: str, data: Any, room: Optional[str] = None, hrn: Optional[str] = None):
    """
    Emits an event to a specific Socket.IO room.
    Optimized to only process and log if the room has active subscribers.
    """
    global socketio_instance, main_event_loop
    if not socketio_instance: return

    # Optimization: If room is provided, check if it has active subscribers before heavy JSON serialization
    if room:
        room_key = room.upper()
        # Find if any interval for this instrument has subscribers
        has_subscribers = False
        for (ik, interval), sids in room_subscribers.items():
            if ik == room_key and len(sids) > 0:
                has_subscribers = True
                break

        # Also check for exact room matches (some rooms might not be in room_subscribers dict if they are global)
        if not has_subscribers and room_key not in ["GLOBAL", "ALERTS"]:
            # If no one is listening to this specific instrument room, skip emission to save CPU/Network
            return

    if isinstance(data, (dict, list)):
        data = json.loads(json.dumps(data, cls=LocalDBJSONEncoder))
    try:
        if main_event_loop and main_event_loop.is_running():
            asyncio.run_coroutine_threadsafe(socketio_instance.emit(event, data, to=room), main_event_loop)
            if room:
                # Reduced log noise: only log if it's a primary instrument or has subscribers
                log_msg = f"Emitted {event} to room {room}"
                if hrn and hrn.upper() != room:
                    log_msg += f" ({hrn})"
                logger.debug(log_msg) # Changed to debug to keep console clean
    except Exception as e:
        logger.error(f"Emit Error: {e}")

def flush_tick_buffer():
    global tick_buffer
    to_insert = []
    with buffer_lock:
        if tick_buffer:
            to_insert = tick_buffer
            tick_buffer = []

    if to_insert:
        # Retry logic for DB insertion
        max_retries = 3
        for attempt in range(max_retries):
            try:
                db.insert_ticks(to_insert)
                logger.debug(f"Flushed {len(to_insert)} ticks to DB")
                return
            except Exception as e:
                logger.error(f"DB Insert Attempt {attempt+1} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(1) # Wait before retry
                else:
                    # Final failure - put data back into buffer so it's not lost
                    logger.error("Final DB insert failure. Returning ticks to buffer.")
                    with buffer_lock:
                        tick_buffer = to_insert + tick_buffer

def periodic_flush():
    """Background task to flush ticks every 10 seconds."""
    while True:
        try:
            time.sleep(10)
            flush_tick_buffer()
        except Exception as e:
            logger.error(f"Error in periodic_flush: {e}")
            time.sleep(5)

def periodic_maintenance():
    """Background task to optimize DB and cleanup old data."""
    # Wait for initial load
    time.sleep(60)
    while True:
        try:
            from config import DATABASE_CONFIG
            retention = DATABASE_CONFIG.get('retention_days', 30)
            db.cleanup_old_data(retention)
            db.optimize_storage()
            # Run every 24 hours
            time.sleep(24 * 3600)
        except Exception as e:
            logger.error(f"Error in periodic_maintenance: {e}")
            time.sleep(3600)

# Start background threads
threading.Thread(target=periodic_flush, daemon=True).start()
threading.Thread(target=periodic_maintenance, daemon=True).start()

last_emit_times = {}

def on_message(message: Union[Dict, str]):
    global tick_buffer
    try:
        data = json.loads(message) if isinstance(message, str) else message
        feeds_map = {}

        # Handle Chart/OHLCV Updates - Indices often update primarily here
        # This block extracts real-time OHLC data and converts it into synthetic ticks
        # if the standard tick feed is delayed or unavailable for the instrument.
        if data.get('type') == 'chart_update':
            instrument_key = data.get('instrumentKey')
            interval = str(data.get('interval', '1'))
            if instrument_key:
                payload = data['data']
                if isinstance(payload, dict):
                    payload['instrumentKey'] = instrument_key
                    payload['interval'] = interval

                # Multi-Room Emission System:
                # We emit to three different rooms to support various frontend components:
                # 1. Technical Key (e.g., NSE_INDEX|NIFTY 50) - used by low-level providers.
                # 2. Canonical Key (e.g., NSE:NIFTY) - used by the Main Terminal/Strategy.
                # 3. HRN (e.g., NIFTY) - used by the Options Dashboard for simplicity.
                hrn = symbol_mapper.get_hrn(instrument_key)
                internal_key = symbol_mapper.from_upstox_key(instrument_key)

                # 1. Technical Room
                emit_event('chart_update', payload, room=instrument_key.upper(), hrn=hrn)

                # 2. Canonical Room (e.g. NSE:NIFTY)
                if internal_key != instrument_key:
                    emit_event('chart_update', payload, room=internal_key.upper(), hrn=hrn)

                # 3. HRN Room (Human Readable Name)
                if hrn and hrn != instrument_key and hrn != internal_key:
                    emit_event('chart_update', payload, room=hrn.upper(), hrn=hrn)

                # Synthetic Tick Generation for indices from chart updates
                # Only generate ticks from the most granular (primary) interval to avoid double-counting
                if payload.get('ohlcv') and interval == get_primary_interval(instrument_key):
                    last_ohlcv = payload['ohlcv'][-1]
                    # Robust type casting using helpers
                    ts_ms = safe_int(last_ohlcv[0] * 1000 if last_ohlcv[0] is not None else time.time() * 1000)
                    price = safe_float(last_ohlcv[4])
                    volume = safe_float(last_ohlcv[5])

                    # Deduplicate: only process if price or volume or timestamp changed
                    prev = last_processed_tick.get(instrument_key, {})
                    if ts_ms != prev.get('ts_ms') or price != prev.get('price') or volume != prev.get('volume'):
                        # last_ohlcv format: [ts, o, h, l, c, v]
                        feeds_map[instrument_key] = {
                            'last_price': price,
                            'tv_volume': volume,
                            'ts_ms': ts_ms,
                            'source': 'tv_chart_fallback',
                            'interval': interval
                        }
                        last_processed_tick[instrument_key] = {'ts_ms': ts_ms, 'price': price, 'volume': volume}

        # Handle Standard Live Feeds (Quote session)
        if not feeds_map:
            feeds_map = data.get('feeds', {})
        if not feeds_map: return

        current_time = datetime.now()
        sym_feeds = {}
        today_str = current_time.strftime("%Y-%m-%d")

        for inst_key, feed_datum in feeds_map.items():
            # Standard Quote Feed Deduplication (in addition to Chart)
            if feed_datum.get('source') != 'tv_chart_fallback':
                # Robust type casting for quote fields using helpers
                ts_ms = safe_int(feed_datum.get('ts_ms') or time.time() * 1000)
                price = safe_float(feed_datum.get('last_price'))
                volume = safe_float(feed_datum.get('tv_volume'))

                prev = last_processed_tick.get(inst_key, {})
                if ts_ms == prev.get('ts_ms') and price == prev.get('price') and volume == prev.get('volume'):
                    continue # Skip redundant quote
                last_processed_tick[inst_key] = {'ts_ms': ts_ms, 'price': price, 'volume': volume}

            # Use technical symbol as is
            feed_datum.update({
                'instrumentKey': inst_key,
                'date': today_str,
                'last_price': safe_float(feed_datum.get('last_price')),
                'source': feed_datum.get('source', 'tv_wss')
            })

            ts_val = safe_int(feed_datum.get('ts_ms') or time.time() * 1000)
            if 0 < ts_val < 10000000000: ts_val *= 1000
            feed_datum['ts_ms'] = ts_val

            delta_vol = 0
            is_index = inst_key in UPSTOX_INDEX_MAP or "INDEX" in inst_key.upper()
            is_candle_source = feed_datum.get('source') == 'tv_chart_fallback'
            interval = str(feed_datum.get('interval', '1'))

            # Track daily and candle volumes separately, and per-interval for candles
            if is_candle_source:
                tracker_key = f"{inst_key}_{interval}_candle"
            else:
                tracker_key = f"{inst_key}_daily"

            # Use tv_volume if present, otherwise try upstox_volume
            curr_vol = feed_datum.get('tv_volume')
            if curr_vol is None:
                curr_vol = feed_datum.get('upstox_volume')

            if curr_vol is not None:
                curr_vol = safe_float(curr_vol)
                prev_vol = latest_total_volumes.get(tracker_key, 0)

                if prev_vol > 0:
                    # Detect reset (common in candle volume at the start of a new candle)
                    if is_candle_source and curr_vol < prev_vol * 0.5:
                        delta_vol = curr_vol
                    else:
                        delta_vol = max(0, curr_vol - prev_vol)
                else:
                    # First time seeing this source for this instrument
                    delta_vol = 0

                latest_total_volumes[tracker_key] = curr_vol

            # Special case for Index synthetic volume:
            # only force it if no other real volume has been detected for this tick
            # and only if it's a new timestamp to avoid over-inflation from multiple updates to the same candle
            if is_index and delta_vol <= 0 and is_candle_source:
                prev_ts = last_processed_tick.get(inst_key, {}).get('ts_ms')
                if ts_val != prev_ts:
                    delta_vol = 1

            # Final safety check: Clamp extreme LTQ that would ruin chart scaling
            # Unless it's a known liquid stock, anything > 5M in a single tick is likely a calculation error
            if delta_vol > 5000000:
                logger.warning(f"Extreme volume detected for {inst_key}: {delta_vol}. Clamping.")
                delta_vol = 100 if is_index else delta_vol % 10000

            feed_datum['ltq'] = safe_int(delta_vol)
            sym_feeds[inst_key] = feed_datum

        # Throttled UI Emission
        now = time.time()
        if now - last_emit_times.get('GLOBAL_TICK', 0) > 0.05:
            for inst_key, feed in sym_feeds.items():
                hrn = symbol_mapper.get_hrn(inst_key)
                internal_key = symbol_mapper.from_upstox_key(inst_key)

                # 1. Emit to provider-specific room (Technical Key)
                emit_event('raw_tick', {inst_key: feed}, room=inst_key.upper(), hrn=hrn)

                # 2. Emit to internal canonical room (e.g. NSE:NIFTY)
                if internal_key != inst_key:
                    emit_event('raw_tick', {internal_key: feed}, room=internal_key.upper(), hrn=hrn)

                # 3. Emit to HRN-based room (Human Readable Name)
                if hrn and hrn != inst_key and hrn != internal_key:
                    emit_event('raw_tick', {hrn: feed}, room=hrn.upper(), hrn=hrn)

            last_emit_times['GLOBAL_TICK'] = now

        with buffer_lock:
            tick_buffer.extend(list(sym_feeds.values()))
            if len(tick_buffer) >= TICK_BATCH_SIZE:
                threading.Thread(target=flush_tick_buffer, daemon=True).start()

        # Internal callbacks
        for cb in internal_tick_callbacks:
            try:
                cb(sym_feeds)
            except Exception as e:
                logger.error(f"Error in internal tick callback: {e}")

    except Exception as e:
        logger.error(f"Error in data_engine on_message: {e}")

def subscribe_instrument(instrument_key: str, sid: str, interval: str = "1"):
    instrument_key = instrument_key.upper()

    # If the key is an HRN, resolve it to the technical key for the provider
    if '|' not in instrument_key and ':' not in instrument_key:
        resolved = symbol_mapper.resolve_to_key(instrument_key)
        if resolved:
            logger.info(f"Resolved HRN {instrument_key} to technical key {resolved}")
            instrument_key = resolved.upper()

    key = (instrument_key, str(interval))
    if key not in room_subscribers:
        room_subscribers[key] = set()
    if sid not in room_subscribers[key]:
        room_subscribers[key].add(sid)
        logger.info(f"Room {instrument_key} ({interval}m) now has {len(room_subscribers[key])} subscribers")
    for provider in live_stream_registry.get_all():
        try:
            provider.set_callback(on_message)
            provider.start()
            provider.subscribe([instrument_key], interval=interval)
        except Exception as e:
            logger.error(f"Error subscribing via provider: {e}")

def is_sid_using_instrument(sid: str, instrument_key: str) -> bool:
    """Check if a specific client is still using this instrument in any interval."""
    instrument_key = instrument_key.upper()
    for (r_key, r_interval), sids in room_subscribers.items():
        if r_key == instrument_key and sid in sids:
            return True
    return False

def unsubscribe_instrument(instrument_key: str, sid: str, interval: str = "1"):
    instrument_key = instrument_key.upper()

    # Same resolution logic for unsubscription consistency
    if '|' not in instrument_key and ':' not in instrument_key:
        resolved = symbol_mapper.resolve_to_key(instrument_key)
        if resolved:
            instrument_key = resolved.upper()

    key = (instrument_key, str(interval))
    if key in room_subscribers and sid in room_subscribers[key]:
        room_subscribers[key].remove(sid)
        logger.info(f"Room {instrument_key} ({interval}m) now has {len(room_subscribers[key])} subscribers")
        if len(room_subscribers[key]) == 0:
            logger.info(f"Unsubscribing from {instrument_key} ({interval}m) as no more subscribers")
            for provider in live_stream_registry.get_all():
                try:
                    provider.unsubscribe(instrument_key, interval=interval)
                except Exception as e:
                    logger.error(f"Error unsubscribing via provider: {e}")
            del room_subscribers[key]

def handle_disconnect(sid: str):
    """Cleanup all subscriptions for a disconnected client."""
    to_cleanup = []
    for (key, interval), sids in room_subscribers.items():
        if sid in sids:
            to_cleanup.append((key, interval))

    for key, interval in to_cleanup:
        unsubscribe_instrument(key, sid, interval)

def start_websocket_thread(keys: Optional[List[str]] = None):
    """Initializes and starts all registered live stream providers."""
    from core.provider_registry import initialize_default_providers
    initialize_default_providers()
    subscribe_keys = keys or INITIAL_INSTRUMENTS
    for provider in live_stream_registry.get_all():
        try:
            provider.set_callback(on_message)
            provider.start()
            provider.subscribe(subscribe_keys)
        except Exception as e:
            logger.error(f"Error starting provider during init: {e}")
