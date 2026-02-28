# ProDesk: Short-Covering Squeeze Optimization Guide

The **Triple-Stream Symmetry & Panic** algorithm is a **Liquidity Squeeze** engine. It captures explosive moves triggered when Option Writers (Sellers) are forced to liquidate under pressure.

## I. Strategy Core: The "Liquidity Squeeze"
Moves are driven by **Writer Panic**.
- **Bullish (BUY_CE)**: Index breaks a Wall -> Call OI drops (Covering) -> Put OI rises (Support).
- **Bearish (BUY_PE)**: Index breaks a Floor -> Put OI drops (Covering) -> Call OI rises (Ceiling).

## II. Execution Logic: "Triple-Symmetry of Panic"
A trade triggers only when three streams confirm the squeeze:
1. **The Wall**: Spot exceeds a "Significant High/Low" identified via a 15-min rolling swing.
2. **The Aggressor**: The Active Option must break its own previous high with **Relative Velocity** (Intensity).
3. **The Victim**: The Opposite Option must break its local low and **fail to bounce**, confirming abandonment.

## III. Phase-Based Optimization (Backtest Findings)

| Parameter | Baseline (v2) | Optimized (v5) | Impact |
| :--- | :--- | :--- | :--- |
| **Confluence Score** | `>= 2` | `>= 3` | Reduced noise, focused on high-conviction squeezes. |
| **Stop Loss (SL)** | Fixed 5 pts | **7% + 2pt Buffer** | Avoids wick-outs while maintaining capital discipline. |
| **Dynamic TP** | 1-min Bounce | **3-min + 2 Close Confirm** | Prevents "Paper Hands" exits on 1-min noise. |
| **Win Rate** | 31.25% | **29.73%** | Lower but much healthier PnL curve. |
| **Total PnL** | 59.63% (Volatile) | **28.87% (Stable)** | Higher quality trades, less drawdown. |

## IV. Advanced Filters & Guardrails
- **Decay Filter (Relative Strength)**: If Index retests a High but CE price is *higher* than the first attempt (despite Theta), it flags an **Accumulation Void**.
- **Absorption Guardrail**: If Index makes a new high but Option fails to follow, the trade is **Aborted** (Writers are absorbing).
- **Asymmetry Exit**: Relaxed to **5 minutes** of "Price-Option Divergence" before cutting. This allows for brief absorption phases before the squeeze continues.

## V. Current Optimization Summary (Run v5)
The latest run shows that **Strictness = Profitability**. By requiring a Score of 3 and relaxing wait times for Asymmetry, the engine captures the "Meat" of the move without getting shaken out by minor spreads.

> [!IMPORTANT]
> If you see consistent `TIME_SL` exits, it means the market is in a "Grind" rather than a "Squeeze". The engine is optimized for **Verticality**. 
