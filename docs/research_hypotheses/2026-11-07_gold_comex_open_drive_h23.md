# Research Hypothesis H23: COMEX Gold Cash Open Drive (08:20 ET) on MGC

**Status:** ACTIVE RESEARCH CANDIDATE (Belfort Step 01–04)  
**Date Pre-Registered:** November 7, 2026  
**Primary Instrument:** `MGC` (Micro Gold Futures, $10.00/point multiplier, $1.00 per 0.10 tick)  
**Execution Window:** `08:20:00 ET` to `09:15:00 ET` (Mandatory flat before 09:30 US equity open)  
**Strategy ID:** `gold_comex_open_s6`  
**Strategy Tier:** `StrategyTier.CANDIDATE`  
**Source Dataset:** `data/raw/gc_1m_2020_2026_et.parquet` (SHA-256: `4be8c9f73920d9ebb28609431869231ac49ebd43dd14b48e0f6a05a84763b3df`)

---

## 1. Economic & Institutional Rationale (Belfort Step 01)

### The Structural Question: "Why should price go from point A to point B?"
1. **Who is in the market?**: 
   New York commercial bullion bank trading desks (J.P. Morgan, HSBC, Citi), commodity hedge funds, and precious metals market makers on the COMEX exchange.
2. **Why at this time?**: 
   At **08:20:00 ET**, the physical COMEX trading floor opens in New York. Prior to 08:20 ET, gold trades electronically on lower overnight volume across Asian and London sessions. At 08:20:00 ET, US institutional market participants come online, causing 1-minute volume to double (+106% from 251 to 518 contracts).
3. **Why does price move from point A to point B?**: 
   US bullion dealers enter the market with accumulated client orders, sovereign hedging programs, and intermarket dollar/rates positioning.
   - When the opening range breaks directionally with elevated volume, market makers widen spreads away from the breakout direction, forcing programmatic momentum to drive price toward overnight reference extremes (Overnight High/Low or prior session Value Area).
   - In addition, between 08:20 and 08:35 ET, early US macroeconomic data (08:30 releases) is absorbed. A post-open directional breakout establishes the dominant morning trend leading into the 09:30 US cash equity open.

### The Belfort One-Sentence Formula
> *"I believe Micro Gold (`MGC`) trends directionally between 08:20 and 09:15 ET when breaking out of its COMEX opening range because the 08:20 ET New York physical open unleashes commercial bullion liquidity that drives price toward pre-market extremes before the US equity open."*

---

## 2. Quantitative Rules & Execution Specifications (Belfort Step 02)

1. **Pre-Market Reference Range (08:00:00 to 08:19:59 ET)**:
   - Compute pre-pit high ($\text{Pre}_{\text{high}}$) and low ($\text{Pre}_{\text{low}}$) over the 20 minutes prior to COMEX open.
2. **Opening Range Definition**:
   - **Variant A (08:20–08:29 ET 10-minute OR, entry at 08:30:00 ET)**:
     - $\text{OR}_{\text{high}} = \max(\text{high}_{08:20..08:29})$, $\text{OR}_{\text{low}} = \min(\text{low}_{08:20..08:29})$, $\text{OR}_{\text{range}} = \text{OR}_{\text{high}} - \text{OR}_{\text{low}}$.
     - Signal evaluated at 08:29:00 bar close (08:30:00 ET).
   - **Variant B (08:20–08:34 ET 15-minute OR, entry at 08:35:00 ET post-macro)**:
     - $\text{OR}_{\text{high}} = \max(\text{high}_{08:20..08:34})$, $\text{OR}_{\text{low}} = \min(\text{low}_{08:20..08:34})$, $\text{OR}_{\text{range}} = \text{OR}_{\text{high}} - \text{OR}_{\text{low}}$.
     - Signal evaluated at 08:34:00 bar close (08:35:00 ET).
3. **Entry Logic**:
   - **Bullish Breakout (Long)**:
     - Signal bar close $> \text{OR}_{\text{high}}$ AND signal bar close location $\ge 0.65$.
     - Minimum return: $|(\text{close} - \text{open}_{08:20}) / \text{open}_{08:20}| \ge 0.08\%$ (~$2.00 on Gold).
   - **Bearish Breakdown (Short)**:
     - Signal bar close $< \text{OR}_{\text{low}}$ AND signal bar close location $\le 0.35$.
     - Minimum return: $|(\text{close} - \text{open}_{08:20}) / \text{open}_{08:20}| \ge 0.08\%$.
   - Direction modes to evaluate: Long-Only (matching Gold structural accumulation bias) vs Long+Short.
4. **Execution & Risk Budgeting**:
   - **Entry**: Market order at next bar open (08:30:00 or 08:35:00 ET).
   - **Slippage Model**: 0.20 points adverse slippage ($2.00 per micro) on market/stop exits; 0.10 points ($1.00 per micro) on limit target fills.
   - **Commission**: $1.20 round-turn per micro contract.
   - **Stop Loss**: $\text{clip}(0.50 \times \text{OR}_{\text{range}}, 2.5, 8.0)$ gold points ($25.00 to $80.00 per micro contract).
   - **Profit Target**: $1.50R$ multiple ($\text{entry} + d \times 1.50 \times \text{stop\_points}$).
   - **Position Sizing**: Governed by $250 max-risk budget:
     $$\text{contracts} = \text{clip}\left(\left\lfloor \frac{250.0}{\text{stop\_points} \times 10.0} \right\rfloor, 1, 4\right) \text{ micros}$$
5. **Mandatory Exit Rules**:
   - Limit order at profit target (trade-through fill).
   - Stop loss fill with gap-through open protection.
   - Mandatory session flat at **09:15:00 ET** (prior to 09:30 equity open).

---

## 3. Pre-Registered Falsification Criteria (Belfort Step 04 & 05)

1. **In-Sample Period (2021-01-01 to 2024-12-31)**:
   - Minimum trade count $N \ge 80$.
   - Net Profit Factor $\ge 1.25$ after all slippage and commissions.
   - Net Profit $> 0$.
2. **Out-of-Sample Period (2025-01-01 to 2026-10-30)**:
   - Net Profit Factor $\ge 1.15$.
   - Maximum Drawdown must not breach the LucidFlex 25K $1,000 trailing limit.
3. **Correlation Gate (Belfort Step 06)**:
   - Pairwise return correlation against Strategy 1 (09:45 VA Breakout), Strategy 2 (08:35 Macro Momentum), and Strategy 3 (10:15 Gold London Fix) must be $< 0.40$.
