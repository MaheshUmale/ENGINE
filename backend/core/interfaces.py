from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime

class ILiveStreamProvider(ABC):
    """Interface for real-time data streaming."""

    @abstractmethod
    def subscribe(self, symbols: List[str], interval: str = "1"):
        """Subscribe to live updates for symbols."""
        pass

    @abstractmethod
    def unsubscribe(self, symbol: str, interval: str = "1"):
        """Unsubscribe from live updates."""
        pass

    @abstractmethod
    def set_callback(self, callback: Callable[[Dict[str, Any]], None]):
        """Set the callback for incoming data."""
        pass

    @abstractmethod
    def start(self):
        """Start the streaming connection."""
        pass

    @abstractmethod
    def stop(self):
        """Stop the streaming connection."""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if the provider is connected."""
        pass


class IOptionsDataProvider(ABC):
    """Interface for fetching options chain and OI data."""

    @abstractmethod
    async def get_option_chain(self, underlying: str) -> Dict[str, Any]:
        """Fetch the full option chain for an underlying."""
        pass

    @abstractmethod
    async def get_oi_data(self, underlying: str, expiry: str, time_str: str) -> Dict[str, Any]:
        """Fetch OI data for a specific expiry and time."""
        pass

    @abstractmethod
    async def get_expiry_dates(self, underlying: str) -> List[str]:
        """Fetch available expiry dates."""
        pass


class IHistoricalDataProvider(ABC):
    """Interface for fetching historical market data."""

    @abstractmethod
    async def get_hist_candles(self, symbol: str, interval: str, count: int) -> List[List]:
        """Fetch historical candles [ts, o, h, l, c, v]."""
        pass
