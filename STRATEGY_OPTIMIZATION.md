# ProDesk Symmetry Strategy Optimization Guide

The **Triple-Stream Symmetry & Panic** algorithm is a high-precision scalping strategy. To achieve optimal performance in different market regimes (Trending vs. Sideways), you can tune several parameters in the configuration and logic.

## 1. Tuning Swing Detection (Walls)

The strategy relies on identifying "Walls" (Swing Highs and Lows).
- **ATR Multiplier**: In `backend/brain/SymmetryAnalyzer.py`, the significance of a swing is often filtered by ATR.
  - *Increase* the multiplier (e.g., from 1.5x to 2.0x) to filter out noise in volatile markets (India VIX > 18).
  - *Decrease* the multiplier (e.g., to 1.0x) for scalping tight ranges in low volatility (India VIX < 12).
- **Pullback Confirmation**: The default requires a 2-candle pullback.
  - For faster entries in aggressive trends, reduce this to 1 candle.
  - For more conservative entries (reducing false breakouts), increase to 3 candles.

## 2. Confluence Score Optimization

Signals are only triggered when the `confluence_score` meets a threshold.
- **Panic Weighting**: Currently, "OI Panic" (Short Covering detected via OI Delta) is weighted heavily.
  - If you see many "Buying Traps" (price goes up but fails), increase the required OI Panic threshold.
- **Index Symmetry**: Ensure `ENABLE_INDEX_SYNC` is `True` in `config.py`. This requires NIFTY and BANKNIFTY to move in the same direction, significantly reducing "Divergence Traps."

## 3. Dynamic Stop Loss & Take Profit

- **ATR-Based SL**: Use `1.5 * ATR` for the initial stop loss.
- **Profit Locking**:
  - Implement a "Break-even switch": Once the trade moves +1% (option price), move the SL to the entry price.
  - **Aggressive Trailing**: Use a 1-minute `EMA(9)` as a trailing stop for "Panic Run" trades. Exit as soon as the price closes below/above the EMA.

## 4. Market Regime Filtering

- **Time of Day**: The strategy performs best during high-volume periods (09:15 - 11:00 and 13:30 - 15:30).
- **Gap Handling**: Avoid trading in the first 15 minutes if there is a massive gap (>1%) as symmetry levels are not yet established.

## 5. Optimization Workflow

1. **Run Backtest**: Use `python backend/backtest_symmetry.py --underlying NSE:NIFTY --count 2000` to get a baseline.
2. **Analyze Failures**: Look at the "SL" trades in the log.
   - If SLs happen immediately, your SL is too tight.
   - If SLs happen after a long sideways move, implement a "Time-Based Exit" (e.g., exit if not in profit within 10 minutes).
3. **Adjust & Repeat**: Modify `backend/symmetry_engine/strategy.py` and re-run the backtest.
