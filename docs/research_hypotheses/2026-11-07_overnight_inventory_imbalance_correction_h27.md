# Research Hypothesis H27: Dalton's Overnight Inventory Imbalance Correction (09:35 ET) on MES & MNQ

**Status:** ACTIVE RESEARCH CANDIDATE (Belfort Step 01–05)  
**Date Pre-Registered:** November 7, 2026  
**Primary Instruments:** `MES` (Micro S&P 500) & `MNQ` (Micro Nasdaq 100)  
**Execution Window:** `09:35:00 ET` to `10:15:00 ET` (Entry at 09:35 ET; mandatory flat at 10:15 ET)  
**Strategy ID:** `overnight_inventory_correction_s10`  
**Strategy Tier:** `StrategyTier.CANDIDATE`  
**Source Datasets:**  
- `data/raw/es_1m_2020_2026_cqg_et.parquet` (SHA-256: `36f0a1042b9981b8166c32d2aad5b5452f7027fb210da65547d928dd791290f3`)  
- `data/raw/nq_1m_2017_2026_cqg_et.parquet` (SHA-256: `c9d78a716f5afe040c590fc974e980edfee029081ba47875f041b034c38b737a`)

---

## 1. Economic & Institutional Rationale (Belfort Step 01)

### The Structural Question: "Why should price go from point A to point B?"
1. **Who is in the market?**: 
   Overnight electronic Globex traders (retail, international funds, systematic CTAs) holding unhedged directional overnight inventory versus New York Cash Equity Opening Specialists and institutional market makers entering at 09:30:00 ET.
2. **Why at this time?**: 
   At **09:30:00 ET**, the New York Stock Exchange opens with 10x to 20x the liquidity and transaction volume of the entire overnight session.
   - Throughout the overnight session (18:00 to 09:29 ET), trading frequently becomes one-sided, resulting in **100% net long inventory** (or net short) relative to the prior session settlement price.
   - When the cash bell rings, overnight traders want to see their directional move validated by fresh institutional buying at the opening bell.
3. **Why does price move from point A to point B?**: 
   In Auction Market Theory (James Dalton, *Mind over Markets*), if overnight inventory is 100% net long (trading $\ge 85\%$ above prior session settlement), but the cash open (09:30–09:34 ET) **fails to break and accept above the Overnight High (ONH)**, New York institutional participants refuse to pay inflated overnight prices.
   - With no new institutional buyers entering above the overnight high, the market is structurally "too long."
   - Trapped overnight longs face imminent margin compression and panic liquidation.
   - A violent cascade of sell market orders drives price back to the prior session settlement price ($P_{\text{settle}}$), which acts as the ultimate structural equilibrium / fair-value magnet.
   - Conversely, when overnight inventory is 100% net short ($\ge 85\%$ below settlement) and fails to accept below the Overnight Low (ONL), trapped shorts are forced to cover, propelling price back upward to prior settlement.

### The Belfort One-Sentence Formula
> *"I believe Micro S&P 500 (`MES`) and Micro Nasdaq (`MNQ`) mean-revert to the prior session settlement price between 09:35 and 10:15 ET when overnight inventory is heavily one-sided (>= 85% volume on one side of settlement) and the 09:30–09:34 cash open fails to expand the overnight extreme, because trapped overnight traders are forced to liquidate into institutional liquidity."*

---

## 2. Quantitative Rules & Execution Specifications (Belfort Step 02)

1. **Prior Settlement Determination**:
   - Prior session settlement price $P_{\text{settle}}$ defined as the official cash close at 16:00:00 ET of session $d-1$.
2. **Overnight Inventory Imbalance Condition (18:00:00 to 09:29:59 ET)**:
   - Calculate total volume and volume traded above/below $P_{\text{settle}}$:
     $$\text{Ratio}_{\text{long}} = \frac{\sum_{t \in \text{ON}} \text{Vol}_t \cdot \mathbb{I}(C_t > P_{\text{settle}})}{\sum_{t \in \text{ON}} \text{Vol}_t}$$
     $$\text{Ratio}_{\text{short}} = \frac{\sum_{t \in \text{ON}} \text{Vol}_t \cdot \mathbb{I}(C_t < P_{\text{settle}})}{\sum_{t \in \text{ON}} \text{Vol}_t}$$
   - **Long Imbalance**: $\text{Ratio}_{\text{long}} \ge 0.85$ AND $\text{Open}_{09:30} \ge P_{\text{settle}} + \text{min\_dist}$.
   - **Short Imbalance**: $\text{Ratio}_{\text{short}} \ge 0.85$ AND $\text{Open}_{09:30} \le P_{\text{settle}} - \text{min\_dist}$.
   - Minimum Distance:
     - `MES`: 6.0 index points ($30.00)
     - `MNQ`: 25.0 index points ($50.00)
3. **Opening Auction Acceptance Failure (09:30:00 to 09:34:59 ET)**:
   - Identify Overnight High ($\text{ONH}$) and Overnight Low ($\text{ONL}$) from 18:00 to 09:29 ET.
   - For Long Inventory Imbalance:
     - The 09:34:00 1-minute close must be **below** $\text{ONH} - 1.0$ pt (failed to break out / rejected).
     - The 5-minute opening bar (09:30–09:34) closes in the lower half: $\text{Close}_{09:34} < (\text{High}_{5\text{m}} + \text{Low}_{5\text{m}}) / 2$.
   - For Short Inventory Imbalance:
     - The 09:34:00 1-minute close must be **above** $\text{ONL} + 1.0$ pt.
     - The 5-minute opening bar closes in the upper half: $\text{Close}_{09:34} > (\text{High}_{5\text{m}} + \text{Low}_{5\text{m}}) / 2$.
4. **Execution & Risk Budgeting**:
   - **Entry**: Market order at 09:35:00 ET open.
     - Short for Long Inventory Imbalance; Long for Short Inventory Imbalance.
   - **Stop Loss**:
     - Short: Placed at $\text{ONH} + \text{buffer}$ (MES: 2.0 pts; MNQ: 8.0 pts). Capped at max stop: MES 12.0 pts ($60); MNQ 50.0 pts ($100).
     - Long: Placed at $\text{ONL} - \text{buffer}$. Capped at max stop: MES 12.0 pts ($60); MNQ 50.0 pts ($100).
   - **Profit Target**:
     - Placed at $P_{\text{settle}} \pm 1.0$ pt (or 1.5R, whichever is reached first).
   - **Mandatory Time Exit**:
     - **10:15:00 ET** (40-minute maximum holding duration before European fix flows interfere).
   - **Position Sizing**:
     - 1 to 2 micro contracts scaled to risk $\le \$150$ per trade.
   - **Slippage & Commission Model**:
     - 1 tick adverse entry + 1 tick adverse exit + $1.24 RT commission.

---

## 3. Pre-Registered Falsification Criteria (Belfort Step 04 & 05)

The candidate is strictly deemed **FALSIFIED** if:
1. **Step 04 In-Sample Failure (2021-01 to 2024-12)**:
   - In-Sample Profit Factor $< 1.25$
   - Total trade count $N < 100$
   - Max Drawdown $> \$1,000$ (LucidFlex account breach)
2. **Step 05 Out-of-Sample Decay (2025-01 to 2026-10)**:
   - Out-of-Sample Profit Factor $< 1.15$
   - Performance decay $> 25\%$ relative to In-Sample
3. **Execution Robustness (Step 06)**:
   - Profit Factor drops $< 1.00$ at 2 ticks adverse slippage.
