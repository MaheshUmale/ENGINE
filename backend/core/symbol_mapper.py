
import logging
import pandas as pd
from datetime import datetime
from typing import Dict, Optional, Any
from db.local_db import db
try:
    from config import UPSTOX_INDEX_MAP
except ImportError:
    UPSTOX_INDEX_MAP = {}

logger = logging.getLogger(__name__)

class SymbolMapper:
    _instance = None
    _upstox_to_internal: Dict[str, str] = {}
    _internal_to_upstox: Dict[str, str] = {}
    _mapping_cache: Dict[str, str] = {
        "NSE_INDEX|NIFTY 50": "NIFTY",
        "NSE_INDEX|NIFTY BANK": "BANKNIFTY",
        "NSE_INDEX|INDIA VIX": "INDIA VIX",
        "NSE|NIFTY": "NIFTY",
        "NSE|BANKNIFTY": "BANKNIFTY",
        "NSE|INDIAVIX": "INDIA VIX"
    } # instrument_key -> HRN
    _reverse_cache: Dict[str, str] = {
        "NIFTY": "NSE|NIFTY",
        "BANKNIFTY": "NSE|BANKNIFTY",
        "INDIA VIX": "NSE|INDIAVIX"
    } # HRN -> instrument_key

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SymbolMapper, cls).__new__(cls)
        return cls._instance

    def get_hrn(self, instrument_key: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Converts an instrument key to a Human Readable Name.
        Format: NIFTY 03 OCT 2024 CALL 25000
        """
        if not instrument_key: return ""

        # Standardize input key - Uppercase is essential for consistent room routing
        key = instrument_key.upper().replace(':', '|')

        if key in self._mapping_cache:
            return self._mapping_cache[key]

        # Try to find in Local DB
        try:
            res = db.get_metadata(key)
            if res:
                hrn = res['hrn']
                self._mapping_cache[key] = hrn
                self._reverse_cache[hrn] = key
                return hrn
        except:
            pass

        # If not found and metadata provided, generate and store
        if metadata:
            hrn = self._generate_hrn(key, metadata)
            if hrn:
                self._store_mapping(key, hrn, metadata)
                return hrn

        # Fallback to simple normalization if no metadata
        if '|' in key:
            parts = key.split('|')
            if len(parts) == 2 and parts[0] == 'NSE':
                return parts[1] # Return just RELIANCE for NSE|RELIANCE
        return key.replace('|', ':').replace('NSE INDEX', '').strip()

    def _generate_hrn(self, instrument_key: str, meta: Dict[str, Any]) -> str:
        """
        Generates HRN from metadata.
        meta keys: symbol, type, strike, expiry, trading_symbol
        """
        # Prefer trading_symbol for EQ/EQUITY as 'symbol' is often the long company name
        itype = meta.get('type', '').upper()
        if itype in ['EQ', 'EQUITY'] and meta.get('trading_symbol'):
            symbol = meta.get('trading_symbol', '').upper()
        else:
            symbol = meta.get('symbol', '').upper()

        if "NIFTY 50" in symbol: symbol = "NIFTY"
        if "NIFTY BANK" in symbol: symbol = "BANKNIFTY"

        strike = meta.get('strike')
        expiry = meta.get('expiry') # YYYY-MM-DD

        if itype in ['INDEX', 'EQ', 'EQUITY', 'TB']:
            return symbol

        if itype == 'FUT':
            if expiry:
                dt = datetime.strptime(expiry, "%Y-%m-%d")
                return f"{symbol} {dt.strftime('%d %b %Y').upper()} FUT"
            return f"{symbol} FUT"

        if itype in ['CE', 'PE', 'CALL', 'PUT']:
            option_type = 'CALL' if itype in ['CE', 'CALL'] else 'PUT'
            if expiry:
                dt = datetime.strptime(expiry, "%Y-%m-%d")
                expiry_str = dt.strftime('%d %b %Y').upper()
                return f"{symbol} {expiry_str} {option_type} {int(strike) if strike else ''}".strip()
            return f"{symbol} {option_type} {int(strike) if strike else ''}".strip()

        return instrument_key

    def _store_mapping(self, instrument_key: str, hrn: str, metadata: Dict[str, Any]):
        try:
            db.update_metadata(instrument_key, hrn, metadata)
        except:
            pass
        self._mapping_cache[instrument_key] = hrn
        self._reverse_cache[hrn] = instrument_key

    def resolve_to_key(self, hrn: str) -> Optional[str]:
        """Resolves a Human Readable Name back to an instrument key."""
        if not hrn: return None

        target = hrn.upper().strip()
        if target in self._reverse_cache:
            return self._reverse_cache[target]

        try:
            rows = db.query("SELECT instrument_key FROM metadata WHERE hrn = ?", (target,))
            if rows:
                key = rows[0]['instrument_key']
                self._mapping_cache[key] = target
                self._reverse_cache[target] = key
                return key
        except:
            pass

        return None

    def get_symbol(self, key_or_hrn: str) -> str:
        """Extracts the base symbol (NIFTY, BANKNIFTY) from a key or HRN."""
        if not key_or_hrn: return ""

        target = key_or_hrn.upper().replace(':', '|').strip()

        # 1. Handle Indices
        if "NIFTY BANK" in target or "BANKNIFTY" in target:
            return "BANKNIFTY"
        if "NIFTY" in target:
            return "NIFTY"
        if "INDIA VIX" in target or "INDIAVIX" in target:
            return "INDIA VIX"

        # 2. Handle technical keys with prefixes (e.g., NSE|RELIANCE)
        if "|" in target:
            return target.split("|")[-1]

        # 3. Handle HRN formats (e.g., RELIANCE 26 FEB 2026 CALL 2500)
        return target.split(" ")[0]

    def register_mapping(self, internal_symbol: str, upstox_key: str):
        """Registers a bidirectional mapping between internal symbol and Upstox key."""
        int_key = internal_symbol.upper()
        u_key = upstox_key.upper()
        self._internal_to_upstox[int_key] = upstox_key
        self._upstox_to_internal[u_key] = internal_symbol
        logger.debug(f"Registered mapping: {internal_symbol} <-> {upstox_key}")

    def to_upstox_key(self, internal_key: str) -> str:
        """Translates internal key (NSE:NIFTY) to Upstox key (NSE_INDEX|Nifty 50)."""
        if not internal_key: return ""

        # If it already looks like an Upstox key, return it as is (preserving case)
        if '|' in internal_key and not internal_key.startswith('NSE:'):
            # Check if it's a known index but incorrectly cased
            upper_key = internal_key.upper()
            for k, v in UPSTOX_INDEX_MAP.items():
                if v.upper() == upper_key:
                    return v # Return correctly cased index key
            return internal_key

        key = internal_key.upper().replace('|', ':')

        # Handle prefixes: NIFTY26... vs NSE:NIFTY26...
        no_prefix_key = key.split(':')[-1]
        prefixed_key = f"NSE:{no_prefix_key}"

        # 1. Check dynamic mapping (both variations)
        for k in [prefixed_key, no_prefix_key, key]:
            if k in self._internal_to_upstox:
                return self._internal_to_upstox[k]

        # 2. Check Static Index Map
        for k in [prefixed_key, no_prefix_key, key]:
            if k in UPSTOX_INDEX_MAP:
                return UPSTOX_INDEX_MAP[k]

        # Default mapping for equity/options if they follow common patterns
        # If it looks like an F&O symbol (e.g. NIFTY26...) and has no prefix, add NSE_FO|
        import re
        if re.match(r'^(NIFTY|BANKNIFTY|FINNIFTY|RELIANCE|HDFCBANK)\d{2}', no_prefix_key):
            return f"NSE_FO|{no_prefix_key}"

        return key.replace(':', '|')

    def to_tv_symbol(self, internal_key: str) -> str:
        """
        Translates internal key or Upstox technical key to TradingView symbol (e.g. NSE:NIFTY).
        Uses database metadata for accurate resolution of numeric/technical keys.
        """
        if not internal_key: return ""

        # Standardize key for lookup/comparison
        key = internal_key.upper().replace(':', '|')

        # 1. Fast path for Indices
        index_map = {
            "NIFTY": "NSE:NIFTY",
            "NIFTY 50": "NSE:NIFTY",
            "BANKNIFTY": "NSE:BANKNIFTY",
            "NIFTY BANK": "NSE:BANKNIFTY",
            "INDIA VIX": "NSE:INDIAVIX",
            "INDIAVIX": "NSE:INDIAVIX",
            "SENSEX": "BSE:SENSEX"
        }

        base_symbol = key.split('|')[-1]
        if base_symbol in index_map:
            return index_map[base_symbol]

        # 2. Database Lookup for technical/numeric keys (e.g., NSE_FO|54910)
        try:
            # Try original key and standardized key
            for k in [internal_key, key, key.replace('|', ':')]:
                res = db.get_metadata(k)
                if res and res.get('metadata'):
                    meta = res['metadata']
                    tsym = meta.get('trading_symbol')
                    if tsym:
                        exch = meta.get('exchange', 'NSE')
                        # TradingView uses 'NSE' for both NSE and NFO segments
                        tv_exch = 'NSE' if exch in ['NSE', 'NFO'] else 'BSE' if exch in ['BSE', 'BFO'] else exch
                        return f"{tv_exch}:{tsym}"
        except Exception as e:
            logger.debug(f"TV symbol resolution DB lookup failed: {e}")

        # 3. Heuristic fallbacks if DB lookup fails
        if "BANKNIFTY" in key: return "NSE:BANKNIFTY"
        if "NIFTY" in key: return "NSE:NIFTY"

        # If it already looks like a TV symbol, return it
        if ':' in internal_key and not internal_key.startswith('NSE_'):
            return internal_key.upper()

        # Last resort: Strip prefix and assume NSE
        clean_sym = key.split('|')[-1]
        return f"NSE:{clean_sym}"

    def from_upstox_key(self, upstox_key: str) -> str:
        """Translates Upstox key to internal canonical symbol."""
        u_key = upstox_key.upper()

        # Check dynamic mapping first
        if u_key in self._upstox_to_internal:
            return self._upstox_to_internal[u_key]

        # Reverse lookup in UPSTOX_INDEX_MAP
        for int_key, val in UPSTOX_INDEX_MAP.items():
            if val.upper() == u_key:
                return int_key

        return upstox_key.replace('|', ':').upper()

symbol_mapper = SymbolMapper()
