"""
Options Strategy Builder Module
Builds and analyzes multi-leg options strategies with P&L visualization
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, date
import json

logger = logging.getLogger(__name__)


class StrategyType(Enum):
    """Types of options strategies."""
    # Single Leg
    LONG_CALL = "Long Call"
    LONG_PUT = "Long Put"
    SHORT_CALL = "Short Call"
    SHORT_PUT = "Short Put"

    # Spreads
    BULL_CALL_SPREAD = "Bull Call Spread"
    BEAR_PUT_SPREAD = "Bear Put Spread"
    BULL_PUT_SPREAD = "Bull Put Spread"
    BEAR_CALL_SPREAD = "Bear Call Spread"

    # Iron Condors & Butterflies
    IRON_CONDOR = "Iron Condor"
    IRON_BUTTERFLY = "Iron Butterfly"
    LONG_CALL_BUTTERFLY = "Long Call Butterfly"
    LONG_PUT_BUTTERFLY = "Long Put Butterfly"

    # Straddles & Strangles
    LONG_STRADDLE = "Long Straddle"
    SHORT_STRADDLE = "Short Straddle"
    LONG_STRANGLE = "Long Strangle"
    SHORT_STRANGLE = "Short Strangle"

    # Calendars & Diagonals
    CALL_CALENDAR = "Call Calendar Spread"
    PUT_CALENDAR = "Put Calendar Spread"

    # Custom
    CUSTOM = "Custom Strategy"


@dataclass
class Leg:
    """Single leg of an options strategy."""
    strike: float
    option_type: str  # 'call' or 'put'
    position: str  # 'long' or 'short'
    quantity: int
    premium: float
    expiry: str
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    iv: float = 0.0

    @property
    def net_premium(self) -> float:
        """Calculate net premium for this leg."""
        mult = 1 if self.position == 'long' else -1
        return self.premium * self.quantity * mult


@dataclass
class Strategy:
    """Complete options strategy."""
    name: str
    strategy_type: StrategyType
    underlying: str
    spot_price: float
    legs: List[Leg] = field(default_factory=list)
    entry_date: str = field(default_factory=lambda: datetime.now().strftime('%Y-%m-%d'))

    @property
    def net_premium(self) -> float:
        """Calculate total net premium."""
        return sum(leg.net_premium for leg in self.legs)

    @property
    def max_profit(self) -> Optional[float]:
        """Calculate maximum profit potential."""
        if self.strategy_type in [StrategyType.LONG_CALL, StrategyType.LONG_PUT]:
            return float('inf')

        metrics = self._calculate_general_metrics()
        return metrics.get('max_profit')

    @property
    def max_loss(self) -> Optional[float]:
        """Calculate maximum loss."""
        if self.strategy_type == StrategyType.SHORT_CALL:
            return float('inf')

        metrics = self._calculate_general_metrics()
        return metrics.get('max_loss')

    @property
    def breakeven_points(self) -> List[float]:
        """Calculate breakeven price points."""
        metrics = self._calculate_general_metrics()
        return metrics.get('breakevens', [])

    @property
    def net_delta(self) -> float:
        """Calculate net delta of strategy."""
        return sum(
            leg.delta * leg.quantity * (1 if leg.position == 'long' else -1)
            for leg in self.legs
        )

    @property
    def net_gamma(self) -> float:
        """Calculate net gamma of strategy."""
        return sum(
            leg.gamma * leg.quantity * (1 if leg.position == 'long' else -1)
            for leg in self.legs
        )

    @property
    def net_theta(self) -> float:
        """Calculate net theta of strategy."""
        return sum(
            leg.theta * leg.quantity * (1 if leg.position == 'long' else -1)
            for leg in self.legs
        )

    @property
    def net_vega(self) -> float:
        """Calculate net vega of strategy."""
        return sum(
            leg.vega * leg.quantity * (1 if leg.position == 'long' else -1)
            for leg in self.legs
        )

    def _calculate_general_metrics(self) -> Dict[str, Any]:
        """Exhaustive P&L analysis for any multi-leg strategy."""
        if not self.legs:
            return {'max_profit': 0.0, 'max_loss': 0.0, 'breakevens': []}

        # Collect strikes and boundary points for evaluation
        strikes = sorted([l.strike for l in self.legs])

        # evaluation points: 0, strikes, and far points
        test_prices = [0.0] + strikes
        # Add points around strikes and far out to detect slopes
        test_prices.append(max(strikes) * 2)
        test_prices = sorted(list(set(test_prices)))

        pnls = [self.calculate_pnl(p) for p in test_prices]

        # Check slopes at extreme ends for unlimited potential
        p_vlow1, p_vlow2 = 0.0, 1.0
        v_vlow1, v_vlow2 = self.calculate_pnl(p_vlow1), self.calculate_pnl(p_vlow2)

        p_vhigh1, p_vhigh2 = max(strikes) * 10, max(strikes) * 10 + 1
        v_vhigh1, v_vhigh2 = self.calculate_pnl(p_vhigh1), self.calculate_pnl(p_vhigh2)

        # Unlimited Profit
        if v_vlow2 > v_vlow1 + 0.01 or v_vhigh2 > v_vhigh1 + 0.01:
            max_profit = float('inf')
        else:
            max_profit = max(max(pnls), v_vlow1, v_vhigh1)

        # Unlimited Loss (Max Loss is positive value)
        if v_vlow2 < v_vlow1 - 0.01 or v_vhigh2 < v_vhigh1 - 0.01:
            max_loss = float('inf')
        else:
            max_loss = abs(min(min(pnls), v_vlow1, v_vhigh1, 0))

        # Breakevens: detect zero crossings in piecewise linear function
        breakevens = []
        for i in range(len(test_prices) - 1):
            p1, p2 = test_prices[i], test_prices[i+1]
            v1, v2 = self.calculate_pnl(p1), self.calculate_pnl(p2)
            if v1 * v2 <= 0 and v1 != v2:
                slope = (v2 - v1) / (p2 - p1)
                be = p1 - v1 / slope
                breakevens.append(round(be, 2))

        # Also check infinite segment
        if v_vhigh1 * v_vhigh2 <= 0 and v_vhigh1 != v_vhigh2:
             # This happens if it crosses zero at very high price
             slope = (v_vhigh2 - v_vhigh1) / (p_vhigh2 - p_vhigh1)
             be = p_vhigh1 - v_vhigh1 / slope
             breakevens.append(round(be, 2))

        return {
            'max_profit': max_profit,
            'max_loss': max_loss,
            'breakevens': sorted(list(set(breakevens)))
        }

    def calculate_pnl(self, underlying_price: float) -> float:
        """Calculate P&L at given underlying price."""
        total_pnl = 0

        for leg in self.legs:
            # Intrinsic value at expiration
            if leg.option_type == 'call':
                intrinsic = max(0, underlying_price - leg.strike)
            else:
                intrinsic = max(0, leg.strike - underlying_price)

            # P&L for this leg
            if leg.position == 'long':
                leg_pnl = (intrinsic - leg.premium) * leg.quantity
            else:
                leg_pnl = (leg.premium - intrinsic) * leg.quantity

            total_pnl += leg_pnl

        return total_pnl

    def generate_pnl_table(
        self,
        price_range_pct: float = 0.1,
        steps: int = 20
    ) -> List[Dict[str, Any]]:
        """Generate P&L table across price range."""
        min_price = self.spot_price * (1 - price_range_pct)
        max_price = self.spot_price * (1 + price_range_pct)
        step_size = (max_price - min_price) / steps

        pnl_table = []
        for i in range(steps + 1):
            price = min_price + (step_size * i)
            pnl = self.calculate_pnl(price)

            pnl_table.append({
                'underlying_price': round(price, 2),
                'pnl': round(pnl, 2),
                'pnl_pct': round((pnl / abs(self.net_premium) * 100) if self.net_premium != 0 else 0, 2)
            })

        return pnl_table


class StrategyBuilder:
    """
    Build and analyze options strategies.

    Features:
    - Pre-built strategy templates
    - Custom strategy builder
    - P&L analysis and visualization
    - Risk metrics calculation
    """

    def __init__(self):
        self.strategies: Dict[str, Strategy] = {}

    def create_strategy(
        self,
        name: str,
        strategy_type: StrategyType,
        underlying: str,
        spot_price: float,
        legs: List[Dict[str, Any]]
    ) -> Strategy:
        """
        Create a new options strategy.

        Args:
            name: Strategy name
            strategy_type: Type of strategy
            underlying: Underlying symbol
            spot_price: Current spot price
            legs: List of leg dictionaries

        Returns:
            Strategy object
        """
        leg_objects = []
        for leg_data in legs:
            leg = Leg(
                strike=leg_data['strike'],
                option_type=leg_data['option_type'],
                position=leg_data['position'],
                quantity=leg_data.get('quantity', 1),
                premium=leg_data['premium'],
                expiry=leg_data['expiry'],
                delta=leg_data.get('delta', 0),
                gamma=leg_data.get('gamma', 0),
                theta=leg_data.get('theta', 0),
                vega=leg_data.get('vega', 0),
                iv=leg_data.get('iv', 0)
            )
            leg_objects.append(leg)

        strategy = Strategy(
            name=name,
            strategy_type=strategy_type,
            underlying=underlying,
            spot_price=spot_price,
            legs=leg_objects
        )

        # Attempt to populate Greeks if missing
        self._populate_greeks(strategy)

        self.strategies[name] = strategy
        return strategy

    def _populate_greeks(self, strategy: Strategy):
        """Estimate Greeks for legs that have none."""
        try:
            from core.greeks_calculator import greeks_calculator

            today = date.today()
            for leg in strategy.legs:
                # If Greeks are all 0, calculate them
                if leg.delta == 0 and leg.gamma == 0 and leg.theta == 0:
                    try:
                        expiry_date = datetime.strptime(leg.expiry, "%Y-%m-%d").date()
                        days_to_expiry = max((expiry_date - today).days, 0)
                        time_to_expiry = max(days_to_expiry / 365.0, 0.0001)

                        greeks = greeks_calculator.calculate_all_greeks(
                            strategy.spot_price,
                            leg.strike,
                            time_to_expiry,
                            0.20, # Base IV
                            leg.option_type,
                            leg.premium
                        )

                        leg.delta = greeks.get('delta', 0)
                        leg.gamma = greeks.get('gamma', 0)
                        leg.theta = greeks.get('theta', 0)
                        leg.vega = greeks.get('vega', 0)
                        leg.iv = greeks.get('implied_volatility', 0)
                    except Exception as e:
                        logger.warning(f"Error estimating greeks for leg {leg.strike}: {e}")
        except ImportError:
            logger.warning("GreeksCalculator not available for strategy builder")
        except Exception as e:
            logger.error(f"Error in _populate_greeks: {e}")

    def create_bull_call_spread(
        self,
        underlying: str,
        spot_price: float,
        lower_strike: float,
        higher_strike: float,
        lower_premium: float,
        higher_premium: float,
        expiry: str,
        quantity: int = 1
    ) -> Strategy:
        """Create a Bull Call Spread strategy."""
        legs = [
            {
                'strike': lower_strike,
                'option_type': 'call',
                'position': 'long',
                'quantity': quantity,
                'premium': lower_premium,
                'expiry': expiry
            },
            {
                'strike': higher_strike,
                'option_type': 'call',
                'position': 'short',
                'quantity': quantity,
                'premium': higher_premium,
                'expiry': expiry
            }
        ]

        return self.create_strategy(
            f"BullCall_{underlying}_{lower_strike}_{higher_strike}",
            StrategyType.BULL_CALL_SPREAD,
            underlying,
            spot_price,
            legs
        )

    def create_iron_condor(
        self,
        underlying: str,
        spot_price: float,
        put_sell_strike: float,
        put_buy_strike: float,
        call_sell_strike: float,
        call_buy_strike: float,
        premiums: Dict[str, float],
        expiry: str,
        quantity: int = 1
    ) -> Strategy:
        """Create an Iron Condor strategy."""
        legs = [
            {
                'strike': put_buy_strike,
                'option_type': 'put',
                'position': 'long',
                'quantity': quantity,
                'premium': premiums['put_buy'],
                'expiry': expiry
            },
            {
                'strike': put_sell_strike,
                'option_type': 'put',
                'position': 'short',
                'quantity': quantity,
                'premium': premiums['put_sell'],
                'expiry': expiry
            },
            {
                'strike': call_sell_strike,
                'option_type': 'call',
                'position': 'short',
                'quantity': quantity,
                'premium': premiums['call_sell'],
                'expiry': expiry
            },
            {
                'strike': call_buy_strike,
                'option_type': 'call',
                'position': 'long',
                'quantity': quantity,
                'premium': premiums['call_buy'],
                'expiry': expiry
            }
        ]

        return self.create_strategy(
            f"IronCondor_{underlying}_{put_sell_strike}_{call_sell_strike}",
            StrategyType.IRON_CONDOR,
            underlying,
            spot_price,
            legs
        )

    def create_long_straddle(
        self,
        underlying: str,
        spot_price: float,
        strike: float,
        call_premium: float,
        put_premium: float,
        expiry: str,
        quantity: int = 1
    ) -> Strategy:
        """Create a Long Straddle strategy."""
        legs = [
            {
                'strike': strike,
                'option_type': 'call',
                'position': 'long',
                'quantity': quantity,
                'premium': call_premium,
                'expiry': expiry
            },
            {
                'strike': strike,
                'option_type': 'put',
                'position': 'long',
                'quantity': quantity,
                'premium': put_premium,
                'expiry': expiry
            }
        ]

        return self.create_strategy(
            f"Straddle_{underlying}_{strike}",
            StrategyType.LONG_STRADDLE,
            underlying,
            spot_price,
            legs
        )

    def analyze_strategy(self, strategy_name: str) -> Dict[str, Any]:
        """Get comprehensive analysis of a strategy."""
        strategy = self.strategies.get(strategy_name)
        if not strategy:
            return {'error': 'Strategy not found'}

        pnl_table = strategy.generate_pnl_table()

        max_profit = strategy.max_profit
        if max_profit == float('inf'):
            max_profit_str = 'Unlimited'
        elif max_profit is None:
            max_profit_str = 'N/A'
        else:
            max_profit_str = round(max_profit, 2)

        max_loss = strategy.max_loss
        if max_loss == float('inf'):
            max_loss_str = 'Unlimited'
        elif max_loss is None:
            max_loss_str = 'N/A'
        else:
            max_loss_str = round(max_loss, 2)

        return {
            'name': strategy.name,
            'type': strategy.strategy_type.value,
            'underlying': strategy.underlying,
            'spot_price': strategy.spot_price,
            'net_premium': round(strategy.net_premium, 2),
            'max_profit': max_profit_str,
            'max_loss': max_loss_str,
            'breakeven_points': strategy.breakeven_points,
            'net_delta': round(strategy.net_delta, 4),
            'net_gamma': round(strategy.net_gamma, 6),
            'net_theta': round(strategy.net_theta, 4),
            'net_vega': round(strategy.net_vega, 4),
            'legs': [
                {
                    'strike': leg.strike,
                    'option_type': leg.option_type,
                    'position': leg.position,
                    'quantity': leg.quantity,
                    'premium': leg.premium,
                    'net_premium': round(leg.net_premium, 2)
                }
                for leg in strategy.legs
            ],
            'pnl_table': pnl_table,
            'payoff_chart_data': self._generate_payoff_chart_data(strategy)
        }

    def _generate_payoff_chart_data(self, strategy: Strategy) -> Dict[str, Any]:
        """Generate data for payoff chart."""
        pnl_table = strategy.generate_pnl_table()

        prices = [p['underlying_price'] for p in pnl_table]
        pnls = [p['pnl'] for p in pnl_table]

        # Find key points
        max_profit = max(pnls)
        max_loss = min(pnls)

        return {
            'prices': prices,
            'pnl': pnls,
            'max_profit': max_profit,
            'max_loss': max_loss,
            'breakevens': strategy.breakeven_points,
            'current_price': strategy.spot_price
        }

    def get_strategy_recommendations(
        self,
        market_view: str,  # 'bullish', 'bearish', 'neutral', 'volatile'
        iv_rank: float
    ) -> List[Dict[str, Any]]:
        """
        Get strategy recommendations based on market view and IV.

        Args:
            market_view: Expected market direction
            iv_rank: Current IV rank (0-100)

        Returns:
            List of recommended strategies
        """
        recommendations = []

        if market_view == 'bullish':
            if iv_rank < 30:
                recommendations.append({
                    'strategy': 'Long Call',
                    'rationale': 'Low IV - good for buying options',
                    'risk_level': 'high'
                })
            recommendations.append({
                'strategy': 'Bull Call Spread',
                'rationale': 'Defined risk bullish play',
                'risk_level': 'medium'
            })

        elif market_view == 'bearish':
            if iv_rank < 30:
                recommendations.append({
                    'strategy': 'Long Put',
                    'rationale': 'Low IV - good for buying options',
                    'risk_level': 'high'
                })
            recommendations.append({
                'strategy': 'Bear Put Spread',
                'rationale': 'Defined risk bearish play',
                'risk_level': 'medium'
            })

        elif market_view == 'neutral':
            if iv_rank > 50:
                recommendations.append({
                    'strategy': 'Iron Condor',
                    'rationale': 'High IV - benefit from selling premium',
                    'risk_level': 'medium'
                })
            recommendations.append({
                'strategy': 'Calendar Spread',
                'rationale': 'Profit from time decay difference',
                'risk_level': 'low'
            })

        elif market_view == 'volatile':
            if iv_rank < 40:
                recommendations.append({
                    'strategy': 'Long Straddle',
                    'rationale': 'Low IV - cheap volatility play',
                    'risk_level': 'high'
                })
            recommendations.append({
                'strategy': 'Long Strangle',
                'rationale': 'Cheaper than straddle, needs bigger move',
                'risk_level': 'high'
            })

        return recommendations


# Global instance
strategy_builder = StrategyBuilder()
