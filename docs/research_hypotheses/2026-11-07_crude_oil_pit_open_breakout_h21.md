# Research Hypothesis H21: Crude Oil Pit Open Breakout (09:00 ET) on MCL

**Status:** ACTIVE RESEARCH CANDIDATE (Belfort Step 01–04)  
**Date Pre-Registered:** November 7, 2026  
**Primary Instrument:** `MCL` (NYMEX Micro WTI Crude Oil)  
**Execution Window:** `09:15:00 ET` entry &bull; `11:30:00 ET` mandatory session flat (European energy close)  
**Strategy ID:** `cl_pit_open_s4`  
**Strategy Tier:** `StrategyTier.CANDIDATE`  

---

## 1. Economic & Institutional Rationale (Belfort Step 01)

### The Structural Question: "Why should price go from point A to point B?"
1. **Who is in the market?**: 
   Physical oil producers (E&P companies locking forward production prices), commercial refiners (purchasing crude feedstock batches), pipeline transport operators, and institutional commodity swap dealers.
2. **Why at this time?**: 
   While electronic trading on CME Globex is continuous, **09:00:00 ET** is the official floor/pit opening bell on NYMEX. Commercial physical delivery benchmarks, exchange-for-physical (EFP) swap balances, and corporate hedging orders benchmark to this exact 09:00 ET timestamp—30 minutes prior to the US cash equity open (09:30 ET).
3. **Why does price move from point A to point B?**: 
   If overnight electronic trade has displaced price outside the prior session's fair value (the 70% pit Value Area computed from the previous session's 09:00–14:30 ET floor hours), commercial physical hedgers who were waiting for the 09:00 ET open are forced to execute resting orders at market rather than waiting for a mean reversion that is not coming. 
   When the initial 15-minute price discovery window (09:00:00 to 09:14:59 ET) holds and closes outside the prior Value Area with cumulative session VWAP confirmation, commercial hedging momentum drives price directionally toward outer profile volume shelves before European energy markets begin settling.

### The Belfort One-Sentence Formula
> *"I believe Micro Crude Oil (`MCL`) trends directionally between 09:15 and 10:30 ET when opening outside the prior pit Value Area because commercial physical hedgers and swap dealers begin executing bulk daily allocations at the 09:00 ET NYMEX floor open."*

---

## 2. Quantitative Rules & Execution Specifications (Belfort Step 02)

Every rule is mechanical and unambiguous:

1. **Prior Session Reference Boundary (09:00:00 to 14:30:00 ET of Day $T-1$)**:
   - Compute prior session Value Area High ($\text{VAH}_{\text{pit}}$), Value Area Low ($\text{VAL}_{\text{pit}}$), and Point of Control ($\text{POC}_{\text{pit}}$) using 70% volume distribution across \$0.05 price bins.
   - Reference levels are strictly lagged ($T-1$) with zero lookahead bias.
2. **Floor Open Conditioning (09:00:00 ET of Day $T$)**:
   - Floor open bar (09:00 ET open) must be outside prior pit Value Area: $\text{open}_{09:00} > \text{VAH}_{\text{pit}}$ (Bullish setup) OR $\text{open}_{09:00} < \text{VAL}_{\text{pit}}$ (Bearish setup).
3. **Opening Discovery Bar & VWAP Filter (09:00:00 to 09:14:59 ET)**:
   - Compute 15-minute Opening Range: $\text{OR}_{\text{high}} = \max(\text{high}_{09:00..09:14})$, $\text{OR}_{\text{low}} = \min(\text{low}_{09:00..09:14})$, $\text{OR}_{\text{range}} = \text{OR}_{\text{high}} - \text{OR}_{\text{low}}$.
   - Compute cumulative session VWAP from 09:00:00 ET.
   - Signal bar is the 09:14 ET bar closing at 09:15:00 ET:
     - **LONG**: 09:14 close $> \text{VAH}_{\text{pit}}$ AND 09:14 close $> \text{VWAP}$ AND close location $\ge 0.60$.
     - **SHORT**: 09:14 close $< \text{VAL}_{\text{pit}}$ AND 09:14 close $< \text{VWAP}$ AND close location $\le 0.40$.
4. **Order Execution & Risk Budgeting**:
   - **Entry**: Market order at 09:15:00 ET (modeled with 1-tick adverse slippage: \$0.01 per contract = \$1.00).
   - **Stop Loss**: Stop order placed at $\text{entry} - d \times \text{clip}(0.50 \times \text{OR}_{\text{range}}, 0.30, 0.75)$ points (\$30.00 to \$75.00 per micro contract).
   - **Profit Target**: Limit order placed at $\text{entry} + d \times (1.50 \times \text{stop\_points})$ (1.50R reward/risk).
   - **Commission**: \$1.24 round-turn per micro contract.
   - **Position Sizing**: Governed by \$250 max-risk budget: $\text{contracts} = \text{clip}(\lfloor 250.0 / (\text{stop\_points} \times 100.0) \rfloor, 1, 4)$ micros.
5. **Mandatory Exit Rules**:
   - **Profit Target**: Fill on touch/trade-through.
   - **Stop Loss**: Fill at stop or gap-through open.
   - **Time Exit**: Mandatory flat at **11:30:00 ET** prior to European energy market floor close.
