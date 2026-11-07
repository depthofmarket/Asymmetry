# Research Hypothesis H29: WTI Crude Oil NYMEX Settlement Auction Imbalance (14:27 ET on MCL)

**Status:** ACTIVE RESEARCH CANDIDATE (Belfort Step 01–05)  
**Date Pre-Registered:** November 7, 2026  
**Primary Instrument:** `MCL` (Micro WTI Crude Oil Futures)  
**Execution Window:** `14:27:00 ET` to `14:35:00 ET` (Entry at 14:27 or 14:28 ET; exit at 14:30 or 14:35 ET)  
**Strategy ID:** `candidate_crude_settlement_s12`  
**Strategy Tier:** `StrategyTier.CANDIDATE`  
**Source Dataset:**  
- `data/raw/cl_1m_2020_2026_et.parquet` (SHA-256: `7f99fefece90be3114b7eb39060a5fe251038700a7238d3e1caac4f5909d1c90`)

---

## 1. Economic & Institutional Rationale (Belfort Step 01)

### The Structural Question: "Why should price go from point A to point B?"
1. **Who is in the market?**: 
   Physical commercial hedgers (pipeline schedulers, refiners, terminal operators), OTC commodity swap dealers, and institutional index funds executing Trade-at-Settlement (TAS) orders.
2. **Why at this time?**: 
   At **14:28:00 to 14:30:00 ET**, the New York Mercantile Exchange (NYMEX / CME Group) executes the official 2-minute daily settlement auction for Light Sweet Crude Oil (`CL`). 
   - Over 5,000 contracts trade within this 2-minute window (a 600% surge over normal volume).
   - All physical crude oil delivery contracts across Cushing, Oklahoma and the US Gulf Coast settle against this official VWAP print.
3. **Why does price move from point A to point B?**: 
   When commercial participants have a net imbalance to execute into settlement, they must complete execution before 14:30:00 ET.
   - **Continuation Hypothesis**: Between 14:20 and 14:27 ET, aggressive pre-settlement accumulation drives price outside the 14:00–14:20 consolidation range. Entering on the 14:27 ET close captures the institutional rush into the 14:28–14:29 ET settlement peak.
   - **Post-Settlement Reversal Hypothesis**: Once the 14:30:00 ET settlement print concludes, commercial buying/selling pressure instantly vanishes (volume collapses from 2,600 to 300 contracts/min). Price snaps back from any artificial settlement dislocation between 14:30 and 14:35 ET.

### The Belfort One-Sentence Formula
> *"I believe Micro WTI Crude Oil (`MCL`) exhibits systematic directional displacement around the 14:28–14:30 ET NYMEX settlement auction because commercial hedgers and swap dealers are forced to execute massive physical benchmark allocations before the 14:30:00 ET closing print."*

---

## 2. Quantitative Rules & Execution Specifications (Belfort Step 02)

1. **Pre-Settlement Base Window (14:00:00 to 14:19:59 ET)**:
   - Identify pre-settlement baseline range:
     - $H_{\text{base}} = \max(\text{high}_{14:00..14:19})$
     - $L_{\text{base}} = \min(\text{low}_{14:00..14:19})$
     - $\text{Range}_{\text{base}} = H_{\text{base}} - L_{\text{base}}$
2. **Pre-Settlement Thrust Window (14:20:00 to 14:27:59 ET)**:
   - $O_{14:20}$: Open price at 14:20 ET.
   - $C_{14:27}$: Close price at 14:27 ET.
   - Directional Return: $|\text{ret}| = |(C_{14:27} - O_{14:20}) / O_{14:20}| \ge 0.15\%$.
   - **Long Drive**: $C_{14:27} > H_{\text{base}}$ AND $\text{Close Location} \ge 0.70$.
   - **Short Drive**: $C_{14:27} < L_{\text{base}}$ AND $\text{Close Location} \le 0.30$.
3. **Execution Variants to Test**:
   - **Variant 1 (Drive Into Settlement)**: Enter at 14:28:00 ET open in the direction of the thrust; exit at 14:30:00 ET close (holding strictly for the 2-minute settlement window).
   - **Variant 2 (Post-Settlement Snapback / Fade)**: Enter at 14:30:00 ET open fading the extended settlement move; exit at 14:35:00 ET close.
4. **Risk Budgeting & Cost Model**:
   - Micro Crude Oil (`MCL`): $1 point ($1.00/bbl) = $100.00; tick size = $0.01 = $1.00 per micro.
   - Adverse Slippage: 1 tick entry + 1 tick exit ($2.00/micro).
   - Commission: $1.24 round-trip per micro ($3.24 total net friction).
   - Protective Stop Loss: 20 cents ($20.00 per micro).
   - Target: 30 cents ($30.00 per micro, 1.5R) or time exit.

---

## 3. Pre-Registered Falsification Criteria (Belfort Step 04 & 05)

The candidate is strictly deemed **FALSIFIED** if:
1. **Step 04 In-Sample Failure (2021-01 to 2024-12)**:
   - In-Sample Profit Factor $< 1.25$
   - Total trade count $N < 80$
   - Max Drawdown $> \$1,000$ (LucidFlex account breach)
2. **Step 05 Out-of-Sample Decay (2025-01 to 2026-10)**:
   - Out-of-Sample Profit Factor $< 1.15$
   - Performance decay $> 25\%$ relative to In-Sample
3. **Execution Robustness (Step 06)**:
   - Profit Factor drops $< 1.00$ at 2 ticks adverse slippage.
