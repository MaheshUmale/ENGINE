# ProDesk: Comprehensive Squeeze Mechanics & Optimization Guide

The **Triple-Stream Symmetry & Panic** algorithm has been fully overhauled from a simple "Breakout" strategy into a high-precision **Short-Covering Squeeze** engine. 

To achieve optimal performance and maintain the >30% 1-minute win rate demonstrated in backtesting, you must understand the five core phases and the parameters you can tune.

## 1. Phase I: The Wall (Reference Level)
The strategy relies on identifying "Walls" (Swing Highs and Lows) where writers previously defended successfully at least once.
- **ATR Threshold**: In `backend/brain/SymmetryAnalyzer.py`, the significance of a swing is filtered by the ATR. 
  - *Increase* `atr_threshold` (e.g., from 1.5x to 2.0x) to filter out noise in volatile markets (India VIX > 15).
  - *Decrease* for scalping tight continuous trends.
- **Pullback Requirement**: The system requires a minimum **3-candle pullback** to define a swing. This natively forces the engine to only take trades on the **"Second Attempt"** of a level.

## 2. Phase II & III: The Trigger (Triple Symmetry)
Signals are only triggered when the `score` meets a minimum threshold (currently `>= 2`).
- **Relative Velocity (`calculate_relative_velocity`)**: The Active Option must be moving significantly faster than the Index. If the Index moves 10 points but the Call only moves 1 point, writers are absorbing the move.
- **Symmetry of Panic**: The most crucial signal. The Opposite Option **must be making fresh lows and unable to bounce**. If you buy a Call, the Put writers must be in full control of the floor.

## 3. Phase IV: The Guardrails (Filtering 80% of Noise)
These filters prevent the "29% Win Rate Tap" that plagues standard breakout bots.
- **The Absorption Filter**: Aborts if the Index makes a new high but the Option does not.
- **The Void Check**: Ensure `check_void_above` has access to accurate OPRA/Option chain data. It must verify there are no massive OI clusters within 5-10 points above the breakout.
- **PCR Momentum**: The `calculate_pcr_momentum` compares the live PCR to the Start of Day (SOD) and the 10-minute Moving Average.
- **Cooldowns**: The `analyze` function enforces a **15-Minute Cooldown** (`> 900 seconds`) between trades. **Do not remove this.** It prevents the bot from machine-gunning entries during false chop.

## 4. Phase V: Dynamic Exits (The Real Edge)
Stop relying on arbitrary Risk:Reward ratios like 1:2 on a 1-minute chart.
- **Buffered Stop Loss**: The SL is placed 5 points below the low of the breakout candle. This buffer prevents getting wicked-out by algorithmic spreads before the squeeze resolves.
- **Dynamic Take Profit (Opposite Bounce)**: Implemented in `backtest_symmetry.py`. The bot holds the Active Option until the *Opposite* Option forms a Green Candle that closes higher than its previous high. As long as the victim option is bleeding, hold the active option.

## 5. Optimization & Tuning Workflow

1. **Baseline**: Run `python backend/backtest_symmetry.py --underlying NSE:NIFTY --count 500`.
2. **Review the Log**: Check the `backtest_results.txt`.
3. **Adjusting the Buffer**: If you see trades getting stopped out ('SL') followed by a massive move in your direction, increase the SL buffer in `SymmetryAnalyzer.py` from `-5.0` to `-10.0`.
4. **Whipsaws**: If you are entering trades that immediately die, double-check that your `calculate_pcr_momentum` has accurate real-time data feeding it. Without PCR momentum, the breakout will fail.
