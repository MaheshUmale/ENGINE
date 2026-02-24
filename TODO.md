# PRODESK Implementation TODO & Upgrades

This list tracks the remaining features and planned upgrades for the ProDesk Trading Terminal.

## 🟢 Priority: High (Trading Functionality)
- [x] **State Recovery Engine**: Implement a robust session recovery mechanism so that the Trading Bot can resume active trades and trailing stop-losses after a server restart.
- [ ] **Dynamic Slippage Modeling**: Enhance the paper trading engine to use a dynamic slippage model based on current Bid-Ask spread rather than a fixed percentage.
- [ ] **Multi-Broker API Integration**: Add execution modules for Zerodha (Kite) and Dhan APIs to allow transition from paper to live trading.

## 🟡 Priority: Medium (Analysis & UI)
- [ ] **Portfolio-Level Greeks**: Add a new tab in the Options Dashboard to track aggregate Delta, Theta, and Vega exposure across all open positions.
- [x] **Custom Indicator Builder**: Create a UI-based indicator builder allowing users to define custom confluence rules using price, volume, and OI data (Implemented JavaScript-based scripting).
- [x] **Historical Strategy Optimizer**: A tool to automatically find the best Symmetry parameters (ATR multiplier, pullback depth) for a specific symbol over the last 30 days (GUI-based Backtester implemented).

## 🔵 Priority: Low (Features & UX)
- [ ] **PWA Conversion**: Add a manifest and service worker to make the terminal installable as a mobile app.
- [ ] **ML Volatility Forecast**: Implement a simple Scikit-Learn or TensorFlow model to predict IV spikes 15 minutes in advance.
- [ ] **Telegram Bot Integration**: Allow users to query bot status, PnL, and latest signals via a Telegram bot.
- [ ] **Strategy Marketplace**: Allow users to save and share their strategy builder configurations as JSON templates.

## 🛠️ Maintenance & Optimization
- [ ] **DuckDB Partitioning**: Implement daily partitioning for the `ticks` table in DuckDB to maintain query performance as data grows.
- [ ] **WebSocket Load Balancing**: Prepare the `DataEngine` to handle multi-instance distribution for high-symbol-count environments.
- [ ] **Unit Test Suite**: Expand the `tests/` directory to cover core strategy logic and Greeks calculation accuracy.
