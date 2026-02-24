from .database import get_session, Trade
from core.greeks_calculator import greeks_calculator
from core.options_manager import options_manager
import datetime
import pytz

def calculate_portfolio_greeks(index_name=None):
    """
    Calculates aggregate Greeks for all open paper trading positions.
    """
    session = get_session()
    try:
        query = session.query(Trade).filter_by(status='OPEN', side='BUY')
        if index_name:
            query = query.filter_by(index_name=index_name)

        open_trades = query.all()

        total_delta = 0.0
        total_theta = 0.0
        total_vega = 0.0
        total_gamma = 0.0

        ist = pytz.timezone('Asia/Kolkata')
        now = datetime.datetime.now(ist)

        for trade in open_trades:
            # We need current spot and option info
            underlying = f"NSE:{trade.index_name}"
            # Discovery via options_manager to get expiry
            chain_res = options_manager.get_chain_with_greeks(underlying)
            spot = chain_res.get('spot_price', 0)

            # Use instrument_ce or instrument_pe based on the side (BUY_CE or BUY_PE)
            active_key = trade.instrument_ce if 'CE' in (trade.instrument_key or '') else trade.instrument_pe

            # Find item in current chain
            item = next((c for c in chain_res.get('chain', []) if c['symbol'] == active_key), None)

            if item:
                strike = item['strike']
                expiry = item['expiry'] # Expected to be a date object or string
                opt_type = item['option_type']
                ltp = item['ltp']

                if isinstance(expiry, str):
                    expiry_date = datetime.datetime.strptime(expiry, "%Y-%m-%d").date()
                else:
                    expiry_date = expiry

                days_to_expiry = max((expiry_date - now.date()).days, 0)
                time_to_expiry = days_to_expiry / 365.0

                greeks = greeks_calculator.calculate_all_greeks(
                    spot, strike, time_to_expiry, 0.20, opt_type, ltp
                )

                qty = trade.quantity
                total_delta += greeks['delta'] * qty
                total_gamma += greeks['gamma'] * qty
                total_theta += greeks['theta'] * qty
                total_vega += greeks['vega'] * qty

        return {
            "delta": round(total_delta, 2),
            "gamma": round(total_gamma, 4),
            "theta": round(total_theta, 2),
            "vega": round(total_vega, 2),
            "position_count": len(open_trades)
        }
    finally:
        session.close()
