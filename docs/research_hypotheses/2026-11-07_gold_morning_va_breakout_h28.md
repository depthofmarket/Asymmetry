# Research Hypothesis H28: Micro Gold Morning Value Area Breakout (09:45 ET on MGC)

**Status:** ACTIVE RESEARCH CANDIDATE (Belfort Step 01–05)  
**Date Pre-Registered:** November 7, 2026  
**Primary Instrument:** `MGC` (Micro Gold Futures)  
**Execution Window:** `09:45:00 ET` to `10:15:00 ET` (Entry at 09:45:00 ET; mandatory flat at 10:15:00 ET)  
**Strategy ID:** `candidate_gold_va_breakout_s11`  
**Strategy Tier:** `StrategyTier.CANDIDATE`  
**Source Dataset:**  
- `data/raw/gc_1m_2020_2026_et.parquet` (SHA-256: `4be8c9f73920d9ebb28609431869231ac49ebd43dd14b48e0f6a05a84763b3df`)

---

## 1. Economic & Institutional Rationale (Belfort Step 01)

### The Structural Question: "Why should price go from point A to point B?"
1. **Who is in the market?**: 
   Global multi-asset institutional portfolio managers, macro commodity hedge funds, and bullion banking algorithmic desks executing cross-asset allocations between US equities, US Treasuries, and Gold.
2. **Why at this time?**: 
   At **09:30:00 ET**, the New York cash equity market opens. Even though COMEX Gold trading is continuous, cross-asset macro capital flows (driven by equity open reactions, bond yield shifts, and US Dollar index repricing) flood into Gold in the first 15 minutes of the US cash session (09:30 to 09:44 ET).
3. **Why does price move from point A to point B?**: 
   When Gold establishes a directional drive in the first 15 minutes of the US cash open that breaks and closes outside the prior session's 70% Value Area (`VAH` / `VAL`) with strong candle close location ($\ge 0.65$ for long, $\le 0.35$ for short), it reflects genuine institutional initiative buying or selling.
   - Passive liquidity clustered at prior-day Value Area levels is overwhelmed.
   - Informed institutional flow drives a directional trend extension from 09:45 to 10:15 ET heading directly into the 10:00–10:15 ET LBMA PM Fixing auction.

### The Belfort One-Sentence Formula
> *"I believe Micro Gold (`MGC`) trends directionally between 09:45 and 10:15 ET when breaking outside its prior session 70% Value Area during the 09:30–09:44 ET US equity cash open, because multi-asset institutional capital rebalances gold holdings against opening equity and bond volatility."*

---

## 2. Quantitative Rules & Execution Specifications (Belfort Step 02)

1. **Prior Session Profile Calculation**:
   - Prior session RTH window defined from 08:20 to 13:30 ET (or 00:00 to 16:00 ET full session).
   - Compute Point of Control (`POC`), Value Area High (`VAH`, 70% volume), and Value Area Low (`VAL`, 70% volume) from completed session $d-1$.
2. **15-Minute Opening Drive Window (09:30:00 to 09:44:59 ET)**:
   - $O_{09:30}$: 09:30 bar open.
   - $C_{09:44}$: 09:44 bar close.
   - $H_{15m} = \max(\text{high}_{09:30..09:44})$; $L_{15m} = \min(\text{low}_{09:30..09:44})$.
   - $\text{Range}_{15m} = H_{15m} - L_{15m}$.
   - **Directional Drive Filter**: $|\text{ret}_{15m}| = |(C_{09:44} - O_{09:30}) / O_{09:30}| \ge 0.08\%$.
   - **Close Location**:
     $$\text{CL} = \frac{C_{09:44} - L_{15m}}{H_{15m} - L_{15m}}$$
3. **Value Area Breakout Acceptance Filter**:
   - **Long (`+1`)**: $C_{09:44} > \text{prior\_VAH}$ AND $\text{CL} \ge 0.65$.
   - **Short (`-1`)**: $C_{09:44} < \text{prior\_VAL}$ AND $\text{CL} \le 0.35$.
4. **Execution & Risk Budgeting**:
   - **Entry**: Market order at 09:45:00 ET open.
   - **Stop Loss**: $1.0 \times \text{Range}_{15m}$, clipped to bounds:
     - `MGC`: minimum $3.00/oz ($30), maximum $12.00/oz ($120).
   - **Profit Target**: $1.50R$ multiple ($\text{stop\_points} \times 1.50$).
   - **Mandatory Time Exit**: 10:15:00 ET (30-minute holding window).
   - **Position Sizing**: 1 to 2 micro contracts scaled to risk $\le \$120$.
   - **Cost Model**: 1 tick adverse entry + 1 tick adverse exit ($0.10/oz \times 10 = \$1.00$ per side) + $1.24 RT commission ($3.24 total net friction per micro).

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
