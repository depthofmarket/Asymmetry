# L2 Parquet Ingestion Quick Reference

**Received 5 years of level 2 parquet data? Use this quick reference.**

## One-Command Ingest (Recommended)

If your data is in zip files in `~/Downloads/l2_data` or similar:

```bash
cd /Users/novo/trading_strategy/nq-scalper-backtest
python3 scripts/ingest_l2_parquet_5year.py \
  --download-dir ~/Downloads/l2_data \
  --start-year 2021 \
  --end-year 2026
```

This will:
1. ✅ Create semester folder structure (2021_H1, 2021_H2, ..., 2026_H1)
2. ✅ Discover & inspect your zips to categorize by date
3. ⏸️ Ask for confirmation before moving
4. ✅ Move archives into their assigned folders
5. ✅ Audit parquet schema, row counts, & quality

That's it! No manual folder creation or multi-step commands needed.

## Dry-Run First (Safer)

To preview what will be moved without actually moving:

```bash
python3 scripts/ingest_l2_parquet_5year.py \
  --download-dir ~/Downloads/l2_data \
  --no-move
```

You'll see all archives that would be moved, their date ranges, and any warnings.

## Skip Audit (Faster, Not Recommended)

If you just want to organize and skip the schema audit:

```bash
python3 scripts/ingest_l2_parquet_5year.py \
  --download-dir ~/Downloads/l2_data \
  --no-audit
```

## Custom Parameters

```bash
python3 scripts/ingest_l2_parquet_5year.py \
  --download-dir ~/path/to/l2/zips \
  --archive-root data/raw/l2_nq/zip_archives \
  --start-year 2020 \
  --end-year 2027 \
  --audit-files 20 \
  --audit-rows 5000
```

Options:
- `--download-dir`: Where your zips are (default: `~/Downloads`)
- `--archive-root`: Where to organize into folders (default: `data/raw/l2_nq/zip_archives`)
- `--start-year`: Earliest year (default: `2021`)
- `--end-year`: Latest year (default: `2026`)
- `--audit-files`: How many parquet files to sample (default: `10`)
- `--audit-rows`: Rows per file to audit (default: `2000`)
- `--no-move`: Dry-run (inspect but don't move)
- `--no-audit`: Skip parquet audit phase

## What Happens After

Once ingestion completes:

1. **Check audit reports:**
   ```
   results/research_master/l2_parquet_audit/
     - l2_parquet_audit_report.md          ← Main report
     - l2_parquet_file_manifest.csv        ← File inventory
     - l2_parquet_sample_quality.csv       ← Per-file diagnostics
   ```

2. **Review for warnings:**
   - Missing columns?
   - Timestamp parsing issues?
   - Bid-ask spread outliers?
   - Schema inconsistencies across files?

3. **Your data is now ready for:**
   - Building microstructure features
   - Liquidity absorption signals
   - Execution realism validation
   - L2-triggered backtests

## Structured Data Location

```
data/raw/l2_nq/
├── zip_archives/
│   ├── 2021_H1/
│   │   ├── archive1.zip
│   │   ├── archive2.zip
│   │   └── ...
│   ├── 2021_H2/
│   ├── 2022_H1/
│   └── ... (up to 2026_H1)
└── manifests/
    └── l2_zip_archive_inventory.csv
```

## Troubleshooting

### "No parquet files found"
→ Check that files end in `.parquet` and zips are in the right directory.

### "Column not found: bid_px_00"
→ Your data uses different column names. Check `l2_parquet_audit_report.md` for detected columns, then we can add mapping.

### "Timestamp parsing error"
→ Audit will flag the format. Common: `ts_event`, `ts_recv`, `timestamp`. Check the report.

### Archives not moving?
→ Run with `--no-move` first to preview. Check for warnings (e.g., "needs manual review").

## Full Documentation

See `L2_DATA_INGESTION_GUIDE.md` in the repo root for detailed workflows and advanced options.

## Key Files

- **Coordinator script**: `scripts/ingest_l2_parquet_5year.py` (this one-shot tool)
- **Archive manager**: `scripts/manage_l2_download_archives.py` (low-level archive org)
- **Audit tool**: `scripts/inspect_l2_parquet_dataset.py` (schema & quality check)
- **Core modules**: 
  - `backtest/l2_archive_inventory.py` (archive discovery & org)
  - `backtest/l2_parquet_audit.py` (parquet inspection)

---

**Ready? Run this:**
```bash
python3 scripts/ingest_l2_parquet_5year.py --download-dir ~/Downloads/l2_data
```
