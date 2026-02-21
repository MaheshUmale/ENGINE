# Triple-Stream Symmetry & Unwinding Engine - TODO List

## Implementation Status (README Specification)

### 1. Data Orchestration
- [x] Stream Index Spot, ATM Call (CE), ATM Put (PE) simultaneously.
- [x] Timeframe support (1-min, 3-min, 5-min).
- [x] Dynamic strike update (every 5 mins or > 25 pts index move).
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
- [x] Paper Trading Engine: Simulation at LTP.
- [x] Database Persistence: Raw ticks, aggregated candles, signals, trades, reference levels.
- [x] Backtesting Mechanism: Historical simulation with daily ATM discovery.
- [x] Parallel Monitoring: Run NIFTY and BANKNIFTY in the same process.
- [x] Visualization: Interactive Plotly candlestick chart with signal/trade markers at Index Spot.

---

## Improvisations & Enhancements

### Pending / In-Progress
- [ ] **Multi-Strike Discovery**: Implement discovery of 7 strikes (3 OTM, 1 ATM, 3 ITM) as per user's preferred logic.
- [ ] **Advanced Swing Detection**: Refine swing detection using multi-candle confirmation (ZigZag style).
- [ ] **Realistic Execution**: Add slippage (0.1%) and transaction cost simulation to Paper Trading.
- [ ] **Robust Streamer**: Implement auto-reconnect and error recovery for `MarketDataStreamerV3`.
- [ ] **Project Setup**: Create `requirements.txt` and standardize folder structure.

### Proposed
- [ ] **Dashboard**: Simple web dashboard (FastAPI + Jinja2) to view live trades and signals.
- [ ] **Risk Management**: Implement Max Daily Loss and Max Open Positions.
- [ ] **Alerts**: Integrate Telegram/Discord notifications for signals.
