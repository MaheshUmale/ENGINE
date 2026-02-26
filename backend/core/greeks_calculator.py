"""
Options Greeks Calculator Module
Calculates Delta, Gamma, Theta, Vega, Rho using Black-Scholes model
"""

import math
from typing import Dict, Any, Optional, List
from datetime import datetime, date
import logging

logger = logging.getLogger(__name__)


class GreeksCalculator:
    """
    Calculate option Greeks using Black-Scholes model.

    Supports both call and put options with real-time calculations.
    """

    def __init__(self):
        self.risk_free_rate = 0.10  # 10% annual risk-free rate for India

    def calculate_all_greeks(
        self,
        spot_price: float,
        strike_price: float,
        time_to_expiry: float,  # in years
        volatility: float,  # annualized IV (e.g., 0.20 for 20%)
        option_type: str = 'call',
        option_price: Optional[float] = None
    ) -> Dict[str, float]:
        """
        Calculate all Greeks for an option.

        Args:
            spot_price: Current underlying price
            strike_price: Option strike price
            time_to_expiry: Time to expiry in years
            volatility: Implied volatility (annualized)
            option_type: 'call' or 'put'
            option_price: Current option price (for implied vol calculation)

        Returns:
            Dictionary containing all Greeks and implied volatility
        """
        try:
            S = max(spot_price, 0.01)
            K = max(strike_price, 0.01)
            T = max(time_to_expiry, 0.0001)  # Prevent division by zero
            r = self.risk_free_rate
            sigma = max(volatility, 0.0001)

            # Calculate d1 and d2
            d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
            d2 = d1 - sigma * math.sqrt(T)

            # Standard normal PDF and CDF
            nd1 = self._normal_pdf(d1)
            Nd1 = self._normal_cdf(d1)
            Nd2 = self._normal_cdf(d2)
            N_minus_d1 = self._normal_cdf(-d1)
            N_minus_d2 = self._normal_cdf(-d2)

            # Calculate Greeks
            if option_type.lower() == 'call':
                delta = Nd1
                theta = (-S * nd1 * sigma / (2 * math.sqrt(T))
                        - r * K * math.exp(-r * T) * Nd2) / 365  # Daily theta
                rho = K * T * math.exp(-r * T) * Nd2 / 100  # Per 1% rate change
            else:  # put
                delta = Nd1 - 1
                theta = (-S * nd1 * sigma / (2 * math.sqrt(T))
                        + r * K * math.exp(-r * T) * N_minus_d2) / 365
                rho = -K * T * math.exp(-r * T) * N_minus_d2 / 100

            # Gamma and Vega are the same for calls and puts
            gamma = nd1 / (S * sigma * math.sqrt(T))
            vega = S * nd1 * math.sqrt(T) / 100  # Per 1% vol change

            # Calculate implied volatility if option price is provided
            implied_vol = volatility
            if option_price and option_price > 0:
                implied_vol = self._calculate_implied_volatility(
                    S, K, T, r, option_price, option_type
                )

            result = {
                'delta': round(delta, 4),
                'gamma': round(gamma, 6),
                'theta': round(theta, 4),
                'vega': round(vega, 4),
                'rho': round(rho, 4),
                'implied_volatility': round(implied_vol * 100, 2),  # Return as percentage
                'd1': round(d1, 4),
                'd2': round(d2, 4),
                'intrinsic_value': self._calculate_intrinsic_value(S, K, option_type),
                'time_value': self._calculate_time_value(S, K, T, r, sigma, option_price, option_type) if option_price else 0
            }

            # Final safety check for JSON-incompatible values
            for key, val in result.items():
                if isinstance(val, (int, float)) and (math.isinf(val) or math.isnan(val)):
                    result[key] = 0.0

            return result

        except Exception as e:
            logger.error(f"Error calculating Greeks: {e}")
            return self._default_greeks()

    def _normal_cdf(self, x: float) -> float:
        """Cumulative distribution function for standard normal."""
        return 0.5 * (1 + math.erf(x / math.sqrt(2)))

    def _normal_pdf(self, x: float) -> float:
        """Probability density function for standard normal."""
        return (1 / math.sqrt(2 * math.pi)) * math.exp(-0.5 * x ** 2)

    def _calculate_implied_volatility(
        self,
        S: float,
        K: float,
        T: float,
        r: float,
        market_price: float,
        option_type: str,
        precision: float = 0.0001,
        max_iterations: int = 100
    ) -> float:
        """
        Calculate implied volatility using Newton-Raphson method.
        """
        S = max(S, 0.01)
        K = max(K, 0.01)
        T = max(T, 0.0001)
        sigma = 0.3  # Initial guess

        for _ in range(max_iterations):
            d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
            d2 = d1 - sigma * math.sqrt(T)

            if option_type.lower() == 'call':
                price = S * self._normal_cdf(d1) - K * math.exp(-r * T) * self._normal_cdf(d2)
            else:
                price = K * math.exp(-r * T) * self._normal_cdf(-d2) - S * self._normal_cdf(-d1)

            vega = S * self._normal_pdf(d1) * math.sqrt(T)

            if abs(price - market_price) < precision:
                return sigma

            if vega > 1e-6:
                diff = (price - market_price) / vega
                # Prevent extreme jumps that cause divergence
                if abs(diff) > 0.5:
                    diff = 0.5 if diff > 0 else -0.5
                sigma = sigma - diff
            else:
                # If vega is too small, shift sigma slightly to try another area
                sigma = sigma + 0.1 if (price or 0) < market_price else sigma - 0.1

            # Clamp sigma to a realistic range [0.1%, 1000%]
            sigma = max(0.001, min(sigma, 10.0))

        return sigma

    def _calculate_intrinsic_value(self, S: float, K: float, option_type: str) -> float:
        """Calculate intrinsic value of option."""
        if option_type.lower() == 'call':
            return max(0, S - K)
        else:
            return max(0, K - S)

    def _calculate_time_value(
        self,
        S: float,
        K: float,
        T: float,
        r: float,
        sigma: float,
        market_price: Optional[float],
        option_type: str
    ) -> float:
        """Calculate time value of option."""
        if market_price is None:
            return 0
        intrinsic = self._calculate_intrinsic_value(S, K, option_type)
        return max(0, market_price - intrinsic)

    def _default_greeks(self) -> Dict[str, float]:
        """Return default values when calculation fails."""
        return {
            'delta': 0.0,
            'gamma': 0.0,
            'theta': 0.0,
            'vega': 0.0,
            'rho': 0.0,
            'implied_volatility': 0.0,
            'd1': 0.0,
            'd2': 0.0,
            'intrinsic_value': 0.0,
            'time_value': 0.0
        }

    def calculate_chain_greeks(
        self,
        spot_price: float,
        chain_data: List[Dict[str, Any]],
        expiry_date: date
    ) -> List[Dict[str, Any]]:
        """
        Calculate Greeks for entire option chain.

        Args:
            spot_price: Current underlying price
            chain_data: List of option chain items
            expiry_date: Expiry date of options

        Returns:
            Chain data with Greeks added
        """
        today = date.today()
        days_to_expiry = max((expiry_date - today).days, 0)
        time_to_expiry = days_to_expiry / 365.0

        result = []
        for item in chain_data:
            try:
                raw_strike = item.get('strike')
                strike = float(raw_strike if raw_strike is not None else 0.0)

                option_type = item.get('option_type', 'call')

                raw_ltp = item.get('ltp')
                ltp = float(raw_ltp if raw_ltp is not None else 0.0)

                # Estimate IV from LTP if available, else use default
                iv = 0.20  # Default 20%
                if ltp > 0:
                    iv = self._estimate_iv_from_price(spot_price, strike, time_to_expiry, ltp, option_type)

                greeks = self.calculate_all_greeks(
                    spot_price, strike, time_to_expiry, iv, option_type, ltp
                )

                # Add Greeks to item
                item_with_greeks = {**item, **greeks}
                result.append(item_with_greeks)

            except Exception as e:
                logger.error(f"Error calculating Greeks for strike {item.get('strike')}: {e}")
                result.append({**item, **self._default_greeks()})

        return result

    def _estimate_iv_from_price(
        self,
        S: float,
        K: float,
        T: float,
        price: float,
        option_type: str
    ) -> float:
        """Estimate IV from market price using approximation."""
        # Simple approximation - can be improved
        moneyness = abs(S - K) / S
        base_iv = 0.20

        # ATM options typically have higher IV (volatility smile)
        if moneyness < 0.02:
            base_iv = 0.25
        elif moneyness < 0.05:
            base_iv = 0.22

        return base_iv

    def get_atm_strike(self, spot_price: float, strikes: List[float]) -> float:
        """Find the ATM (At-The-Money) strike price."""
        if not strikes:
            return spot_price
        return min(strikes, key=lambda x: abs(x - spot_price))

    def categorize_strike(
        self,
        strike: float,
        spot_price: float,
        option_type: str = 'call',
        threshold_itm: float = 0.01,
        threshold_otm: float = 0.01
    ) -> str:
        """
        Categorize strike as ITM, ATM, or OTM.

        Args:
            strike: Strike price
            spot_price: Current spot price
            option_type: 'call' or 'put'
            threshold_itm: Threshold for ITM (default 1%)
            threshold_otm: Threshold for OTM (default 1%)

        Returns:
            'ITM', 'ATM', or 'OTM'
        """
        if spot_price <= 0:
            return 'ATM'

        # Within threshold of spot price is ATM
        if abs(strike - spot_price) / spot_price <= 0.005:  # Within 0.5%
            return 'ATM'

        if option_type.lower() == 'call':
            if strike < spot_price:
                return 'ITM'
            else:
                return 'OTM'
        else:  # put
            if strike > spot_price:
                return 'ITM'
            else:
                return 'OTM'


# Global instance
greeks_calculator = GreeksCalculator()
