from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest

import pandas as pd

from backtest.research_protocol import (
    DEFAULT_BLOCKED_AGENT_COMMANDS,
    append_research_audit_event,
    export_research_protocol_report,
    fingerprint_file,
    verify_research_protocol,
    write_research_protocol_manifest,
)


EXECUTION_REALISM_EDGE_THESIS = {
    "edge_type": "execution_realism",
    "mechanism": (
        "Short-horizon NQ backtests can look profitable when target fills, spread, and adverse selection "
        "are understated; the research edge is avoiding false positives before strategy promotion."
    ),
    "counterparty": (
        "Liquidity providers, fast participants, and the bid-ask spread capture costs from impatient "
        "liquidity-taking orders and optimistic resting-limit assumptions."
    ),
    "persistence_reason": (
        "Spread, depth, queue priority, and adverse selection are structural microstructure costs that "
        "should persist across NQ scalping strategies."
    ),
    "falsification_tests": [
        "Reject promotion if saved trades only survive optimistic target-fill assumptions.",
        "Reject promotion if TBBO spread or trade-vs-mid evidence shows configured costs are too low.",
    ],
    "failure_modes": [
        "Execution audit is mistaken for directional alpha.",
        "A short TBBO sample is mined for signal filters instead of used as cost evidence.",
    ],
}


L2_MICROSTRUCTURE_EDGE_THESIS = {
    "edge_type": "microstructure_inefficiency",
    "mechanism": (
        "Short-horizon NQ continuation may be more reliable when completed-bar aggressive flow aligns "
        "with location acceptance and the L2 replay does not show immediate adverse selection."
    ),
    "counterparty": (
        "Urgent liquidity takers and passive liquidity providers who must reprice after book pressure "
        "create the short-term imbalance this research is trying to detect."
    ),
    "persistence_reason": (
        "Order-book pressure, liquidity-taking urgency, and location acceptance are recurring intraday "
        "microstructure mechanics, not one-off parameter settings."
    ),
    "falsification_tests": [
        "Reject if next-bar-open signal research fails after conservative cost stress.",
        "Reject if L2 replay erases the apparent edge through spread, latency, or adverse selection.",
    ],
    "failure_modes": [
        "Raw Databento side codes are misread as buyer or seller aggression without convention proof.",
        "L2 data is mined for filters instead of used as execution-realism evidence.",
    ],
}


class ResearchProtocolTests(unittest.TestCase):
    def test_manifest_records_custom_edge_thesis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "research_protocol.json"
            write_research_protocol_manifest(
                manifest_path,
                experiment_id="power_hour_mechanics",
                objective="Pre-register a directional signal thesis before any candidate exists.",
                hypothesis="Accepted late-session trend pressure may create continuation into the close.",
                edge_thesis={
                    "edge_type": "behavioral_bias",
                    "mechanism": (
                        "Late-session NQ continuation may come from risk reduction and benchmark/closing-flow "
                        "pressure after the market accepts a directional intraday repricing."
                    ),
                    "counterparty": (
                        "Late discretionary traders and hedgers who must reduce exposure near the close may pay "
                        "for immediacy in the accepted direction."
                    ),
                    "persistence_reason": (
                        "Closing-flow pressure, risk limits, and intraday anchoring behavior are recurring market "
                        "mechanics rather than a single historical parameter fit."
                    ),
                    "falsification_tests": [
                        "Reject if transition-era support fails after cost.",
                        "Reject if positive results only appear in one recent time slice.",
                    ],
                    "failure_modes": [
                        "The apparent edge may just be same-sample hour mining.",
                    ],
                },
            )

            report = verify_research_protocol(manifest_path)

            self.assertTrue(report.passed, report.summary())
            checks = {check.check: check.status for check in report.checks if check.section == "edge_thesis"}
            self.assertEqual(checks["edge_type"], "PASS")
            self.assertEqual(checks["falsification_tests"], "PASS")

    def test_protocol_fails_metric_only_edge_thesis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "research_protocol.json"
            write_research_protocol_manifest(
                manifest_path,
                experiment_id="metric_only_story",
                objective="Demonstrate that performance summaries are not an edge thesis.",
                hypothesis="This intentionally bad protocol should fail because the causal thesis is empty.",
                edge_thesis={
                    "edge_type": "structural_inefficiency",
                    "mechanism": "The backtest looks good and has high profit factor.",
                    "counterparty": "",
                    "persistence_reason": "The numbers look good historically.",
                    "falsification_tests": ["Reject if it loses."],
                    "failure_modes": [],
                },
            )

            report = verify_research_protocol(manifest_path)

            self.assertFalse(report.passed)
            failed = {check.check for check in report.checks if check.status == "FAIL"}
            self.assertIn("mechanism_not_metric_only", failed)
            self.assertIn("counterparty", failed)
            self.assertIn("falsification_tests", failed)
            self.assertIn("failure_modes", failed)

    def test_protocol_fails_without_edge_thesis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "research_protocol.json"
            write_research_protocol_manifest(
                manifest_path,
                experiment_id="missing_edge_thesis",
                objective="Demonstrate that a bare hypothesis is not enough.",
                hypothesis="A manifest should fail unless it explains why a real edge could exist.",
            )

            report = verify_research_protocol(manifest_path)

            self.assertFalse(report.passed)
            failed = {check.check for check in report.checks if check.status == "FAIL"}
            self.assertIn("edge_thesis_exists", failed)

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
                edge_thesis=EXECUTION_REALISM_EDGE_THESIS,
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
                edge_thesis=EXECUTION_REALISM_EDGE_THESIS,
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

    def test_manifest_passes_when_l2_is_execution_replay_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            l2_protocol_path = root / "l2_replay_protocol.json"
            l2_protocol_path.write_text('{"manifest_type":"l2_replay_protocol"}\n', encoding="utf-8")
            manifest_path = root / "research_protocol.json"
            write_research_protocol_manifest(
                manifest_path,
                experiment_id="l2_aggressive_flow_location",
                objective="Use L2 only to audit fills and adverse selection before candidate promotion.",
                hypothesis=(
                    "Aggressive-flow and location context may define a pre-candidate signal, while L2 "
                    "replay remains an execution-realism gate rather than alpha evidence."
                ),
                phase="hypothesis",
                edge_thesis=L2_MICROSTRUCTURE_EDGE_THESIS,
                data_sources=[
                    {
                        "name": "l2_replay_protocol",
                        "path": l2_protocol_path,
                        "sample_role": "l2_replay",
                        "purpose": "execution_replay_and_audit",
                    }
                ],
                audit_requirements={"l2_replay_protocol_path": l2_protocol_path},
            )

            report = verify_research_protocol(manifest_path)

            self.assertTrue(report.passed, report.summary())
            l2_rows = [
                check for check in report.checks if check.check == "l2_replay_protocol:l2_execution_realism_only"
            ]
            self.assertEqual(l2_rows[0].status, "PASS")
            protocol_rows = [
                check for check in report.checks if check.check == "l2_replay_protocol_manifest_exists"
            ]
            self.assertEqual(protocol_rows[0].status, "PASS")

    def test_protocol_fails_when_l2_is_marked_as_alpha_mining(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            l2_protocol_path = root / "l2_replay_protocol.json"
            l2_protocol_path.write_text('{"manifest_type":"l2_replay_protocol"}\n', encoding="utf-8")
            manifest_path = root / "research_protocol.json"
            write_research_protocol_manifest(
                manifest_path,
                experiment_id="bad_l2_use",
                objective="Find a new strategy filter directly from L2 depth data.",
                hypothesis="This intentionally bad protocol should fail because L2 is treated as alpha mining.",
                edge_thesis=L2_MICROSTRUCTURE_EDGE_THESIS,
                data_sources=[
                    {
                        "name": "l2_filter_source",
                        "path": l2_protocol_path,
                        "sample_role": "l2_replay",
                        "purpose": "alpha_mining",
                    }
                ],
                audit_requirements={"l2_replay_protocol_path": l2_protocol_path},
            )

            report = verify_research_protocol(manifest_path)

            self.assertFalse(report.passed)
            failed = {check.check for check in report.checks if check.status == "FAIL"}
            self.assertIn("l2_filter_source:l2_execution_realism_only", failed)

    def test_protocol_fails_when_llm_saw_evaluation_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "research_protocol.json"
            write_research_protocol_manifest(
                manifest_path,
                experiment_id="leaky_eval",
                objective="Demonstrate lockbox leakage checks.",
                hypothesis="The protocol should reject promotion when evaluation metrics were exposed to the LLM.",
                edge_thesis=EXECUTION_REALISM_EDGE_THESIS,
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
                edge_thesis=EXECUTION_REALISM_EDGE_THESIS,
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


    def test_protocol_fails_when_blocked_agent_commands_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "research_protocol.json"
            write_research_protocol_manifest(
                manifest_path,
                experiment_id="omitted_blocked_commands",
                objective="Verify that omitting blocked agent commands fails the hard gate.",
                hypothesis="Agent guardrails must fail hard when blocked commands are omitted from manifest.",
                edge_thesis=EXECUTION_REALISM_EDGE_THESIS,
                blocked_agent_commands=[],
            )

            report = verify_research_protocol(manifest_path)

            self.assertFalse(report.passed, "Report must fail when blocked commands are omitted")
            failed_checks = [c for c in report.checks if c.section == "agent_contract" and not c.passed]
            self.assertEqual(len(failed_checks), len(DEFAULT_BLOCKED_AGENT_COMMANDS))
            for check in failed_checks:
                self.assertEqual(check.severity, "hard")
                self.assertEqual(check.status, "FAIL")

    def test_protocol_validates_all_default_blocked_commands_as_hard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "research_protocol.json"
            write_research_protocol_manifest(
                manifest_path,
                experiment_id="default_blocked_commands",
                objective="Verify that all default blocked commands pass with hard severity.",
                hypothesis="Default research protocol manifest must include all blocked commands.",
                edge_thesis=EXECUTION_REALISM_EDGE_THESIS,
            )

            report = verify_research_protocol(manifest_path)

            self.assertTrue(report.passed, report.summary())
            blocked_checks = [c for c in report.checks if c.check.startswith("blocked_for_agent:")]
            self.assertEqual(len(blocked_checks), len(DEFAULT_BLOCKED_AGENT_COMMANDS))
            for check in blocked_checks:
                self.assertEqual(check.severity, "hard")
                self.assertEqual(check.status, "PASS")

    def test_protocol_fails_when_partial_blocked_commands_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "research_protocol.json"
            # Keep only 2 of the 5 blocked commands
            partial_commands = ["main_backtest.py", "scripts/probe_candidate_frequency.py"]
            write_research_protocol_manifest(
                manifest_path,
                experiment_id="partial_blocked_commands",
                objective="Verify that omitting any blocked script fails validation gate.",
                hypothesis="Omitting batch scripts must trigger a hard failure.",
                edge_thesis=EXECUTION_REALISM_EDGE_THESIS,
                blocked_agent_commands=partial_commands,
            )

            report = verify_research_protocol(manifest_path)

            self.assertFalse(report.passed, "Report must fail when batch scripts are omitted")
            failed_cmd_checks = [
                c.check for c in report.checks if c.check.startswith("blocked_for_agent:") and not c.passed
            ]
            self.assertIn("blocked_for_agent:scripts/run_edge_candidates_batch.sh", failed_cmd_checks)
            self.assertIn("blocked_for_agent:scripts/run_next_vp_candidates_batch.sh", failed_cmd_checks)
            self.assertIn("blocked_for_agent:scripts/run_2021_frequency_candidates_batch.sh", failed_cmd_checks)


if __name__ == "__main__":
    unittest.main()

