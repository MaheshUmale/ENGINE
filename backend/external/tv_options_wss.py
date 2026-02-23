import websocket
import json
import threading
import time
import logging
import re
import string
import random
from datetime import datetime
from typing import List, Dict, Any, Optional, Callable
from config import TV_COOKIE
from core.interfaces import ILiveStreamProvider
from core.utils import safe_int, safe_float

logger = logging.getLogger(__name__)

def generate_session():
    return "qs_" + "".join(random.choice(string.ascii_letters) for _ in range(12))

def format_message(m, p):
    payload = json.dumps({"m": m, "p": p}, separators=(',', ':'))
    return f"~m~{len(payload)}~m~{payload}"

class OptionsWSS(ILiveStreamProvider):
    def __init__(self, underlying: str, on_data_callback: Callable = None):
        self.underlying = underlying
        self.callback = on_data_callback
        self.ws = None
        self.stop_event = threading.Event()
        self.thread = None
        self.session_id = generate_session()
        self.symbols = set()
        self.is_ready = False

    def _get_url(self):
        return "wss://data.tradingview.com/socket.io/websocket"

    def start(self):
        url = self._get_url()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Origin": "https://www.tradingview.com"
        }
        self.ws = websocket.WebSocketApp(
            url,
            header=headers,
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close
        )
        self.thread = threading.Thread(target=self.ws.run_forever, daemon=True)
        self.thread.start()
        logger.info(f"Options Quote WSS started for {self.underlying} with session {self.session_id}")

    def stop(self):
        self.stop_event.set()
        if self.ws:
            self.ws.close()

    def is_connected(self) -> bool:
        return self.ws and self.ws.sock and self.ws.sock.connected

    def set_callback(self, callback: Callable):
        self.callback = callback

    def subscribe(self, symbols: List[str], interval: str = "1"):
        self.add_symbols(symbols)

    def unsubscribe(self, symbol: str, interval: str = "1"):
        # OptionsWSS doesn't currently implement individual unsubscribe logic
        pass

    def on_open(self, ws):
        logger.info(f"Options Quote WSS Connection opened for {self.underlying}")
        # 1) Create QUOTE Session
        ws.send(format_message("quote_create_session", [self.session_id]))
        # 2) Set FIELDS
        ws.send(format_message("quote_set_fields", [self.session_id, "ask", "bid", "lp", "volume"]))
        self.is_ready = True

        # Re-add existing symbols if any (in case of reconnect)
        if self.symbols:
            logger.info(f"Resubscribing to {len(self.symbols)} symbols for {self.underlying}")
            self._send_subscription(list(self.symbols))

    def add_symbols(self, symbols: list):
        if not symbols: return
        new_symbols = []
        for s in symbols:
            if s not in self.symbols:
                self.symbols.add(s)
                new_symbols.append(s)

        if not new_symbols: return

        if self.is_ready and self.ws and self.ws.sock and self.ws.sock.connected:
            self._send_subscription(new_symbols)

    def _send_subscription(self, symbols: list):
        # 3) Add Symbols
        # TV allows adding multiple symbols in one message
        msg = format_message("quote_add_symbols", [self.session_id] + symbols)
        try:
            self.ws.send(msg)
            logger.debug(f"Subscribed to {len(symbols)} symbols for {self.underlying}")
        except Exception as e:
            logger.error(f"Failed to send subscription: {e}")

    def on_message(self, ws, message):
        if message.startswith("~h~"):
            ws.send(f"~m~{len(message)}~m~{message}")
            return

        try:
            # Handle multiple messages in one frame
            payloads = re.split(r"~m~\d+~m~", message)
            for p in payloads:
                if not p or p.strip() == "": continue
                try:
                    data = json.loads(p)
                except json.JSONDecodeError:
                    continue

                # We expect "m": "qsd" (Quote Session Data)
                if data.get('m') == 'qsd':
                    # data['p'][0] is session_id, data['p'][1] is the quote object
                    if len(data.get('p', [])) < 2: continue

                    quote_data = data['p'][1]
                    symbol = quote_data.get('n')
                    status = quote_data.get('s')
                    values = quote_data.get('v', {})

                    if symbol:
                        self.callback({
                            'symbol': symbol,
                            'status': status,
                            'lp': safe_float(values.get('lp')),
                            'volume': safe_int(values.get('volume')),
                            'bid': safe_float(values.get('bid')),
                            'ask': safe_float(values.get('ask'))
                        })
        except Exception as e:
            logger.error(f"Error in Options Quote WSS message handling: {e}")

    def on_error(self, ws, error):
        logger.error(f"Options Quote WSS Error for {self.underlying}: {error}")

    def on_close(self, ws, close_status_code, close_msg):
        logger.info(f"Options Quote WSS Closed for {self.underlying}: {close_status_code} {close_msg}")
        self.is_ready = False
        # Optional: Implement exponential backoff reconnect if stop_event is not set
        if not self.stop_event.is_set():
            logger.info(f"Attempting to reconnect Options Quote WSS for {self.underlying} in 5 seconds...")
            time.sleep(5)
            self.start()
