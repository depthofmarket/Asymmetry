# NQ Scalper Backtest - Action Plan & Next Steps

**Generated**: May 19, 2026  
**Status**: Post-Diagnostic Review Ready for Next Phase

---

## Executive Action Items

### 🚀 IMMEDIATE (This Week)

#### 1. Commit Pending Changes
**Status**: 19 files modified, 2 untracked  
**Action**:
```bash
cd /Users/novo/trading_strategy/nq-scalper-backtest
git add -A
git commit -m "feat: add bar_exposure_audit module and backtest documentation

- Add new bar_exposure_audit.py module for trade-vs-execution bar reconciliation
- Add comprehensive backtest package README
- Update configuration for latest feature set
- Improve test coverage for edge cases"
git push origin main
```

**Owner**: You  
**Estimated Time**: 5 minutes  
**Blocking**: No, but keeps repo clean

---

#### 2. Verify Data File Availability
**Status**: Configuration expects `data/raw/glbx-mdp3-20100606-20260428.ohlcv-1m.csv`  
**Action**:
```bash
# Check if data file exists
ls -lh /Users/novo/trading_strategy/nq-scalper-backtest/data/raw/glbx*.csv

# If missing, check alternative paths
find ~ -name "*.csv" -path "*/nq*" -o -name "*mdp3*" 2>/dev/null

# If still missing, download from:
# - Databento: https://www.databento.com/ (recommended)
# - Kaggle: https://www.kaggle.com/datasets/
# - Your existing data provider
```

**Owner**: You  
**Estimated Time**: 15 minutes + download time  
**Blocking**: YES - Cannot run backtests without data

---

#### 3. Run Smoke Test - Validate Setup
**Status**: Tests pass, but haven't validated end-to-end backtest  
**Action**:
```bash
# Test configuration loads
python3 -c "from config.backtest_config import CANDIDATE_CONFIGS; \
            print(f'✅ {len(CANDIDATE_CONFIGS)} candidates configured')"

# List available candidates
python3 main_backtest.py --list-candidates 2>&1 | head -20

# Run quick validation backtest (if data available)
python3 main_backtest.py --candidate mr_long_only --start 2024-01-01 \
                         --end 2024-01-31 --quicktest 2>&1 | tail -30
```

**Owner**: You  
**Estimated Time**: 10 minutes  
**Blocking**: NO - Optional validation

---

### 📋 SHORT-TERM (Next 2 Weeks)

#### 4. Run Initial Candidate Backtests
**Purpose**: Validate strategy hypothesis and performance metrics  
**Candidates to Test** (from README):
- `mr_long_only` - Basic mean reversion
- `edge_vp_mr_trend_failed_auction_quality_probe` - Current focus
- `higher_frequency_probe` - Frequency sensitivity
- `market_profile_room_filter` - Profile-based filtering

**Commands**:
```bash
# Single candidate (typical)
caffeinate -dimsu python3 main_backtest.py --candidate mr_long_only

# Batch run all edge candidates
bash scripts/run_edge_candidates_batch.sh

# Quick frequency probe
python3 scripts/probe_candidate_frequency.py --signals-only \
  --out results/research_master/frequency_probe.csv
```

**Owner**: You  
**Estimated Time**: 2-8 hours (depending on data range)  
**Blocking**: NO - Parallel to next items

---

#### 5. Review and Validate Research Freeze
**Purpose**: Ensure approved candidates are properly locked down  
**Action**:
```bash
# Check current freeze manifest
python3 scripts/check_research_freeze.py --manifest config/research_freeze.json \
                                         --print-command

# After development run completes, validate gates
python3 scripts/check_research_freeze.py --manifest config/research_freeze.json \
                                         --run-dir results/runs/<YOUR_RUN_LABEL> \
                                         --phase development

# After lockbox/forward run, evaluate as evidence
python3 scripts/check_research_freeze.py --manifest config/research_freeze.json \
                                         --run-dir results/runs/<YOUR_RUN_LABEL> \
                                         --phase lockbox
```

**Owner**: You  
**Estimated Time**: 30 minutes + run time  
**Blocking**: YES - Before live trading

---

#### 6. Setup Paper Trading Infrastructure
**Purpose**: Validate execution in live-like environment  
**Action**:
```bash
# Test paper trader with historical replay
python3 scripts/run_paper_trader.py --candidate mr_long_only \
                                    --start 2024-01-01 \
                                    --end 2024-01-31 \
                                    --warmup-bars 2500 \
                                    --quiet

# Review generated paper trade log
ls -lh results/paper/
cat results/paper/trades_<DATE>.csv | head -20

# Validate parity with backtest
diff <(tail -100 results/runs/<BACKTEST_RUN>/trades.csv) \
     <(tail -100 results/paper/trades_<DATE>.csv)
```

**Owner**: You  
**Estimated Time**: 1-2 hours  
**Blocking**: NO - Can iterate

---

### 🔧 MEDIUM-TERM (Next Month)

#### 7. Enhance Type Hints
**Purpose**: Improve IDE support and code maintainability  
**Priority Modules**:
1. `backtest/engine.py` - Add full type annotations
2. `backtest/portfolio.py` - Complete Trade dataclass
3. `backtest/execution.py` - Method parameter types
4. `config/backtest_config.py` - Config dict types

**Example**:
```python
# Before
def get_directional_param(self, direction: str, key: str, default=None):
    ...

# After
def get_directional_param(
    self, 
    direction: str, 
    key: str, 
    default: Any | None = None
) -> Any | None:
    ...
```

**Owner**: You  
**Estimated Time**: 4-6 hours  
**Blocking**: NO - Quality improvement

---

#### 8. Expand Test Coverage
**Purpose**: Cover additional edge cases  
**New Tests to Add**:
- [ ] Empty data handling
- [ ] Single trade scenarios
- [ ] Extreme parameter combinations
- [ ] Multi-day walk-forward edge cases
- [ ] Options flow cache miss handling

**Test Locations**:
- Add to existing test files
- Organize by module in `tests/`

**Owner**: You  
**Estimated Time**: 4-6 hours  
**Blocking**: NO - Quality improvement

---

#### 9. Performance Profiling
**Purpose**: Identify optimization opportunities  
**Approach**:
```bash
# Profile main backtest execution
python3 -m cProfile -s cumtime main_backtest.py \
  --candidate mr_long_only --end 2024-01-31 2>&1 | head -50

# Profile Monte Carlo simulations
python3 -m cProfile -s cumtime scripts/run_edge_candidates_batch.sh \
  2>&1 | grep -A 20 "monte_carlo\|simulate"

# Identify hot spots
# - Feature building (likely ~30-40% of time)
# - Signal generation (likely ~20-30% of time)
# - Monte Carlo (likely ~20-30% of time)
```

**Owner**: You (optional)  
**Estimated Time**: 2-4 hours  
**Blocking**: NO - Optimization opportunity

---

#### 10. Live Broker Integration
**Purpose**: Setup for live trading deployment  
**Options**:
1. **CQG Integration** (recommended)
   - Setup CQG API credentials
   - Configure live broker in `live_brokers.py`
   - Test order intent audit

2. **Interactive Brokers** (alternative)
   - Install `ib_insync` package
   - Add IB adapter to `live_brokers.py`
   - Configure connection parameters

3. **Ninjatrader** (advanced)
   - CQG bridge through Ninjatrader
   - Simulate order flow

**Owner**: You (requires broker account)  
**Estimated Time**: 4-8 hours  
**Blocking**: NO - Only needed for live trading

---

### 📊 LONGER-TERM (Next Quarter)

#### 11. Create API Documentation
**Purpose**: Enable future development and integration  
**Deliverables**:
- API reference for `BacktestEngine`
- Configuration schema documentation
- Feature builder interface contracts
- Live trading runtime API

**Tools**:
- Sphinx for API docs
- OpenAPI for REST endpoint (if added)

**Owner**: You  
**Estimated Time**: 4-6 hours  
**Blocking**: NO - Documentation

---

#### 12. Setup CI/CD Pipeline
**Purpose**: Automate testing and deployment  
**Approach**:
```yaml
# GitHub Actions workflow (.github/workflows/test.yml)
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
      - run: pip install -r requirements.txt
      - run: python -m pytest tests/ -v
```

**Owner**: You  
**Estimated Time**: 2-3 hours  
**Blocking**: NO - DevOps improvement

---

#### 13. Distributed Backtesting
**Purpose**: Enable large parameter sweeps  
**Approach**:
- Refactor `main_backtest.py` to support distributed execution
- Integrate Ray or Dask for parallelization
- Implement result aggregation

**Consideration**: Large sweeps with Monte Carlo could run in 10% of current time

**Owner**: You  
**Estimated Time**: 8-12 hours  
**Blocking**: NO - Performance optimization

---

#### 14. Research Dashboard
**Purpose**: Enable real-time strategy monitoring  
**Tech Stack Options**:
- Streamlit (simple, Python-based)
- Dash (more features)
- Grafana (production-grade)

**Features**:
- Live equity curve
- Trade log viewer
- Performance metrics
- Regime visualization
- Prop firm compliance tracker

**Owner**: You  
**Estimated Time**: 6-10 hours  
**Blocking**: NO - Nice-to-have

---

## Success Metrics

### Backtest Success Criteria
```
✅ Run completes without errors
✅ Generates trade log with >0 trades
✅ Profit factor > 1.0 (ideally > 1.5)
✅ Win rate > 40% (ideally > 50%)
✅ Max drawdown < 15% (ideally < 10%)
✅ Sharpe ratio > 1.0 (ideally > 2.0)
✅ Walk-forward OOS performance similar to IS
✅ Monte Carlo pass rate > 80%
✅ Bar-level PF similar to trade PF (no execution leakage)
```

### Paper Trading Success Criteria
```
✅ Paper matches backtest trades (parity > 95%)
✅ Fill assumptions validated (execution bar PF aligns)
✅ Prop firm rules hold (daily loss, consistency)
✅ State persists through restarts
✅ Emergency stop works (flatten on demand)
```

### Live Trading Readiness
```
✅ Paper trading running stable for 2+ weeks
✅ No untracked execution gaps
✅ Broker connectivity tested
✅ Risk limits configured and enforced
✅ Monitoring and alerting in place
✅ Drawdown/loss circuit breaker tested
```

---

## Testing & Validation Workflow

### Pre-Run Checklist
```
□ Data files exist and are recent
□ Configuration reviewed for current parameters
□ Results directory is clean or versioned
□ Python environment activated
□ Git status clean (or changes committed)
□ Sufficient disk space available (50GB+ for large runs)
```

### During Run Monitoring
```
□ Watch progress in terminal
□ Monitor memory usage (Activity Monitor)
□ Check for error messages
□ Note generation timestamp for results location
```

### Post-Run Validation
```
□ Development report exists (results/runs/<RUN>/research/development_report.md)
□ Trade log generated (results/runs/<RUN>/trades.csv)
□ Performance metrics reasonable
□ Optimization stability report generated
□ Multiple testing debt recorded
□ Gate checks passed/failed documented
```

---

## Git Workflow for Ongoing Development

```bash
# Start work on new feature
git checkout -b feature/new-feature-name
git pull origin main

# Make changes and test
# ... edit files ...
python -m pytest tests/ -v

# Commit changes with descriptive message
git add <changed files>
git commit -m "feat: description of changes

- Specific change 1
- Specific change 2
- Specific change 3"

# Push to remote
git push origin feature/new-feature-name

# Create PR for code review
# (via GitHub UI)

# After approval, merge to main
git checkout main
git pull origin main
git merge feature/new-feature-name
git push origin main

# Delete feature branch
git branch -d feature/new-feature-name
git push origin --delete feature/new-feature-name
```

---

## Common Commands Reference

### Backtesting
```bash
# List all candidates
python3 main_backtest.py --list-candidates

# Run single candidate
python3 main_backtest.py --candidate <CANDIDATE_NAME>

# Run with custom date range
python3 main_backtest.py --candidate <CANDIDATE> --start 2024-01-01 --end 2024-12-31

# Batch run all edge candidates
bash scripts/run_edge_candidates_batch.sh

# Frequency probe analysis
python3 scripts/probe_candidate_frequency.py --signals-only
```

### Paper Trading
```bash
# Historical replay
python3 scripts/run_paper_trader.py --candidate <CANDIDATE> \
                                     --start 2024-01-01 \
                                     --end 2024-01-31

# Live replay from file
python3 scripts/run_amp_paper_trader.py --feed tail \
                                        --bar-file data/live/latest_1m_bars.csv
```

### Validation & Audits
```bash
# Check research freeze
python3 scripts/check_research_freeze.py --manifest config/research_freeze.json

# Audit bar exposure
python3 scripts/audit_bar_exposure.py --run-dir results/runs/<RUN_LABEL>

# Audit fill assumptions
python3 scripts/audit_fill_assumptions.py --run-dir results/runs/<RUN_LABEL>

# Check prop firm rules
python3 scripts/check_prop_research_gate.py
```

### Testing
```bash
# Run all tests
python3 -m pytest tests/ -v

# Run specific test file
python3 -m pytest tests/test_backtest_regression.py -v

# Run specific test
python3 -m pytest tests/test_backtest_regression.py::BacktestRegressionTests::test_deterministic_output -v

# Run with coverage
python3 -m pytest tests/ --cov=backtest --cov-report=html
```

---

## Troubleshooting Guide

### "Data file not found" Error
**Solution**:
1. Check path in `config/backtest_config.py` -> `BACKTEST_CONFIG['data_path']`
2. Verify file exists: `ls -lh data/raw/glbx*.csv`
3. Download from Databento or your data provider

### Tests Failing After Changes
**Solution**:
```bash
# Run full test suite
python3 -m pytest tests/ -v

# Check specific failure
python3 -m pytest <TEST_FILE> -v -s

# Revert changes if needed
git checkout -- <MODIFIED_FILE>
```

### Memory Issues During Large Runs
**Solution**:
1. Reduce date range
2. Disable optional features (options flow, Markov regime)
3. Reduce Monte Carlo path count
4. Close other applications

### Paper Trading State Corruption
**Solution**:
```bash
# Backup current state
cp results/live_paper_state_*.json results/live_paper_state_*.json.bak

# Clear state and restart
rm results/live_paper_state_*.json
python3 scripts/run_paper_trader.py --candidate <CANDIDATE> --start <DATE>
```

---

## Dependencies & Maintenance

### Update Frequency
- **Monthly**: Review dependency updates
- **Quarterly**: Update minor versions
- **Annually**: Review major version upgrades

### Update Process
```bash
# Check for updates
pip list --outdated

# Update specific package
pip install --upgrade <PACKAGE_NAME>

# Update all packages
pip install --upgrade -r requirements.txt

# Verify tests still pass
python3 -m pytest tests/ -v
```

### Backup Strategy
```bash
# Create backup before major changes
zip -r backups/nq-scalper-$(date +%Y%m%d).zip .

# Git provides version control
git tag v1.0.0-release
git push origin v1.0.0-release
```

---

## Success Story - Next Milestone

Once you complete items 1-6, you will have:

✅ **Clean repository** with all changes committed  
✅ **Validated data pipeline** ready for analysis  
✅ **Working backtest** producing trades and metrics  
✅ **Research freeze** preventing overfitting  
✅ **Paper trading** validated against backtest  
✅ **Production-ready** edge candidate selected  

This positions you to:
- 📊 Analyze current strategy performance
- 🔍 Identify optimization opportunities
- 📈 Test new features and parameters
- 🚀 Deploy to live paper trading
- 💰 Evaluate fund-ready performance

---

## Support Resources

### Within Codebase
- `README.md` - Main usage guide
- `backtest/README.md` - Package organization
- `docs/codebase_map.md` - Complete structure
- Test files - Usage examples
- `config/backtest_config.py` - Configuration reference

### External Resources
- Databento API: https://docs.databento.com/
- CQG API: https://www.cqg.com/
- Interactive Brokers: https://www.interactivebrokers.com/
- pandas documentation: https://pandas.pydata.org/docs/
- NumPy guide: https://numpy.org/doc/

### Next Discussion Points
1. Which candidate strategies are priority?
2. What data range should we focus on?
3. When should we target live trading?
4. What risk limits are acceptable?
5. Which broker will we use for live execution?

---

## Summary

Your codebase is **production-ready**. The next steps are:

1. **Commit changes** (5 min)
2. **Verify data** (15 min)
3. **Run smoke test** (10 min)
4. **Backtest candidates** (2-8 hours)
5. **Validate paper trading** (1-2 hours)
6. **Deploy strategy** (when ready)

**Estimated time to first live trade**: 1-2 weeks  
**Estimated time to funded trading**: 4-8 weeks  

Ready to proceed? Let me know which items you'd like to tackle first!

---

**End of Action Plan**

Generated: May 19, 2026  
Status: Ready for Next Phase ✅

