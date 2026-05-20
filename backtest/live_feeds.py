from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol
import os
import time

import pandas as pd

from backtest.live import LiveBar


class LiveBarFeed(Protocol):
    """Source of completed 1-minute bars for the live paper runtime."""

    def __iter__(self) -> Iterable[LiveBar]:
        ...


class CsvReplayFeed:
    """Replay historical bars through the live feed interface."""

    def __init__(
        self,
        data: pd.DataFrame,
        *,
        sleep_seconds: float = 0.0,
    ):
        self.data = data.copy()
        self.sleep_seconds = max(0.0, float(sleep_seconds))

    def __iter__(self) -> Iterable[LiveBar]:
        if self.data.empty:
            return
        data = self.data.copy()
        data["time"] = pd.to_datetime(data["time"])
        data = data.sort_values("time").reset_index(drop=True)
        for _, row in data.iterrows():
            if self.sleep_seconds > 0:
                time.sleep(self.sleep_seconds)
            yield LiveBar.from_record(row)


class FileTailBarFeed:
    """
    Poll a CSV file for appended completed bars.

    This is intentionally simple and platform-agnostic. Any bridge that can
    append rows with time/open/high/low/close/volume columns can feed the paper
    runtime before a broker-native API is ready.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        poll_seconds: float = 1.0,
        start_at_end: bool = True,
    ):
        self.path = Path(path)
        self.poll_seconds = max(0.1, float(poll_seconds))
        self.start_at_end = bool(start_at_end)
        self._last_emitted_time: pd.Timestamp | None = None
        if start_at_end and self.path.exists():
            existing = self._read_file()
            if not existing.empty:
                self._last_emitted_time = pd.to_datetime(existing["time"]).max()

    def poll_once(self) -> list[LiveBar]:
        if not self.path.exists():
            return []
        data = self._read_file()
        if data.empty:
            return []

        data["time"] = pd.to_datetime(data["time"])
        data = data.sort_values("time").drop_duplicates(subset="time", keep="last")
        if self._last_emitted_time is not None:
            data = data.loc[data["time"].gt(self._last_emitted_time)]
        if data.empty:
            return []

        bars = [LiveBar.from_record(row) for _, row in data.iterrows()]
        self._last_emitted_time = pd.Timestamp(bars[-1].time)
        return bars

    def __iter__(self) -> Iterable[LiveBar]:
        while True:
            for bar in self.poll_once():
                yield bar
            time.sleep(self.poll_seconds)

    def _read_file(self) -> pd.DataFrame:
        try:
            df = pd.read_csv(self.path)
        except pd.errors.EmptyDataError:
            return pd.DataFrame()
        required = {"time", "open", "high", "low", "close"}
        missing = required.difference(df.columns)
        if missing:
            raise ValueError(f"live bar file missing columns: {sorted(missing)}")
        if "volume" not in df.columns:
            df["volume"] = 0.0
        return df[["time", "open", "high", "low", "close", "volume"]].copy()


class CqgWebApiSetupError(RuntimeError):
    pass


@dataclass(frozen=True)
class CqgWebApiConfig:
    username: str
    password: str
    contract_symbol: str
    account_id: str = ""
    server_url: str = "wss://demoapi.cqg.com"
    client_app_id: str = "WebAPITest"
    client_version: str = "nq-scalper-paper/0.1"
    private_label: str = "WebAPITest"
    samples_path: Path | None = None

    @classmethod
    def from_env(cls, *, require_account: bool = False) -> "CqgWebApiConfig":
        missing = [
            name
            for name in ("CQG_USERNAME", "CQG_PASSWORD", "CQG_CONTRACT_SYMBOL")
            if not os.environ.get(name)
        ]
        if require_account and not os.environ.get("CQG_ACCOUNT_ID"):
            missing.append("CQG_ACCOUNT_ID")
        if missing:
            raise CqgWebApiSetupError(
                "Missing CQG environment variables: "
                + ", ".join(missing)
                + ". See config/live_trading.example.env."
            )

        samples_path = os.environ.get("CQG_WEBAPI_SAMPLES_PATH")
        return cls(
            username=str(os.environ["CQG_USERNAME"]),
            password=str(os.environ["CQG_PASSWORD"]),
            contract_symbol=str(os.environ["CQG_CONTRACT_SYMBOL"]),
            account_id=str(os.environ.get("CQG_ACCOUNT_ID", "")),
            server_url=str(os.environ.get("CQG_SERVER_URL", "wss://demoapi.cqg.com")),
            client_app_id=str(os.environ.get("CQG_CLIENT_APP_ID", "WebAPITest")),
            client_version=str(os.environ.get("CQG_CLIENT_VERSION", "nq-scalper-paper/0.1")),
            private_label=str(os.environ.get("CQG_PRIVATE_LABEL", "WebAPITest")),
            samples_path=Path(samples_path).expanduser() if samples_path else None,
        )

    def validate_python_samples(self) -> None:
        if self.samples_path is None:
            raise CqgWebApiSetupError(
                "CQG_WEBAPI_SAMPLES_PATH is not set. Clone CQG's WebAPIPythonSamples "
                "repo and point this variable at that folder."
            )
        required = [
            self.samples_path / "WebAPI" / "webapi_2_pb2.py",
            self.samples_path / "WebAPI" / "historical_2_pb2.py",
            self.samples_path / "WebAPI" / "webapi_client.py",
        ]
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise CqgWebApiSetupError(
                "CQG WebAPI Python sample files are missing: " + ", ".join(missing)
            )


class CqgWebApiFeed:
    """
    Placeholder for a CQG WebAPI time-bar subscription.

    CQG's public WebAPI uses generated protobuf modules and a WebSocket client
    from their sample package. We keep this object explicit so the runtime can
    fail with setup instructions until credentials, entitlements, and generated
    protocol modules are available locally.
    """

    def __init__(self, config: CqgWebApiConfig):
        self.config = config

    def check_ready(self) -> None:
        self.config.validate_python_samples()
        try:
            import websocket  # noqa: F401
            import google.protobuf  # noqa: F401
        except ModuleNotFoundError as exc:
            raise CqgWebApiSetupError(
                "Missing CQG WebAPI Python dependency. Install the dependencies "
                "used by CQG's WebAPIPythonSamples package first."
            ) from exc

    def __iter__(self) -> Iterable[LiveBar]:
        self.check_ready()
        raise CqgWebApiSetupError(
            "CQG WebAPI feed transport is scaffolded but not enabled yet. "
            "After AMP/CQG confirms WebAPI access, wire the TimeBarRequest "
            "subscription here using CQG's generated WebAPI modules."
        )
