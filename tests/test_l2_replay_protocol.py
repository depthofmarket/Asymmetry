from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest
import zipfile

from backtest.l2_dataset_qa import build_l2_dataset_qa, write_l2_dataset_qa_artifacts
from backtest.l2_replay_protocol import (
    build_l2_replay_protocol_manifest,
    export_l2_replay_protocol_report,
    render_l2_replay_command,
    verify_l2_replay_protocol,
    write_l2_replay_protocol_manifest,
)


class L2ReplayProtocolTests(unittest.TestCase):
    def test_bounded_source_index_smoke_protocol_passes_and_renders_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path = _write_source_index(
                root,
                {"202401/20240102.csv": "20240102050000010000;1;0;100.00;1\n"},
                start_date="20240102",
                end_date="20240102",
            )
            manifest_path = root / "l2_replay_protocol.json"
            write_l2_replay_protocol_manifest(
                manifest_path,
                experiment_id="l2_smoke",
                objective="Validate a bounded indexed L2 replay request.",
                purpose="strategy_plumbing_smoke",
                source_index_path=str(index_path),
                trade_dates=["20240102"],
                strategy="noop",
                max_rows_per_source=1_000,
                out_dir="results/research_master/l2_orderflow_replay/smoke",
                prefix="smoke",
            )

            report = verify_l2_replay_protocol(manifest_path)

            self.assertTrue(report.passed, report.summary())
            self.assertIn("--source-index", report.command)
            self.assertIn("--trade-date 20240102", report.command)

    def test_missing_source_date_fails_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path = _write_source_index(
                root,
                {"202401/20240102.csv": "20240102050000010000;1;0;100.00;1\n"},
                start_date="20240102",
                end_date="20240102",
            )
            manifest_path = root / "l2_replay_protocol.json"
            write_l2_replay_protocol_manifest(
                manifest_path,
                experiment_id="missing_day",
                objective="Reject replay requests that do not resolve to source data.",
                purpose="strategy_plumbing_smoke",
                source_index_path=str(index_path),
                trade_dates=["20240103"],
                strategy="noop",
            )

            report = verify_l2_replay_protocol(manifest_path)

            self.assertFalse(report.passed)
            failed = {check.check for check in report.checks if check.status == "FAIL"}
            self.assertIn("requested_dates_resolve", failed)

    def test_duplicate_source_date_fails_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archives = root / "csv_archives" / "2025_1st_semester_Jan-Jun"
            archives.mkdir(parents=True)
            with zipfile.ZipFile(archives / "a.zip", "w") as zf:
                zf.writestr("202501/20250102.csv", "20250102050000010000;1;0;100.00;1\n")
            with zipfile.ZipFile(archives / "b.zip", "w") as zf:
                zf.writestr("202501/20250102.csv", "20250102050000020000;1;1;100.25;1\n")
            qa = build_l2_dataset_qa(archives.parent, start_date="20250102", end_date="20250102")
            index_path = write_l2_dataset_qa_artifacts(qa, root / "manifests")["source_index_csv"]
            manifest_path = root / "l2_replay_protocol.json"
            write_l2_replay_protocol_manifest(
                manifest_path,
                experiment_id="duplicate_day",
                objective="Reject ambiguous duplicate source dates.",
                purpose="strategy_plumbing_smoke",
                source_index_path=str(index_path),
                trade_dates=["20250102"],
                strategy="noop",
            )

            report = verify_l2_replay_protocol(manifest_path)

            self.assertFalse(report.passed)
            failed = {check.check for check in report.checks if check.status == "FAIL"}
            self.assertIn("requested_dates_resolve", failed)

    def test_protocol_rejects_lockbox_leakage_and_unfrozen_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path = _write_source_index(
                root,
                {"202401/20240102.csv": "20240102050000010000;1;0;100.00;1\n"},
                start_date="20240102",
                end_date="20240102",
            )
            manifest = build_l2_replay_protocol_manifest(
                experiment_id="leaky_lockbox",
                objective="Reject contaminated lockbox L2 replay requests.",
                purpose="strategy_lockbox_replay",
                source_index_path=str(index_path),
                trade_dates=["20240102"],
                strategy="my_strategy:factory",
                phase="lockbox",
                data_role="lockbox",
            )
            manifest["llm_visibility"]["evaluation_metrics_exposed_to_llm"] = True
            manifest["llm_visibility"]["visible_artifacts"] = ["lockbox_profit_factor.csv"]
            manifest_path = root / "l2_replay_protocol.json"
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            report = verify_l2_replay_protocol(manifest_path)

            self.assertFalse(report.passed)
            failed = {check.check for check in report.checks if check.status == "FAIL"}
            self.assertIn("lockbox_strategy_frozen", failed)
            self.assertIn("evaluation_metrics_hidden_from_llm", failed)
            self.assertIn("visible_artifacts_do_not_name_results", failed)

    def test_protocol_rejects_queue_model_without_queue_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path = _write_source_index(
                root,
                {"202401/20240102.csv": "20240102050000010000;1;0;100.00;1\n"},
                start_date="20240102",
                end_date="20240102",
            )
            manifest = build_l2_replay_protocol_manifest(
                experiment_id="queue_without_proof",
                objective="Reject optimistic queue fills until queue evidence exists.",
                purpose="fill_model_calibration",
                source_index_path=str(index_path),
                trade_dates=["20240102"],
                strategy="noop",
                limit_fill_model="queue",
            )
            manifest_path = root / "l2_replay_protocol.json"
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            report = verify_l2_replay_protocol(manifest_path)

            self.assertFalse(report.passed)
            failed = {check.check for check in report.checks if check.status == "FAIL"}
            self.assertIn("queue_model_requires_proof", failed)

    def test_command_context_mismatch_fails_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path = _write_source_index(
                root,
                {"202401/20240102.csv": "20240102050000010000;1;0;100.00;1\n"},
                start_date="20240102",
                end_date="20240102",
            )
            manifest_path = root / "l2_replay_protocol.json"
            write_l2_replay_protocol_manifest(
                manifest_path,
                experiment_id="context_mismatch",
                objective="Ensure the runner command matches the reviewed protocol.",
                purpose="strategy_plumbing_smoke",
                source_index_path=str(index_path),
                trade_dates=["20240102"],
                strategy="noop",
                max_rows_per_source=1_000,
                out_dir="results/research_master/l2_orderflow_replay/smoke",
                prefix="smoke",
            )

            report = verify_l2_replay_protocol(
                manifest_path,
                command_context={
                    "source_index_path": str(index_path),
                    "trade_dates": ["20240102"],
                    "max_rows_per_source": 50_000,
                    "strategy": "noop",
                    "limit_fill_model": "trade_through",
                    "out_dir": "results/research_master/l2_orderflow_replay/smoke",
                    "prefix": "smoke",
                },
            )

            self.assertFalse(report.passed)
            failed = {check.check for check in report.checks if check.status == "FAIL"}
            self.assertIn("max_rows_per_source", failed)

    def test_export_report_writes_csv_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path = _write_source_index(
                root,
                {"202401/20240102.csv": "20240102050000010000;1;0;100.00;1\n"},
                start_date="20240102",
                end_date="20240102",
            )
            manifest_path = root / "l2_replay_protocol.json"
            write_l2_replay_protocol_manifest(
                manifest_path,
                experiment_id="export_report",
                objective="Write protocol reports.",
                purpose="strategy_plumbing_smoke",
                source_index_path=str(index_path),
                trade_dates=["20240102"],
            )

            report = verify_l2_replay_protocol(manifest_path)
            paths = export_l2_replay_protocol_report(report, root / "out")

            self.assertTrue(paths.csv_path.exists())
            self.assertTrue(paths.markdown_path.exists())
            self.assertIn("L2 Replay Protocol Gate", paths.markdown_path.read_text(encoding="utf-8"))

    def test_render_command_uses_supplied_manifest_path(self) -> None:
        manifest = build_l2_replay_protocol_manifest(
            experiment_id="cmd",
            objective="Render command",
            purpose="strategy_plumbing_smoke",
            source_index_path="data/raw/l2_nq/manifests/l2_source_index.csv",
            trade_dates=["20240102"],
        )

        command = render_l2_replay_command(manifest, manifest_path="custom_manifest.json")

        self.assertIn("--protocol-manifest custom_manifest.json", command)


def _write_source_index(root: Path, members: dict[str, str], *, start_date: str, end_date: str) -> Path:
    archives = root / "csv_archives" / "2024_1st_semester_Jan-Jun"
    archives.mkdir(parents=True)
    with zipfile.ZipFile(archives / "sample.zip", "w") as zf:
        for member, text in members.items():
            zf.writestr(member, text)
    qa = build_l2_dataset_qa(archives.parent, start_date=start_date, end_date=end_date)
    return write_l2_dataset_qa_artifacts(qa, root / "manifests")["source_index_csv"]


if __name__ == "__main__":
    unittest.main()
