# Setup and Run Guide: Triple-Stream Symmetry & Unwinding Engine

This guide explains how to set up and run the Symmetry Trading Engine.

## Prerequisites

- Python 3.10+
- Upstox API Account (for Access Token)

## Installation

1. **Clone the repository** (if you haven't already).
2. **Install dependencies**:
   ```bash
   pip install upstox-python-sdk pandas sqlalchemy aiohttp python-dotenv
   ```

## Configuration

The bot uses environment variables for sensitive data. Create a `.env` file in the root directory:

```env
UPSTOX_ACCESS_TOKEN=your_upstox_access_token_here
TELEGRAM_BOT_TOKEN=your_bot_token_here (optional)
TELEGRAM_CHAT_ID=your_chat_id_here (optional)
```

## Project Structure

- `engine/`: Core logic folder.
    - `config.py`: Strategy parameters and instrument keys.
    - `database.py`: SQLite/SQLAlchemy persistence layer.
    - `data_provider.py`: Upstox API integration and instrument discovery.
    - `strategy.py`: Symmetry-Panic algorithm implementation.
    - `execution.py`: Paper trading engine.
    - `backtester.py`: Historical simulation engine.
    - `main.py`: Live trading bot orchestration.
- `run.py`: Entry point for live trading and backtesting.
- `trading_engine.db`: Local SQLite database (created on first run).

## Usage

### 1. Running the Backtester

To test the strategy on today's data or recent history:

```bash
# Backtest NIFTY for the current day
python3 run.py --mode backtest --index NIFTY --days 0

# Backtest BANKNIFTY for the last 5 days
python3 run.py --mode backtest --index BANKNIFTY --days 5
```

### 2. Running the Live Bot

To start monitoring and trading NIFTY and BANKNIFTY in real-time:

```bash
python3 run.py --mode live
```

### 3. Running the Dashboard

To view your trades and signals in a web browser:

```bash
python3 run.py --mode dashboard
```
Then visit `http://localhost:8000`.

### 4. Running Live Bot with Dashboard (Simultaneously)

To run the bot in live mode and monitor it via the dashboard at the same time, you should start them in separate terminal windows or as background processes.

#### Option A: Separate Terminals (Recommended)
1. **Terminal 1**: Start the Live Bot
   ```bash
   python3 run.py --mode live
   ```
2. **Terminal 2**: Start the Dashboard
   ```bash
   python3 run.py --mode dashboard
   ```

#### Option B: Background Execution (Linux/Mac)
You can launch both from a single terminal:
```bash
python3 run.py --mode dashboard & python3 run.py --mode live
```

#### Option C: All-in-One Full Mode (Recommended)
The project includes a built-in `full` mode that handles starting both processes for you:
```bash
python3 run.py --mode full
```

## Strategy Overview

The engine monitors three streams simultaneously:
1. **Index Spot**: Maps the structural levels.
2. **ATM Call (CE)**: Monitors buyer strength and short covering.
3. **ATM Put (PE)**: Monitors seller panic and breakdown.

### Confluence Conditions for a Buy Signal:
- **Price Symmetry**: Index and Option both break their respective local highs.
- **PE Breakdown**: The opposite option breaks its local support.
- **OI Panic**: Call OI decreasing (unwinding) and Put OI increasing (floor building).
- **Decay Filter**: If the Call price is higher than its previous peak at the same Index level, conviction is increased.

## Monitoring Results

All signals, trades, and reference levels are stored in `trading_engine.db`. You can inspect them using any SQLite viewer:

```bash
# View signals
sqlite3 trading_engine.db "SELECT * FROM signals;"

# View executed trades
sqlite3 trading_engine.db "SELECT * FROM trades;"
```
