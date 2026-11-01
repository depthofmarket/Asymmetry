# Research Hypothesis H19: Point-in-Time 3-State Gaussian Hidden Markov Model (HMM) Regimes & Macro Momentum Adaptation

**Status:** APPROVED & VALIDATED  
**Date Pre-Registered:** November 1, 2026  
**Primary Instruments:** `NQ` / `MNQ` (Micro E-mini Nasdaq-100), `ES` / `MES` (Micro E-mini S&P 500), `MGC` (Micro Gold)  
**Execution Windows:**  
- Window 1: `08:35:00 ET` (Strategy 3 / H17: Pre-Market Macro Release Momentum)  
- Window 2: `09:45:00 ET` (Strategy 1 / H4: Dual-Asset Morning Value Area Breakout)  
- Window 3: `10:15:00 ET` (Strategy 2 / H14: Gold PM Fix Structural Breakout)  
**Source Inspiration:** Jeffy Motta's *AntiAchismo* Quant Masterclass (Markov Regime-Switching Models & Asymmetric Volatility Conditioning)  

---

## 1. Economic & Institutional Rationale

Financial markets alternate between distinct latent volatility regimes:
1. **Low Volatility (`low_vol`)**: Compression, steady directional trend persistence, high institutional participation with tight spreads, high signal-to-noise ratio.
2. **Medium Volatility (`mid_vol`)**: Normal market conditions, balanced liquidity, classic auction market theory distributions.
3. **High Volatility (`high_vol`)**: Heightened uncertainty, event-driven liquidity vacuums, wide bid-ask spreads, violent two-way whipsaws, erratic mean-reverting shocks.

Classical fixed-parameter trading rules assume stationary return distributions, leading to severe performance degradation when transitioning into high-volatility environments. In Jeffy Motta's *AntiAchismo* curriculum, Hidden Markov Models (HMM) allow algorithmic systems to detect these unobservable latent states directly from price displacement without lagging moving averages.

### The Macro Release Whipsaw Vulnerability in High Volatility
In Strategy 3 (08:35 ET Macro Momentum on MNQ), the setup captures institutional momentum following 08:30 AM economic releases (CPI, PPI, NFP, GDP, Retail Sales). 
- In **`low_vol` and `mid_vol` regimes**, the 08:30 release creates a clean, decisive institutional repricing that breaks the overnight range and trends cleanly into the 09:25 cash pre-open.
- In **`high_vol` regimes**, overnight ranges are already stretched ($166.9 \text{ pts}$ mean range vs $114.6 \text{ pts}$ in low vol). The 08:30 release generates multi-directional 50–100 pt candles with violent orderbook sweeping. A standard 20–50 pt stop loss is repeatedly absorbed by random intraday volatility before directional resolution, resulting in negative expectancy.

---

## 2. Quantitative Architecture & Point-in-Time Discipline

### Point-in-Time 3-State Gaussian HMM
To prevent lookahead bias, calibration strictly precedes trading execution:
1. **Observation Variable**: Daily normalized range volatility:
   $$v_d = \frac{\text{High}_d - \text{Low}_d}{\text{Close}_d}$$
2. **Rolling Estimation**: Calibrated over a 60-trading-day rolling window ($d-60$ to $d-1$), refitted every 5 trading days.
3. **Transition Dynamics**:
   $$P(S_t = j \mid S_{t-1} = i) = A_{ij}$$
   with Laplace smoothing $\alpha = 0.1$ to guarantee positive transition probabilities.
4. **Gaussian Emission Likelihood**:
   $$P(v_t \mid S_t = k) = \frac{1}{\sqrt{2\pi \sigma_k^2}} \exp\left(-\frac{(v_t - \mu_k)^2}{2\sigma_k^2}\right)$$
5. **Zero-Lookahead Shift**: The regime state inferred at the close of session $d-1$ governs execution for session $d$. Under no circumstances does session $d$'s intraday data leak into its prior regime state.

---

## 3. Empirical Multi-Year Backtest (2021–2026 | 543 Trades)

Tested across the active Candidate A ensemble with full micro transaction costs ($1.24 round-turn commission + 1-tick adverse slippage):

### Breakdown by Latent Markov Regime (NQ Daily)
| Strategy | Markov State | Trades | Win Rate | Profit Factor | Net P&L | Avg Trade | Status |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **Strategy 1 (09:45 VA)** | `low_vol` | 122 | **59.0%** | **1.82** | **+$3,312.38** | +$27.15 | Highly Robust |
| Strategy 1 (09:45 VA) | `mid_vol` | 90 | 56.7% | 1.40 | +$1,499.58 | +$16.66 | Positive Edge |
| Strategy 1 (09:45 VA) | `high_vol` | 104 | 54.8% | **1.66** | **+$3,316.14** | +$31.89 | Highly Robust |
| **Strategy 2 (10:15 Gold)** | `low_vol` | 23 | **60.9%** | **4.04** | **+$686.50** | +$29.85 | Exceptional |
| Strategy 2 (10:15 Gold) | `mid_vol` | 30 | 66.7% | 1.23 | +$221.00 | +$7.37 | Positive Edge |
| Strategy 2 (10:15 Gold) | `high_vol` | 31 | 48.4% | 1.28 | +$307.50 | +$9.92 | Positive Edge |
| **Strategy 3 (08:35 Macro)** | `low_vol` | 37 | **54.1%** | **1.57** | **+$1,399.78** | +$37.83 | Solid Alpha |
| Strategy 3 (08:35 Macro) | `mid_vol` | 64 | **53.1%** | **1.69** | **+$3,442.70** | +$53.79 | Strongest Alpha |
| **Strategy 3 (08:35 Macro)** | `high_vol` | **42** | **38.1%** | **0.73** | **-$1,238.38** | **-$29.49** | **TOXIC DRAG** |

### Key Structural Takeaways:
1. **Strategy 1 & 2 are All-Weather**: Both the 09:45 ET Value Area Breakout and 10:15 ET Gold Fix Breakout generate positive expectancy across all three regimes. In fact, Strategy 1 delivers +$3,316.14 in `high_vol` because institutional volume at the cash open establishes genuine directional breakouts.
2. **Strategy 3 Fails Exclusively in High Volatility**: In `low_vol` and `mid_vol`, Strategy 3 yields +$4,842.48 at a 1.65 PF. In `high_vol`, it loses -$1,238.38. Empirical stop-widening tests (widening stops up to 90 pts) failed to salvage high-volatility pre-market momentum (best result was +$46.21 at 1.01 PF).

---

## 4. Adaptation Alternatives & Portfolio Impact

### Comparison Table across Full 5.8-Year History (2021–2026)
| Variant | Trades | Win Rate | Profit Factor | Net Profit | Max Drawdown | Return / DD |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Active Baseline (Candidate A)** | 543 | 55.06% | 1.48 | $12,947.18 | $1,768.47 | 7.32x |
| **Option 1: Hard Gate S3 in High-Vol** | **501** | **56.49%** | **1.63** | **$14,185.57** | **$1,267.39** | **11.19x** |
| **Option 2: Markov Adaptive Sizing** | **543** | **55.06%** | **1.56** | **$14,916.04** | **$1,511.51** | **9.87x** |
| Option 3: Gate S2 & S3 in High-Vol | 470 | 57.02% | 1.65 | $13,878.07 | $1,214.01 | 11.43x |

*Option 2 Rules:* $1.25\times$ contract sizing in `low_vol`, $1.0\times$ in `mid_vol`, and $0.5\times$ on Strategy 3 in `high_vol` (preserving 100% of trades).

### Monte Carlo Simulation (10,000 Paths on LucidFlex 25K Target $1,500 / DD $1,500)
| Metric | Baseline (543 Trades) | Option 1 (501 Trades) | Option 2 (543 Trades) |
| :--- | :---: | :---: | :---: |
| **Pass Rate** | 56.4% | **65.5%** (+9.1%) | **62.1%** (+5.7%) |
| **Fail Rate** | 24.5% | **15.7%** (-8.8%) | **21.8%** (-2.7%) |
| **Timeout Rate** | 19.1% | 18.8% | 16.1% |
| **Avg Days to Target** | 26.0 days | 25.4 days | 25.1 days |
| **Estimated EV / Eval** | $809.45 | **$958.65** (+18.4%) | **$899.25** (+11.1%) |

---

## 5. Implementation Roadmap
1. Pre-compute and maintain daily point-in-time Markov states in `data/processed/nq_daily_markov_regimes_2020_2026.parquet`.
2. Connect daily Markov regimes to live / demo execution cards in `scripts/run_demo_forward_test.py`.
3. Add `enableMarkovHighVolGate` to `LucidMacroMomentumStudy.java` to allow one-click toggling between Option 1 (Gate) and Baseline/Option 2.
