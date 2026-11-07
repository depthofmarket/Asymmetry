"""
Quantitative Backtest Provenance & Anti-Hallucination System.

Implements the 5 Golden Rules of Quantitative Provenance:
1. One source of truth (SQLite store results/backtest_provenance.db + JSONL mirror).
2. No naked numbers (every stat travels with methodology, date range, data hash).
3. Provenance footers on every tool/script that prints stats.
4. Warnings travel with the number (sample size, gross vs net, outlier dominance).
5. Recording is automatic, not discipline (fail-safe engine hooks).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from config.strategy_registry import (
    StrategyTier,
    get_authorized_baseline_ids,
    get_strategy_tier,
    is_production_baseline,
    is_valid_strategy_id_format,
    register_candidate,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = REPO_ROOT / "results"
DB_PATH = RESULTS_DIR / "backtest_provenance.db"
JSONL_PATH = RESULTS_DIR / "backtest_provenance.jsonl"


@dataclass
class ProvenanceRecord:
    run_id: str
    timestamp: str  # ISO-8601 UTC
    strategy_id: str
    strategy_name: str
    methodology: str  # in_sample, out_of_sample, walk_forward, forward_demo, stress_test
    date_start: str   # YYYY-MM-DD
    date_end: str     # YYYY-MM-DD
    days_count: int
    data_path: str
    data_hash: str    # SHA-256
    git_commit: str
    slippage_model: str
    commission_model: str
    is_net: bool
    total_trades: int
    win_rate: float
    profit_factor: float
    gross_profit: float
    net_profit: float
    max_drawdown: float
    sharpe_ratio: float
    largest_win: float
    largest_win_pct_of_net: float
    strategy_tier: str = "BASELINE"
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    omega_ratio: float = 0.0
    cvar_95: float = 0.0
    ulcer_index: float = 0.0
    expectancy: float = 0.0
    sqn: float = 0.0
    kelly_fraction: float = 0.0
    half_kelly: float = 0.0
    tail_risk_ratio: float = 0.0
    recovery_factor: float = 0.0
    deflated_sharpe: float = 0.0
    bundle_path: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProvenanceStore:
    """ACID SQLite store with auto-updating JSONL audit mirror and SHA-256 caching."""

    def __init__(self, db_path: Path = DB_PATH, jsonl_path: Path = JSONL_PATH):
        self.db_path = Path(db_path)
        self.jsonl_path = Path(jsonl_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS data_files (
                    file_path TEXT PRIMARY KEY,
                    file_size INTEGER NOT NULL,
                    mtime_ns INTEGER NOT NULL,
                    sha256_hash TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS backtest_runs (
                    run_id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    strategy_name TEXT NOT NULL,
                    methodology TEXT NOT NULL,
                    date_start TEXT NOT NULL,
                    date_end TEXT NOT NULL,
                    days_count INTEGER NOT NULL,
                    data_path TEXT NOT NULL,
                    data_hash TEXT NOT NULL,
                    git_commit TEXT NOT NULL,
                    slippage_model TEXT NOT NULL,
                    commission_model TEXT NOT NULL,
                    is_net INTEGER NOT NULL,
                    total_trades INTEGER NOT NULL,
                    win_rate REAL NOT NULL,
                    profit_factor REAL NOT NULL,
                    gross_profit REAL NOT NULL,
                    net_profit REAL NOT NULL,
                    max_drawdown REAL NOT NULL,
                    sharpe_ratio REAL NOT NULL,
                    largest_win REAL NOT NULL,
                    largest_win_pct_of_net REAL NOT NULL,
                    strategy_tier TEXT DEFAULT 'BASELINE',
                    sortino_ratio REAL DEFAULT 0.0,
                    calmar_ratio REAL DEFAULT 0.0,
                    omega_ratio REAL DEFAULT 0.0,
                    cvar_95 REAL DEFAULT 0.0,
                    ulcer_index REAL DEFAULT 0.0,
                    expectancy REAL DEFAULT 0.0,
                    sqn REAL DEFAULT 0.0,
                    kelly_fraction REAL DEFAULT 0.0,
                    half_kelly REAL DEFAULT 0.0,
                    tail_risk_ratio REAL DEFAULT 0.0,
                    recovery_factor REAL DEFAULT 0.0,
                    deflated_sharpe REAL DEFAULT 0.0,
                    bundle_path TEXT DEFAULT '',
                    metrics_json TEXT DEFAULT '{}',
                    warnings_json TEXT NOT NULL,
                    params_json TEXT NOT NULL,
                    notes TEXT
                )
            """)
            # Migration check: Ensure new institutional metrics columns exist for backwards compatibility
            cur = conn.execute("PRAGMA table_info(backtest_runs)")
            existing_cols = {row["name"] for row in cur.fetchall()}
            migrations = {
                "strategy_tier": "TEXT DEFAULT 'BASELINE'",
                "sortino_ratio": "REAL DEFAULT 0.0",
                "calmar_ratio": "REAL DEFAULT 0.0",
                "omega_ratio": "REAL DEFAULT 0.0",
                "cvar_95": "REAL DEFAULT 0.0",
                "ulcer_index": "REAL DEFAULT 0.0",
                "expectancy": "REAL DEFAULT 0.0",
                "sqn": "REAL DEFAULT 0.0",
                "kelly_fraction": "REAL DEFAULT 0.0",
                "half_kelly": "REAL DEFAULT 0.0",
                "tail_risk_ratio": "REAL DEFAULT 0.0",
                "recovery_factor": "REAL DEFAULT 0.0",
                "deflated_sharpe": "REAL DEFAULT 0.0",
                "bundle_path": "TEXT DEFAULT ''",
                "metrics_json": "TEXT DEFAULT '{}'",
            }
            for col_name, col_def in migrations.items():
                if col_name not in existing_cols:
                    conn.execute(f"ALTER TABLE backtest_runs ADD COLUMN {col_name} {col_def}")
                    if col_name == "strategy_tier":
                        conn.execute(
                            "UPDATE backtest_runs SET strategy_tier = 'FORWARD_DEMO' WHERE strategy_id = 'lucid_flex_forward_demo'"
                        )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_strategy ON backtest_runs(strategy_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_strategy_tier ON backtest_runs(strategy_tier)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_timestamp ON backtest_runs(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_data_hash ON backtest_runs(data_hash)")
            conn.commit()

    def get_git_commit(self) -> str:
        """Retrieves current HEAD commit hash safely."""
        try:
            res = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                timeout=5.0,
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()[:10]
        except Exception:
            pass
        return "unknown_commit"

    def compute_data_hash(self, filepath: str | Path) -> str:
        """
        Computes cryptographic SHA-256 of data file.
        Uses cached mtime + size check for sub-millisecond lookups on untouched files.
        """
        p = Path(filepath)
        if not p.is_absolute():
            p = REPO_ROOT / p
        if not p.exists():
            return "file_not_found"

        stat = p.stat()
        file_size = stat.st_size
        mtime_ns = stat.st_mtime_ns
        rel_path = str(p.relative_to(REPO_ROOT)) if p.is_relative_to(REPO_ROOT) else str(p)

        # 1. Check cache
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT sha256_hash FROM data_files WHERE file_path = ? AND file_size = ? AND mtime_ns = ?",
                (rel_path, file_size, mtime_ns),
            ).fetchone()
            if row:
                return str(row["sha256_hash"])

        # 2. Compute full SHA-256
        sha256 = hashlib.sha256()
        with open(p, "rb") as f:
            while chunk := f.read(131072):  # 128 KB chunks
                sha256.update(chunk)
        digest = sha256.hexdigest()

        # 3. Store in cache
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO data_files (file_path, file_size, mtime_ns, sha256_hash, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(file_path) DO UPDATE SET
                    file_size = excluded.file_size,
                    mtime_ns = excluded.mtime_ns,
                    sha256_hash = excluded.sha256_hash,
                    updated_at = excluded.updated_at
                """,
                (rel_path, file_size, mtime_ns, digest, now_iso),
            )
            conn.commit()

        return digest

    @staticmethod
    def evaluate_warnings(
        total_trades: int,
        is_net: bool,
        slippage_model: str,
        commission_model: str,
        largest_win: float,
        net_profit: float,
        days_count: int,
    ) -> list[str]:
        """
        Rule 4: Standard Prop Quant Warning Pack:
        - Low sample size (N < 30)
        - Gross execution (zero slippage / zero commission)
        - Outlier dominance (>35% net profit from single largest win)
        - Short evaluation window (<60 days)
        """
        warnings = []
        if total_trades < 30:
            warnings.append(f"LOW_SAMPLE_SIZE: N={total_trades} trades (< 30 required for statistical power)")

        slip_lower = str(slippage_model or "").lower()
        comm_lower = str(commission_model or "").lower()
        if not is_net or "0" in slip_lower or "zero" in slip_lower or "none" in slip_lower or "none" in comm_lower:
            warnings.append("GROSS_EXECUTION: Reported without realistic slippage and/or commission deductions")

        if net_profit > 0 and largest_win > 0:
            win_pct = (largest_win / net_profit) * 100.0
            if win_pct > 35.0:
                warnings.append(f"OUTLIER_DOMINANCE: Top trade represents {win_pct:.1f}% of total net profit (> 35% threshold)")

        if days_count > 0 and days_count < 60:
            warnings.append(f"SHORT_EVALUATION_WINDOW: Span is only {days_count} calendar days (< 60 days required)")

        return warnings

    def record_run(
        self,
        strategy_id: str,
        strategy_name: str,
        methodology: str,
        date_start: str,
        date_end: str,
        data_path: str | Path,
        total_trades: int,
        win_rate: float,
        profit_factor: float,
        gross_profit: float,
        net_profit: float,
        max_drawdown: float,
        sharpe_ratio: float,
        largest_win: float,
        strategy_tier: Optional[StrategyTier | str] = None,
        slippage_model: str = "CQG Realized Parity",
        commission_model: str = "$0.70/micro side ($1.40 RT)",
        is_net: bool = True,
        days_count: int = 0,
        run_id: Optional[str] = None,
        git_commit: Optional[str] = None,
        params: Optional[dict[str, Any]] = None,
        notes: str = "",
        explicit_warnings: Optional[list[str]] = None,
        # Institutional Metrics
        sortino_ratio: float = 0.0,
        calmar_ratio: float = 0.0,
        omega_ratio: float = 0.0,
        cvar_95: float = 0.0,
        ulcer_index: float = 0.0,
        expectancy: float = 0.0,
        sqn: float = 0.0,
        kelly_fraction: float = 0.0,
        half_kelly: float = 0.0,
        tail_risk_ratio: float = 0.0,
        recovery_factor: float = 0.0,
        deflated_sharpe: float = 0.0,
        bundle_path: str = "",
        bundle: Optional[Any] = None,
        extended_metrics: Optional[dict[str, Any]] = None,
    ) -> ProvenanceRecord:
        """
        Fail-safe automatic backtest recording (Rule 5).
        Calculates cryptographic hash, flags warnings, validates strategy identity & tier,
        persists to SQLite and mirrors to JSONL.
        """
        if not strategy_id or not isinstance(strategy_id, str) or not is_valid_strategy_id_format(strategy_id):
            raise ValueError(f"Invalid strategy_id: '{strategy_id}'. Must be a non-empty alphanumeric slug.")

        clean_strat_id = strategy_id.strip()
        known_tier = get_strategy_tier(clean_strat_id)

        # Tier resolution & baseline protection
        if strategy_tier is not None:
            resolved_tier = StrategyTier.from_str(strategy_tier)
            if resolved_tier == StrategyTier.BASELINE and not is_production_baseline(clean_strat_id):
                raise ValueError(
                    f"Strategy '{clean_strat_id}' is not an authorized production baseline and cannot be "
                    f"recorded with tier 'BASELINE'. Authorized baselines: {get_authorized_baseline_ids()}."
                )
        else:
            if known_tier is not None:
                resolved_tier = known_tier
            else:
                # Unregistered strategies default to CANDIDATE tier to prevent baseline contamination
                resolved_tier = StrategyTier.CANDIDATE
                register_candidate(clean_strat_id, name=strategy_name)

        strategy_tier_str = resolved_tier.value

        now = datetime.now(timezone.utc)
        timestamp_str = now.isoformat()

        if not run_id:
            slug = clean_strat_id.lower().replace(" ", "_")
            run_id = f"run_{now.strftime('%Y%m%d_%H%M%S')}_{slug}"

        if not git_commit:
            git_commit = self.get_git_commit()

        data_hash = self.compute_data_hash(data_path)

        # Calculate days if not provided
        if days_count <= 0:
            try:
                d1 = datetime.strptime(str(date_start)[:10], "%Y-%m-%d")
                d2 = datetime.strptime(str(date_end)[:10], "%Y-%m-%d")
                days_count = max(1, (d2 - d1).days + 1)
            except Exception:
                days_count = 1

        largest_win_pct = (largest_win / net_profit * 100.0) if (net_profit > 0 and largest_win > 0) else 0.0

        auto_warnings = self.evaluate_warnings(
            total_trades=total_trades,
            is_net=is_net,
            slippage_model=slippage_model,
            commission_model=commission_model,
            largest_win=largest_win,
            net_profit=net_profit,
            days_count=days_count,
        )
        all_warnings = list(dict.fromkeys(auto_warnings + (explicit_warnings or [])))

        # Auto-populate institutional metrics from extended_metrics dict if provided
        ext = dict(extended_metrics or {})
        if sortino_ratio == 0.0 and "sortino_ratio" in ext:
            sortino_ratio = float(ext["sortino_ratio"])
        elif sortino_ratio == 0.0 and "sortino" in ext:
            sortino_ratio = float(ext["sortino"])

        if calmar_ratio == 0.0 and "calmar_ratio" in ext:
            calmar_ratio = float(ext["calmar_ratio"])
        elif calmar_ratio == 0.0 and "calmar" in ext:
            calmar_ratio = float(ext["calmar"])

        if omega_ratio == 0.0 and "omega_ratio" in ext:
            omega_ratio = float(ext["omega_ratio"])
        elif omega_ratio == 0.0 and "omega" in ext:
            omega_ratio = float(ext["omega"])

        if cvar_95 == 0.0 and "cvar_95" in ext:
            cvar_95 = float(ext["cvar_95"])
        elif cvar_95 == 0.0 and "cvar95" in ext:
            cvar_95 = float(ext["cvar95"])

        if ulcer_index == 0.0 and "ulcer_index" in ext:
            ulcer_index = float(ext["ulcer_index"])

        if expectancy == 0.0 and "expectancy" in ext:
            expectancy = float(ext["expectancy"])

        if sqn == 0.0 and "sqn" in ext:
            sqn = float(ext["sqn"])

        if kelly_fraction == 0.0 and "full_kelly_fraction" in ext:
            kelly_fraction = float(ext["full_kelly_fraction"])
        elif kelly_fraction == 0.0 and "kelly_fraction" in ext:
            kelly_fraction = float(ext["kelly_fraction"])

        if half_kelly == 0.0 and "half_kelly" in ext:
            half_kelly = float(ext["half_kelly"])

        if tail_risk_ratio == 0.0 and "tail_risk_ratio" in ext:
            tail_risk_ratio = float(ext["tail_risk_ratio"])

        if recovery_factor == 0.0 and "recovery_factor" in ext:
            recovery_factor = float(ext["recovery_factor"])

        if deflated_sharpe == 0.0 and "deflated_sharpe" in ext:
            deflated_sharpe = float(ext["deflated_sharpe"])
        elif deflated_sharpe == 0.0 and "dsr" in ext:
            deflated_sharpe = float(ext["dsr"])

        if bundle is not None and hasattr(bundle, "save"):
            saved_p = bundle.save()
            bundle_path = str(saved_p.relative_to(REPO_ROOT)) if saved_p.is_relative_to(REPO_ROOT) else str(saved_p)

        record = ProvenanceRecord(
            run_id=run_id,
            timestamp=timestamp_str,
            strategy_id=clean_strat_id,
            strategy_name=strategy_name,
            methodology=methodology,
            date_start=str(date_start)[:10],
            date_end=str(date_end)[:10],
            days_count=days_count,
            data_path=str(data_path),
            data_hash=data_hash,
            git_commit=git_commit,
            slippage_model=slippage_model,
            commission_model=commission_model,
            is_net=bool(is_net),
            total_trades=total_trades,
            win_rate=round(win_rate, 2),
            profit_factor=round(profit_factor, 2) if not math.isinf(profit_factor) else 999.0,
            gross_profit=round(gross_profit, 2),
            net_profit=round(net_profit, 2),
            max_drawdown=round(max_drawdown, 2),
            sharpe_ratio=round(sharpe_ratio, 2),
            largest_win=round(largest_win, 2),
            largest_win_pct_of_net=round(largest_win_pct, 1),
            strategy_tier=strategy_tier_str,
            sortino_ratio=round(sortino_ratio, 2),
            calmar_ratio=round(calmar_ratio, 2),
            omega_ratio=round(omega_ratio, 2),
            cvar_95=round(cvar_95, 2),
            ulcer_index=round(ulcer_index, 2),
            expectancy=round(expectancy, 2),
            sqn=round(sqn, 2),
            kelly_fraction=round(kelly_fraction, 4),
            half_kelly=round(half_kelly, 4),
            tail_risk_ratio=round(tail_risk_ratio, 2),
            recovery_factor=round(recovery_factor, 2),
            deflated_sharpe=round(deflated_sharpe, 4),
            bundle_path=str(bundle_path or ""),
            metrics=ext,
            warnings=all_warnings,
            params=params or {},
            notes=notes,
        )

        # Insert or replace in SQLite
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO backtest_runs (
                    run_id, timestamp, strategy_id, strategy_name, methodology,
                    date_start, date_end, days_count, data_path, data_hash, git_commit,
                    slippage_model, commission_model, is_net, total_trades, win_rate,
                    profit_factor, gross_profit, net_profit, max_drawdown, sharpe_ratio,
                    largest_win, largest_win_pct_of_net, strategy_tier,
                    sortino_ratio, calmar_ratio, omega_ratio, cvar_95, ulcer_index,
                    expectancy, sqn, kelly_fraction, half_kelly, tail_risk_ratio,
                    recovery_factor, deflated_sharpe, bundle_path, metrics_json,
                    warnings_json, params_json, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    timestamp = excluded.timestamp,
                    strategy_id = excluded.strategy_id,
                    strategy_name = excluded.strategy_name,
                    methodology = excluded.methodology,
                    date_start = excluded.date_start,
                    date_end = excluded.date_end,
                    days_count = excluded.days_count,
                    data_path = excluded.data_path,
                    data_hash = excluded.data_hash,
                    git_commit = excluded.git_commit,
                    slippage_model = excluded.slippage_model,
                    commission_model = excluded.commission_model,
                    is_net = excluded.is_net,
                    total_trades = excluded.total_trades,
                    win_rate = excluded.win_rate,
                    profit_factor = excluded.profit_factor,
                    gross_profit = excluded.gross_profit,
                    net_profit = excluded.net_profit,
                    max_drawdown = excluded.max_drawdown,
                    sharpe_ratio = excluded.sharpe_ratio,
                    largest_win = excluded.largest_win,
                    largest_win_pct_of_net = excluded.largest_win_pct_of_net,
                    strategy_tier = excluded.strategy_tier,
                    sortino_ratio = excluded.sortino_ratio,
                    calmar_ratio = excluded.calmar_ratio,
                    omega_ratio = excluded.omega_ratio,
                    cvar_95 = excluded.cvar_95,
                    ulcer_index = excluded.ulcer_index,
                    expectancy = excluded.expectancy,
                    sqn = excluded.sqn,
                    kelly_fraction = excluded.kelly_fraction,
                    half_kelly = excluded.half_kelly,
                    tail_risk_ratio = excluded.tail_risk_ratio,
                    recovery_factor = excluded.recovery_factor,
                    deflated_sharpe = excluded.deflated_sharpe,
                    bundle_path = excluded.bundle_path,
                    metrics_json = excluded.metrics_json,
                    warnings_json = excluded.warnings_json,
                    params_json = excluded.params_json,
                    notes = excluded.notes
                """,
                (
                    record.run_id,
                    record.timestamp,
                    record.strategy_id,
                    record.strategy_name,
                    record.methodology,
                    record.date_start,
                    record.date_end,
                    record.days_count,
                    record.data_path,
                    record.data_hash,
                    record.git_commit,
                    record.slippage_model,
                    record.commission_model,
                    1 if record.is_net else 0,
                    record.total_trades,
                    record.win_rate,
                    record.profit_factor,
                    record.gross_profit,
                    record.net_profit,
                    record.max_drawdown,
                    record.sharpe_ratio,
                    record.largest_win,
                    record.largest_win_pct_of_net,
                    record.strategy_tier,
                    record.sortino_ratio,
                    record.calmar_ratio,
                    record.omega_ratio,
                    record.cvar_95,
                    record.ulcer_index,
                    record.expectancy,
                    record.sqn,
                    record.kelly_fraction,
                    record.half_kelly,
                    record.tail_risk_ratio,
                    record.recovery_factor,
                    record.deflated_sharpe,
                    record.bundle_path,
                    json.dumps(record.metrics),
                    json.dumps(record.warnings),
                    json.dumps(record.params),
                    record.notes,
                ),
            )
            conn.commit()

        # Sync to JSONL mirror
        self._sync_jsonl_mirror()

        return record

    def _sync_jsonl_mirror(self) -> None:
        """Mirrors all records from SQLite into JSONL for git tracking."""
        runs = self.list_runs(include_candidates=True, limit=100000)
        runs_sorted = sorted(runs, key=lambda r: r.timestamp)
        with open(self.jsonl_path, "w", encoding="utf-8") as f:
            for r in runs_sorted:
                f.write(json.dumps(r.to_dict()) + "\n")

    def _row_to_record(self, row: sqlite3.Row) -> ProvenanceRecord:
        tier_val = "BASELINE"
        keys = row.keys()
        if "strategy_tier" in keys and row["strategy_tier"]:
            tier_val = row["strategy_tier"]
        else:
            known = get_strategy_tier(row["strategy_id"])
            if known:
                tier_val = known.value

        return ProvenanceRecord(
            run_id=row["run_id"],
            timestamp=row["timestamp"],
            strategy_id=row["strategy_id"],
            strategy_name=row["strategy_name"],
            methodology=row["methodology"],
            date_start=row["date_start"],
            date_end=row["date_end"],
            days_count=row["days_count"],
            data_path=row["data_path"],
            data_hash=row["data_hash"],
            git_commit=row["git_commit"],
            slippage_model=row["slippage_model"],
            commission_model=row["commission_model"],
            is_net=bool(row["is_net"]),
            total_trades=row["total_trades"],
            win_rate=row["win_rate"],
            profit_factor=row["profit_factor"],
            gross_profit=row["gross_profit"],
            net_profit=row["net_profit"],
            max_drawdown=row["max_drawdown"],
            sharpe_ratio=row["sharpe_ratio"],
            largest_win=row["largest_win"],
            largest_win_pct_of_net=row["largest_win_pct_of_net"],
            strategy_tier=tier_val,
            sortino_ratio=float(row["sortino_ratio"]) if ("sortino_ratio" in keys and row["sortino_ratio"] is not None) else 0.0,
            calmar_ratio=float(row["calmar_ratio"]) if ("calmar_ratio" in keys and row["calmar_ratio"] is not None) else 0.0,
            omega_ratio=float(row["omega_ratio"]) if ("omega_ratio" in keys and row["omega_ratio"] is not None) else 0.0,
            cvar_95=float(row["cvar_95"]) if ("cvar_95" in keys and row["cvar_95"] is not None) else 0.0,
            ulcer_index=float(row["ulcer_index"]) if ("ulcer_index" in keys and row["ulcer_index"] is not None) else 0.0,
            expectancy=float(row["expectancy"]) if ("expectancy" in keys and row["expectancy"] is not None) else 0.0,
            sqn=float(row["sqn"]) if ("sqn" in keys and row["sqn"] is not None) else 0.0,
            kelly_fraction=float(row["kelly_fraction"]) if ("kelly_fraction" in keys and row["kelly_fraction"] is not None) else 0.0,
            half_kelly=float(row["half_kelly"]) if ("half_kelly" in keys and row["half_kelly"] is not None) else 0.0,
            tail_risk_ratio=float(row["tail_risk_ratio"]) if ("tail_risk_ratio" in keys and row["tail_risk_ratio"] is not None) else 0.0,
            recovery_factor=float(row["recovery_factor"]) if ("recovery_factor" in keys and row["recovery_factor"] is not None) else 0.0,
            deflated_sharpe=float(row["deflated_sharpe"]) if ("deflated_sharpe" in keys and row["deflated_sharpe"] is not None) else 0.0,
            bundle_path=row["bundle_path"] if ("bundle_path" in keys and row["bundle_path"]) else "",
            metrics=json.loads(row["metrics_json"]) if ("metrics_json" in keys and row["metrics_json"]) else {},
            warnings=json.loads(row["warnings_json"]) if row["warnings_json"] else [],
            params=json.loads(row["params_json"]) if row["params_json"] else {},
            notes=row["notes"] or "",
        )

    def get_run(self, run_id: str) -> Optional[ProvenanceRecord]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM backtest_runs WHERE run_id = ?", (run_id,)).fetchone()
            if not row:
                return None
            rec = self._row_to_record(row)
            if getattr(rec, "strategy_tier", "") == "CANDIDATE" or getattr(rec, "strategy_tier", "") == StrategyTier.CANDIDATE.value:
                if "CANDIDATE_TIER_QUARANTINED" not in rec.warnings:
                    rec.warnings.append("CANDIDATE_TIER_QUARANTINED")
            return rec

    def get_latest_run(
        self,
        strategy_id: Optional[str] = None,
        include_candidates: bool = False,
    ) -> Optional[ProvenanceRecord]:
        with self._get_connection() as conn:
            if strategy_id:
                row = conn.execute(
                    "SELECT * FROM backtest_runs WHERE strategy_id = ? ORDER BY timestamp DESC LIMIT 1",
                    (strategy_id.strip(),),
                ).fetchone()
            else:
                if include_candidates:
                    row = conn.execute(
                        "SELECT * FROM backtest_runs ORDER BY timestamp DESC LIMIT 1"
                    ).fetchone()
                else:
                    row = conn.execute(
                        "SELECT * FROM backtest_runs WHERE strategy_tier IN ('BASELINE', 'FORWARD_DEMO') ORDER BY timestamp DESC LIMIT 1"
                    ).fetchone()

            if not row:
                return None
            rec = self._row_to_record(row)
            if getattr(rec, "strategy_tier", "") == "CANDIDATE" or getattr(rec, "strategy_tier", "") == StrategyTier.CANDIDATE.value:
                if "CANDIDATE_TIER_QUARANTINED" not in rec.warnings:
                    rec.warnings.append("CANDIDATE_TIER_QUARANTINED")
            return rec

    def list_runs(
        self,
        strategy_id: Optional[str] = None,
        tier: Optional[StrategyTier | str] = None,
        include_candidates: bool = False,
        limit: int = 50,
    ) -> list[ProvenanceRecord]:
        conditions = []
        params_list: list[Any] = []
        if strategy_id:
            conditions.append("strategy_id = ?")
            params_list.append(strategy_id.strip())

        if tier is not None:
            tier_str = str(tier.value if isinstance(tier, StrategyTier) else tier).strip().upper()
            if tier_str in ("ALL", "*"):
                # Explicit request for all tiers: do not filter by tier
                pass
            else:
                target_tier = StrategyTier.from_str(tier).value
                conditions.append("strategy_tier = ?")
                params_list.append(target_tier)
        elif not include_candidates:
            # Default quarantine: exclude CANDIDATE and REJECTED runs from production reports
            conditions.append("strategy_tier IN ('BASELINE', 'FORWARD_DEMO')")

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"SELECT * FROM backtest_runs {where_clause} ORDER BY timestamp DESC LIMIT ?"
        params_list.append(limit)

        with self._get_connection() as conn:
            rows = conn.execute(query, tuple(params_list)).fetchall()
            records = []
            for r in rows:
                rec = self._row_to_record(r)
                if (getattr(rec, "strategy_tier", "") == "CANDIDATE" or getattr(rec, "strategy_tier", "") == StrategyTier.CANDIDATE.value):
                    if "CANDIDATE_TIER_QUARANTINED" not in rec.warnings:
                        rec.warnings.append("CANDIDATE_TIER_QUARANTINED")
                records.append(rec)
            return records

    @staticmethod
    def format_footer(record: ProvenanceRecord) -> str:
        """Standardized Provenance Footer adhering to Rules 2, 3, and 4."""
        warn_str = "None (Clean Run)"
        if record.warnings:
            warn_str = "\n".join(f"  ⚠️  {w}" for w in record.warnings)

        net_tag = "NET (Includes slippage & comms)" if record.is_net else "GROSS (UNVERIFIED COSTS)"

        risk_str = ""
        if (
            record.sortino_ratio > 0
            or record.calmar_ratio > 0
            or record.cvar_95 > 0
            or record.ulcer_index > 0
            or record.half_kelly > 0
        ):
            risk_str = (
                f"\nRisk Metrics : Sortino: {record.sortino_ratio:.2f} | "
                f"Calmar: {record.calmar_ratio:.2f} | "
                f"Omega: {record.omega_ratio:.2f} | "
                f"CVaR95: ${record.cvar_95:,.2f} | "
                f"Ulcer: {record.ulcer_index:.2f}% | "
                f"Half-Kelly: {record.half_kelly:.3f}"
            )

        bundle_str = f"\nBundle (.obtf): {record.bundle_path}" if record.bundle_path else ""

        return f"""
────────────────────────────────────────────────────────────────────────────
PROVENANCE VERIFICATION FOOTER (Rule 2 & 3)
────────────────────────────────────────────────────────────────────────────
Run ID       : {record.run_id}
Strategy     : {record.strategy_id} — {record.strategy_name}
Strategy Tier: {record.strategy_tier}
Methodology  : {record.methodology.upper()}
Date Range   : {record.date_start} to {record.date_end} ({record.days_count} days)
Data File    : {record.data_path}
Data SHA-256 : {record.data_hash}
Git Commit   : {record.git_commit}{bundle_str}
Cost Model   : {record.slippage_model} | {record.commission_model} [{net_tag}]
Core Metrics : Trades: {record.total_trades} | Win%: {record.win_rate}% | PF: {record.profit_factor} | Net: ${record.net_profit:,.2f} | MaxDD: -${abs(record.max_drawdown):,.2f}{risk_str}
Warning Flags:
{warn_str}
────────────────────────────────────────────────────────────────────────────"""

    @classmethod
    def quote_stat(cls, record: ProvenanceRecord, stat_name: str) -> str:
        """
        Quotes a single stat with mandatory provenance context (Rule 2 + Rule 4).
        Searches record attributes, extended metrics, and standard aliases.
        """
        stat_lower = stat_name.lower().replace(" ", "_").strip()

        alias_map = {
            "sortino": "sortino_ratio",
            "calmar": "calmar_ratio",
            "omega": "omega_ratio",
            "cvar": "cvar_95",
            "cvar95": "cvar_95",
            "var95": "var_95_historical",
            "ulcer": "ulcer_index",
            "kelly": "kelly_fraction",
            "half_kelly": "half_kelly",
            "edge": "expectancy_score",
            "dsr": "deflated_sharpe",
            "psr": "probabilistic_sharpe_ratio",
            "sqn": "sqn",
            "tail_ratio": "tail_risk_ratio",
            "recovery": "recovery_factor",
            "winrate": "win_rate",
            "pf": "profit_factor",
            "net": "net_profit",
            "gross": "gross_profit",
            "dd": "max_drawdown",
            "maxdd": "max_drawdown",
            "sharpe": "sharpe_ratio",
        }

        lookup_keys = [stat_lower]
        if stat_lower in alias_map:
            lookup_keys.append(alias_map[stat_lower])

        val = None
        matched_key = stat_name
        for k in lookup_keys:
            if hasattr(record, k):
                attr_val = getattr(record, k)
                if attr_val is not None and not (isinstance(attr_val, (int, float)) and attr_val == 0.0 and k not in ("max_drawdown", "net_profit")):
                    val = attr_val
                    matched_key = k
                    break
            if hasattr(record, "metrics") and isinstance(record.metrics, dict) and k in record.metrics:
                val = record.metrics[k]
                matched_key = k
                break

        # Fallback if val is still None (e.g. 0.0 values)
        if val is None:
            for k in lookup_keys:
                if hasattr(record, k):
                    val = getattr(record, k)
                    matched_key = k
                    break
                if hasattr(record, "metrics") and isinstance(record.metrics, dict) and k in record.metrics:
                    val = record.metrics[k]
                    matched_key = k
                    break

        if val is None:
            return f"Error: Metric '{stat_name}' not tracked in provenance record {record.run_id}."

        warnings_block = ""
        if record.warnings:
            warnings_block = " ⚠️ [WARNINGS: " + " | ".join(record.warnings) + "]"

        formatted_val = f"{val:,.2f}" if isinstance(val, (int, float)) else str(val)

        return (
            f"**{record.strategy_name} {stat_name}**: {formatted_val}\n"
            f"(Methodology: {record.methodology} | Dates: {record.date_start} to {record.date_end} | "
            f"Data Hash: `{record.data_hash[:12]}...` | Cost: {'Net' if record.is_net else 'Gross'})"
            f"{warnings_block}\n"
            f"{cls.format_footer(record)}"
        )


# Global default instance for convenience
default_store = ProvenanceStore()
