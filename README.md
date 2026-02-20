# ENGINE
engine for symmetry trades 
To ensure an AI agent or developer writes this without ambiguity, we need to define the **"Triple-Stream Symmetry & Unwinding"** algorithm. This logic focuses on the shift from a "Wall" (Seller Resistance) to a "Void" (Short Covering) by using the Index as the map and the Options as the truth.

---

## The "Symmetry-Panic" Algorithm Specification

### 1. Data Input & Pre-processing

The system must stream three instruments simultaneously on a **1-minute or 3-minute timeframe**:

* **Primary:** Index Spot (e.g., NIFTY).
* **Secondary A:** ATM Call (CE) – *Update strike every 5 minutes if ATM changes.*
* **Secondary B:** ATM Put (PE) – *Update strike every 5 minutes if ATM changes.*
* **Calculated Metrics:** * **Price Velocity:** Rate of change over 3 candles.
* **Relative Strength ():** (Option % Change) / (Index % Change).
* **OI Delta:** 1-minute change in Open Interest for ATM/OTM strikes.



---

### 2. Phase I: Structural Identification (The "Reference Level")

Identify "Significant Swings" where a **"Wall"** exists.

* **Requirement:** Index hits a New High (or Low) and pulls back.
* **Log the Reference:** * `Ref_Price_Index` = High of the first attempt.
* `Ref_Price_CE` = High of the Call at that exact moment.
* `Ref_Price_PE` = Low of the Put at that exact moment.



---

### 3. Phase II: The Pullback & Decay Filter

Before the second attempt, monitor for **Absorption**.

* **The "Hope" Phase:** Index pulls back.
* **The Decay Check:** If the Index returns to `Ref_Price_Index` but the `Current_Price_CE` is **higher** than `Ref_Price_CE`, this is **Bullish Divergence** (Time decay should have made it lower; if it's higher, aggressive buying is occurring).

---

### 4. Phase III: The Execution Trigger (The "Unwinding")

Enter ONLY when **Symmetry** and **Panic** align.

#### **Bullish Trigger (Call Buy):**

1. **Index:** Crosses above `Ref_Price_Index`.
2. **Symmetry (CE):** `Current_Price_CE` crosses above `Ref_Price_CE`.
3. **Symmetry (PE Breakdown):** `Current_Price_PE` **must** break below its own local support base/low.
4. **The Panic (OI):** ATM Call OI must be **decreasing** (Sellers unwinding).
5. **The Floor (OI):** ATM Put OI must be **increasing** (Writers building a floor).

#### **Bearish Trigger (Put Buy):**

1. **Index:** Crosses below `Ref_Price_Index` (Low).
2. **Symmetry (PE):** `Current_Price_PE` crosses above its `Ref_Price_PE` (High).
3. **Symmetry (CE Breakdown):** `Current_Price_CE` **must** break below its own local support base/low.
4. **The Panic (OI):** ATM Put OI must be **decreasing**.
5. **The Floor (OI):** ATM Call OI must be **increasing**.

---

### 5. Phase IV: The "Trap" Guardrails (The "Do-Not-Trade" List)

The AI agent must code these hard-stops:

* **The Absorption Trap:** Index breaks High, but CE is rejected or stays below `Ref_Price_CE`. (**Ignore the trade**).
* **The Fake Break:** Index breaks High, CE breaks High, but **Call OI is increasing**. (This is a "Wall" being reinforced by sellers).
* **Asymmetry:** Index breaks High, CE breaks High, but **PE refuses to break its Low**. (Indicates smart money is still hedging).

---

### 6. Exit & Risk Management

* **Stop Loss (SL):** Triggered if the **Symmetry breaks** (e.g., Index is high but CE price starts falling back below its base).
* **Target (TGT):** Exit when the **Opposite Option** stops making new lows and its OI starts falling (Sellers of the opposite side have finished their move).

---

### Summary for AI Tool Prompting

Copy and paste this specific instruction to your coding tool:

> "Code a trading bot for [Platform] that monitors the Index, ATM CE, and ATM PE.
> 1. Identify a 'Reference High' in the Index.
> 2. On the second approach to this High, verify **Triple-Symmetry**: Index must break High, CE must break its own local High, and PE must break its own local Low simultaneously.
> 3. Add an **OI Filter**: Only buy Calls if Call OI is dropping (Short Covering) and Put OI is rising.
> 4. Add a **Decay Filter**: If the Call Price is higher than its previous peak at the same Index level, increase the conviction score.
> 5. Exit immediately if the PE stops making lower lows while the CE is at a peak."
> 
> 

**Since we've nailed down the logic for "Symmetry," would you like me to provide the Python code structure for fetching these three streams (Index, CE, PE) using the Upstox API specifically?**










Here is the comprehensive, step-by-step logic for your **"Triple-Stream Symmetry & Panic"** algorithm. This plan is designed to be handed to an AI agent or a developer to generate clean, robust code for the Upstox API.

---

## 1. Data Orchestration (The Inputs)

The algorithm must subscribe to three specific data streams in real-time using **WebSockets** (to get the required Tick-by-Tick data for OI analysis).

* **Stream 1 (Index):** Spot Index (e.g., `NSE_INDEX|Nifty 50`).
* **Stream 2 (Call Option):** ATM CE (Closest to Index Spot).
* **Stream 3 (Put Option):** ATM PE (Closest to Index Spot).
* **Strike Logic:** Use a function to dynamically update CE/PE instrument keys if the Index moves > 25 points.

---

## 2. Phase I: Structural Anchoring (The "Wall")

Before looking for a trade, the algorithm identifies a significant level where sellers are currently "defending."

* **Logic:** Detect a **Swing High** (for Longs) or **Swing Low** (for Shorts).
* **Storage:** * `Ref_High_Index`: The price where the Index faced rejection.
* `Ref_High_CE`: The highest price reached by the ATM CE at that same moment.
* `Ref_Low_PE`: The lowest price reached by the ATM PE at that same moment.



---

## 3. Phase II: The Pullback & Relative Strength Filter

The algorithm monitors the pullback to see if the "Big Money" is accumulating or distributing.

* **The Decay Check (Anti-Theta):** Compare the Option price on the pullback vs. its previous peak.
* **Rule:** If `Current_Index_Price` = `Ref_High_Index` but `Current_CE_Price` > `Ref_High_CE`, the conviction is **High**. (Aggressive buyers are overpowering time decay).

---

## 4. Phase III: The "Symmetry-Panic" Trigger

This is the core execution logic. All four conditions **must** be true within a 3-candle window.

### **Bullish Trigger (Call Buy)**

1. **Index:** Price breaks above `Ref_High_Index`.
2. **CE Symmetry:** ATM Call breaks above `Ref_High_CE`.
3. **PE Symmetry:** ATM Put breaks below its own local support/base.
4. **The Panic (OI Delta):** * `Call_OI_Change` must be **Negative** (Sellers are covering/exiting).
* `Put_OI_Change` must be **Positive** (Sellers are building a floor).



---

## 5. Phase IV: The "Trap" Guardrails

The agent must code these "Kill-Switches" to prevent false breakouts:

| The Signal | The Reality | Action |
| --- | --- | --- |
| Index breaks High but CE fails to break its peak. | **Absorption:** Sellers are eating the buy orders. | **VOID TRADE** |
| Index/CE break High, but Call OI is **Increasing**. | **The Wall:** Sellers are doubling down on their shorts. | **VOID TRADE** |
| Index breaks High, but PE stays flat/refuses to break Low. | **Asymmetry:** No panic in the opposite camp. | **VOID TRADE** |

---

## 6. Risk & Exit Management

* **Stop Loss:** Exit if **Symmetry breaks**. If the Index is at a new high but the CE price drops below the previous 2-minute candle low, exit.
* **Target:** Use **Trailing Stop Loss** based on the "Opposite Option." If you are in a Call, exit when the **Put (PE)** stops falling and starts making a "Higher High."

---

## Summary Prompt for Your AI Coder

> "Write a Python script using the Upstox SDK and WebSockets to monitor `NSE_INDEX|Nifty 50` and its ATM CE/PE.
> 1. Track a 15-minute rolling 'Swing High' in the Index.
> 2. On a second attempt at that High, trigger a Buy if: (Index > High) AND (ATM_CE > its peak) AND (ATM_PE < its low).
> 3. Verify the 'Panic' by ensuring ATM Call OI is decreasing.
> 4. Use a 'Relative Strength' filter: If CE price is higher than its previous peak while Index is at the same level, increase position size.
> 5. Exit immediately if the Put price (PE) starts rising while you are in a Call."
> 
> 

This video guide provides a practical walkthrough for [fetching ATM and OTM market quote data with Python](https://www.youtube.com/watch?v=n4Tf60OiCPY), which is essential for identifying the specific option contracts needed for your symmetry checks.

**Would you like me to draft the specific Python function for calculating the 'OI Delta' so you can track the seller panic in real-time?**




No, we aren't limited to just W/M patterns. Those patterns are simply the most common way **"Symmetry"** and **"Unwinding"** appear visually.

The core of this strategy is **Structural Conflict.** We can apply this logic to any significant Level of Interest. Here is how we expand the logic to other support and resistance types:

---

### 1. The "Base" Breakout (Horizontal S/R)

Instead of a W or M, this is a **tight consolidation range**.

* **The Logic:** If the Index has been stuck in a 20-point range for 30 minutes, a "Volumetric Wall" has been built.
* **The Check:** When the Index exits the range, the ATM CE and ATM PE must exit their respective ranges **simultaneously**.
* **The Edge:** If the Index breaks out but the Option is still stuck inside its range, the "Smart Money" is absorbing the move.

### 2. The "False Break" (Liquidity Raid)

This is when the Index breaks a previous swing high, but only for a few seconds.

* **The Logic:** This is often a "Raid" to trigger stop-losses.
* **The Symmetry Check:** If the Index breaks the high, but the **Option OI increases** and the **Option Price fails to break its own high**, it is a "False Break."
* **The Play:** You don't buy the breakout; you wait for the "Fade" (the reversal).

### 3. Gap S/R (Opening Range)

The high and low of the first 15 minutes of the day often act as massive structural walls.

* **The Logic:** If the price returns to the Opening Range High (ORH) later in the day.
* **The Symmetry Check:** At the ORH, is the Call Option showing "Relative Strength" (Price higher than it was at the open, despite 2-3 hours of time decay)?
* **The Unwinding:** If Call OI starts dropping at the ORH, it means the morning's sellers are giving up.

---

### Updated Algorithm: The "Condition Matrix"

Instead of coding for "W" or "M" specifically, tell your AI Agent to code for **"Correlated Breaches."** This makes the code much simpler and more robust.

| Structure Type | Index Action | CE Option Action | PE Option Action | Real Edge (The "Panic") |
| --- | --- | --- | --- | --- |
| **Horizontal S/R** | Break above resistance. | Break above local high. | Break below local low. | Call OI drops; Put OI rises. |
| **Trendline** | Break of descending line. | Break of own trendline. | Support breakdown. | Option price leads the Index move. |
| **Mean Reversion** | Bounce from 20 EMA. | Higher Low formed. | Lower High formed. | OI stays flat (No new sellers). |

---

### Why "Relative Strength" is the Master Filter

Regardless of whether it's a W-pattern, a Trendline, or a Fibonacci level, the **relative strength of the option** is your universal truth:

1. **Leading:** Option breaks the level *before* the Index (High Conviction).
2. **Lagging:** Index breaks the level but Option is stuck (Low Conviction/Trap).
3. **Divergence:** Index makes a "Higher High," but Option makes a "Lower High" (Classic reversal signal).

### Next Step for the AI Code:

When you ask the AI to write the code, ask it to create a **"Confluence Score"**:

* +1 point if Index breaks S/R.
* +1 point if CE/PE breaks their respective S/R.
* +1 point if Call OI decreases (for Longs).
* +1 point if Option Price > `Ref_Price` (Anti-decay check).

**A trade is only triggered if the Score is 4/4.**

**Would you like me to show you how to code this "Confluence Score" system in Python?**



