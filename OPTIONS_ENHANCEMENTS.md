# PRODESK Enhanced Options Trading Platform

## Overview

This document outlines the comprehensive enhancements made to the NSE Options Trading App, transforming it into a professional-grade options analysis and trading platform.

## New Features

### 1. Options Greeks Calculator (`core/greeks_calculator.py`)

**Features:**
- Real-time calculation of all major Greeks:
  - **Delta**: Measures rate of change of option price relative to underlying
  - **Gamma**: Rate of change of Delta
  - **Theta**: Time decay (daily)
  - **Vega**: Sensitivity to volatility changes
  - **Rho**: Sensitivity to interest rate changes
- Implied Volatility (IV) calculation using Newton-Raphson method
- Intrinsic and Time Value calculation
- ATM/ITM/OTM strike categorization
- Chain-wide Greeks calculation

**API Endpoints:**
- `GET /api/options/greeks/{underlying}` - Calculate Greeks for specific option
- `GET /api/options/chain/{underlying}/with-greeks` - Get chain with all Greeks

### 2. Implied Volatility Analyzer (`core/iv_analyzer.py`)

**Features:**
- **IV Rank**: Current IV relative to 52-week range (0-100 scale)
- **IV Percentile**: Percentage of days with IV below current level
- **IV Skew Analysis**: OTM put vs OTM call IV comparison
- **Term Structure Analysis**: IV across different expiries
- IV spike detection
- Trading signals based on IV levels

**API Endpoints:**
- `GET /api/options/iv-analysis/{underlying}` - Get comprehensive IV metrics

**Interpretation:**
- IV Rank > 70: Favorable for selling options (Iron Condors, Credit Spreads)
- IV Rank < 30: Favorable for buying options (Long Straddles, Debit Spreads)

### 3. OI Buildup Analyzer (`core/oi_buildup_analyzer.py`)

**Features:**
- Automatic detection of OI buildup patterns:
  - **Long Buildup**: OI increases + Price increases (Bullish)
  - **Short Buildup**: OI increases + Price decreases (Bearish)
  - **Long Unwinding**: OI decreases + Price decreases (Bearish)
  - **Short Covering**: OI decreases + Price increases (Bullish)
- Pattern strength classification (strong/moderate/weak)
- Support/Resistance levels based on OI concentration
- Overall market sentiment analysis

**API Endpoints:**
- `GET /api/options/oi-buildup/{underlying}` - Get buildup analysis
- `GET /api/options/support-resistance/{underlying}` - Get key levels

### 4. Strategy Builder (`core/strategy_builder.py`)

**Features:**
- Pre-built strategy templates:
  - Single Leg: Long/Short Calls and Puts
  - Vertical Spreads: Bull Call, Bear Put, Bull Put, Bear Call
  - Iron Condors and Iron Butterflies
  - Straddles and Strangles
  - Calendar Spreads
- Custom strategy builder
- P&L calculation at any underlying price
- Risk metrics: Max Profit, Max Loss, Breakeven points
- Net Greeks calculation for entire strategy
- Payoff chart data generation
- Strategy recommendations based on market view and IV

**API Endpoints:**
- `POST /api/strategy/build` - Build custom strategy
- `POST /api/strategy/bull-call-spread` - Create bull call spread
- `POST /api/strategy/iron-condor` - Create iron condor
- `POST /api/strategy/long-straddle` - Create long straddle
- `GET /api/strategy/{strategy_id}/analysis` - Get strategy analysis
- `GET /api/strategy/recommendations` - Get strategy recommendations

### 5. Alert System (`core/alert_system.py`)

**Features:**
- Multiple alert types:
  - Price above/below thresholds
  - Price change percentage
  - OI change percentage
  - PCR above/below thresholds
  - IV rank thresholds
  - Volume spikes
  - OI buildup patterns
  - Greeks thresholds
- Cooldown periods to prevent spam
- Multiple notification channels (WebSocket, extensible)
- Preset alerts for common scenarios

**API Endpoints:**
- `POST /api/alerts/create` - Create new alert
- `GET /api/alerts` - Get all alerts
- `DELETE /api/alerts/{alert_id}` - Delete alert
- `POST /api/alerts/{alert_id}/pause` - Pause alert
- `POST /api/alerts/{alert_id}/resume` - Resume alert

### 6. Refined Options Dashboard (Unified UI)

**Implementation Details:**
- **Analysis Overview**: Merges three distinct analysis views into a single cockpit to minimize tab-switching.
- **Net Delta & Theta**: Calculated as `Σ(OI * Greek)` for the entire chain, providing a "Market Net Exposure" metric in Millions (M).
- **IV Rank Logic**: Robust calculation using `(Current IV - Min IV) / (Max IV - Min IV)`. Fallback to 0.0 if sufficient history is unavailable, ensuring high-integrity signals.
- **Tabbed Interface**:
  - **Chain**: Real-time Greeks, Volume, and OI profile.
  - **Analysis Overview**: Spot-PCR Confluence, OI Distribution, and Merged Trend charts.
  - **Strategies**: Payoff charts and risk/reward metrics for multi-leg positions.
  - **Scalper**: Real-time confluence tracking and automated execution logs.
  - **System**: Real-time TradingView data engine health, cache metrics, and latency monitoring.

## Database Schema Updates

### Enhanced `options_snapshots` Table
```sql
-- New columns added:
- iv (Implied Volatility)
- delta
- gamma
- theta
- vega
- intrinsic_value
- time_value
```

## API Summary

### Options Endpoints
| Endpoint | Description |
|----------|-------------|
| `GET /api/options/chain/{underlying}` | Get option chain with Greeks |
| `GET /api/options/greeks/{underlying}` | Calculate Greeks for option |
| `GET /api/options/oi-buildup/{underlying}` | OI buildup analysis |
| `GET /api/options/iv-analysis/{underlying}` | IV analysis |
| `GET /api/options/support-resistance/{underlying}` | Key levels |
| `GET /api/options/pcr-trend/{underlying}` | PCR historical data |
| `GET /api/options/oi-analysis/{underlying}` | OI distribution |
| `POST /api/options/backfill` | Trigger backfill |

### Strategy Endpoints
| Endpoint | Description |
|----------|-------------|
| `POST /api/strategy/build` | Build custom strategy |
| `POST /api/strategy/bull-call-spread` | Bull call spread |
| `POST /api/strategy/iron-condor` | Iron condor |
| `POST /api/strategy/long-straddle` | Long straddle |
| `GET /api/strategy/{id}/analysis` | Strategy analysis |
| `GET /api/strategy/recommendations` | Get recommendations |

### Alert Endpoints
| Endpoint | Description |
|----------|-------------|
| `POST /api/alerts/create` | Create alert |
| `GET /api/alerts` | List alerts |
| `DELETE /api/alerts/{id}` | Delete alert |
| `POST /api/alerts/{id}/pause` | Pause alert |
| `POST /api/alerts/{id}/resume` | Resume alert |

## Usage Examples

### Calculate Greeks
```javascript
const response = await fetch('/api/options/greeks/NSE:NIFTY?strike=25000&option_type=call&spot_price=24800&option_price=150');
const greeks = await response.json();
// Returns: { delta, gamma, theta, vega, rho, implied_volatility, ... }
```

### Build Iron Condor
```javascript
const response = await fetch('/api/strategy/iron-condor', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        underlying: 'NSE:NIFTY',
        spot_price: 25000,
        put_sell_strike: 24800,
        put_buy_strike: 24600,
        call_sell_strike: 25200,
        call_buy_strike: 25400,
        premiums: { put_buy: 15, put_sell: 35, call_sell: 40, call_buy: 18 },
        expiry: '2024-02-29'
    })
});
```

### Create PCR Alert
```javascript
const response = await fetch('/api/alerts/create', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        name: 'NIFTY PCR High',
        alert_type: 'pcr_above',
        underlying: 'NSE:NIFTY',
        condition: { threshold: 1.5 },
        cooldown_minutes: 30
    })
});
```

## Trading Strategies Guide

### High IV Environment (IV Rank > 70)
- **Iron Condor**: Sell OTM call and put spreads
- **Credit Spreads**: Directional plays with premium collection
- **Short Strangle**: Sell OTM calls and puts

### Low IV Environment (IV Rank < 30)
- **Long Straddle**: Buy ATM call and put
- **Long Strangle**: Buy OTM call and put
- **Debit Spreads**: Directional plays with limited risk

### Bullish View
- **Bull Call Spread**: Buy ITM call, sell OTM call
- **Short Put**: Collect premium if bullish
- **Cash-Secured Put**: Acquire stock at discount

### Bearish View
- **Bear Put Spread**: Buy ITM put, sell OTM put
- **Short Call**: Collect premium if bearish
- **Protective Put**: Insurance for long stock

## Performance Considerations

- Interface-based data ingestion for multi-provider redundancy
- Automatic failover for Open Interest data
- Optimized circular buffers for high-speed scalper signal generation
- Greeks calculations use optimized Black-Scholes model
- IV history maintained for 252 trading days
- Alert cooldowns prevent notification spam
- WebSocket rooms for efficient real-time updates
- Database indexing on underlying and timestamp

### 7. NSE Confluence Scalper (`brain/nse_confluence_scalper.py`)

**Features:**
- **Multi-Dimensional Confluence**: Executes trades only when all signals align:
  - **Price Levels**: Underlying at Support/Resistance or High Volume Node (HVN).
  - **Trend Confirmation**: PCR trend matching the trade direction.
  - **Breakout/Breakdown**: Option price breaking local swing high + inverse option breaking local swing low.
- **High-Speed Execution**: Uses 500-tick circular buffers for millisecond-level calculation.
- **Automated Level Detection**: Swing points via `scipy.signal.find_peaks` and Volume Profile HVNs.
- **Risk Management**:
  - Fixed ₹2,000 risk per trade with auto-quantity calculation.
  - 15% Hard Stop Loss or Confluence Level.
  - Trailing Stop Loss moved to Break-even after +10% gain.
  - **Theta Protection**: Automatic exit if premium doesn't move >1% within 3 minutes of entry.
- **Real-time Logging**: Detailed "Log Pulse" in the dashboard.
- **Trade Persistence**: All executed trades saved to `trades.csv`.

**API Endpoints:**
- `POST /api/scalper/start` - Start scalper for specific underlying
- `POST /api/scalper/stop` - Stop active scalper
- `GET /api/scalper/status` - Get running status and active trades

### 8. Advanced Historical Trends

**Features:**
- **Relative Analysis**: Multi-chart view in PCR Trend tab to compare:
  - **Spot Price Trend**: Line chart with localized IST time.
  - **PCR Trend**: Combined OI and Volume PCR tracking.
  - **Total OI Trend**: Aggregate market participation over time.
  - **OI Change Trend**: Bar chart highlighting net buyer/seller momentum.
- **Auto-Scaling**: All Y-axes dynamically adjust for clear visualization of relative changes.

### 9. Interface-Based Architecture (`core/interfaces.py`)

**Features:**
- **Decoupled Providers**: All external data feeds (WSS, OI, History) are interface-based.
- **Provider Registry**: Manage multiple sources with priority and weightage.
- **Redundancy**: Automatic failover (e.g., switches to NSE India if Trendlyne is unavailable).
- **Extensibility**: Add new data providers without modifying core application logic.

## Regional Localization

- **Indian Standard Time (IST)**: All timestamps across the terminal are localized to IST (UTC+5:30).
- **Dashboard Synchronization**: "Last Updated" and chart X-axes default to 09:15-15:30 IST market hours.

## Future Enhancements

Potential features for future releases:
- Paper trading module
- Backtesting engine
- Machine learning for IV prediction
- Multi-broker order integration
- Portfolio-level Greeks tracking
- Multi-leg order suggestions
- Historical strategy performance

## Credits

Enhanced by the ProDesk Development Team
Version 3.0 - February 2026
