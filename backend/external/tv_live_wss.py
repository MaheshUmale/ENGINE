import websocket
import json
import random
import string
import threading
import time
import logging
import re
import requests
import numpy as np
from config import TV_COOKIE
from core.symbol_mapper import symbol_mapper
from core.utils import safe_int, safe_float

logger = logging.getLogger(__name__)

class TradingViewWSS:
    def __init__(self, on_message_callback):
        self.callback = on_message_callback
        self.ws = None
        self.session = self._generate_session()
        self.quote_session = self._generate_session("qs_")

        self.chart_sessions = {} # session_id -> {'hrn': hrn, 'interval': interval, 'symbol': symbol}
        self.symbol_interval_to_session = {} # (symbol, interval) -> session_id

        self.series_id = "s1"
        self.study_id = "st1"
        self.symbols = [] # For quote session
        self.last_volumes = {}
        self.last_prices = {}
        self.last_times = {}
        self.history = {} # (symbol, interval) -> data
        self.ohlcv_map = {} # (symbol, interval) -> {timestamp: candle}
        self.indicator_metadata = {}
        self.stop_event = threading.Event()
        self.thread = None

    def _generate_session(self, prefix=""):
        return prefix + "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(12))

    def _send_message(self, func, param_list):
        if not self.ws or not self.ws.sock or not self.ws.sock.connected:
            return
        try:
            message = json.dumps({"m": func, "p": param_list}, separators=(",", ":"))
            payload = f"~m~{len(message)}~m~{message}"
            self.ws.send(payload)
        except Exception as e:
            logger.error(f"Error sending message to TV WSS: {e}")

    def subscribe(self, symbols, interval="1"):
        symbols = [s.upper() for s in symbols]
        new_symbols = [s for s in symbols if s not in self.symbols]
        self.symbols.extend(new_symbols)
        if self.ws and self.ws.sock and self.ws.sock.connected:
            if new_symbols:
                for symbol in new_symbols:
                    self._send_message("quote_add_symbols", [self.quote_session, symbol])

            for symbol in symbols:
                self.ensure_chart_session(symbol, interval)

    def unsubscribe(self, symbol, interval="1"):
        symbol = symbol.upper()
        key = (symbol, interval)
        if key in self.symbol_interval_to_session:
            session_id = self.symbol_interval_to_session.pop(key)
            if session_id in self.chart_sessions:
                del self.chart_sessions[session_id]
            logger.info(f"Releasing chart session {session_id} for {symbol} ({interval}m)")
            self._send_message("chart_delete_session", [session_id])

        # Check if symbol is still needed in any other interval for quote session
        still_needed = any(s == symbol for (s, i) in self.symbol_interval_to_session.keys())
        if not still_needed and symbol in self.symbols:
            self.symbols.remove(symbol)
            self._send_message("quote_remove_symbols", [self.quote_session, symbol])

    def ensure_chart_session(self, symbol, interval):
        key = (symbol, interval)
        if key in self.symbol_interval_to_session:
            return

        session_id = self._generate_session("cs_")
        self.symbol_interval_to_session[key] = session_id
        # Use full technical symbol for routing
        self.chart_sessions[session_id] = {'hrn': symbol_mapper.get_hrn(symbol), 'interval': interval, 'symbol': symbol}

        logger.info(f"Creating chart session {session_id} for {symbol} ({interval}m)")

        self._send_message("chart_create_session", [session_id, ""])

        symbol_payload = f"={json.dumps({'symbol': symbol, 'adjustment': 'splits'})}"
        self._send_message("resolve_symbol", [session_id, "sds_sym_1", symbol_payload])
        self._send_message("create_series", [session_id, "sds_1", "s1", "sds_sym_1", interval, 300, ""])

        # from config import TV_STUDY_ID
        # if TV_STUDY_ID:
        #     try:
        #         if TV_STUDY_ID not in self.indicator_metadata:
        #             self.indicator_metadata[TV_STUDY_ID] = self.get_indicator_metadata(TV_STUDY_ID)

        #         meta_info = self.indicator_metadata[TV_STUDY_ID]
        #         self._create_study(session_id, self.study_id, "sds_1", meta_info)
        #     except Exception as e:
        #         logger.error(f"Failed to load study for {symbol}: {e}")

    def _create_study(self, session_id, study_id, series_id, metadata):
        inputs = {"text": metadata["script"]}
        if "pineId" in metadata: inputs["pineId"] = metadata["pineId"]
        if "pineVersion" in metadata: inputs["pineVersion"] = metadata["pineVersion"]
        for input_id, input_val in metadata.get("inputs", {}).items():
            inputs[input_id] = {"v": input_val.get("value"), "f": input_val.get("isFake", False), "t": input_val.get("type")}
        indicator_type = "Script@tv-scripting-101!"
        if metadata.get("type") == "strategy": indicator_type = "StrategyScript@tv-scripting-101!"
        self._send_message("create_study", [session_id, study_id, study_id, series_id, indicator_type, inputs])

    def get_user_data(self):
        if not TV_COOKIE: return None
        url = "https://www.tradingview.com/"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        try:
            res = requests.get(url, headers=headers, cookies=TV_COOKIE, timeout=15)
            auth_token = re.search(r'"auth_token":"(.*?)"', res.text)
            if auth_token: return auth_token.group(1)
        except Exception as e:
            logger.error(f"Error getting user data: {e}")
        return None

    def get_indicator_metadata(self, indicator_id, version="last"):
        url = f"https://pine-facade.tradingview.com/pine-facade/translate/{indicator_id}/{version}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        try:
            response = requests.get(url, headers=headers, cookies=TV_COOKIE, timeout=10)
            data = response.json()
        except Exception as e:
            logger.error(f"Error fetching indicator metadata: {e}")
            raise Exception(f"Failed to fetch indicator metadata: {e}")
        if not isinstance(data, dict) or not data.get("success"):
            raise Exception(f"Failed to get indicator metadata: {data.get('reason') if isinstance(data, dict) else 'Unknown error'}")
        result = data.get("result", {})
        metaInfo = result.get("metaInfo", {})
        inputs = {item["id"]: {"name": item.get("name"), "type": item.get("type"), "value": item.get("defval"), "isFake": item.get("isFake", False)} for item in metaInfo.get("inputs", []) if item.get("id") not in ["text", "pineId", "pineVersion"]}
        plots = {}
        styles = metaInfo.get("styles", {})
        for i, p in enumerate(metaInfo.get("plots", [])):
            plot_id = p.get("id")
            style = styles.get(plot_id, {})
            title = style.get("title", plot_id).replace(" ", "_")
            if title in [p["title"] for p in plots.values()]: title = f"{title}_{plot_id}"
            plots[plot_id] = {"id": plot_id, "index": i, "title": title, "type": style.get("plottype"), "color": style.get("color"), "linewidth": style.get("linewidth", 1), "linestyle": style.get("linestyle", 0)}
        return {"pineId": metaInfo.get("scriptIdPart", indicator_id), "pineVersion": metaInfo.get("pine", {}).get("version", version), "inputs": inputs, "plots": plots, "script": result.get("ilTemplate"), "type": metaInfo.get("extra", {}).get("kind") or metaInfo.get("package", {}).get("type") or "study"}

    def on_open(self, ws):
        logger.info("TV WSS Connection opened")
        token = self.get_user_data() or "unauthorized_user_token"
        self._send_message("set_auth_token", [token])
        self._send_message("set_locale", ["en", "US"])
        self._send_message("quote_create_session", [self.quote_session])
        self._send_message("quote_set_fields", [self.quote_session, "lp", "lp_time", "volume"])

        # Resubscribe existing symbols
        if self.symbols:
            logger.info(f"Resubscribing to {len(self.symbols)} symbols on open")
            for symbol in self.symbols:
                self._send_message("quote_add_symbols", [self.quote_session, symbol])
                # Note: interval "1" is default for initial symbols
                self.ensure_chart_session(symbol, "1")

    def on_message(self, ws, message):
        if isinstance(message, bytes): message = message.decode('utf-8')
        payloads = [p for p in re.split(r"~m~\d+~m~", message) if p]
        for msg in payloads:
            if msg.startswith("~h~"):
                try: ws.send(f"~m~{len(msg)}~m~{msg}")
                except: pass
                continue
            try:
                data = json.loads(msg)
                m_type = data.get("m")
                logger.info(f"TV WSS Message received: {m_type}")
                p = data.get("p", [])
                if m_type == "qsd" and len(p) > 1:
                    self._handle_qsd(p[1])
                elif m_type in ["timescale_update", "du"] and len(p) > 1:
                    self._handle_chart_update(p[0], p[1])
                elif m_type in ["error", "critical_error"]:
                    logger.error(f"TV WSS Protocol Error: {p}")
            except Exception as e:
                logger.error(f"Error handling TV WSS message: {e}")

    def _handle_qsd(self, quote_data):
        symbol = quote_data["n"]
        clean_symbol = symbol[1:] if symbol.startswith('=') else symbol
        values = quote_data.get("v", {})
        if 'lp' in values: self.last_prices[clean_symbol] = values['lp']
        if 'lp_time' in values: self.last_times[clean_symbol] = values['lp_time']
        if 'volume' in values: self.last_volumes[clean_symbol] = float(values['volume'])

        price = self.last_prices.get(clean_symbol)
        if price is not None:
            ts_ms = safe_int((self.last_times.get(clean_symbol) or time.time()) * 1000)
            # Use full technical symbol for feeds to avoid mixups
            feed_msg = {
                'type': 'live_feed',
                'feeds': {
                    clean_symbol: {
                        'last_price': safe_float(price),
                        'ts_ms': ts_ms,
                        'tv_volume': safe_float(self.last_volumes.get(clean_symbol)),
                        'oi': safe_float(values.get('open_interest')),
                        'source': 'tradingview_wss'
                    }
                }
            }
            self.callback(feed_msg)

    def _handle_chart_update(self, session_id, chart_data):
        meta = self.chart_sessions.get(session_id)
        if not meta: return

        symbol = meta['symbol']
        interval = meta['interval']
        hist_key = (symbol, interval)
        # Use full technical symbol as instrumentKey
        update_msg = {'type': 'chart_update', 'instrumentKey': symbol, 'interval': interval, 'data': {}}

        series_key = "sds_1" if "sds_1" in chart_data else "$prices" if "$prices" in chart_data else None
        if series_key:
            prices = chart_data[series_key].get("s", [])
            candles = [item['v'] for item in prices]

            if candles:
                if hist_key not in self.ohlcv_map: self.ohlcv_map[hist_key] = {}
                if hist_key not in self.history: self.history[hist_key] = {}

                # Use the map to ensure we have unique candles by timestamp
                # and that we don't lose history when updates come in
                for c in candles:
                    ts = c[0]
                    # Only store candles with valid timestamps
                    if ts > 1e9:
                        self.ohlcv_map[hist_key][ts] = c

                # Get sorted list of candles
                full_ohlcv = [self.ohlcv_map[hist_key][ts] for ts in sorted(self.ohlcv_map[hist_key].keys())]

                # Limit history to 2000 candles to avoid memory bloat
                if len(full_ohlcv) > 2000:
                    full_ohlcv = full_ohlcv[-2000:]
                    # Cleanup map
                    valid_ts = {c[0] for c in full_ohlcv}
                    self.ohlcv_map[hist_key] = {ts: c for ts, c in self.ohlcv_map[hist_key].items() if ts in valid_ts}

                # Save back to history
                self.history[hist_key]['ohlcv'] = full_ohlcv
                update_msg['data']['ohlcv'] = full_ohlcv if len(candles) > 10 else candles

        # Recalculate indicators from history
        if hist_key in self.history and 'ohlcv' in self.history[hist_key]:
            ohlcv_data = self.history[hist_key]['ohlcv']
            indicators = []
            try:
                import pandas as pd
                df = pd.DataFrame(ohlcv_data, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
                ema9 = df['c'].ewm(span=9, adjust=False).mean()
                indicators.append({
                    "id": "ema_9",
                    "title": "EMA 9",
                    "type": "line",
                    "style": {"color": "#3b82f6", "lineWidth": 1},
                    "data": [
                        {"time": safe_int(ohlcv_data[i][0]), "value": safe_float(val)}
                        for i, val in enumerate(ema9)
                        if i >= 8 and np.isfinite(val)
                    ],
                    "hideLabel": True
                })
                ema20 = df['c'].ewm(span=20, adjust=False).mean()
                indicators.append({
                    "id": "ema_20",
                    "title": "EMA 20",
                    "type": "line",
                    "style": {"color": "#f97316", "lineWidth": 1},
                    "data": [
                        {"time": safe_int(ohlcv_data[i][0]), "value": safe_float(val)}
                        for i, val in enumerate(ema20)
                        if i >= 19 and np.isfinite(val)
                    ],
                    "hideLabel": True
                })

                from brain.MarketPsychologyAnalyzer import MarketPsychologyAnalyzer
                analyzer = MarketPsychologyAnalyzer()
                zones, signals = analyzer.analyze(ohlcv_data)

                if zones:
                    indicators.append({
                        "id": "battle_zones",
                        "type": "price_lines",
                        "title": "Zones",
                        "data": [
                            {
                                "price": safe_float(zone['price']),
                                "color": "rgba(59, 130, 246, 0.4)",
                                "lineStyle": 2,
                                "title": ""
                            } for zone in zones
                        ]
                    })

                marker_data = []
                for ts, sig_type in signals.items():
                    unix_ts = safe_int(ts.timestamp() if hasattr(ts, 'timestamp') else ts)
                    marker_data.append({
                        "time": unix_ts,
                        "position": "aboveBar" if "SHORT" in sig_type else "belowBar",
                        "color": "#ef4444" if "SHORT" in sig_type else "#22c55e",
                        "shape": "arrowDown" if "SHORT" in sig_type else "arrowUp",
                        "text": sig_type
                    })

                if marker_data:
                    indicators.append({
                        "id": "psych_signals",
                        "type": "markers",
                        "title": "Psychology Signals",
                        "data": marker_data
                    })

                update_msg['data']['indicators'] = indicators
                self.history[hist_key]['indicators'] = indicators
            except Exception as e:
                logger.error(f"Error calculating indicators live: {e}")

        if update_msg['data']:
            self.callback(update_msg)

    def start(self):
        self.stop_event.clear()
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Origin": "https://www.tradingview.com"}
        self.ws = websocket.WebSocketApp("wss://data.tradingview.com/socket.io/websocket?type=chart", header=headers, on_open=self.on_open, on_message=self.on_message, on_error=lambda ws,e: logger.error(f"TV WSS Error: {e}"), on_close=lambda ws,sc,msg: logger.info(f"TV WSS Closed: {sc} {msg}"))
        self.thread = threading.Thread(target=self.ws.run_forever, kwargs={"skip_utf8_validation": True, "ping_interval": 20, "ping_timeout": 10}, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.ws: self.ws.close()

tv_wss = None
def start_tv_wss(on_message_callback, symbols=None):
    global tv_wss
    if tv_wss is None:
        tv_wss = TradingViewWSS(on_message_callback)
        if symbols: tv_wss.subscribe(symbols)
        tv_wss.start()
    return tv_wss
def get_tv_wss(): return tv_wss
