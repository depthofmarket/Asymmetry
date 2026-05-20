#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.live_feeds import CqgWebApiConfig, CqgWebApiSetupError


BASE_REQUIRED = ("CQG_USERNAME", "CQG_PASSWORD", "CQG_CONTRACT_SYMBOL")
ACCOUNT_REQUIRED = ("CQG_ACCOUNT_ID",)
OPTIONAL = (
    "CQG_SERVER_URL",
    "CQG_PRIVATE_LABEL",
    "CQG_CLIENT_APP_ID",
    "CQG_CLIENT_VERSION",
    "CQG_WEBAPI_SAMPLES_PATH",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate local CQG WebAPI environment variables.")
    parser.add_argument("--require-account", action="store_true", help="Also require CQG_ACCOUNT_ID.")
    parser.add_argument("--validate-samples", action="store_true", help="Check CQG WebAPIPythonSamples files.")
    return parser.parse_args()


def collect_env_status(*, require_account: bool) -> tuple[list[str], dict[str, str]]:
    required = list(BASE_REQUIRED)
    if require_account:
        required.extend(ACCOUNT_REQUIRED)
    missing = [name for name in required if not os.environ.get(name)]
    present = {
        name: _masked_value(name, os.environ.get(name, ""))
        for name in (*required, *OPTIONAL)
        if os.environ.get(name)
    }
    return missing, present


def main() -> int:
    args = parse_args()
    missing, present = collect_env_status(require_account=args.require_account)
    if present:
        print("CQG environment values found:")
        for name in sorted(present):
            print(f"  {name}={present[name]}")
    else:
        print("No CQG environment values found.")

    if missing:
        print("\nMissing required values:")
        for name in missing:
            print(f"  {name}")
        print("\nUse config/live_trading.example.env as the template.")
        return 1

    try:
        config = CqgWebApiConfig.from_env(require_account=args.require_account)
        if args.validate_samples:
            config.validate_python_samples()
    except CqgWebApiSetupError as exc:
        print(f"\nCQG setup problem: {exc}")
        return 1

    print("\nCQG environment check passed.")
    if not args.validate_samples:
        print("Run with --validate-samples after cloning CQG WebAPIPythonSamples.")
    return 0


def _masked_value(name: str, value: str) -> str:
    if name == "CQG_PASSWORD":
        return "***"
    if len(value) <= 4:
        return value
    return value[:2] + "***" + value[-2:]


if __name__ == "__main__":
    raise SystemExit(main())
