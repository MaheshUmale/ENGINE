"""
Open Interest (OI) Buildup Analyzer Module
Detects Long Buildup, Short Buildup, Long Unwinding, Short Covering
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class OIBuildupType(Enum):
    """Types of OI buildup patterns."""
    LONG_BUILDUP = "Long Buildup"
    SHORT_BUILDUP = "Short Buildup"
    LONG_UNWINDING = "Long Unwinding"
    SHORT_COVERING = "Short Covering"
    NEUTRAL = "Neutral"


@dataclass
class OIBuildupSignal:
    """OI Buildup signal for a strike."""
    strike: float
    option_type: str
    buildup_type: OIBuildupType
    strength: str  # 'strong', 'moderate', 'weak'
    oi_change_pct: float
    price_change_pct: float
    interpretation: str


class OIBuildupAnalyzer:
    """
    Analyze Open Interest buildup patterns.

    Key Patterns:
    - Long Buildup: OI increases + Price increases (Bullish)
    - Short Buildup: OI increases + Price decreases (Bearish)
    - Long Unwinding: OI decreases + Price decreases (Bearish)
    - Short Covering: OI decreases + Price increases (Bullish)
    """

    def __init__(self):
        self.threshold_oi_change = 2.0  # 2% OI change threshold
        self.threshold_price_change = 0.5  # 0.5% price change threshold

    def analyze_buildup(
        self,
        current_data: Dict[str, Any],
        previous_data: Optional[Dict[str, Any]] = None,
        oi_change: Optional[float] = None,
        price_change: Optional[float] = None
    ) -> OIBuildupSignal:
        """
        Analyze buildup pattern for a single strike.

        Args:
            current_data: Current OI and price data
            previous_data: Previous OI and price data (optional)
            oi_change: Pre-calculated OI change percentage
            price_change: Pre-calculated price change percentage

        Returns:
            OIBuildupSignal with pattern and interpretation
        """
        strike = current_data.get('strike', 0)
        option_type = current_data.get('option_type', 'call')

        # Calculate changes if previous data provided
        if previous_data and oi_change is None:
            oi_change = self._calculate_change(
                current_data.get('oi', 0),
                previous_data.get('oi', 0)
            )

        if previous_data and price_change is None:
            price_change = self._calculate_change(
                current_data.get('ltp', 0),
                previous_data.get('ltp', 0)
            )

        oi_change = oi_change or 0
        price_change = price_change or 0

        # Determine buildup type
        buildup_type, strength = self._classify_buildup(oi_change, price_change)

        # Generate interpretation
        interpretation = self._generate_interpretation(
            buildup_type, option_type, strike, oi_change, price_change
        )

        return OIBuildupSignal(
            strike=strike,
            option_type=option_type,
            buildup_type=buildup_type,
            strength=strength,
            oi_change_pct=round(oi_change, 2),
            price_change_pct=round(price_change, 2),
            interpretation=interpretation
        )

    def analyze_chain_buildup(
        self,
        current_chain: List[Dict[str, Any]],
        previous_chain: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Analyze buildup patterns for entire option chain.

        Args:
            current_chain: Current option chain data
            previous_chain: Previous option chain data (optional)

        Returns:
            Dictionary with buildup analysis summary
        """
        signals = []

        # Create lookup for previous data
        prev_lookup = {}
        if previous_chain:
            for item in previous_chain:
                key = (item.get('strike'), item.get('option_type'))
                prev_lookup[key] = item

        # Analyze each strike
        for item in current_chain:
            key = (item.get('strike'), item.get('option_type'))
            prev_item = prev_lookup.get(key)

            signal = self.analyze_buildup(item, prev_item)
            signals.append(signal)

        # Generate summary
        summary = self._generate_summary(signals)

        return {
            'signals': [
                {
                    'strike': s.strike,
                    'option_type': s.option_type,
                    'buildup_type': s.buildup_type.value,
                    'strength': s.strength,
                    'oi_change_pct': s.oi_change_pct,
                    'price_change_pct': s.price_change_pct,
                    'interpretation': s.interpretation
                }
                for s in signals
            ],
            'summary': summary
        }

    def _calculate_change(self, current: float, previous: float) -> float:
        """Calculate percentage change."""
        if previous == 0:
            return 100 if current > 0 else 0
        return ((current - previous) / previous) * 100

    def _classify_buildup(
        self,
        oi_change: float,
        price_change: float
    ) -> Tuple[OIBuildupType, str]:
        """
        Classify buildup pattern based on OI and price changes.

        Returns:
            Tuple of (buildup_type, strength)
        """
        # Determine strength based on magnitude
        abs_oi_change = abs(oi_change)
        abs_price_change = abs(price_change)

        if abs_oi_change >= 10 and abs_price_change >= 2:
            strength = 'strong'
        elif abs_oi_change >= 5 and abs_price_change >= 1:
            strength = 'moderate'
        else:
            strength = 'weak'

        # Classify pattern
        if oi_change > self.threshold_oi_change:
            if price_change > self.threshold_price_change:
                return OIBuildupType.LONG_BUILDUP, strength
            elif price_change < -self.threshold_price_change:
                return OIBuildupType.SHORT_BUILDUP, strength

        elif oi_change < -self.threshold_oi_change:
            if price_change < -self.threshold_price_change:
                return OIBuildupType.LONG_UNWINDING, strength
            elif price_change > self.threshold_price_change:
                return OIBuildupType.SHORT_COVERING, strength

        return OIBuildupType.NEUTRAL, 'weak'

    def _generate_interpretation(
        self,
        buildup_type: OIBuildupType,
        option_type: str,
        strike: float,
        oi_change: float,
        price_change: float
    ) -> str:
        """Generate human-readable interpretation."""
        interpretations = {
            OIBuildupType.LONG_BUILDUP: {
                'call': f"Fresh long positions building at {strike} CE - Bullish",
                'put': f"Fresh long positions building at {strike} PE - Bearish"
            },
            OIBuildupType.SHORT_BUILDUP: {
                'call': f"Fresh short positions building at {strike} CE - Bearish resistance",
                'put': f"Fresh short positions building at {strike} PE - Bullish support"
            },
            OIBuildupType.LONG_UNWINDING: {
                'call': f"Longs exiting at {strike} CE - Bearish",
                'put': f"Longs exiting at {strike} PE - Bullish"
            },
            OIBuildupType.SHORT_COVERING: {
                'call': f"Shorts covering at {strike} CE - Bullish breakout",
                'put': f"Shorts covering at {strike} PE - Bearish breakdown"
            },
            OIBuildupType.NEUTRAL: {
                'call': f"No significant activity at {strike} CE",
                'put': f"No significant activity at {strike} PE"
            }
        }

        return interpretations.get(buildup_type, {}).get(option_type, "Unknown pattern")

    def _generate_summary(self, signals: List[OIBuildupSignal]) -> Dict[str, Any]:
        """Generate summary of buildup patterns."""
        total = len(signals)
        if total == 0:
            return {}

        # Count patterns
        pattern_counts = {}
        for signal in signals:
            pattern = signal.buildup_type.value
            pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1

        # Find strongest signals
        strong_signals = [s for s in signals if s.strength == 'strong']

        # Determine overall sentiment
        bullish_signals = sum(1 for s in signals
                            if s.buildup_type in [OIBuildupType.LONG_BUILDUP, OIBuildupType.SHORT_COVERING])
        bearish_signals = sum(1 for s in signals
                            if s.buildup_type in [OIBuildupType.SHORT_BUILDUP, OIBuildupType.LONG_UNWINDING])

        if bullish_signals > bearish_signals * 1.5:
            sentiment = 'strongly_bullish'
        elif bullish_signals > bearish_signals:
            sentiment = 'bullish'
        elif bearish_signals > bullish_signals * 1.5:
            sentiment = 'strongly_bearish'
        elif bearish_signals > bullish_signals:
            sentiment = 'bearish'
        else:
            sentiment = 'neutral'

        return {
            'total_strikes_analyzed': total,
            'pattern_distribution': pattern_counts,
            'strong_signals_count': len(strong_signals),
            'overall_sentiment': sentiment,
            'bullish_signals': bullish_signals,
            'bearish_signals': bearish_signals,
            'key_levels': self._identify_key_levels(signals)
        }

    def _identify_key_levels(self, signals: List[OIBuildupSignal]) -> Dict[str, List[float]]:
        """Identify key support and resistance levels from buildup patterns."""
        resistance_levels = []
        support_levels = []

        for signal in signals:
            if signal.buildup_type == OIBuildupType.SHORT_BUILDUP:
                if signal.option_type == 'call':
                    resistance_levels.append(signal.strike)
                else:
                    support_levels.append(signal.strike)
            elif signal.buildup_type == OIBuildupType.LONG_BUILDUP:
                if signal.option_type == 'call':
                    support_levels.append(signal.strike)
                else:
                    resistance_levels.append(signal.strike)

        return {
            'resistance': sorted(resistance_levels),
            'support': sorted(support_levels)
        }

    def detect_institutional_distribution(self, chain_data: List[Dict[str, Any]], spot_price: float) -> Dict[str, Any]:
        """Detects aggressive selling and distribution by smart money."""
        # Aggressive distribution: Heavy Call writing at strikes near or above spot
        # or heavy Put unwinding.
        calls = [c for c in chain_data if c.get('option_type') == 'call' and (c.get('strike') or 0) >= spot_price]

        # Sort by OI change to find most aggressive writing
        aggressive_writing = sorted(calls, key=lambda x: x.get('oi_change') or 0, reverse=True)

        top_distribution_strikes = aggressive_writing[:3]
        is_aggressive = any((s.get('oi_change') or 0) > 100000 for s in top_distribution_strikes)

        return {
            'is_aggressive_distribution': is_aggressive,
            'distribution_levels': [s.get('strike') for s in top_distribution_strikes],
            'status': "DISTRIBUTION DETECTED" if is_aggressive else "STABLE"
        }

    def detect_market_control(self, chain_data: List[Dict[str, Any]]) -> str:
        """Identifies if buyers or sellers are firmly in control."""
        total_call_oi_chg = sum(c.get('oi_change') or 0 for c in chain_data if c.get('option_type') == 'call')
        total_put_oi_chg = sum(c.get('oi_change') or 0 for c in chain_data if c.get('option_type') == 'put')

        if total_put_oi_chg > total_call_oi_chg * 1.5:
            return "BUYERS_IN_CONTROL"
        elif total_call_oi_chg > total_put_oi_chg * 1.5:
            return "SELLERS_IN_CONTROL"
        return "NEUTRAL_CONTROL"

    def predict_sideways_session(self, history: List[Dict[str, Any]]) -> bool:
        """Spots low-volatility, sideways sessions in advance."""
        if len(history) < 5: return False

        # Check if price has stayed within 0.2% range for last 5 intervals
        prices = [h.get('spot_price') or h.get('underlying_price', 0) for h in history[-5:]]
        if 0 in prices: return False

        price_range = (max(prices) - min(prices)) / prices[0]
        return price_range < 0.002 # 0.2% range

    def detect_fake_breakout(self, spot_price: float, prev_spot: float, chain_data: List[Dict[str, Any]]) -> bool:
        """Flags breakouts that lack volume and institutional support."""
        if prev_spot == 0: return False

        price_move = (spot_price - prev_spot) / prev_spot
        if abs(price_move) < 0.001: return False # Not a significant move

        # If price up but Call OI also up (writing into strength) or Put OI down (unwinding support)
        if price_move > 0:
            call_oi_chg = sum(c.get('oi_change', 0) for c in chain_data if c.get('option_type') == 'call' and c.get('strike') > spot_price)
            if call_oi_chg > 50000: return True # Heavy resistance being built

        # If price down but Put OI also up (writing into weakness) or Call OI down
        if price_move < 0:
            put_oi_chg = sum(c.get('oi_change', 0) for c in chain_data if c.get('option_type') == 'put' and c.get('strike') < spot_price)
            if put_oi_chg > 50000: return True # Heavy support being built

        return False

    def get_support_resistance_from_oi(
        self,
        chain_data: List[Dict[str, Any]],
        spot_price: float = 0,
        top_n: int = 3
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Identify support and resistance levels based on OI concentration.

        Args:
            chain_data: Option chain with OI data
            spot_price: Current spot price to filter relevant levels
            top_n: Number of top levels to return

        Returns:
            Dictionary with support and resistance levels
        """
        # Separate calls and puts
        calls = [c for c in chain_data if c.get('option_type') == 'call']
        puts = [p for p in chain_data if p.get('option_type') == 'put']

        # Filter: Resistance should be above spot, Support should be below spot
        if spot_price > 0:
            calls = [c for c in calls if (c.get('strike') or 0) >= spot_price]
            puts = [p for p in puts if (p.get('strike') or 0) <= spot_price]

        # Fallback: if filtered results are empty, use original set (or top/bottom of chain)
        # However, for "Institutional" levels, empty is often more accurate if spot is at extremes.
        # We'll stick to filtered, but ensure they aren't completely empty if possible.

        # Sort by OI
        calls_by_oi = sorted(calls, key=lambda x: x.get('oi') or 0, reverse=True)
        puts_by_oi = sorted(puts, key=lambda x: x.get('oi') or 0, reverse=True)

        # Highest call OI = Resistance (writers expect price to stay below)
        resistance = [
            {
                'strike': c.get('strike'),
                'oi': c.get('oi') or 0,
                'oi_change': c.get('oi_change') or 0,
                'strength': self._calculate_level_strength(c)
            }
            for c in calls_by_oi[:top_n]
        ]

        # Highest put OI = Support (writers expect price to stay above)
        support = [
            {
                'strike': p.get('strike'),
                'oi': p.get('oi') or 0,
                'oi_change': p.get('oi_change') or 0,
                'strength': self._calculate_level_strength(p)
            }
            for p in puts_by_oi[:top_n]
        ]

        return {
            'resistance_levels': resistance,
            'support_levels': support
        }

    def _calculate_level_strength(self, item: Dict[str, Any]) -> str:
        """Calculate strength of a support/resistance level."""
        oi = item.get('oi') or 0
        oi_change = item.get('oi_change') or 0

        if oi > 1000000 and oi_change > 50000:
            return 'very_strong'
        elif oi > 500000 and oi_change > 20000:
            return 'strong'
        elif oi > 100000:
            return 'moderate'
        else:
            return 'weak'


# Global instance
oi_buildup_analyzer = OIBuildupAnalyzer()
