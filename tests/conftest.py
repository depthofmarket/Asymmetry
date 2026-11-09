"""
Pytest configuration for test suite classification and portability (Requirement 7).

Categories:
1. Portable unit tests (default): run everywhere without private data or local environment dependencies.
2. Private data integration tests (marked with @pytest.mark.private_data): require private market datasets in data/raw or data/processed.
   - Default: skipped in environments without private data, with clear diagnostic message.
   - Opt-in: set RUN_PRIVATE_DATA_TESTS=1. When opted in, missing data will fail (not convert to false success).
3. Generated results tests (marked with @pytest.mark.generated_results): require artifacts in results/.
   - Default: skipped in environments where results/ is absent.
   - Opt-in: set RUN_GENERATED_RESULTS_TESTS=1.
4. Local account state tests (marked with @pytest.mark.local_account_state): require local demo ledgers.
   - Default: skipped in environments where results/forward_test/ is absent.
   - Opt-in: set RUN_LOCAL_ACCOUNT_TESTS=1.
5. macOS / LaunchAgent tests (marked with @pytest.mark.macos_env): require macOS.
"""

from __future__ import annotations

import os
import platform
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    run_private_data = os.environ.get("RUN_PRIVATE_DATA_TESTS", "0").lower() in ("1", "true", "yes")
    run_generated_results = os.environ.get("RUN_GENERATED_RESULTS_TESTS", "0").lower() in ("1", "true", "yes")
    run_local_account = os.environ.get("RUN_LOCAL_ACCOUNT_TESTS", "0").lower() in ("1", "true", "yes")

    has_results_db = (REPO_ROOT / "results" / "backtest_provenance.db").exists()
    has_account_ledger = (REPO_ROOT / "results" / "forward_test" / "demo_trades_ledger.csv").exists()
    is_macos = platform.system() == "Darwin"

    for item in items:
        # Category 2: Private Market Datasets
        if "private_data" in item.keywords and not run_private_data:
            item.add_marker(
                pytest.mark.skip(
                    reason="Requires private market datasets in data/ (opt in via RUN_PRIVATE_DATA_TESTS=1)"
                )
            )

        # Category 3: Generated Research Results
        if "generated_results" in item.keywords and not run_generated_results and not has_results_db:
            item.add_marker(
                pytest.mark.skip(
                    reason="Requires generated research artifacts in results/ (opt in via RUN_GENERATED_RESULTS_TESTS=1)"
                )
            )

        # Category 4: Local Account-State Files
        if "local_account_state" in item.keywords and not run_local_account and not has_account_ledger:
            item.add_marker(
                pytest.mark.skip(
                    reason="Requires local account-state ledger in results/forward_test/ (opt in via RUN_LOCAL_ACCOUNT_TESTS=1)"
                )
            )

        # Category 5: macOS Environment
        if "macos_env" in item.keywords and not is_macos:
            item.add_marker(
                pytest.mark.skip(
                    reason="Requires macOS operating system and MotiveWave environment"
                )
            )
