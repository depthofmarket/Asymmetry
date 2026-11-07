# Research Hypothesis H24: 60-Minute Initial Balance Range Extension (10:30 ET) on MES & MNQ

**Status:** ACTIVE RESEARCH CANDIDATE (Belfort Step 01–04)  
**Date Pre-Registered:** November 7, 2026  
**Primary Instruments:** `MES` (Micro S&P 500) & `MNQ` (Micro Nasdaq 100)  
**Execution Window:** `10:30:00 ET` to `12:00:00 ET` (Entry cutoff at 11:15 ET; mandatory flat at 12:00 ET)  
**Strategy ID:** `initial_balance_extension_s7`  
**Strategy Tier:** `StrategyTier.CANDIDATE`  
**Source Datasets:**  
- `data/raw/es_1m_2020_2026_cqg_et.parquet` (SHA-256: `36f0a1042b9981b8166c32d2aad5b5452f7027fb210da65547d928dd791290f3`)  
- `data/raw/nq_1m_2017_2026_cqg_et.parquet` (SHA-256: `c9d78a716f5afe040c590fc974e980edfee029081ba47875f041b034c38b737a`)

---

## 1. Economic & Institutional Rationale (Belfort Step 01)

### The Structural Question: "Why should price go from point A to point B?"
1. **Who is in the market?**: 
   Other Timeframe (OTF) multi-day asset allocators, systematic CTA trend expansion programs, and institutional execution algorithms completing midday tranches.
2. **Why at this time?**: 
   At **10:30:00 ET**, the first 60 minutes of the New York cash equity session (09:30 to 10:29 ET) completes the classic Steidlmayer/Dalton **Initial Balance (IB)**.
   - The opening auction chaos of the first 15–30 minutes has subsided.
   - Tier-1 and Tier-2 10:00 AM ET macroeconomic releases (ISM PMI, JOLTS, Consumer Confidence, New Home Sales) have been fully priced in and absorbed.
   - European financial centers enter their afternoon liquidity window ahead of their 11:30–12:00 ET fixings.
3. **Why does price move from point A to point B?**: 
   On sessions that open *inside* the prior session's Value Area (where Strategy 1 generates no signal, accounting for ~65% of all sessions), the market spends the first hour coiling within the Initial Balance.
   - If price remains trapped within the IB, it is a balanced Normal Day.
   - However, when price breaks and closes *outside* the 60-minute Initial Balance high or low after 10:30 ET with strong candle close location, it reflects initiative Other Timeframe (OTF) institutional capital rejecting the opening balance.
   - Institutional algorithmic trend programs systematically buy strength or sell weakness, expanding the day into a Normal Variation Day (1.5x IB extension) or Trend Day (2.0x+ IB extension) heading into the European close.

### The Belfort One-Sentence Formula
> *"I believe Micro S&P 500 (`MES`) and Micro Nasdaq (`MNQ`) trend directionally between 10:35 and 12:00 ET when closing outside the 60-minute Initial Balance (09:30–10:29 ET) on sessions that opened inside value, because Other Timeframe (OTF) institutional allocators step in to drive auction expansion after the first-hour balance settles."*

---

## 2. Quantitative Rules & Execution Specifications (Belfort Step 02)

1. **Orthogonality Gate (Zero Overlap with Strategy 1)**:
   - On session $d$, determine whether Strategy 1 (`morning_va_breakout_s1`) triggered at 09:44 ET.
   - **Hard Mutual Exclusivity**: If Strategy 1 fired on session $d$, this strategy is **100% GATED / INACTIVE**. It trades exclusively on Strategy 1 flat sessions.
2. **Initial Balance Reference Window (09:30:00 to 10:29:59 ET)**:
   - $\text{IB}_{\text{high}} = \max(\text{high}_{09:30..10:29})$
   - $\text{IB}_{\text{low}} = \min(\text{low}_{09:30..10:29})$
   - $\text{IB}_{\text{range}} = \text{IB}_{\text{high}} - \text{IB}_{\text{low}}$
   - Valid Range Filter:
     - `MES`: $10.0 \le \text{IB}_{\text{range}} \le 60.0$ index points.
     - `MNQ`: $40.0 \le \text{IB}_{\text{range}} \le 250.0$ index points.
3. **Breakout Trigger Window (10:30:00 to 11:15:00 ET)**:
   - Scan completed 1-minute bars strictly between 10:30 and 11:15 ET. The first bar to satisfy trigger criteria enters on the subsequent bar open:
     - **Bullish Extension (Long)**:
       - 1-min close $> \text{IB}_{\text{high}} + \text{buffer}$
       - 1-min bar close location $(close - low) / (high - low) \ge 0.65$
     - **Bearish Extension (Short)**:
       - 1-min close $< \text{IB}_{\text{low}} - \text{buffer}$
       - 1-min bar close location $(close - low) / (high - low) \le 0.35$
     - Buffer:
       - `MES`: 1.0 point (4 ticks)
       - `MNQ`: 4.0 points (16 ticks)
4. **Execution & Risk Budgeting**:
   - **Entry**: Market order at next bar open following trigger confirmation.
   - **Slippage Model**:
     - `MES`: 0.25 pts limit ($1.25), 0.50 pts market/stop ($2.50 per micro).
     - `MNQ`: 0.75 pts limit ($1.50), 1.50 pts market/stop ($3.00 per micro).
   - **Commission**: $1.20 round-turn per micro contract.
   - **Stop Loss**: $\text{clip}(0.40 \times \text{IB}_{\text{range}}, \text{min\_stop}, \text{max\_stop})$:
     - `MES`: min 5.0 pts ($25.00), max 15.0 pts ($75.00).
     - `MNQ`: min 20.0 pts ($40.00), max 60.0 pts ($120.00).
   - **Profit Target**: $1.50R$ multiple ($\text{entry} \pm 1.50 \times \text{stop\_points}$).
   - **Position Sizing**: Governed by $250 max-risk budget:
     - `MES`: $\text{contracts} = \text{clip}(\lfloor 250.0 / (\text{stop\_points} \times 5.0) \rfloor, 1, 4)$ micros.
     - `MNQ`: $\text{contracts} = \text{clip}(\lfloor 250.0 / (\text{stop\_points} \times 2.0) \rfloor, 1, 4)$ micros.
5. **Mandatory Exit Rules**:
   - Limit order at profit target (trade-through fill).
   - Stop loss fill with gap-through open protection.
   - Mandatory session flat at **12:00:00 ET** (entry cutoff at 11:15 ET; max 90-minute holding window).

---

## 3. Pre-Registered Falsification Criteria (Belfort Step 04 & 05)

1. **In-Sample Period (2021-01-01 to 2024-12-31)**:
   - Minimum trade count $N \ge 100$.
   - Net Profit Factor $\ge 1.25$ after all slippage and commissions.
   - Net Profit $> 0$.
2. **Out-of-Sample Period (2025-01-01 to 2026-10-30)**:
   - Net Profit Factor $\ge 1.15$.
   - Maximum Drawdown must not breach the LucidFlex 25K $1,000 trailing limit.
3. **Correlation Gate (Belfort Step 06)**:
   - Pairwise return correlation against Strategy 1, Strategy 2, and Strategy 3 must be $< 0.40$.
