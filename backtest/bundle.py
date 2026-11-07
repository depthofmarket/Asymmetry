"""
Open Backtest Format (.obtf) Bundle Specification & Storage Engine.

Implements Tier 2 storage for quantitative backtests:
- Tier 1 (SQLite backtest_provenance.db): Fast metadata, indexing, and high-level metrics.
- Tier 2 (.obtf bundles in results/bundles/): Self-contained, portable, versioned compressed
  containers containing complete trade-by-trade logs, fill slippage, MFE/MAE excursions,
  tick/minute-level equity curves, and signal audit traces.

Container Architecture:
  <run_id>.obtf (ZIP_DEFLATED container)
    ├── manifest.json       (Run metadata, data SHA-256, git commit, full 92-metric snapshot)
    ├── trades.parquet      (Complete trade execution log with MFE, MAE, slippage, and exit reasons)
    ├── equity.parquet      (Session/tick equity curve, high-water mark, and drawdown series)
    └── audit_log.json      (Signal confluence scores, declarative veto traces, and runtime notes)
"""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

import numpy as np
import pandas as pd

from backtest import metrics as bm

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = REPO_ROOT / "results"
BUNDLES_DIR = RESULTS_DIR / "bundles"
OBTF_SPEC_VERSION = "1.0.0"


@dataclass
class BacktestBundle:
    """
    Self-contained portable backtest container.
    """
    manifest: dict[str, Any]
    trades: pd.DataFrame
    equity: pd.DataFrame
    audit_log: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        run_id: str,
        strategy_id: str,
        strategy_name: str,
        trades_df: pd.DataFrame,
        daily_series: pd.Series | np.ndarray | None = None,
        capital: float = 25000.0,
        methodology: str = "walk_forward",
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
        data_path: str = "",
        data_hash: str = "",
        git_commit: str = "",
        slippage_model: str = "CQG Realized Parity",
        commission_model: str = "$1.40 RT ($0.70/side micro)",
        is_net: bool = True,
        strategy_tier: str = "BASELINE",
        params: Optional[dict[str, Any]] = None,
        audit_log: Optional[list[dict[str, Any]]] = None,
        notes: str = "",
    ) -> BacktestBundle:
        """
        Creates a validated BacktestBundle from trade logs and equity curves,
        automatically calculating the full 92 institutional metrics snapshot.
        """
        # 1. Normalize Trades DataFrame
        df_t = trades_df.copy()
        if "trade_id" not in df_t.columns:
            df_t.insert(0, "trade_id", [f"T_{i:05d}" for i in range(1, len(df_t) + 1)])

        # Ensure numeric PnL
        pnl_col = "research_pnl" if "research_pnl" in df_t.columns else ("net_pnl" if "net_pnl" in df_t.columns else "pnl")
        pnl_arr = df_t[pnl_col].to_numpy(dtype=float) if pnl_col in df_t.columns else np.array([], dtype=float)

        # 2. Derive or normalize equity series
        if daily_series is not None:
            if isinstance(daily_series, pd.Series):
                r_arr = daily_series.to_numpy(dtype=float)
                d_idx = [str(d)[:10] for d in daily_series.index]
            else:
                r_arr = np.asarray(daily_series, dtype=float)
                d_idx = [f"D_{i:04d}" for i in range(len(r_arr))]
        else:
            r_arr = pnl_arr
            d_idx = [str(d)[:10] for d in df_t.get("date", range(len(pnl_arr)))]

        eq_curve = np.cumsum(r_arr)
        hwm = np.maximum.accumulate(np.maximum(eq_curve, 0.0))
        dd_dollars = hwm - eq_curve
        dd_pct = (dd_dollars / (capital + hwm)) * 100.0 if capital > 0 else np.zeros_like(dd_dollars)

        df_equity = pd.DataFrame({
            "session": d_idx,
            "daily_pnl": np.round(r_arr, 2),
            "equity": np.round(eq_curve, 2),
            "hwm": np.round(hwm, 2),
            "drawdown_dollars": np.round(dd_dollars, 2),
            "drawdown_pct": np.round(dd_pct, 2),
        })

        # 3. Compute Complete 92 Institutional Metrics
        calculated_metrics = bm.calculate_institutional_metrics(
            trades=pnl_arr,
            daily_returns=r_arr,
            capital=capital,
        )

        d_start = str(date_start or (df_t["date"].min() if "date" in df_t.columns and not df_t.empty else ""))
        d_end = str(date_end or (df_t["date"].max() if "date" in df_t.columns and not df_t.empty else ""))

        manifest = {
            "obtf_version": OBTF_SPEC_VERSION,
            "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "strategy_id": strategy_id,
            "strategy_name": strategy_name,
            "strategy_tier": strategy_tier,
            "methodology": methodology,
            "date_start": d_start[:10],
            "date_end": d_end[:10],
            "data_path": str(data_path),
            "data_hash": str(data_hash),
            "git_commit": str(git_commit),
            "capital": float(capital),
            "cost_model": {
                "slippage_model": slippage_model,
                "commission_model": commission_model,
                "is_net": bool(is_net),
            },
            "trade_count": int(len(df_t)),
            "sessions_count": int(len(df_equity)),
            "metrics": calculated_metrics,
            "params": params or {},
            "notes": str(notes),
        }

        return cls(
            manifest=manifest,
            trades=df_t,
            equity=df_equity,
            audit_log=audit_log or [],
        )

    def save(self, filepath: Optional[str | Path] = None) -> Path:
        """
        Saves the BacktestBundle to a single .obtf compressed zip container.
        """
        if filepath is None:
            BUNDLES_DIR.mkdir(parents=True, exist_ok=True)
            run_id = self.manifest.get("run_id", "unnamed_run")
            p = BUNDLES_DIR / f"{run_id}.obtf"
        else:
            p = Path(filepath)
            p.parent.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(str(p), mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            # 1. Manifest
            manifest_bytes = json.dumps(self.manifest, indent=2).encode("utf-8")
            zf.writestr("manifest.json", manifest_bytes)

            # 2. Trades Parquet
            trades_buf = io.BytesIO()
            self.trades.to_parquet(trades_buf, engine="pyarrow", compression="snappy", index=False)
            zf.writestr("trades.parquet", trades_buf.getvalue())

            # 3. Equity Parquet
            equity_buf = io.BytesIO()
            self.equity.to_parquet(equity_buf, engine="pyarrow", compression="snappy", index=False)
            zf.writestr("equity.parquet", equity_buf.getvalue())

            # 4. Audit Log
            audit_bytes = json.dumps(self.audit_log, indent=2).encode("utf-8")
            zf.writestr("audit_log.json", audit_bytes)

        return p

    @classmethod
    def read_manifest(cls, filepath: str | Path) -> dict[str, Any]:
        """
        Sub-millisecond manifest inspection without decoding parquet payloads.
        """
        p = Path(filepath)
        if not p.exists():
            raise FileNotFoundError(f"OBTF bundle not found at {p}")

        with zipfile.ZipFile(str(p), mode="r") as zf:
            with zf.open("manifest.json") as f:
                return json.loads(f.read().decode("utf-8"))

    @classmethod
    def load(cls, filepath: str | Path, load_payload: bool = True) -> BacktestBundle:
        """
        Loads an .obtf bundle from disk.
        """
        p = Path(filepath)
        if not p.exists():
            raise FileNotFoundError(f"OBTF bundle not found at {p}")

        with zipfile.ZipFile(str(p), mode="r") as zf:
            with zf.open("manifest.json") as f:
                manifest = json.loads(f.read().decode("utf-8"))

            if not load_payload:
                return cls(manifest=manifest, trades=pd.DataFrame(), equity=pd.DataFrame(), audit_log=[])

            # Trades
            with zf.open("trades.parquet") as f:
                trades_df = pd.read_parquet(io.BytesIO(f.read()), engine="pyarrow")

            # Equity
            with zf.open("equity.parquet") as f:
                equity_df = pd.read_parquet(io.BytesIO(f.read()), engine="pyarrow")

            # Audit log
            audit_log = []
            if "audit_log.json" in zf.namelist():
                with zf.open("audit_log.json") as f:
                    audit_log = json.loads(f.read().decode("utf-8"))

        return cls(manifest=manifest, trades=trades_df, equity=equity_df, audit_log=audit_log)

    def get_summary(self) -> dict[str, Any]:
        """
        Provides a structured executive summary of trade execution and risk dynamics.
        """
        m = self.manifest.get("metrics", {})
        cost = self.manifest.get("cost_model", {})

        return {
            "run_id": self.manifest.get("run_id"),
            "strategy_id": self.manifest.get("strategy_id"),
            "strategy_name": self.manifest.get("strategy_name"),
            "tier": self.manifest.get("strategy_tier"),
            "methodology": self.manifest.get("methodology"),
            "date_range": f"{self.manifest.get('date_start')} to {self.manifest.get('date_end')}",
            "trades_count": len(self.trades),
            "core_metrics": {
                "net_pnl": m.get("net_pnl", 0.0),
                "profit_factor": m.get("profit_factor", 0.0),
                "win_rate": m.get("win_rate", 0.0),
                "max_drawdown": m.get("max_drawdown", 0.0),
                "sharpe_ratio": m.get("sharpe_ratio", 0.0),
            },
            "institutional_risk": {
                "sortino_ratio": m.get("sortino_ratio", 0.0),
                "calmar_ratio": m.get("calmar_ratio", 0.0),
                "omega_ratio": m.get("omega_ratio", 0.0),
                "cvar_95": m.get("cvar_95", 0.0),
                "ulcer_index": m.get("ulcer_index", 0.0),
                "half_kelly": m.get("half_kelly", 0.0),
                "sqn": m.get("sqn", 0.0),
                "deflated_sharpe": m.get("deflated_sharpe", 0.0),
                "trimmed_profit_factor": m.get("trimmed_profit_factor", 0.0),
                "top_5_wins_pct": m.get("top_5_wins_pct", 0.0),
            },
            "cost_model": cost,
        }
