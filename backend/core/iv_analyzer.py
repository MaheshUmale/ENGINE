"""
Implied Volatility (IV) Analyzer Module
Tracks IV rank, IV percentile, and IV skew analysis
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
import statistics

logger = logging.getLogger(__name__)


@dataclass
class IVMetrics:
    """IV metrics for a specific underlying."""
    current_iv: float
    iv_rank: float  # 0-100 scale
    iv_percentile: float  # 0-100 scale
    iv_52w_high: float
    iv_52w_low: float
    iv_20d_avg: float
    iv_skew: float  # Difference between OTM put IV and OTM call IV
    term_structure: Dict[str, float]  # IV across different expiries


class IVAnalyzer:
    """
    Analyze Implied Volatility patterns and metrics.

    Features:
    - IV Rank and Percentile calculation
    - IV Skew analysis
    - Term structure analysis
    - Historical IV tracking
    """

    def __init__(self, lookback_days: int = 252):
        self.lookback_days = lookback_days  # Default 1 year
        self.iv_history: Dict[str, List[Dict[str, Any]]] = {}  # underlying -> IV history

    def add_iv_reading(
        self,
        underlying: str,
        iv_value: float,
        timestamp: Optional[datetime] = None,
        expiry: Optional[str] = None
    ):
        """Add a new IV reading to history."""
        if underlying not in self.iv_history:
            self.iv_history[underlying] = []

        reading = {
            'timestamp': timestamp or datetime.now(),
            'iv': iv_value,
            'expiry': expiry
        }

        self.iv_history[underlying].append(reading)

        # Keep only lookback period
        cutoff = datetime.now() - timedelta(days=self.lookback_days)
        self.iv_history[underlying] = [
            r for r in self.iv_history[underlying]
            if r['timestamp'] > cutoff
        ]

    def calculate_iv_rank(
        self,
        underlying: str,
        current_iv: float,
        days: int = 252
    ) -> float:
        """
        Calculate IV Rank (0-100 scale).

        IV Rank = (Current IV - 52W Low) / (52W High - 52W Low) * 100
        """
        history = self._get_history(underlying, days)

        # If very little data, return 0 instead of 50 to avoid fake neutral signal
        if not history:
            return 0.0

        iv_values = [h['iv'] for h in history]
        # Include current IV in the range calculation to avoid division by zero or negative rank
        iv_values.append(current_iv)

        iv_low = min(iv_values)
        iv_high = max(iv_values)

        if iv_high == iv_low:
            return 0.0

        iv_rank = ((current_iv - iv_low) / (iv_high - iv_low)) * 100
        return round(max(0, min(100, iv_rank)), 2)

    def calculate_iv_percentile(
        self,
        underlying: str,
        current_iv: float,
        days: int = 252
    ) -> float:
        """
        Calculate IV Percentile (0-100 scale).

        Percentage of days in the past where IV was below current IV.
        """
        history = self._get_history(underlying, days)

        if len(history) < 30:
            return 50.0

        iv_values = [h['iv'] for h in history]
        below_count = sum(1 for iv in iv_values if iv < current_iv)

        percentile = (below_count / len(iv_values)) * 100
        return round(percentile, 2)

    def calculate_iv_skew(
        self,
        chain_data: List[Dict[str, Any]],
        spot_price: float,
        otm_threshold: float = 0.02
    ) -> Dict[str, float]:
        """
        Calculate IV skew from option chain.

        Args:
            chain_data: Option chain with IV values
            spot_price: Current spot price
            otm_threshold: Threshold for OTM options

        Returns:
            Dictionary with skew metrics
        """
        otm_calls = []
        otm_puts = []
        atm_options = []

        for item in chain_data:
            strike = item.get('strike', 0)
            iv = item.get('implied_volatility', 0) / 100  # Convert from percentage
            option_type = item.get('option_type', 'call')

            moneyness = (strike - spot_price) / spot_price

            if abs(moneyness) <= 0.01:  # ATM
                atm_options.append(iv)
            elif option_type == 'call' and moneyness > otm_threshold:
                otm_calls.append(iv)
            elif option_type == 'put' and moneyness < -otm_threshold:
                otm_puts.append(iv)

        avg_atm_iv = statistics.mean(atm_options) if atm_options else 0
        avg_otm_call_iv = statistics.mean(otm_calls) if otm_calls else 0
        avg_otm_put_iv = statistics.mean(otm_puts) if otm_puts else 0

        # Skew is typically measured as OTM Put IV - ATM IV
        put_skew = (avg_otm_put_iv - avg_atm_iv) / avg_atm_iv * 100 if avg_atm_iv > 0 else 0
        call_skew = (avg_otm_call_iv - avg_atm_iv) / avg_atm_iv * 100 if avg_atm_iv > 0 else 0

        return {
            'put_skew': round(put_skew, 2),
            'call_skew': round(call_skew, 2),
            'skew_ratio': round(avg_otm_put_iv / avg_otm_call_iv, 2) if avg_otm_call_iv > 0 else 1,
            'avg_atm_iv': round(avg_atm_iv * 100, 2),
            'avg_otm_put_iv': round(avg_otm_put_iv * 100, 2),
            'avg_otm_call_iv': round(avg_otm_call_iv * 100, 2)
        }

    def analyze_term_structure(
        self,
        expiry_ivs: Dict[str, float]
    ) -> Dict[str, Any]:
        """
        Analyze IV term structure across expiries.

        Args:
            expiry_ivs: Dictionary mapping expiry dates to IV values

        Returns:
            Term structure analysis
        """
        if not expiry_ivs:
            return {'shape': 'flat', 'slope': 0}

        sorted_expiries = sorted(expiry_ivs.items())

        if len(sorted_expiries) < 2:
            return {'shape': 'flat', 'slope': 0}

        # Calculate slope (change in IV per month)
        first_iv = sorted_expiries[0][1]
        last_iv = sorted_expiries[-1][1]
        months = len(sorted_expiries)

        slope = (last_iv - first_iv) / months

        # Determine shape
        if slope > 1:
            shape = 'contango'  # IV increases with time
        elif slope < -1:
            shape = 'backwardation'  # IV decreases with time
        else:
            shape = 'flat'

        return {
            'shape': shape,
            'slope': round(slope, 2),
            'near_iv': round(first_iv, 2),
            'far_iv': round(last_iv, 2),
            'term_structure': {k: round(v, 2) for k, v in sorted_expiries}
        }

    def get_iv_metrics(
        self,
        underlying: str,
        current_iv: float
    ) -> IVMetrics:
        """Get comprehensive IV metrics for an underlying."""
        history = self._get_history(underlying, self.lookback_days)

        iv_values = [h['iv'] for h in history] if history else [current_iv]

        # Calculate 20-day average
        recent_history = self._get_history(underlying, 20)
        recent_ivs = [h['iv'] for h in recent_history] if recent_history else [current_iv]

        return IVMetrics(
            current_iv=round(current_iv, 2),
            iv_rank=self.calculate_iv_rank(underlying, current_iv),
            iv_percentile=self.calculate_iv_percentile(underlying, current_iv),
            iv_52w_high=round(max(iv_values), 2) if iv_values else current_iv,
            iv_52w_low=round(min(iv_values), 2) if iv_values else current_iv,
            iv_20d_avg=round(statistics.mean(recent_ivs), 2) if recent_ivs else current_iv,
            iv_skew=0,  # Calculated separately
            term_structure={}
        )

    def _get_history(
        self,
        underlying: str,
        days: int
    ) -> List[Dict[str, Any]]:
        """Get IV history for specified period."""
        if underlying not in self.iv_history:
            return []

        cutoff = datetime.now() - timedelta(days=days)
        return [h for h in self.iv_history[underlying] if h['timestamp'] > cutoff]

    def get_iv_signal(
        self,
        iv_rank: float,
        iv_percentile: float
    ) -> Dict[str, str]:
        """
        Generate trading signal based on IV metrics.

        High IV = Favorable for selling options
        Low IV = Favorable for buying options
        """
        if iv_rank > 70 or iv_percentile > 80:
            return {
                'signal': 'SELL_VOL',
                'description': 'IV is elevated - Consider selling options/spreads',
                'strategies': ['Iron Condor', 'Credit Spreads', 'Short Strangle']
            }
        elif iv_rank < 30 or iv_percentile < 20:
            return {
                'signal': 'BUY_VOL',
                'description': 'IV is depressed - Consider buying options/spreads',
                'strategies': ['Long Straddle', 'Debit Spreads', 'Calendar Spreads']
            }
        else:
            return {
                'signal': 'NEUTRAL',
                'description': 'IV is at normal levels',
                'strategies': ['Directional Trades', 'Ratio Spreads']
            }

    def detect_iv_spike(
        self,
        underlying: str,
        current_iv: float,
        threshold: float = 2.0
    ) -> bool:
        """
        Detect if IV has spiked significantly.

        Args:
            threshold: Number of standard deviations for spike detection

        Returns:
            True if IV spike detected
        """
        history = self._get_history(underlying, 20)

        if len(history) < 10:
            return False

        iv_values = [h['iv'] for h in history]
        mean_iv = statistics.mean(iv_values)
        std_iv = statistics.stdev(iv_values) if len(iv_values) > 1 else 0

        if std_iv == 0:
            return False

        z_score = (current_iv - mean_iv) / std_iv
        return z_score > threshold


# Global instance
iv_analyzer = IVAnalyzer()
