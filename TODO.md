# Triple-Stream Symmetry & Unwinding Engine - TODO List

## Implementation Status (README Specification)

### 1. Data Orchestration
- [x] Stream Index Spot, ATM Call (CE), ATM Put (PE) simultaneously.
- [x] Timeframe support (1-min, 3-min, 5-min).
- [x] Dynamic strike update every 5 mins.
- [x] Dynamic strike update on Index move > 25 pts (NIFTY) / 100 pts (BANKNIFTY).
- [x] Use Futures volume as a proxy for Index volume.
- [x] Implement Upstox V3 Market Data Streamer with Auto-Reconnect.
- [x] Modernize history fetching to Upstox V3 APIs with manual request fallbacks.

### 2. Strategy Logic (The Algorithm)
- [x] **Phase I**: Identify "Significant Swings" and log Reference Levels (Index, CE, PE).
- [x] **Phase II**: Implement Decay Filter (Anti-Theta) for bullish/bearish divergence.
- [x] **Phase III**: Triple-Symmetry & Panic Trigger (Index break, CE break, PE breakdown, OI Panic).
- [x] **Phase IV**: Trap Guardrails (Absorption, Fake Break, Asymmetry).
- [x] **Exit Logic**:
    - [x] Symmetry breaks (LTP vs Base).
    - [x] Opposite Option stops making lows/OI falling (The "Target" exit).

### 3. Analytics & Metrics
- [x] Price Velocity: Rate of change over 3 candles.
- [x] Relative Strength: (Option % Change) / (Index % Change).
- [x] OI Delta: 1-minute change in Open Interest.
- [x] Confluence Score: 4/4 point system for trade entry.

### 4. System Features
- [x] Paper Trading Engine: Simulation at LTP with Slippage (0.1%) and Transaction Fees.
- [x] Database Persistence: Raw ticks, aggregated candles, signals, trades, reference levels.
- [x] Backtesting Mechanism: Day-by-day historical simulation with daily ATM discovery.
- [x] Parallel Monitoring: Run NIFTY and BANKNIFTY in the same process.
- [x] Visualization: Interactive Plotly candlestick chart with signal/trade markers at Index Spot.
- [x] Risk Management: Max Daily Loss and Max Positions enforcement.
- [x] Alert System: Telegram notification support.
- [x] Web Dashboard: FastAPI-based dashboard for real-time monitoring.

---

## Improvisations & Enhancements

### Completed
- [x] **Multi-Strike Discovery**: Discovery of 7 strikes (3 OTM, 1 ATM, 3 ITM) for broader context.
- [x] **Advanced Swing Detection**: 2-candle pullback confirmation for high-conviction walls.
- [x] **Realistic Execution Engine**: Integrated STT, GST, and Brokerage simulation.
- [x] **V3 Streaming**: Protobuf-decoded real-time market data streaming.
- [x] **Clean Visualization**: Automatic removal of market gaps in backtest charts.
- [x] **Instrument Master Cache**: Optimized discovery via assets.upstox.com JSON master.

### Pending / Planned Improvements
- [x] **Performance Reporting**: Add detailed metrics (Sharpe Ratio, Win Rate, Max Drawdown) to backtest results.
- [x] **Local Metadata Cache**: Save Instrument Master to disk to avoid 20MB download on every startup.
- [x] **Dynamic Backtesting**: Backtester now periodically updates ATM strikes to reflect mid-day price moves.
- [x] **Tick Batching**: Optimized database performance by batching raw tick persistence.
- [x] **Trailing SL Optimization**: Implement ATR-based dynamic trailing stop losses.
- [x] **Multi-Timeframe Confirmation**: Add logic to confirm 1m signals using 5m trend direction.
- [x] **Auto-Strike Rollover**: Logic to handle expiry day transitions between current and next week contracts.
- [x] **Dashboard Enhancements**: Add equity curve chart and performance metrics (Sharpe, Drawdown).
