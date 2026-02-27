"""
Enhanced ProTrade API Server
Optimized, Organized, and Simplified for high-performance trading analytics.
"""

import os
import asyncio
import logging
import httpx
import pandas as pd
import io
import socketio
from datetime import datetime
from typing import Any, Optional, List
from contextlib import asynccontextmanager
from logging.config import dictConfig
from urllib.parse import unquote
import re

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from config import LOGGING_CONFIG, INITIAL_INSTRUMENTS, SERVER_PORT
from core import data_engine
from core.provider_registry import initialize_default_providers, historical_data_registry, options_data_registry
from core.options_manager import options_manager
from core.symbol_mapper import symbol_mapper
from core.greeks_calculator import greeks_calculator
from core.strategy_builder import strategy_builder, StrategyType
from core.alert_system import alert_system, AlertType
from brain.nse_confluence_scalper import scalper
from symmetry_engine.main import TradingBot
from symmetry_engine.database import get_session, Signal, Trade, ReferenceLevel
from external.tv_api import tv_api
from external.tv_scanner import search_options
from db.local_db import db

# ==================== UTILS & CACHING ====================

class APICache:
    """Simple TTL cache to reduce redundant computations and DB queries."""
    def __init__(self, ttl_seconds=60):
        self.cache = {}
        self.ttl = ttl_seconds

    def get(self, key):
        if key in self.cache:
            val, ts = self.cache[key]
            if datetime.now().timestamp() - ts < self.ttl:
                return val
            del self.cache[key]
        return None

    def set(self, key, value):
        self.cache[key] = (value, datetime.now().timestamp())

# Specialized caches
hist_cache = APICache(ttl_seconds=30)
pcr_cache = APICache(ttl_seconds=60)

def format_error(e: Exception, message: str = "Internal Server Error"):
    logging.error(f"{message}: {str(e)}")
    return {"status": "error", "message": str(e)}

def validate_sql(sql: str):
    """
    SECURITY: Basic validation to ensure only SELECT queries are executed via the API.
    Prevents DML/DDL operations from being triggered via the unauthenticated DB Explorer.
    """
    forbidden = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE", "REPLACE"]
    # Ensure it starts with SELECT
    if not re.match(r"^\s*SELECT\b", sql, re.IGNORECASE):
        raise HTTPException(400, "Only SELECT queries are allowed via this endpoint")
    # Check for forbidden keywords with word boundaries
    for word in forbidden:
        if re.search(rf"\b{word}\b", sql, re.IGNORECASE):
            raise HTTPException(400, f"Query contains forbidden keyword: {word}")

# ==================== INITIALIZATION ====================

dictConfig(LOGGING_CONFIG)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle management for the Trading Terminal."""
    logger.info("Initializing ProTrade Terminal Services...")
    global main_loop

    # Initialize Symmetry Database early to avoid race conditions
    from symmetry_engine.database import init_db
    init_db()

    # Sync instruments from Upstox in the background
    from core.instrument_manager import instrument_manager
    asyncio.create_task(instrument_manager.fetch_and_store_instruments())

    initialize_default_providers()
    main_loop = asyncio.get_running_loop()

    data_engine.set_socketio(sio, loop=main_loop)
    data_engine.start_websocket_thread(INITIAL_INSTRUMENTS)

    options_manager.set_socketio(sio, loop=main_loop)
    await options_manager.start()

    scalper.set_socketio(sio, loop=main_loop)

    # Initialize and start Symmetry Trading Bot
    bot = TradingBot(loop=main_loop)
    from core.data_engine import register_tick_callback
    register_tick_callback(bot.handle_tick_sync)
    asyncio.create_task(bot.run())

    yield

    logger.info("Shutting down ProTrade Terminal...")
    try:
        await options_manager.stop()
        data_engine.flush_tick_buffer()
    except Exception as e:
        logger.error(f"Shutdown error: {e}")

fastapi_app = FastAPI(title="ProTrade Enhanced API", lifespan=lifespan)
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*', ping_timeout=60, ping_interval=25)
main_loop = None

# SECURITY: Restricted CORS origins to prevent cross-site request forgery and unauthorized access
# from malicious websites when the server is running on a local machine.
fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:3001", "http://127.0.0.1:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory="backend/templates")

# ==================== SOCKET.IO HANDLERS ====================

@sio.event
async def connect(sid, environ): logger.info(f"Client connected: {sid}")

@sio.event
async def disconnect(sid):
    logger.info(f"Client disconnected: {sid}")
    data_engine.handle_disconnect(sid)

@sio.on('subscribe')
async def handle_subscribe(sid, data):
    keys = data.get('instrumentKeys', [])
    interval = str(data.get('interval', '1'))
    for key in keys:
        k = key.upper()
        await sio.enter_room(sid, k)
        data_engine.subscribe_instrument(k, sid, interval=interval)

@sio.on('subscribe_options')
async def handle_subscribe_options(sid, data):
    underlying = data.get('underlying')
    if underlying: await sio.enter_room(sid, f"options_{underlying}")

@sio.on('unsubscribe_options')
async def handle_unsubscribe_options(sid, data):
    underlying = data.get('underlying')
    if underlying: await sio.leave_room(sid, f"options_{underlying}")

@sio.on('unsubscribe')
async def handle_unsubscribe(sid, data):
    keys = data.get('instrumentKeys', [])
    interval = str(data.get('interval', '1'))
    for key in keys:
        k = key.upper()
        data_engine.unsubscribe_instrument(k, sid, interval=interval)
        if not data_engine.is_sid_using_instrument(sid, k):
            await sio.leave_room(sid, k)

# ==================== CORE API ====================

@fastapi_app.get("/health")
async def health_check():
    return {"status": "healthy", "version": "3.0-optimized"}

@fastapi_app.get("/api/tv/search")
async def tv_search(text: str = Query(..., min_length=1)):
    """Proxies TradingView symbol search and merges local options results."""
    exchange = ""
    search_text = text
    if ":" in text:
        exchange, search_text = text.split(":", 1)

    url = f"https://symbol-search.tradingview.com/symbol_search/v3/?text={search_text}&hl=1&exchange={exchange}&lang=en&search_type=&domain=production&sort_by_country=IN"
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.tradingview.com/'}

    tv_results = {"symbols": []}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, timeout=5.0)
            if resp.status_code == 200: tv_results = resp.json()
    except Exception as e: logger.error(f"Search proxy error: {e}")

    # Merge options
    upper_text = search_text.upper()
    underlying = next((idx for idx in ["NIFTY", "BANKNIFTY"] if idx in upper_text), None)
    if not underlying and 3 <= len(upper_text) <= 15 and upper_text.isalpha(): underlying = upper_text

    if underlying:
        try:
            opt_data = await search_options(underlying)
            if opt_data and 'symbols' in opt_data:
                parts = upper_text.split()
                filtered = []
                for item in opt_data['symbols']:
                    s = item.get('s', '')
                    if all(p in s.upper().replace(":", "") for p in parts):
                        exch, name = s.split(':', 1) if ':' in s else ("NSE", s)
                        filtered.append({"symbol": name, "description": f"{name} Option", "exchange": exch, "type": "option"})

                existing = {s['symbol'] for s in tv_results.get('symbols', [])}
                tv_results['symbols'] = [f for f in filtered[:100] if f['symbol'] not in existing] + tv_results.get('symbols', [])
        except Exception as e: logger.error(f"Options merging error: {e}")

    return tv_results

@fastapi_app.get("/api/tv/intraday/{instrument_key}")
async def get_intraday(
    instrument_key: str,
    interval: str = '1',
    rvol_len: Optional[int] = None,
    rvol_threshold: Optional[float] = None,
    bubble_threshold: Optional[float] = None,
    ray_wick_ratio: Optional[float] = None,
    max_rays: Optional[int] = None,
    ema_9: Optional[int] = None,
    ema_20: Optional[int] = None
):
    """Fetch intraday candles with automated technical indicators."""
    # Settings object for analyzer
    settings = {
        'rvol_len': rvol_len,
        'rvol_threshold': rvol_threshold,
        'bubble_threshold': bubble_threshold,
        'ray_wick_ratio': ray_wick_ratio,
        'max_rays': max_rays
    }
    # Filter None values
    settings = {k: v for k, v in settings.items() if v is not None}

    # Cache key should include settings
    cache_key = f"intraday_{instrument_key}_{interval}_{hash(frozenset(settings.items()))}"
    cached = hist_cache.get(cache_key)
    if cached: return cached

    try:
        clean_key = unquote(instrument_key).upper()
        # Use registry for historical data with automatic fallback
        candles = []

        # Prioritize Upstox for BSE (delay) and all Indices (speed/sync)
        providers = historical_data_registry.get_all()
        hrn = symbol_mapper.get_hrn(clean_key)
        is_index = "INDEX" in clean_key or hrn in ["NIFTY", "BANKNIFTY", "INDIA VIX"] or "BSE:" in clean_key
        if is_index:
            providers = sorted(providers, key=lambda p: 20 if "Upstox" in type(p).__name__ else 10, reverse=True)

        for provider in providers:
            try:
                candles = await provider.get_hist_candles(clean_key, interval, 5000)
                if candles and len(candles) > 0:
                    break
            except Exception as e:
                logger.warning(f"Historical provider {type(provider).__name__} failed: {e}")
                continue

        if not candles:
            return {"status": "error", "message": "No historical data available from any provider"}

        indicators = []
        if candles:
            # Sort candles once ascending (oldest first)
            candles = sorted(candles, key=lambda x: x[0])
            df = pd.DataFrame(candles, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
            # Standard EMAs
            ema_spans = [(ema_9 or 9, "#3b82f6"), (ema_20 or 20, "#f97316")]
            for span, color in ema_spans:
                ema = df['c'].ewm(span=span, adjust=False).mean()
                indicators.append({
                    "id": f"ema_{span}", "title": f"EMA {span}", "type": "line",
                    "style": {"color": color, "lineWidth": 1},
                    "data": [{"time": int(df['ts'][i]), "value": float(val)} for i, val in enumerate(ema) if i >= span-1],
                    "hideLabel": True
                })

            # Market Psychology Signals
            try:
                from brain.MarketPsychologyAnalyzer import MarketPsychologyAnalyzer
                zones, signals = MarketPsychologyAnalyzer().analyze(candles)
                psych_markers = []
                for ts, sig_type in signals.items():
                    psych_markers.append({
                        "time": int(ts.timestamp()),
                        "position": "aboveBar" if "SHORT" in sig_type else "belowBar",
                        "color": "#ef4444" if "SHORT" in sig_type else "#22c55e",
                        "shape": "arrowDown" if "SHORT" in sig_type else "arrowUp",
                        "text": sig_type
                    })
                if psych_markers:
                    indicators.append({
                        "id": "psych_signals", "type": "markers", "title": "Psychology",
                        "data": psych_markers
                    })
            except Exception: pass

            # Symmetry Analysis for Indices (Triple-Stream Symmetry & Panic)
            if is_index and interval == '1':
                try:
                    from brain.SymmetryAnalyzer import SymmetryAnalyzer
                    # Determine ATM strike
                    last_spot = candles[-1][4]
                    strike_interval = 50 if "NIFTY" in clean_key and "BANK" not in clean_key else 100
                    atm_strike = round(last_spot / strike_interval) * strike_interval

                    # Ensure symbols are cached
                    if clean_key not in options_manager.symbol_map_cache:
                        await options_manager._refresh_wss_symbols(clean_key)

                    ce_sym = options_manager.symbol_map_cache.get(clean_key, {}).get(f"{float(atm_strike)}_call") or \
                             options_manager.symbol_map_cache.get(clean_key, {}).get(f"{int(atm_strike)}_call")
                    pe_sym = options_manager.symbol_map_cache.get(clean_key, {}).get(f"{float(atm_strike)}_put") or \
                             options_manager.symbol_map_cache.get(clean_key, {}).get(f"{int(atm_strike)}_put")

                    if ce_sym and pe_sym:
                        # Fetch candles for CE and PE in parallel
                        ce_task = historical_data_registry.get_primary().get_hist_candles(ce_sym, '1', 1000)
                        pe_task = historical_data_registry.get_primary().get_hist_candles(pe_sym, '1', 1000)
                        ce_candles, pe_candles = await asyncio.gather(ce_task, pe_task)

                        if ce_candles and pe_candles:
                            # Fetch OI change data from DuckDB for 'Panic' filter
                            oi_dict = {}
                            try:
                                # Match timestamps to candle granularity (1m)
                                snaps = await asyncio.to_thread(db.query, """
                                    SELECT timestamp, symbol, oi_change FROM options_snapshots
                                    WHERE symbol IN (?, ?)
                                    ORDER BY timestamp ASC
                                """, (ce_sym, pe_sym))
                                for s in snaps:
                                    ts = int(pd.to_datetime(s['timestamp']).timestamp())
                                    if ts not in oi_dict: oi_dict[ts] = {}
                                    if s['symbol'] == ce_sym: oi_dict[ts]['ce_oi_chg'] = s['oi_change']
                                    else: oi_dict[ts]['pe_oi_chg'] = s['oi_change']
                            except Exception as e:
                                logger.warning(f"OI Data fetch failed for symmetry: {e}")

                            analyzer = SymmetryAnalyzer(clean_key)
                            symmetry_signals = analyzer.analyze(candles, ce_candles, pe_candles, oi_data=oi_dict)

                            if symmetry_signals:
                                sym_markers = []
                                for sig in symmetry_signals:
                                    sym_markers.append({
                                        "time": int(sig['time']),
                                        "position": "belowBar" if sig['type'] == 'BUY_CE' else "aboveBar",
                                        "color": "#10b981" if sig['type'] == 'BUY_CE' else "#ef4444",
                                        "shape": "arrowUp" if sig['type'] == 'BUY_CE' else "arrowDown",
                                        "text": f"SYM:{sig['type']} (S:{sig['score']})",
                                        "id": f"sym_{sig['time']}_{sig['type']}",
                                        "sl": sig.get('sl'),
                                        "tp": sig.get('tp'),
                                        "score": sig.get('score'),
                                        "signal_type": sig['type'],
                                        "entry_price": sig.get('price')
                                    })

                                indicators.append({
                                    "id": "symmetry_signals", "type": "markers", "title": "Symmetry Signals",
                                    "data": sym_markers
                                })
                except Exception as e:
                    logger.error(f"Symmetry analysis error for {clean_key}: {e}")

            # Actual Bot Signals, Trades, and Reference Levels from Symmetry Engine
            if is_index and interval == '1':
                try:
                    # Map HRN or clean_key to index_name used in symmetry engine
                    index_name = "NIFTY" if "NIFTY" in clean_key else "BANKNIFTY" if "BANKNIFTY" in clean_key else None
                    if index_name:
                        session = get_session()
                        # Fetch signals (limited to last 1000 for chart performance)
                        bot_signals = session.query(Signal).filter(Signal.index_name == index_name).order_by(Signal.timestamp.desc()).limit(500).all()
                        # Fetch trades
                        bot_trades = session.query(Trade).filter(Trade.index_name == index_name).order_by(Trade.timestamp.desc()).limit(500).all()
                        # Fetch ref levels
                        bot_ref_levels = session.query(ReferenceLevel).filter(ReferenceLevel.index_name == index_name).order_by(ReferenceLevel.timestamp.desc()).limit(100).all()
                        session.close()

                        bot_markers = []
                        import datetime
                        for sig in bot_signals:
                            # Floor to nearest minute to align with candles
                            # Use UTC timezone to avoid local server time shift
                            ts = int(sig.timestamp.replace(tzinfo=datetime.timezone.utc).timestamp())
                            ts = ts - (ts % 60)
                            bot_markers.append({
                                "time": ts,
                                "position": "belowBar" if "CE" in sig.side else "aboveBar",
                                "color": "#3b82f6", # Bot signals in Blue
                                "shape": "arrowUp" if "CE" in sig.side else "arrowDown",
                                "text": f"BOT:{sig.side}",
                                "id": f"bot_sig_{sig.id}"
                            })

                        for tr in bot_trades:
                            # Floor to nearest minute
                            ts = int(tr.timestamp.replace(tzinfo=datetime.timezone.utc).timestamp())
                            ts = ts - (ts % 60)
                            bot_markers.append({
                                "time": ts,
                                "position": "belowBar" if tr.side == 'BUY' else "aboveBar",
                                "color": "#eab308", # Bot trades in Yellow
                                "shape": "circle" if tr.side == 'BUY' else "square",
                                "text": f"BOT-{tr.side} @ {tr.price}",
                                "id": f"bot_trade_{tr.id}"
                            })

                        if bot_markers:
                            indicators.append({
                                "id": "bot_actions", "type": "markers", "title": "Bot Actions",
                                "data": bot_markers
                            })

                        # Ref levels as price lines
                        ref_lines = []
                        # Use a set to only show unique/latest levels per type if many exist
                        seen_types = set()
                        for ref in bot_ref_levels:
                            if ref.type not in seen_types:
                                ref_lines.append({
                                    "price": ref.index_price,
                                    "color": "#6366f1" if ref.type == 'High' else "#f43f5e",
                                    "width": 1,
                                    "title": f"BOT-{ref.type}"
                                })
                                seen_types.add(ref.type)

                        if ref_lines:
                            indicators.append({
                                "id": "bot_ref_levels", "type": "price_lines", "title": "Bot Ref Levels",
                                "data": ref_lines
                            })
                except Exception as e:
                    logger.error(f"Error fetching bot data for chart: {e}")

            # RVOL & High Volume Node Indicators
            try:
                from brain.VolumeAnalyzer import VolumeAnalyzer
                vol_data = VolumeAnalyzer().analyze(candles, settings=settings)

                # 1. RVOL Markers (Bubbles)
                if vol_data['markers']:
                    indicators.append({
                        "id": "volume_bubbles", "type": "markers", "title": "Vol Bubbles",
                        "data": vol_data['markers']
                    })

                # 2. High Volume Nodes (Lines)
                if vol_data['lines']:
                    indicators.append({
                        "id": "volume_nodes", "type": "price_lines", "title": "High Vol Nodes",
                        "data": vol_data['lines']
                    })

                # 3. Volume Rays (Requested Levels)
                if vol_data.get('volume_rays'):
                    indicators.append({
                        "id": "volume_rays",
                        "type": "price_lines",
                        "title": "V-Ray",
                        "data": vol_data['volume_rays'],
                        "hideLabel": True # Requested: REMOVE LABELS from Y AXIS
                    })

                # 4. EVWMA & Dynamic Pivot
                if vol_data['evwma']:
                    indicators.append({
                        "id": "evwma", "type": "line", "title": "EVWMA",
                        "style": {"color": "#63c58c", "lineWidth": 2},
                        "data": vol_data['evwma'],
                        "hideLabel": True
                    })
                if vol_data['dyn_pivot']:
                    indicators.append({
                        "id": "dyn_pivot", "type": "line", "title": "DynPivot",
                        "style": {"color": "#e44451", "lineWidth": 2},
                        "data": vol_data['dyn_pivot'],
                        "hideLabel": True
                    })

                # 4. Add RVOL to candles for coloring
                for i, rvol in enumerate(vol_data['rvol']):
                    if i < len(candles):
                        # Convert list to list if it's already a list, to be safe
                        c_list = list(candles[i])
                        c_list.append(rvol)
                        candles[i] = c_list
            except Exception as e:
                logger.error(f"Volume analysis failed: {e}")

        result = {"instrumentKey": clean_key, "hrn": symbol_mapper.get_hrn(clean_key), "candles": candles or [], "indicators": indicators}
        hist_cache.set(cache_key, result)
        return result
    except Exception as e: return format_error(e, "Intraday fetch failed")

# ==================== OPTIONS API ====================

@fastapi_app.get("/api/options/chain/{underlying}/with-greeks")
async def get_chain_with_greeks(underlying: str, spot_price: Optional[float] = None):
    # Normalize underlying (e.g. nifty -> NSE:NIFTY)
    underlying = symbol_mapper.to_tv_symbol(underlying)
    chain_data = options_manager.get_chain_with_greeks(underlying)
    spot = spot_price or await options_manager.get_spot_price(underlying)

    for item in chain_data.get('chain', []):
        strike, o_type = item.get('strike', 0), item.get('option_type', 'call')
        item['moneyness'] = greeks_calculator.categorize_strike(strike, spot, o_type)
        item['distance_from_atm_pct'] = round(abs(strike - spot) / spot * 100, 2) if spot > 0 else 0

    return {"underlying": underlying, "spot_price": spot, "chain": chain_data.get('chain', []), "source": chain_data.get('source', 'unknown')}

@fastapi_app.get("/api/options/pcr-trend/{underlying}")
async def get_pcr_trend(underlying: str):
    underlying = symbol_mapper.to_tv_symbol(underlying)
    cache_key = f"pcr_trend_{underlying}"
    cached = pcr_cache.get(cache_key)
    if cached: return cached

    history = await asyncio.to_thread(db.query, """
        SELECT timestamp, AVG(pcr_oi) as pcr_oi, AVG(pcr_vol) as pcr_vol, AVG(pcr_oi_change) as pcr_oi_change,
               AVG(underlying_price) as underlying_price, MAX(max_pain) as max_pain, AVG(spot_price) as spot_price,
               MAX(total_oi) as total_oi, MAX(total_oi_change) as total_oi_change
        FROM pcr_history WHERE underlying = ?
        AND CAST((timestamp AT TIME ZONE 'UTC') AT TIME ZONE 'Asia/Kolkata' AS DATE) =
            (SELECT CAST(MAX(timestamp) AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Kolkata' AS DATE) FROM pcr_history WHERE underlying = ?)
        AND CAST((timestamp AT TIME ZONE 'UTC') AT TIME ZONE 'Asia/Kolkata' AS TIME) >= '09:15:00'
        GROUP BY timestamp ORDER BY timestamp ASC
    """, (underlying, underlying), json_serialize=True)

    result = {"history": history}
    pcr_cache.set(cache_key, result)
    return result

@fastapi_app.get("/api/options/oi-analysis/{underlying}")
async def get_oi_analysis(underlying: str):
    underlying = symbol_mapper.to_tv_symbol(underlying)
    latest = await asyncio.to_thread(db.query, "SELECT MAX(timestamp) as ts FROM options_snapshots WHERE underlying = ?", (underlying,))
    if not latest or not latest[0]['ts']: return {"data": [], "totals": None, "timestamp": "NaT"}

    ts = latest[0]['ts']
    data = await asyncio.to_thread(db.query, """
        SELECT strike, SUM(CASE WHEN option_type = 'call' THEN oi ELSE 0 END) as call_oi,
               SUM(CASE WHEN option_type = 'put' THEN oi ELSE 0 END) as put_oi,
               SUM(CASE WHEN option_type = 'call' THEN oi_change ELSE 0 END) as call_oi_change,
               SUM(CASE WHEN option_type = 'put' THEN oi_change ELSE 0 END) as put_oi_change
        FROM options_snapshots WHERE underlying = ? AND timestamp = ? GROUP BY strike ORDER BY strike ASC
    """, (underlying, ts), json_serialize=True)

    # Get aggregate totals for sidebars
    totals = await asyncio.to_thread(db.query, """
        SELECT
            SUM(CASE WHEN option_type = 'call' THEN oi ELSE 0 END) as total_call_oi,
            SUM(CASE WHEN option_type = 'put' THEN oi ELSE 0 END) as total_put_oi,
            SUM(CASE WHEN option_type = 'call' THEN oi_change ELSE 0 END) as total_call_oi_chg,
            SUM(CASE WHEN option_type = 'put' THEN oi_change ELSE 0 END) as total_put_oi_chg
        FROM options_snapshots WHERE underlying = ? AND timestamp = ?
    """, (underlying, ts), json_serialize=True)

    return {
        "timestamp": ts,
        "data": data,
        "totals": totals[0] if totals else {
            "total_call_oi": 0, "total_put_oi": 0,
            "total_call_oi_chg": 0, "total_put_oi_chg": 0
        }
    }

@fastapi_app.get("/api/options/oi-trend-detailed/{underlying}")
async def get_oi_trend_detailed(underlying: str):
    """Provides CE vs PE OI Change and Spot Price over time for the current session."""
    underlying = symbol_mapper.to_tv_symbol(underlying)
    history = await asyncio.to_thread(db.query, """
        SELECT
            s.timestamp,
            SUM(CASE WHEN s.option_type = 'call' THEN s.oi_change ELSE 0 END) as ce_oi_change,
            SUM(CASE WHEN s.option_type = 'put' THEN s.oi_change ELSE 0 END) as pe_oi_change,
            MAX(p.spot_price) as spot_price
        FROM options_snapshots s
        LEFT JOIN pcr_history p ON s.underlying = p.underlying AND s.timestamp = p.timestamp
        WHERE s.underlying = ?
        AND CAST(s.timestamp AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Kolkata' AS DATE) =
            (SELECT CAST(MAX(timestamp) AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Kolkata' AS DATE) FROM options_snapshots WHERE underlying = ?)
        AND CAST(s.timestamp AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Kolkata' AS TIME) >= '09:15:00'
        GROUP BY s.timestamp
        ORDER BY s.timestamp ASC
    """, (underlying, underlying), json_serialize=True)
    return {"history": history}

@fastapi_app.get("/api/options/genie-insights/{underlying}")
async def get_genie_insights(underlying: str):
    underlying = symbol_mapper.to_tv_symbol(underlying)
    return await options_manager.get_genie_insights(underlying)

@fastapi_app.get("/api/options/oi-buildup/{underlying}")
async def get_oi_buildup(underlying: str):
    underlying = symbol_mapper.to_tv_symbol(underlying)
    return options_manager.get_oi_buildup_analysis(underlying)

@fastapi_app.get("/api/options/iv-analysis/{underlying}")
async def get_iv_analysis(underlying: str):
    underlying = symbol_mapper.to_tv_symbol(underlying)
    return options_manager.get_iv_analysis(underlying)

@fastapi_app.get("/api/options/support-resistance/{underlying}")
async def get_sr_levels(underlying: str):
    underlying = symbol_mapper.to_tv_symbol(underlying)
    return options_manager.get_support_resistance(underlying)

@fastapi_app.get("/api/options/high-activity/{underlying}")
async def get_high_activity(underlying: str):
    underlying = symbol_mapper.to_tv_symbol(underlying)
    return options_manager.get_high_activity_strikes(underlying)

@fastapi_app.post("/api/options/backfill")
async def trigger_backfill():
    asyncio.create_task(options_manager.backfill_today())
    return {"status": "success", "message": "Backfill started"}

# ==================== STRATEGY & ALERTS ====================

@fastapi_app.post("/api/options/strategy/build")
async def build_strategy(req: Request):
    body = await req.json()
    st_input = body.get('strategy_type', 'CUSTOM').upper()
    s_type = StrategyType[st_input] if st_input in StrategyType.__members__ else StrategyType.CUSTOM

    # Use current spot if not provided
    spot = body.get('spot_price')
    if not spot: spot = await options_manager.get_spot_price(body.get('underlying'))

    strat = strategy_builder.create_strategy(body.get('name', 'Custom'), s_type, body.get('underlying'), spot, body.get('legs', []))
    return strategy_builder.analyze_strategy(strat.name)

@fastapi_app.get("/api/alerts/list/{underlying}")
async def get_alerts_for_underlying(underlying: str):
    underlying = symbol_mapper.to_tv_symbol(underlying)
    return alert_system.get_alerts(underlying)

@fastapi_app.post("/api/alerts/create")
async def create_alert(req: Request):
    b = await req.json()
    # threshold based alert helper
    condition = {"type": "threshold", "threshold": b.get('threshold')}
    a = alert_system.create_alert(b.get('name'), AlertType(b.get('alert_type')), b.get('underlying'), condition)
    return {"status": "success", "alert": a.to_dict()}

@fastapi_app.post("/api/alerts/toggle/{alert_id}")
async def toggle_alert(alert_id: str):
    alerts = alert_system.get_alerts()
    a = next((x for x in alerts if x.id == alert_id), None)
    if a:
        a.is_active = not a.is_active
        return {"status": "success", "is_active": a.is_active}
    raise HTTPException(404, "Alert not found")

@fastapi_app.delete("/api/alerts/delete/{alert_id}")
async def delete_alert(alert_id: str):
    if alert_system.delete_alert(alert_id): return {"status": "success"}
    raise HTTPException(404, "Alert not found")

# ==================== SCALPER API ====================

@fastapi_app.post("/api/scalper/start")
async def start_scalper(underlying: str = "NSE:NIFTY"):
    underlying = symbol_mapper.to_tv_symbol(underlying)
    scalper.underlying = underlying
    await scalper.start()
    return {"status": "success"}

@fastapi_app.post("/api/scalper/stop")
async def stop_scalper():
    await scalper.stop()
    return {"status": "success"}

@fastapi_app.get("/api/scalper/status")
async def get_scalper_status():
    return {"is_running": scalper.is_running, "underlying": scalper.underlying, "trades": scalper.order_manager.active_trades}

# ==================== TICK & DASHBOARD API ====================

@fastapi_app.get("/api/ticks/history/{instrument_key}")
async def get_tick_history(instrument_key: str, limit: int = 10000):
    history = await asyncio.to_thread(db.query, "SELECT ts_ms, price, qty FROM ticks WHERE instrumentKey = ? ORDER BY ts_ms DESC LIMIT ?", (unquote(instrument_key), limit), json_serialize=True)
    return {"history": history[::-1]}


# ==================== DATABASE API ====================

@fastapi_app.get("/api/db/tables")
async def get_db_tables():
    tables = await asyncio.to_thread(db.get_tables)
    results = []
    for t in tables:
        row_count = (await asyncio.to_thread(db.query, f'SELECT COUNT(*) as c FROM "{t}"'))[0]['c']
        schema = await asyncio.to_thread(db.get_table_schema, t)
        results.append({
            "name": t,
            "row_count": row_count,
            "schema": [{"column_name": c.get('column_name')} for c in schema]
        })
    return {"tables": results}

@fastapi_app.post("/api/db/query")
async def run_db_query(req: Request):
    sql = (await req.json()).get("sql")
    if not sql: raise HTTPException(400, "SQL required")
    validate_sql(sql)
    return {"results": await asyncio.to_thread(db.query, sql, json_serialize=True)}

@fastapi_app.post("/api/db/export")
async def export_db_query(req: Request):
    sql = (await req.json()).get("sql")
    if not sql: raise HTTPException(400, "SQL required")
    validate_sql(sql)
    res = await asyncio.to_thread(db.query, sql, json_serialize=False)
    if not res: raise HTTPException(400, "No data")

    stream = io.StringIO()
    pd.DataFrame(res).to_csv(stream, index=False)
    resp = StreamingResponse(iter([stream.getvalue()]), media_type="text/csv")
    resp.headers["Content-Disposition"] = "attachment; filename=export.csv"
    return resp

# ==================== STATIC ROUTES ====================

@fastapi_app.get("/")
async def serve_index(request: Request, symbol: Optional[str] = None, interval: Optional[str] = None):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "initial_symbol": symbol or "NSE:NIFTY",
        "initial_interval": interval or "1"
    })

@fastapi_app.get("/options")
async def serve_options(request: Request): return templates.TemplateResponse("options_dashboard.html", {"request": request})

@fastapi_app.get("/backtest")
async def serve_backtest(request: Request):
    return templates.TemplateResponse("backtest_gui.html", {"request": request})

@fastapi_app.post("/api/backtest/run")
async def run_backtest_api(request: Request):
    try:
        data = await request.json()
        index_name = data.get('index_name', 'NIFTY')
        from_date = data.get('from_date')
        to_date = data.get('to_date')

        # Strategy Parameters
        params = {
            'swing_window': int(data.get('swing_window', 10)),
            'confluence_threshold': int(data.get('confluence_threshold', 4)),
            'atr_multiplier': float(data.get('atr_multiplier', 1.5)),
            'enable_index_sync': bool(data.get('enable_index_sync', True))
        }

        from symmetry_engine.backtester import Backtester
        import plotly.graph_objects as go
        import json
        import uuid

        # Use a unique DB for each backtest to allow concurrency
        run_id = str(uuid.uuid4())[:8]
        bt_db = f"data/backtest_{run_id}.db"
        bt = Backtester(index_name, db_path=bt_db)
        bt.params = params

        # Run backtest
        logger.info(f"Running backtest for {index_name} with params: {params}")
        final_df = await bt.run_backtest(from_date, to_date)

        # Generate Report from the specific backtest DB
        session = bt.get_backtest_session()
        # Query BUY trades that are CLOSED, as they contain entry_price, exit_price and pnl
        # We also need the exit timestamp which is stored in the corresponding SELL trade
        trades = session.query(Trade).filter(Trade.status == 'CLOSED', Trade.side == 'BUY').order_by(Trade.timestamp.asc()).all()

        # Helper to find exit timestamps
        sell_trades = session.query(Trade).filter(Trade.status == 'CLOSED', Trade.side == 'SELL').all()
        exit_map = {(t.index_name, t.instrument_key, t.quantity, t.pnl): t.timestamp for t in sell_trades}

        # Candles for chart
        candles = []
        import datetime
        if final_df is not None and not final_df.empty:
            for _, row in final_df.iterrows():
                # Naive IST timestamps from backtester are treated as UTC for epoch calculation
                # to ensure they align with the numeric display on the chart.
                ts = int(row['timestamp'].replace(tzinfo=datetime.timezone.utc).timestamp())
                candles.append([
                    ts, row['open_idx'], row['high_idx'], row['low_idx'], row['close_idx']
                ])

        trade_list = []
        equity_data = []
        cum_pnl = 0

        for t in trades:
            cum_pnl += t.pnl
            # Naive IST timestamps from backtester are treated as UTC for epoch calculation
            ts_epoch = int(t.timestamp.replace(tzinfo=datetime.timezone.utc).timestamp())

            # Find exit timestamp
            exit_ts = exit_map.get((t.index_name, t.instrument_key, t.quantity, t.pnl))
            exit_ts_epoch = int(exit_ts.replace(tzinfo=datetime.timezone.utc).timestamp()) if exit_ts else ts_epoch + 300 # Fallback 5m

            trade_list.append({
                "timestamp": ts_epoch,
                "exit_timestamp": exit_ts_epoch,
                "index": t.index_name,
                "instrument": t.instrument_key,
                "price": t.price, # Used as entry price in GUI
                "exit_price": t.exit_price,
                "pnl": t.pnl
            })
            equity_data.append({"time": t.timestamp, "pnl": cum_pnl})

        # Calculate KPIs
        pnls = [t.pnl for t in trades]
        total_pnl = sum(pnls)
        trade_count = len(pnls)
        win_rate = (len([p for p in pnls if p > 0]) / trade_count * 100) if trade_count > 0 else 0

        df_equity = pd.DataFrame(equity_data)
        equity_json = None
        max_dd = 0
        sharpe = 0

        if not df_equity.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df_equity['time'], y=df_equity['pnl'], mode='lines', name='Equity'))
            equity_json = fig.to_json()

            cum_pnl_series = df_equity['pnl']
            max_pnl = cum_pnl_series.expanding().max()
            drawdown = cum_pnl_series - max_pnl
            max_dd = drawdown.min()

            if trade_count > 1:
                avg_pnl = total_pnl / trade_count
                std = pd.Series(pnls).std()
                sharpe = (avg_pnl / std) * (252**0.5) if std != 0 else 0

        session.close()

        # Persistence: Keep the SQLite DB so user can revisit it
        # We can return the db path in the response so the frontend knows which DB to query for detailed analysis if needed.

        return {
            "status": "success",
            "report": {
                "total_pnl": total_pnl,
                "win_rate": win_rate,
                "trade_count": trade_count,
                "max_drawdown": max_dd,
                "sharpe_ratio": sharpe,
                "equity_curve": equity_json,
                "trades": trade_list[::-1], # Latest first for log
                "candles": candles,
                "db_path": bt_db
            }
        }
    except Exception as e:
        logger.error(f"Backtest API error: {e}")
        return {"status": "error", "message": str(e)}

@fastapi_app.get("/api/symmetry/trades")
async def get_symmetry_trades():
    session = get_session()
    try:
        trades = session.query(Trade).order_by(Trade.timestamp.desc()).limit(100).all()
        return [{"id": t.id, "timestamp": t.timestamp, "index": t.index_name, "instrument": t.instrument_key, "side": t.side, "price": t.price, "exit_price": t.exit_price, "pnl": t.pnl, "status": t.status} for t in trades]
    finally:
        session.close()

@fastapi_app.get("/api/symmetry/stats")
async def get_symmetry_stats():
    session = get_session()
    try:
        # Only use 'SELL' trades for stats to avoid doubling PnL (pnl is set on both BUY and SELL records in current paper engine)
        closed_trades = session.query(Trade).filter(Trade.status == 'CLOSED', Trade.side == 'SELL').all()
        if not closed_trades:
            return {"total_pnl": 0, "trade_count": 0, "win_rate": 0, "max_drawdown": 0, "sharpe_ratio": 0, "avg_pnl": 0}

        df = pd.DataFrame([{"pnl": t.pnl, "ts": t.timestamp} for t in closed_trades])
        df = df.sort_values('ts')

        total_pnl = df['pnl'].sum()
        trade_count = len(df)
        win_rate = (len(df[df['pnl'] > 0]) / trade_count * 100) if trade_count > 0 else 0
        avg_pnl = df['pnl'].mean()

        # Drawdown
        cum_pnl = df['pnl'].cumsum()
        max_pnl = cum_pnl.expanding().max()
        drawdown = (cum_pnl - max_pnl).min() if not cum_pnl.empty else 0

        # Sharpe
        sharpe = 0
        if len(df) > 1:
            std = df['pnl'].std()
            sharpe = (avg_pnl / std) * (252**0.5) if std != 0 else 0

        return {
            "total_pnl": float(total_pnl),
            "trade_count": int(trade_count),
            "win_rate": float(win_rate),
            "max_drawdown": float(drawdown),
            "sharpe_ratio": float(sharpe),
            "avg_pnl": float(avg_pnl)
        }
    finally:
        session.close()

@fastapi_app.get("/api/symmetry/portfolio-greeks")
async def get_portfolio_greeks(index_name: Optional[str] = None):
    try:
        from symmetry_engine.portfolio import calculate_portfolio_greeks
        return calculate_portfolio_greeks(index_name)
    except Exception as e:
        logger.error(f"Portfolio Greeks error: {e}")
        return {"delta": 0, "gamma": 0, "theta": 0, "vega": 0, "position_count": 0}

@fastapi_app.get("/api/symmetry/signals")
async def get_symmetry_signals():
    session = get_session()
    try:
        signals = session.query(Signal).order_by(Signal.timestamp.desc()).limit(100).all()
        return [{"id": s.id, "timestamp": s.timestamp, "index": s.index_name, "side": s.side, "price": s.index_price, "score": s.confluence_score, "details": s.details} for s in signals]
    finally:
        session.close()

@fastapi_app.get("/orderflow")
async def serve_orderflow(request: Request): return templates.TemplateResponse("orderflow_chart.html", {"request": request})

@fastapi_app.get("/tick")
async def serve_tick(request: Request): return templates.TemplateResponse("orderflow_chart.html", {"request": request})

@fastapi_app.get("/renko")
async def serve_renko(request: Request): return templates.TemplateResponse("renko_chart.html", {"request": request})

@fastapi_app.get("/db-viewer")
async def serve_db(request: Request): return templates.TemplateResponse("db_viewer.html", {"request": request})

fastapi_app.mount("/static", StaticFiles(directory="backend/static"), name="static")
app = socketio.ASGIApp(sio, fastapi_app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api_server:app", host="0.0.0.0", port=int(os.getenv("PORT", SERVER_PORT)), reload=False)
