import pandas as pd
import datetime
import asyncio
import logging
from core.provider_registry import historical_data_registry, options_data_registry
from core.options_manager import options_manager
from core.symbol_mapper import symbol_mapper
from config import UPSTOX_ACCESS_TOKEN as ACCESS_TOKEN, SYMMETRY_INDICES as INDICES
from .database import get_session, Candle

logger = logging.getLogger(__name__)

class DataProvider:
    def __init__(self, access_token=None):
        self.instruments = {} # Store current instruments for each index
        self.running = False
        self.oi_cache = {} # instrument_key -> last_oi

    def get_market_quote(self, symbol_list):
        """Unified App doesn't have a direct equivalent to Upstox MarketQuoteV3Api->get_ltp for arbitrary lists."""
        return None

    async def get_historical_data(self, instrument_key, interval=1, to_date=None, from_date=None):
        """Fetch historical candles using Unified App's registry."""
        try:
            # interval 1m is supported. Unified app uses '1', '5' etc.
            # Request up to 5000 candles to support multi-day backtests
            count = 5000
            provider = historical_data_registry.get_primary()
            if not provider:
                logger.error("No historical provider available")
                return None

            # Support date range if provider does
            if hasattr(provider, 'get_hist_candles'):
                import inspect
                sig = inspect.signature(provider.get_hist_candles)
                if 'from_date' in sig.parameters:
                    candles = await provider.get_hist_candles(instrument_key, str(interval), count, from_date=from_date, to_date=to_date)
                else:
                    candles = await provider.get_hist_candles(instrument_key, str(interval), count)
            else:
                return None

            if candles:
                # Unified app returns [ts, o, h, l, c, v] where ts is unix seconds
                df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
                # Original expected 'oi' column. If not present, add it as 0
                if 'oi' not in df.columns:
                    df['oi'] = 0
                return df
            return None
        except Exception as e:
            logger.error(f"Historical fetch failed for {instrument_key}: {e}")
            return None

    async def get_instrument_details(self, index_name, reference_date=None):
        """
        Dynamically discovers ATM options and nearest expiry using Unified App's OptionsManager.
        """
        try:
            # Map index name to technical key used in unified app
            # NIFTY -> NSE:NIFTY
            underlying = f"NSE:{index_name}"

            # Discovery via options_manager
            chain_res = options_manager.get_chain_with_greeks(underlying)
            chain = chain_res.get('chain', [])
            spot = chain_res.get('spot_price', 0)

            if not chain or spot == 0:
                # If chain not in DB, try taking a snapshot now
                logger.info(f"Chain not found in DB for {underlying}, taking snapshot (ref={reference_date})...")
                await options_manager.take_snapshot(underlying, reference_date=reference_date)
                chain_res = options_manager.get_chain_with_greeks(underlying)
                chain = chain_res.get('chain', [])
                spot = chain_res.get('spot_price', 0)

            if not chain:
                logger.error(f"Could not discover chain for {underlying}")
                return None

            # Find ATM strike
            strikes = sorted(list(set(c['strike'] for c in chain)))
            atm_strike = min(strikes, key=lambda x: abs(x - spot))

            # Get primary CE/PE keys
            ce_key = next((c['symbol'] for c in chain if c['strike'] == atm_strike and c['option_type'] == 'call'), None)
            pe_key = next((c['symbol'] for c in chain if c['strike'] == atm_strike and c['option_type'] == 'put'), None)

            # Option chain (7 strikes)
            atm_index = strikes.index(atm_strike)
            start_idx = max(0, atm_index - 3)
            end_idx = min(len(strikes), atm_index + 4)
            selected_strikes = strikes[start_idx : end_idx]

            option_keys = []
            for s in selected_strikes:
                s_ce = next((c['symbol'] for c in chain if c['strike'] == s and c['option_type'] == 'call'), None)
                s_pe = next((c['symbol'] for c in chain if c['strike'] == s and c['option_type'] == 'put'), None)
                if s_ce and s_pe:
                    option_keys.append({
                        "strike": float(s),
                        "ce": s_ce,
                        "pe": s_pe
                    })

            expiry = chain[0].get('expiry')
            if hasattr(expiry, 'strftime'):
                expiry = expiry.strftime('%Y-%m-%d')

            return {
                'index': underlying,
                'ce': ce_key,
                'pe': pe_key,
                'fut': underlying, # Unified app doesn't always track FUT explicitly here
                'ltp': spot,
                'strike': float(atm_strike),
                'expiry': str(expiry),
                'option_chain': option_keys
            }
        except Exception as e:
            logger.error(f"Discovery Error in DataProvider: {e}")
            return None

    async def start_streaming(self, instrument_keys, callback):
        """Unified App streaming is managed by data_engine."""
        self.running = True
        self.callback = callback
        # Actual hook into data_engine will be done in main.py or api_server.py
        pass

    def subscribe(self, instrument_keys):
        from core import data_engine
        for key in instrument_keys:
            data_engine.subscribe_instrument(key, "SYMMETRY_BOT", interval="1")

    def unsubscribe(self, instrument_keys):
        from core import data_engine
        for key in instrument_keys:
            data_engine.unsubscribe_instrument(key, "SYMMETRY_BOT", interval="1")

    def calculate_oi_delta(self, instrument_key, current_oi):
        last_oi = self.oi_cache.get(instrument_key)
        self.oi_cache[instrument_key] = current_oi
        if last_oi is not None:
            return current_oi - last_oi
        return 0
