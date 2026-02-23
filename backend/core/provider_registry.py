import logging
from typing import Dict, List, Type, Any, Optional, TypeVar, Generic
from core.interfaces import ILiveStreamProvider, IOptionsDataProvider, IHistoricalDataProvider

logger = logging.getLogger(__name__)

T = TypeVar('T')

class ProviderRegistry(Generic[T]):
    """Registry for managing multiple data providers of a specific type."""
    def __init__(self, interface_type: Type[T]):
        self.interface_type = interface_type
        self.providers: Dict[str, T] = {}
        self.priorities: Dict[str, int] = {}
        self.priority_list: List[str] = []

    def register(self, name: str, provider: T, priority: int = 0):
        """Register a new provider."""
        if not isinstance(provider, self.interface_type):
            raise TypeError(f"Provider {name} must implement {self.interface_type.__name__}")

        self.providers[name] = provider
        self.priorities[name] = priority

        if name not in self.priority_list:
            self.priority_list.append(name)

        # Sort priority list based on stored priorities
        self.priority_list.sort(key=lambda x: self.priorities.get(x, 0), reverse=True)
        logger.info(f"Registered {self.interface_type.__name__} provider: {name} (priority: {priority})")

    def get_provider(self, name: str) -> Optional[T]:
        """Get a specific provider by name."""
        return self.providers.get(name)

    def get_primary(self) -> Optional[T]:
        """Get the highest priority provider."""
        if not self.priority_list:
            return None
        return self.providers[self.priority_list[0]]

    def get_all(self) -> List[T]:
        """Get all registered providers in priority order."""
        return [self.providers[name] for name in self.priority_list]


# Global registries
live_stream_registry = ProviderRegistry(ILiveStreamProvider)
options_data_registry = ProviderRegistry(IOptionsDataProvider)
historical_data_registry = ProviderRegistry(IHistoricalDataProvider)

def initialize_default_providers():
    """Seed the registries with existing implementations."""
    from config import UPSTOX_ACCESS_TOKEN
    from external.providers import (
        TradingViewLiveStreamProvider,
        TrendlyneOptionsProvider,
        NSEOptionsProvider,
        TradingViewHistoricalProvider,
        UpstoxLiveStreamProvider,
        UpstoxOptionsProvider,
        UpstoxHistoricalProvider
    )

    # Live Stream
    live_stream_registry.register("tradingview", TradingViewLiveStreamProvider(), priority=10)
    if UPSTOX_ACCESS_TOKEN:
        live_stream_registry.register("upstox", UpstoxLiveStreamProvider(), priority=20)

    # Options Data
    options_data_registry.register("trendlyne", TrendlyneOptionsProvider(), priority=20)
    options_data_registry.register("nse", NSEOptionsProvider(), priority=5)
    if UPSTOX_ACCESS_TOKEN:
        options_data_registry.register("upstox", UpstoxOptionsProvider(), priority=10)

    # Historical Data
    # TradingView is preferred for charts due to reliable volume and multiple timeframes
    historical_data_registry.register("tradingview", TradingViewHistoricalProvider(), priority=20)
    if UPSTOX_ACCESS_TOKEN:
        historical_data_registry.register("upstox", UpstoxHistoricalProvider(), priority=10)
