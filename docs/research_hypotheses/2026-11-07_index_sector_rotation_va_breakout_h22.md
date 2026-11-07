# Research Hypothesis H22: 4-Index Sector Rotation Value Area Breakout (09:45 ET) on MYM & M2K

**Status:** ACTIVE RESEARCH CANDIDATE (Belfort Step 01–04)  
**Date Pre-Registered:** November 7, 2026  
**Primary Instruments:** `MYM` (Micro Dow Jones Industrial Average) & `M2K` (Micro Russell 2000)  
**Execution Window:** `09:45:00 ET` entry &bull; `11:30:00 ET` mandatory session flat  
**Strategy ID:** `index_sector_rotation_s5`  
**Strategy Tier:** `StrategyTier.CANDIDATE`  

---

## 1. Economic & Institutional Rationale (Belfort Step 01)

### The Structural Question: "Why should price go from point A to point B?"
1. **Who is in the market?**: 
   Institutional sector-rotation equity funds, small-cap asset allocators, dividend/value fund managers, and equity index market-makers.
2. **Why at this time?**: 
   At **09:30:00 ET**, the New York Stock Exchange (NYSE) and NASDAQ cash equity open unleashes market-wide price discovery. By **09:45:00 ET**, the first 15 minutes of heavy institutional opening auctions have settled.
3. **Why does price move from point A to point B?**: 
   The US equity market is not monolithic; it consists of 4 distinct market engines:
   - Mega-cap Tech (`NQ`): Duration and growth sensitive.
   - S&P 500 (`ES`): Large-cap blend.
   - Dow Jones 30 (`YM`): Financials, industrials, healthcare, and cyclical blue-chips.
   - Russell 2000 (`RTY`): Small-cap domestic cyclicals, highly sensitive to regional credit and domestic GDP.
   
   On roughly 65% of all exchange sessions, Tech (`NQ`) and S&P (`ES`) open *inside* the prior day's Value Area, producing zero trade signals for Strategy 1. However, macro fund flows frequently initiate aggressive **intermarket sector rotation**: capital flows out of overextended mega-caps into undervalued industrials (`YM`) or high-beta small caps (`RTY`).
   
   When `MYM` or `M2K` breaks cleanly outside its prior session 70% Value Area while holding its 15-minute Opening Range boundary, it reflects genuine institutional sector reallocation. Market makers adjust liquidity away from the breakout direction, forcing programmatic momentum to drive price toward the next structural profile shelf.

### The Belfort One-Sentence Formula
> *"I believe Micro Dow (`MYM`) and Micro Russell 2000 (`M2K`) trend directionally between 09:45 and 11:30 ET when breaking outside their prior session Value Area because institutional sector rotation shifts capital into cyclical and small-cap assets, creating persistent morning trend drives on sessions where tech equities remain trapped in balance."*

---

## 2. Quantitative Rules & Execution Specifications (Belfort Step 02)

1. **Prior Session Reference Boundary (09:30:00 to 16:00:00 ET of Day $T-1$)**:
   - Compute prior session Value Area High ($\text{VAH}$), Value Area Low ($\text{VAL}$), and Point of Control ($\text{POC}$) using 70% volume distribution:
     - `MYM`: 5.0-point price bins.
     - `M2K`: 0.5-point price bins.
   - Strictly lagged by 1 session ($T-1$) with zero lookahead bias.
2. **Opening Discovery & Value Area Acceptance (09:30:00 to 09:44:59 ET of Day $T$)**:
   - Compute 15-minute Opening Range: $\text{OR}_{\text{high}} = \max(\text{high}_{09:30..09:44})$, $\text{OR}_{\text{low}} = \min(\text{low}_{09:30..09:44})$, $\text{OR}_{\text{range}} = \text{OR}_{\text{high}} - \text{OR}_{\text{low}}$.
   - Signal bar is the 09:44 ET bar closing at 09:45:00 ET:
     - **BULLISH BREAKOUT**: 09:44 close $> \text{VAH}$ AND 09:44 close $> \text{OR}_{\text{high}}$ AND close location $\ge 0.65$.
     - **BEARISH BREAKDOWN**: 09:44 close $< \text{VAL}$ AND 09:44 close $< \text{OR}_{\text{low}}$ AND close location $\le 0.35$.
3. **Execution & Risk Budgeting**:
   - **Entry**: Market order at 09:45:00 ET.
   - **Slippage Model**:
     - `MYM`: 2.0 points adverse slippage ($1.00 per contract).
     - `M2K`: 0.20 points adverse slippage ($1.00 per contract).
   - **Commission**: \$1.20 round-turn per micro contract.
   - **Stop Loss**: 
     - `MYM`: $\text{clip}(0.50 \times \text{OR}_{\text{range}}, 25.0, 100.0)$ index points (\$12.50 to \$50.00 per micro).
     - `M2K`: $\text{clip}(0.50 \times \text{OR}_{\text{range}}, 3.0, 12.0)$ index points (\$15.00 to \$60.00 per micro).
   - **Profit Target**: $1.50R$ multiple ($\text{entry} + d \times 1.50 \times \text{stop\_distance}$).
   - **Position Sizing**: Governed by \$250 max-risk budget:
     - `MYM`: $\text{contracts} = \text{clip}(\lfloor 250.0 / (\text{stop\_points} \times 0.50) \rfloor, 1, 4)$ micros.
     - `M2K`: $\text{contracts} = \text{clip}(\lfloor 250.0 / (\text{stop\_points} \times 5.00) \rfloor, 1, 4)$ micros.
4. **Mandatory Exit Rules**:
   - Limit order at profit target (trade-through fill).
   - Stop loss fill with gap-through open protection.
   - Mandatory session flat at **11:30:00 ET**.
