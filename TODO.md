# Triple-Stream Symmetry & Unwinding Engine - TODO List

## Implementation Status (README Specification)

### 1. Data Orchestration
- [x] Stream Index Spot, ATM Call (CE), ATM Put (PE) simultaneously.
- [x] Timeframe support (1-min, 3-min, 5-min).
- [x] Dynamic strike update (every 5 mins).
- [x] Dynamic strike update on Index move > 25 pts (NIFTY) / 100 pts (BANKNIFTY).
- [x] Use Futures volume as a proxy for Index volume.
- [x] Implement Upstox V3 Market Data Streamer.
- [x] Modernize history fetching to Upstox V3 APIs with V2 fallback.

### 2. Strategy Logic (The Algorithm)
- [x] **Phase I**: Identify "Significant Swings" and log Reference Levels (Index, CE, PE).
- [x] **Phase II**: Implement Decay Filter (Anti-Theta) for bullish/bearish divergence.
- [x] **Phase III**: Triple-Symmetry & Panic Trigger.
    - [x] Index break Reference High/Low.
    - [x] Option break its own Reference High.
    - [x] Opposite Option break below local support/low.
    - [x] OI Panic (Short Covering) - OI Delta calculation.
- [x] **Phase IV**: Trap Guardrails.
    - [x] Absorption Trap detection.
    - [x] Fake Break detection (increasing OI).
    - [x] Asymmetry detection.
- [x] **Exit Logic**:
    - [x] Symmetry breaks (LTP vs Base).
    - [x] Opposite Option stops making lows/OI falling.

### 3. Analytics & Metrics
- [x] Price Velocity: Rate of change over 3 candles.
- [x] Relative Strength: (Option % Change) / (Index % Change).
- [x] OI Delta: 1-minute change in Open Interest.
- [x] Confluence Score: 4/4 point system for trade entry.

### 4. System Features
- [x] Paper Trading Engine: Simulation at LTP with Slippage (0.1%) and Fees.
- [x] Database Persistence: Raw ticks, aggregated candles, signals, trades, reference levels.
- [x] Backtesting Mechanism: Historical simulation with daily ATM discovery.
- [x] Parallel Monitoring: Run NIFTY and BANKNIFTY in the same process.
- [x] Visualization: Interactive Plotly candlestick chart with signal/trade markers at Index Spot.
- [x] Risk Management: Max Daily Loss and Max Positions enforcement.
- [x] Alert System: Telegram notification support.
- [x] Web Dashboard: FastAPI-based dashboard for real-time monitoring.

---

## Improvisations & Enhancements

### Completed
- [x] **Multi-Strike Discovery**: Implement discovery of 7 strikes (3 OTM, 1 ATM, 3 ITM).
- [x] **Advanced Swing Detection**: Refined swing detection using 2-candle confirmation.
- [x] **Realistic Execution**: Added slippage and transaction fee simulation.
- [x] **Robust Streamer**: Enabled auto-reconnect and error recovery.
- [x] **V3 Integration**: Full upgrade to latest Upstox APIs.
- [x] **Dashboard**: Live trade and signal visualization.
- [x] **Dynamic Update Trigger**: Automated instrument update on significant price moves.
