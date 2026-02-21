# Triple-Stream Symmetry & Unwinding Strategy

This document provides a comprehensive technical breakdown of the "Triple-Stream Symmetry & Unwinding" strategy implemented in this project.

## 1. Core Philosophy
The strategy is based on the principle of **Market Symmetry**. Most traders monitor only the Index or a single Option. This engine monitors three streams simultaneously (Index Spot, ATM Call, ATM Put) to identify when one of them is "unwinding" or "panicking," creating a high-probability trade entry.

## 2. Phase I: Swing Discovery & Pullback Confirmation
The engine does not just look for new highs or lows; it looks for **Significant Swings** where a "Wall" has been established.

*   **Logic**: A swing is confirmed only if a new high/low is formed followed by a **2-candle pullback**.
*   **Bullish Wall (Resistance)**: Candle `i-2` is a local High, while candles `i-1` and `i` have lower highs.
*   **Bearish Wall (Support)**: Candle `i-2` is a local Low, while candles `i-1` and `i` have higher lows.
*   **Action**: Once a wall is identified, the system logs the "Reference Level":
    *   Index Spot Price at the wall.
    *   ATM Call (CE) Price at that moment.
    *   ATM Put (PE) Price at that moment.

## 3. Phase II: The Decay Filter (Anti-Theta)
Options lose value over time (Theta). If the Index returns to a previous High level but the Call option price is **higher** than it was when the Index was first at that level, it indicates **Bullish Divergence** (Aggressive buying).

*   **Condition**: Index Price $\ge$ Ref\_Index\_High AND Current\_CE\_Price $>$ Ref\_CE\_Price.
*   **Purpose**: Filters out weak moves and identifies "Anti-Theta" momentum where buyers are willing to pay a premium.

## 4. Phase III: The Triple-Symmetry & Panic Trigger
A trade is triggered when a **Confluence Score of 4/4** is achieved:

| Condition | Logic | Significance |
| :--- | :--- | :--- |
| **Index Break** | Index Spot crosses above/below Ref Level | Momentum confirmation |
| **CE/PE Symmetry** | Active Option crosses its own Ref Level | Price action confirmation |
| **Symmetry Breakdown** | Opposite Option breaks below its local low | Lack of support for the other side |
| **OI Panic** | ATM Call OI $\downarrow$ AND ATM Put OI $\uparrow$ | Short covering & Aggressive writing |

## 5. Phase IV: The "Trap" Guardrails
To prevent getting caught in "Fake-outs" or "Absorption," the engine applies guardrails before entry:

*   **Absorption Trap**: If the Index breaks the level but the Option price stays below its Ref level, it's a Trap.
*   **Asymmetry Trap**: If the opposite option does not break down (remains above its support), the move lacks symmetry.
*   **OI Trap**: If the Call OI is increasing while the Index is rising, it indicates sellers are "absorbing" the buy orders.

## 6. Dynamic Strike Management
Markets move fast. A 25-point move in NIFTY or a 100-point move in BANKNIFTY makes the previous ATM strike irrelevant.

*   **Strike Discovery**: The engine uses the Upstox Instrument Master to identify the current ATM and the nearest expiry.
*   **Auto-Rollover**: Every 5 minutes, or upon a threshold price move, the engine automatically unsubscribes from old strikes and subscribes to the new ATM chain.
*   **Backtest Accuracy**: The backtester simulates this by recalculating the ATM for every minute based on the historical index price.

## 7. Exit Strategy
The strategy uses two primary "Unwinding" exit triggers:

1.  **Symmetry Break (Stop Loss)**: If the Index is above the breakout level but the Option price drops back below the Ref level, symmetry is lost.
2.  **Target Exit (Panic Over)**: The trade is closed when the **Opposite Option stops making new lows** and its **OI begins to fall**, signaling that the "unwinding" move has exhausted.
3.  **Hard Stop**: A default 20% drawdown on the option entry price.

## 8. Performance Metrics
*   **Price Velocity**: Calculated as the rate of change over the last 3 candles.
*   **Relative Strength (RS)**: (Option % Change) / (Index % Change). High RS indicates the option is outperforming the index move.

## 9. Paper Trading Simulation
*   **Slippage**: 0.1% applied to both Entry and Exit.
*   **Transaction Costs**: Turnover-based commission (0.05%) + fixed GST/STT proxy charges (₹20 per side).
*   **Lot Sizing**: NIFTY (75), BANKNIFTY (15).

## 10. Strategy Warmup
To ensure the engine has immediate access to structural levels upon startup:
*   **Historical Ingestion**: The bot fetches and processes the last 2 days of historical data for the Index and relevant ATM options.
*   **State Initialization**: Reference levels (Highs/Lows) and candle history (for Velocity/RS) are pre-calculated before the live stream starts.
*   **Continuity**: This prevents "flying blind" during the first few minutes of a live session or backtest.
