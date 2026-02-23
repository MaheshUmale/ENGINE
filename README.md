# PRODESK Simplified Terminal

A minimal, high-performance trading terminal featuring TradingView charting, real-time WebSocket data, and candle-by-candle replay.

## Features

- **Minimal UI**: Clean interface with only a search bar and a full-screen chart.
- **TradingView Charts**: Powered by TradingView Lightweight Charts (v4.1.1) for professional-grade charting with native zoom and pan.
- **Zoom Controls**: Dedicated (+), (-), and RESET buttons for easy timescale management.
- **Candle-by-Candle Replay**:
  - Enter Replay mode to analyze historical price action.
  - **Select Start**: Click anywhere on the chart to set the starting point for replay.
  - **Playback**: Use Play/Pause, Next, and Previous buttons to step through candles one by one.
- **Real-time Data Flow**:
  - Live quote streaming and indicator plot data via TradingView WebSocket (WSS) protocol.
  - **Indicator Integration**: Directly pulls plot data from Pine Script studies (Bubbles, S/R Dots, Pivot Lines, etc.).
  - **Room-based Broadcasting**: Uses Socket.IO rooms named after symbol HRNs to ensure efficient, targeted data delivery.
- **Multi-Chart Layouts**:
  - Toggle between **1, 2, or 4-chart** grids using the layout selector.
  - Each chart instance operates independently with its own symbol, interval, and indicator state.
  - Automatic grid resizing for optimal screen utilization.
- **Layout Persistence**:
  - Automatically saves your layout, symbols, intervals, and drawing tools to `localStorage`.
  - Restores your previous setup instantly on refresh.
- **URL Parameters**:
  - Open a specific symbol and interval directly via the URL (e.g., `?symbol=NSE:RELIANCE&interval=5`).
  - This mode automatically sets the layout to 1 chart.
- **Maximize Chart**:
  - Use the **MAXIMIZE** button to open the currently active chart in a new browser tab for focused, full-screen analysis.
- **Advanced Visualization**:
  - **Markers & Shapes**: Dynamic rendering of volume bubbles and S/R dots using Lightweight Charts markers.
  - **Bar Coloring**: Real-time candle color updates based on study-provided volume and trend metrics, with a built-in RVOL (Relative Volume) fallback for consistent trend analysis.
  - **Background Shading**: Highlighting of specific market conditions (e.g., breakout zones) via background colors.
  - **Smart Scaling**: Automatic Y-axis management to prevent low-value oscillators from compressing the price action.
- **Enhanced Search & Discovery**:
  - **Unified Search**: Search for indices (NIFTY, BANKNIFTY) or stocks (RELIANCE) and get instant results.
  - **Options Discovery**: Automatically merges results from the TradingView Options Scanner.
  - **Technical Search**: Search using exact technical strings (e.g., `NIFTY260210C25600`) for precise contract selection.
- **Confluence Visuals**:
  - **OI Profile Overlay**: Toggleable vertical histogram directly on the chart showing Call vs Put Open Interest across all strikes.
  - **Analysis Center Sidebar**: Integrated panel showing OiGenie predictions (institutional control), OI Buildup Pulse, and real-time Scalper metrics.
  - **Synchronized Replay**: Historical replay mode now fully synchronizes with historical OI and PCR data, simulating the exact market state for strategy refinement.
- **Triple-Stream Symmetry & Panic Strategy**:
  - Implements the "Wall-to-Void" algorithm for index scalping.
  - **Symmetry Detection**: Synchronizes Index Spot, ATM Call, and ATM Put price action.
  - **Panic Filter**: Real-time OI Delta tracking to detect seller unwinding (short covering).
  - **Decay Divergence**: Detects bullish momentum by identifying option prices that resist theta decay.
  - **Automated Visualization**: Direct marking of BUY_CE/BUY_PE signals on the chart with dynamic SL and TP price lines.
- **Efficient Backend**: Built with FastAPI and DuckDB for low-latency data handling and persistence.
- **Enhanced Data Engine**: Integrated enterprise-grade TradingView module featuring:
  - **Intelligent Caching**: Multi-layered cache for historical and real-time data.
  - **Connection Monitoring**: Real-time tracking of latency, stability, and protocol health.
  - **Fault Recovery**: Automatic data source failover and exponential backoff reconnection.
  - **Data Quality Engine**: Automated validation of OHLC logic and sequence continuity.
- **DuckDB Viewer**: A dedicated SQL-based viewer at `/db-viewer` that shares the application's database connection, allowing real-time table inspection and custom queries without file-locking issues.
- **Options Analysis Dashboard**:
  - A specialized dashboard at `/options` for deep-dive options analysis.
  - **Analysis Overview**: A unified cockpit merging Spot-PCR Confluence, OI Distribution, and Merged OI Trends (Total vs Chg) into a single view.
  - **Real-time Option Chain**: Live streaming of LTP, Greeks (Delta, Theta, IV), and OI metrics.
  - **Institutional Control**: OiGenie Market Control pulse and institutional range detection.
  - **OI Buildup Pulse**: Real-time census of Long/Short buildup and covering across all strikes.
  - **NSE Confluence Scalper**: Automated option buying engine using price action and OI confluence.
  - **System Monitoring**: Dedicated "System" tab for real-time tracking of the TradingView engine's health score, cache hits, and request latency.
  - **Automated Data Management**: Background backfilling and periodic snapshots (every 5 minutes).
- **Specialized Tick-Based Charts**:
  - **Tick Chart**: A dedicated chart at `/tick` that aggregates raw ticks into OHLC candles based on a customizable "ticks per candle" setting.
  - **Renko Chart**: A price-movement-based chart at `/renko` that forms "bricks" based on a customizable box size, filtering out noise.
  - **IST Timestamps**: All tick-based charts are standardized to Indian Standard Time (IST) for accurate market tracking.
  - **Tick/Renko Replay**: Full replay support for both specialized charts, allowing historical tick-by-tick analysis.

## Architecture

- **Frontend**: SPA built with Tailwind CSS. Utilizes `lightweight-charts` for rendering and `Chart.js` for options analysis.
- **Backend**:
  - **Interface-Based Data Layer**: Decoupled ingestion layer using `ILiveStreamProvider`, `IOptionsDataProvider`, and `IHistoricalDataProvider` for multi-source redundancy.
  - `FastAPI`: Serves the UI and provides high-performance REST endpoints.
  - `Data Engine`: The central hub for processing raw ticks and routing updates.
  - `Confluence Engine`: A sophisticated signal generator in `brain/` utilizing `scipy` for technical level discovery.
  - `DuckDB`: Optimized columnar store for high-frequency tick and options history.

## Setup & Running

### Prerequisites

- Python 3.10+
- Dependencies listed in `requirements.txt`

### Installation

1. Install required packages:
   ```bash
   pip install -r requirements.txt
   ```

### Configuration

Set TradingView credentials or session cookies in `config.py` (or via environment variables) to access private indicators and higher-granularity data.

### Running the Server

Start the application from the project root:

```bash
python3 backend/api_server.py
```

- **Main Terminal**: `http://localhost:3000/`
- **Options Dashboard**: `http://localhost:3000/options`
- **Tick Chart**: `http://localhost:3000/tick`
- **Renko Chart**: `http://localhost:3000/renko`
- **DB Viewer**: `http://localhost:3000/db-viewer`

## User Guide

### 1. Multi-Chart Layouts
- **Switching Layouts**: Use the grid icons in the header to toggle between **1, 2, or 4 charts**.
- **Active Chart**: Click anywhere on a chart to make it "Active". The active chart is highlighted with a blue border.
- **Independent Controls**: Symbol search, timeframe selection, and indicator toggles apply only to the **currently active chart**. This allows you to monitor different symbols or timeframes side-by-side.

### 2. Symbol Search & Options
- **Discovery**: Type a symbol (e.g., `RELIANCE`) or index (e.g., `NIFTY`) in the search bar.
- **Options Discovery**: Searching for an index automatically fetches and displays associated option contracts from the TradingView Options Scanner.
- **Technical Symbols**: You can enter exact technical strings like `NSE:NIFTY260210C25600` for direct access to specific contracts.

### 3. Drawing Tools (HLINE)
- **Activation**: Click the **HLINE** button in the header (it will turn blue).
- **Placement**: Click anywhere on the active chart to place a horizontal price line.
- **Quick Shortcut**: Hold **Shift + Click** on the chart to place a horizontal line at any time, even if the HLINE tool is not toggled on.
- **Management**: Drawings are saved automatically and can be removed via the **Indicators** panel.

### 4. Indicator Management
- **Global Toggle**: Use **HIDE ALL / SHOW ALL** to quickly clear the chart of all indicator plots and markers.
- **Individual Control**: Click **INDICATORS** to open the management panel. From here, you can:
  - Toggle the visibility of specific indicator series (lines, areas, histograms).
  - **Customize Colors**: Change the color of any indicator or marker type (e.g., TRAPS) using the built-in color picker.
  - Toggles for markers and signals.
  - Remove individual drawings like horizontal lines.

### 5. Candle Replay
- **Enter Mode**: Click the **REPLAY** button.
- **Data Sync**: Upon entering Replay, the terminal fetches full historical options data for the day.
- **Select Start**: Click on any historical candle to set the starting point.
- **Controls**: Use **Play/Pause**, **Next**, and **Previous** to step through the price action.
- **Simulated Confluence**: As you step through candles, the **OI Profile** and **Analysis Sidebar** automatically update to show the nearest available historical OI/PCR/Scalper data for that specific point in time.
- **Exit**: Click **EXIT** to return to the real-time feed.

### 6. Specialized Charts (Tick & Renko)
- **Tick Chart (`/tick`)**:
  - Visualizes market data as candles formed by a fixed number of ticks (e.g., 50, 100).
  - Use the **Ticks** input in the header to adjust aggregation on the fly.
  - Supports full **Replay** of historical ticks stored in the database.
- **Renko Chart (`/renko`)**:
  - Aggregates price movement into "bricks" of a fixed **Box Size**.
  - Ideal for identifying trends and filtering out minor price fluctuations.
  - Like the tick chart, it supports **Replay** for back-testing and analysis.
- **Timestamps**: Both charts display timestamps in **IST** (Asia/Kolkata) for consistency with Indian market hours.

### 7. Confluence Tools
- **OI Profile**: Toggle this in the header to see the option chain distribution overlaid on your price chart. Red bars represent Call OI (resistance), and green bars represent Put OI (support).
- **Analysis Sidebar**: Toggle this to view a high-level summary of:
  - **OiGenie**: Detects whether buyers or sellers are in control and predicts potential sideways movement.
  - **OI Buildup Pulse**: Real-time census of Long/Short buildup and covering across all strikes.
  - **Scalper Pulse**: If the NSE Confluence Scalper is running, its live metrics and confluence dots will appear here.
- **Symmetry & Panic Pulse**: A dedicated real-time tracker for the Symmetry strategy, showing the active signal type, confluence score, and live PnL relative to the entry price.

### 8. Triple-Stream Symmetry Strategy
The terminal includes a native implementation of the Triple-Stream Symmetry & Panic strategy (inspired by MaheshUmale/ENGINE):
- **Phase I (Reference Level)**: Detects significant swing highs/lows ("Walls") in the index and records the corresponding option prices.
- **Phase II (Pullback)**: Monitors the index return to the reference level.
- **Phase III (The Trigger)**: Executes when the Index, ATM Call, and ATM Put reach a state of symmetry (e.g., Index > High, CE > High, PE < Low) combined with OI panic.
- **Phase IV (Guardrails)**: Built-in absorption traps and asymmetry filters to prevent false breakouts.

To view Symmetry signals:
1. Select an Index symbol (e.g., `NSE:NIFTY`).
2. Ensure the timeframe is set to `1M`.
3. Check the **Analysis** toggle in the header.
4. Signals will appear as markers on the chart. SL and TP levels will be drawn as horizontal dashed lines.

### 9. Strategy Backtesting
You can evaluate the Symmetry strategy using the provided backtest utility:
```bash
export PYTHONPATH=$PYTHONPATH:$(pwd)/backend
python backend/backtest_symmetry.py
```
This script simulates the strategy over historical DuckDB data and provides a detailed performance report including:
- Win Rate %
- Total Cumulative PnL %
- Individual Trade Logs (Entry, Exit, Outcome, PnL)

### 10. Settings & Customization
- **Theme Management**: Use the **Moon/Sun** icon in the header to toggle between **Modern Dark Mode** and **High-Visibility Light Theme**.
- **Theming Logic**: The application uses a unified CSS variable engine (`--bg-main`, `--text-primary`, etc.) ensuring consistent colors across all charts, tables, and dashboards.
- **Typography**: Optimized for readability using the **Plus Jakarta Sans** font family, with distinct weights for data (600) and headers (800).
- **Layout Persistence**: Your layout configuration, selected symbols, timeframes, and drawings are automatically saved to `localStorage`. They will be restored exactly as you left them when you return to the application.

### 11. Changing Features & Config
- **Market Hours**: Most analysis tools default to Indian Standard Time (IST). Ensure your system clock is accurate for optimal real-time synchronization.
- **Data Intervals**: Toggle between 1M, 5M, 15M, and 1H intervals in the terminal header. Note that Options Snapshot data defaults to a 5-minute granularity.
- **DB Inspection**: Use the `/db-viewer` to run raw SQL queries if you need to extract custom datasets or verify snapshot integrity.

### 12. Advanced Configuration (backend/config.py)
Advanced users can tune the system by modifying `backend/config.py`:
- **Greeks Config**: Adjust the `risk_free_rate` (default 10%) or `default_volatility` for Black-Scholes calculations.
- **IV Thresholds**: Change `high_iv_threshold` (default 70) and `low_iv_threshold` (30) to customize IV Rank signals.
- **Snapshot Timing**: Modify `SNAPSHOT_CONFIG` to change the frequency of data collection (default is 180 seconds).
- **Symbol List**: Update `OPTIONS_UNDERLYINGS` to track additional indices or stocks in the Options Dashboard.

## Development & Customization

- **Indicator Mapping**: Indicator plots are mapped in `backend/static/app.js` using the `indicatorSeries` registry. Titles containing "Bubble", "Dot", or "TF" are automatically converted to chart markers.
- **Symbol Normalization**: Symbols are standardized using `backend/core/symbol_mapper.py` to ensure consistency between technical keys (e.g., `NSE:NIFTY`) and human-readable names (`NIFTY`).
