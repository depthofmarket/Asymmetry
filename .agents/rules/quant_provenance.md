---
name: quant_provenance
description: Strict anti-hallucination standing orders for backtests and quantitative metrics.
always_on: true
---

# Quantitative Backtest Provenance Rule

Every backtest auto-records into a single store (`results/backtest_provenance.db`). The AI may quote stats ONLY by querying it — never from memory, prose, or prior chats.

## 5 Golden Rules
1. **One source of truth**: Query `results/backtest_provenance.db` via `python scripts/query_provenance.py`. Never quote numbers from memory.
2. **No naked numbers**: Every stat MUST travel with its methodology, date range, and SHA-256 data hash.
3. **Provenance footers on every tool**: Formatted verification footer must accompany every metric block.
4. **Warnings travel with the number**: Quote low sample size ($N < 30$), gross execution, outlier dominance ($> 35\%$), and short window ($< 60$ days) inline.
5. **Recording is automatic, not discipline**: Backtest engines auto-record on completion.
