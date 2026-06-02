# 🚀 L2 Parquet Data Ingestion Setup Complete

You've received 5 years of level 2 parquet data. This guide shows you exactly how to ingest it into your NQ scalper backtest framework.

## TL;DR – Start Here

**Got your 5-year L2 data? Run this:**

```bash
cd /Users/novo/trading_strategy/nq-scalper-backtest
./ingest_l2.sh --download-dir ~/Downloads/l2_data
```

Or in Python:
```bash
python3 scripts/ingest_l2_parquet_5year.py --download-dir ~/Downloads/l2_data
```

**That's it.** The script will:
1. Create folder structure (2021_H1, 2021_H2, ... 2026_H1)
2. Discover & categorize your zips by date
3. Ask before moving (safe!)
4. Organize files into semester folders
5. Audit parquet schema & quality
6. Generate audit reports

---

## What's Available Now

### 📚 Documentation (Read First)
1. **`L2_QUICK_REFERENCE.md`** ← Start here (2 min read)
2. **`L2_DATA_INGESTION_GUIDE.md`** (detailed workflows)
3. **`L2_PARQUET_READY.md`** (this summary)

### 🔧 Tools (Choose Your Style)

| Tool | Style | Command |
|------|-------|---------|
| **Bash wrapper** | Shell scripting | `./ingest_l2.sh --download-dir ~/path` |
| **Python script** | Python (preferred) | `python3 scripts/ingest_l2_parquet_5year.py --download-dir ~/path` |
| **Low-level archive manager** | Fine-grained control | `python3 scripts/manage_l2_download_archives.py ...` |
| **Manual audit** | Schema inspection | `python3 scripts/inspect_l2_parquet_dataset.py --source data/raw/l2_nq` |

### 📁 Framework Components (Already in Place)
- **Orchestration**: `scripts/ingest_l2_parquet_5year.py` (new!)
- **Archive mgmt**: `backtest/l2_archive_inventory.py`
- **Parquet audit**: `backtest/l2_parquet_audit.py`
- **L2 utilities**: `backtest/l2_mbp.py`, `backtest/l2_book_validation.py`
- **Data structure**: `data/raw/l2_nq/zip_archives/` (auto-created)

---

## Quick Reference by Task

### I want the fastest path from "5 years of zips" to "organized & audited"

```bash
./ingest_l2.sh --download-dir ~/Downloads/l2_data
```

### I want to preview what will happen (dry-run)

```bash
./ingest_l2.sh --download-dir ~/Downloads/l2_data --no-move
```

### I want to skip the audit and just organize

```bash
./ingest_l2.sh --download-dir ~/Downloads/l2_data --no-audit
```

### I want my data going to a custom location

```bash
./ingest_l2.sh --download-dir ~/Downloads/l2_data \
               --archive-root /mnt/external/l2_archives
```

### I want to audit different years (e.g., 2020-2027)

```bash
./ingest_l2.sh --download-dir ~/Downloads/l2_data \
               --start-year 2020 \
               --end-year 2027
```

### I want more thorough audit (sample 20 files, 5000 rows each)

```bash
./ingest_l2.sh --download-dir ~/Downloads/l2_data \
               --audit-files 20 \
               --audit-rows 5000
```

---

## What Happens Step-by-Step

### Stage 1: Folder Creation
```
✓ Creates semester structure:
  data/raw/l2_nq/zip_archives/
    ├── 2021_H1/
    ├── 2021_H2/
    ├── 2022_H1/
    ├── 2022_H2/
    ├── ...
    └── 2026_H1/
```

### Stage 2: Archive Discovery (Dry-Run)
```
✓ Scans ~/Downloads/l2_data for *.zip files
✓ Inspects parquet file dates inside each zip
✓ Determines which semester each archive belongs to
✓ Shows you what would be moved (no actual move yet)
```

### Stage 3: User Confirmation
```
✓ Displays preview of all moves
✓ Asks: "Ready to move archives? (yes/no):"
✓ You decide – no automatic moves without permission
```

### Stage 4: Archive Organization
```
✓ Moves zips into their assigned semester folders
  E.g., 2021-Q1 data → 2021_H1/
        2021-Q3 data → 2021_H2/
```

### Stage 5: Parquet Audit
```
✓ Samples 10 parquet files (configurable)
✓ Inspects schema: columns, data types, null rates
✓ Checks data quality:
  - Timestamp parsing
  - Bid-ask spreads (outlier detection)
  - Top-of-book vs depth level consistency
✓ Generates audit reports
```

---

## Audit Reports

After ingestion, check these files:

```
results/research_master/l2_parquet_audit/
├── l2_parquet_audit_report.md          ← Main report (READ THIS)
├── l2_parquet_file_manifest.csv        ← File inventory
├── l2_parquet_sample_quality.csv       ← Per-file diagnostics
└── l2_parquet_schema_summary.json      ← Schema metadata
```

**What to look for in the report:**
- ✅ All expected columns present? (bid_px_00, ask_px_00, bid_sz_00, ask_sz_00, timestamp)
- ✅ Timestamp parsing successful? (ISO 8601, UTC, or Unix format detected)
- ✅ Row counts reasonable? (no massive gaps or corruptions)
- ✅ Bid-ask spreads normal? (< 2-3 points for NQ; outliers flagged)
- ⚠️ Any schema inconsistencies across files?
- ⚠️ Any null/NaN patterns concerning?

---

## After Ingestion: What's Next?

Your L2 data is now ready for:

### 1. **Microstructure Analysis**
```bash
python3 scripts/run_microstructure_diagnostics.py \
  --l2-data data/raw/l2_nq/zip_archives \
  --bars data/raw/glbx-mdp3-20100606-20260428.ohlcv-1m.csv \
  --out-dir results/research_master/l2_diagnostics
```

### 2. **L2-Powered Signal Development**
- Liquidity absorption signals
- Order book imbalance regimes
- See `backtest/liquidity_absorption_signal.py` for examples

### 3. **Execution Realism Validation**
```bash
python3 scripts/audit_execution_realism.py \
  --run-dir results/runs/<your_backtest_run> \
  --l2-data data/raw/l2_nq/zip_archives
```

### 4. **Live Trading Integration**
- Real-time L2 book state
- Market profile & depth analytics
- See `backtest/live_feeds.py` and `backtest/market_profile.py`

---

## Troubleshooting

### ❌ "No parquet files found"
**Cause**: Zips don't contain `.parquet` files, or files aren't discoverable.  
**Fix**: Ensure your zips contain `*.parquet` files. Extract one manually to verify structure.

### ❌ "Column not found: bid_px_00"
**Cause**: Your data uses different column names (e.g., `bid_price_1` vs `bid_px_00`).  
**Fix**: Check the audit report for detected columns. We can add custom column mapping if needed.

### ❌ "Timestamp parsing error"
**Cause**: Timestamps in unexpected format (Unix seconds, different timezone, etc.).  
**Fix**: Audit will flag the detected format. Let us know and we can add support.

### ❌ "Archive needs manual review before trusting..."
**Cause**: Archive date range is ambiguous or outside year range.  
**Fix**: Check the warning. You may need to manually review the zip contents or adjust --start-year/--end-year.

### ❌ "Duplicate parquet file names inside zip"
**Cause**: Multiple parquet files with same name in one zip (e.g., from multiple sources).  
**Fix**: Audit flags the count. May need to unzip and reorganize manually.

---

## Expected Data Format

The framework works best with parquet files containing:

```
Columns Expected (flexible names):
┌─ Timestamp (one of):
│  ts_event, ts_recv, timestamp, time, datetime, event_time, receive_time
│
├─ Symbol (one of):
│  symbol, raw_symbol, instrument_id, contract, ticker
│
├─ Top of Book (required):
│  bid_px_00 (or bid_price_00, bid_price_0, etc.)
│  ask_px_00 (or ask_price_00, ask_price_0, etc.)
│  bid_sz_00 (or bid_size_00, bid_size_0, etc.)
│  ask_sz_00 (or ask_size_00, ask_size_0, etc.)
│
└─ Depth Levels (optional):
   bid_px_01, bid_px_02, ... (N levels)
   ask_px_01, ask_px_02, ... (N levels)
```

If your columns differ significantly, the audit will detect it and we can add custom mapping.

---

## Directory Structure After Ingest

```
data/raw/l2_nq/
├── zip_archives/                    ← Your organized L2 data
│   ├── 2021_H1/
│   │   ├── archive1.zip             ← Your parquet zips
│   │   ├── archive2.zip
│   │   └── ...
│   ├── 2021_H2/
│   ├── 2022_H1/
│   ├── 2022_H2/
│   ├── ... (2023_H1, 2023_H2, ... 2026_H1)
│
└── manifests/
    └── l2_zip_archive_inventory.csv ← Manifest created during ingest
    
results/research_master/l2_parquet_audit/
├── l2_parquet_audit_report.md
├── l2_parquet_file_manifest.csv
├── l2_parquet_sample_quality.csv
└── l2_parquet_schema_summary.json
```

---

## Key Files & Modules

### Tools
| File | Purpose |
|------|---------|
| `scripts/ingest_l2_parquet_5year.py` | Main coordinator (Python) |
| `ingest_l2.sh` | Bash wrapper for the coordinator |
| `scripts/manage_l2_download_archives.py` | Low-level archive organization |
| `scripts/inspect_l2_parquet_dataset.py` | Schema audit tool |

### Framework
| Module | Purpose |
|--------|---------|
| `backtest/l2_archive_inventory.py` | Archive discovery & folder organization |
| `backtest/l2_parquet_audit.py` | Parquet schema inference & quality checks |
| `backtest/l2_mbp.py` | Databento MBP format support |
| `backtest/l2_book_validation.py` | Book structure validation |
| `backtest/microstructure_diagnostics.py` | Spread, depth, imbalance analytics |
| `backtest/liquidity_absorption_signal.py` | L2-powered signal logic |

### Documentation
| File | Purpose |
|------|---------|
| `L2_QUICK_REFERENCE.md` | 2-minute cheat sheet |
| `L2_DATA_INGESTION_GUIDE.md` | Detailed workflows & advanced options |
| `L2_PARQUET_READY.md` | This summary |

---

## Still Have Questions?

1. **Quick answers**: See `L2_QUICK_REFERENCE.md`
2. **Detailed workflows**: See `L2_DATA_INGESTION_GUIDE.md`
3. **Need help**: Check audit report in `results/research_master/l2_parquet_audit/`

---

## Ready?

### Option A: Bash (Simplest)
```bash
./ingest_l2.sh --download-dir ~/Downloads/l2_data
```

### Option B: Python (Full Control)
```bash
python3 scripts/ingest_l2_parquet_5year.py --download-dir ~/Downloads/l2_data
```

### Option C: Preview First (Safe)
```bash
./ingest_l2.sh --download-dir ~/Downloads/l2_data --no-move
```

**Go!** 🚀
