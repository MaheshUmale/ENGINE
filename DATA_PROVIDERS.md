# ProTrade Data Provider Architecture & Integration Interface

This document provides explicit details on how to integrate external data sources (WebSockets and APIs) into the ProTrade platform.

## 1. Real-Time Streaming Interface (`ILiveStreamProvider`)

To feed live tick data or OHLCV updates from a new WebSocket source, implement the `ILiveStreamProvider` interface.

### Expected Data Structures

The callback set via `set_callback(callback)` MUST be invoked with a dictionary containing one of the following formats:

#### A. Tick Update (Raw Tick)
Used for high-frequency order flow and price tracking.
```python
{
    "type": "raw_tick",
    "data": {
        "NSE:NIFTY": {  # Key is the Instrument Key
            "last_price": 25120.50,
            "ltq": 50,          # Last Traded Quantity (Volume of last tick)
            "ts_ms": 1700000000000, # Timestamp in Milliseconds
            "bid": 25120.00,    # Optional
            "ask": 25121.00     # Optional
        }
    }
}
```

#### B. Chart Update (OHLCV)
Used for updating candlestick charts and indicators.
```python
{
    "type": "chart_update",
    "instrumentKey": "NSE:NIFTY",
    "interval": "1",
    "ohlcv": [
        [1700000000, 25100.0, 25130.0, 25090.0, 25120.5, 15000] # [ts, o, h, l, c, v]
    ]
}
```

## 2. Option Chain & OI Interface (`IOptionsDataProvider`)

To integrate a new Options Data API (like a different broker or data vendor).

### Expected Return Formats

#### `get_option_chain(underlying)`
Must return a dictionary structured for the frontend chain view:
```python
{
    "timestamp": "2024-02-18T10:00:00Z",
    "underlying_price": 25120.5,
    "symbols": [
        {
            "f": [
                "NIFTY240229C25000", # Symbol [0]
                "25000.0",          # Strike [1]
                "call",             # Option Type [2]
                25120.5,            # Spot Price [3] (at time of snapshot)
                150.0,              # LTP [4]
                1500,               # Volume [5]
                250000,             # OI [6]
                50000,              # OI Change [7]
                1709164800,         # Expiry (Unix TS) [8]
                0.55,               # Delta [9]
                0.0002,             # Gamma [10]
                -12.5,              # Theta [11]
                2.5,                # Vega [12]
                0.18                # IV [13]
            ]
        },
        # ... more strikes
    ]
}
```

## 3. Historical Data Interface (`IHistoricalDataProvider`)

### `get_hist_candles(symbol, interval, count)`
Must return a list of lists, where each sub-list is a candle:
`[[ts, o, h, l, c, v], ...]`
- **ts**: Unix timestamp (seconds)
- **o, h, l, c**: Floats
- **v**: Integer

## Integration Steps

1. **Implement Class**: Create a class in `backend/external/` inheriting from the relevant interface.
2. **Handle Errors**: Use internal retries. The application expects providers to handle their own connection stability.
3. **Register**: Add to `backend/core/provider_registry.py`.
   ```python
   # Example: Adding a custom API provider
   from external.my_api import MyApiProvider
   options_data_registry.register("my_vendor", MyApiProvider(), priority=20)
   ```

## Design Principles
- **Asynchronous**: All API methods (`IOptionsDataProvider`, `IHistoricalDataProvider`) MUST be `async`.
- **Non-Blocking**: Heavy processing in `ILiveStreamProvider` callbacks should be offloaded to threads or optimized to avoid blocking the main event loop.
- **Thread Safety**: Providers are shared across multiple components; ensure thread-safe access to internal buffers.
