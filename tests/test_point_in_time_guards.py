from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from backtest.auction_context import add_futures_auction_context
from backtest.point_in_time import assert_columns_blank_before_clock, mask_columns_before_clock
from main_backtest import select_continuous_outright_contract


class PointInTimeGuardTests(unittest.TestCase):
    def test_masks_completed_window_features_before_availability(self) -> None:
        df = pd.DataFrame(
            {
                "time": pd.to_datetime(["2024-01-02 09:55", "2024-01-02 10:00"]),
                "orb_high": [17010.0, 17020.0],
            }
        )

        out = mask_columns_before_clock(df, ["orb_high"], available_at="10:00")

        self.assertTrue(np.isnan(out.loc[0, "orb_high"]))
        self.assertEqual(out.loc[1, "orb_high"], 17020.0)
        assert_columns_blank_before_clock(out, ["orb_high"], available_at="10:00")

    def test_auction_context_hides_final_session_values_until_known(self) -> None:
        bars = pd.DataFrame(
            {
                "time": pd.to_datetime(
                    [
                        "2024-01-01 09:30",
                        "2024-01-01 15:55",
                        "2024-01-02 09:00",
                        "2024-01-02 09:30",
                        "2024-01-02 15:55",
                        "2024-01-02 16:00",
                    ]
                ),
                "open": [100, 105, 108, 110, 115, 116],
                "high": [106, 111, 109, 116, 120, 117],
                "low": [99, 104, 107, 109, 114, 115],
                "close": [105, 110, 108, 115, 119, 116],
                "volume": [10, 10, 10, 10, 10, 10],
                "atr": [2, 2, 2, 2, 2, 2],
            }
        )

        out = add_futures_auction_context(bars)

        pre_open = out.loc[out["time"].eq(pd.Timestamp("2024-01-02 09:00"))].iloc[0]
        rth_open = out.loc[out["time"].eq(pd.Timestamp("2024-01-02 09:30"))].iloc[0]
        after_close = out.loc[out["time"].eq(pd.Timestamp("2024-01-02 16:00"))].iloc[0]

        self.assertTrue(np.isnan(pre_open["gap_points"]))
        self.assertTrue(np.isnan(rth_open["rth_high"]))
        self.assertFalse(np.isnan(rth_open["gap_points"]))
        self.assertFalse(np.isnan(after_close["rth_high"]))

    def test_prior_session_volume_selection_avoids_current_session_winner(self) -> None:
        rows = []
        for time, h_vol, m_vol in [
            ("2024-01-02 09:30", 100, 1),
            ("2024-01-02 09:31", 100, 1),
            ("2024-01-03 09:30", 1, 100),
            ("2024-01-03 09:31", 1, 100),
        ]:
            rows.append({"time": time, "symbol": "NQH24", "open": 1, "high": 1, "low": 1, "close": 1, "volume": h_vol})
            rows.append({"time": time, "symbol": "NQM24", "open": 2, "high": 2, "low": 2, "close": 2, "volume": m_vol})
        data = pd.DataFrame(rows)
        data["time"] = pd.to_datetime(data["time"])

        selected = select_continuous_outright_contract(data, method="prior_session_volume")

        jan3 = selected[pd.to_datetime(selected["time"]).dt.normalize().eq(pd.Timestamp("2024-01-03"))]
        self.assertEqual(set(jan3["symbol"]), {"NQH24"})


if __name__ == "__main__":
    unittest.main()
