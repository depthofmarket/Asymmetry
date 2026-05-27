from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest

import pandas as pd

from backtest.research_protocol import (
    append_research_audit_event,
    export_research_protocol_report,
    fingerprint_file,
    verify_research_protocol,
    write_research_protocol_manifest,
)


class ResearchProtocolTests(unittest.TestCase):
    def test_manifest_passes_when_tbbo_is_execution_audit_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tbbo_path = root / "tbbo_minute_execution_stats.csv"
            tbbo_path.write_text("minute,median_spread_points\n2026-01-01 09:30:00,0.5\n", encoding="utf-8")
            manifest_path = root / "research_protocol.json"
            write_research_protocol_manifest(
                manifest_path,
                experiment_id="tbbo_execution_first",
                objective="Audit execution cost assumptions before candidate promotion.",
                hypothesis="TBBO spread and trade-vs-mid data should be used for execution realism, not alpha mining.",
                phase="hypothesis",
                data_sources=[
                    {
                        "name": "tbbo_minute_stats",
                        "path": tbbo_path,
                        "sample_role": "tbbo",
                        "purpose": "execution_audit",
                    }
                ],
            )

            report = verify_research_protocol(manifest_path)

            self.assertTrue(report.passed, report.summary())
            tbbo_rows = [
                check for check in report.checks if check.check == "tbbo_minute_stats:tbbo_execution_only"
            ]
            self.assertEqual(tbbo_rows[0].status, "PASS")

    def test_protocol_fails_when_tbbo_is_marked_as_alpha_mining(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tbbo_path = root / "tbbo.csv"
            tbbo_path.write_text("minute,median_spread_points\n2026-01-01 09:30:00,0.5\n", encoding="utf-8")
            manifest_path = root / "research_protocol.json"
            write_research_protocol_manifest(
                manifest_path,
                experiment_id="bad_tbbo_use",
                objective="Find a new filter from TBBO.",
                hypothesis="This intentionally bad protocol should fail because TBBO is treated as alpha mining.",
                data_sources=[
                    {
                        "name": "tbbo_filter_source",
                        "path": tbbo_path,
                        "sample_role": "tbbo",
                        "purpose": "alpha_mining",
                    }
                ],
            )

            report = verify_research_protocol(manifest_path)

            self.assertFalse(report.passed)
            failed = {check.check for check in report.checks if check.status == "FAIL"}
            self.assertIn("tbbo_filter_source:tbbo_execution_only", failed)

    def test_protocol_fails_when_llm_saw_evaluation_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "research_protocol.json"
            write_research_protocol_manifest(
                manifest_path,
                experiment_id="leaky_eval",
                objective="Demonstrate lockbox leakage checks.",
                hypothesis="The protocol should reject promotion when evaluation metrics were exposed to the LLM.",
                evaluation_metrics_exposed_to_llm=True,
                llm_visible_artifacts=["research/lockbox_profit_factor.csv"],
            )

            report = verify_research_protocol(manifest_path)

            self.assertFalse(report.passed)
            failed = {check.check for check in report.checks if check.status == "FAIL"}
            self.assertIn("evaluation_metrics_hidden_from_llm", failed)
            self.assertIn("visible_artifacts_do_not_include_evaluation_terms", failed)

    def test_run_artifact_gate_reads_saved_reports_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "results" / "runs" / "example_run"
            research = run_dir / "research"
            (research / "bar_exposure_audit").mkdir(parents=True)
            (research / "execution_realism").mkdir(parents=True)
            (research / "walkforward" / "prop_firm").mkdir(parents=True)
            pd.DataFrame([{"check": "anything", "status": "PASS"}]).to_csv(
                research / "development_report.csv", index=False
            )
            pd.DataFrame([{"check": "promotion_eligible", "status": "PASS"}]).to_csv(
                research / "research_discipline_gate.csv", index=False
            )
            pd.DataFrame([{"decision": "inconclusive_or_candidate_survives"}]).to_csv(
                research / "bar_exposure_audit" / "bar_exposure_audit_summary.csv", index=False
            )
            pd.DataFrame([{"scenario": "target_stop_like_slippage", "profit_factor": 1.1}]).to_csv(
                research / "execution_realism" / "execution_realism_summary.csv", index=False
            )
            pd.DataFrame([{"sample_scope": "walkforward_oos", "expected_net_payout_per_eval_attempt": 1.0}]).to_csv(
                research / "walkforward" / "prop_firm" / "walkforward_stitched_summary.csv", index=False
            )
            manifest_path = root / "research_protocol.json"
            write_research_protocol_manifest(
                manifest_path,
                experiment_id="saved_artifact_check",
                objective="Check saved artifacts without replaying strategy logic.",
                hypothesis="A saved run should only pass the protocol when required reports already exist.",
                audit_requirements={"require_tbbo_baseline_when_tbbo_used": False},
            )

            report = verify_research_protocol(manifest_path, run_dir=run_dir)
            out_paths = export_research_protocol_report(report, root / "research")

            self.assertTrue(report.passed, report.summary())
            self.assertTrue(out_paths.csv_path.exists())
            self.assertTrue(out_paths.markdown_path.exists())

    def test_fingerprint_and_audit_event_are_deterministic_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_path = root / "input.csv"
            data_path.write_text("a\n1\n", encoding="utf-8")

            fingerprint = fingerprint_file(data_path, mode="sha256")
            event = append_research_audit_event(
                root / "audit.jsonl",
                actor="test",
                event_type="unit",
                action="record",
                inputs={"path": data_path},
                outputs={"sha256": fingerprint["sha256"]},
            )

            self.assertEqual(
                fingerprint["sha256"],
                "309b0e45a73d3fc5325e2b6ed0a01ef8b9cde6b05a5633c1f893f970d52bfddc",
            )
            self.assertEqual(event["actor"], "test")
            rows = [json.loads(line) for line in (root / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(rows[0]["outputs"]["sha256"], fingerprint["sha256"])


if __name__ == "__main__":
    unittest.main()
