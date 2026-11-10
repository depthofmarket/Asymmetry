package com.motivewave.platform.study.custom;

/**
 * Behavioral checks for the rejected 10:00 window. No MotiveWave SDK required.
 */
public final class MacroTenAmOrderGateTest {
    private static int failures = 0;

    public static void main(String[] args) {
        boolean[] requested = {false, true};
        for (boolean persisted : requested) {
            expect(!MacroTenAmOrderGate.orderSubmissionPermitted(
                MacroTenAmOrderGate.WINDOW_TIER2_1000,
                MacroTenAmOrderGate.SIGNAL_BUY_10AM,
                MacroTenAmOrderGate.FLATTEN_LABEL_10AM,
                persisted
            ), "10:00 buy must not submit when persisted=" + persisted);

            expect(!MacroTenAmOrderGate.orderSubmissionPermitted(
                MacroTenAmOrderGate.WINDOW_TIER2_1000,
                MacroTenAmOrderGate.SIGNAL_SELL_10AM,
                null,
                persisted
            ), "10:00 sell must not submit when persisted=" + persisted);

            expect(!MacroTenAmOrderGate.orderSubmissionPermitted(
                MacroTenAmOrderGate.WINDOW_TIER1_0835,
                MacroTenAmOrderGate.SIGNAL_BUY_10AM,
                null,
                persisted
            ), "a 10:00 signal must not submit an 08:35 slot when persisted=" + persisted);

            expect(!MacroTenAmOrderGate.orderSubmissionPermitted(
                MacroTenAmOrderGate.WINDOW_TIER1_0835,
                MacroTenAmOrderGate.SIGNAL_BUY_0835,
                MacroTenAmOrderGate.FLATTEN_LABEL_10AM,
                persisted
            ), "rewriting the signal to 08:35 must not submit a 10:35 flatten trade");

            expect(MacroTenAmOrderGate.orderSubmissionPermitted(
                MacroTenAmOrderGate.WINDOW_TIER1_0835,
                MacroTenAmOrderGate.SIGNAL_BUY_0835,
                "09:25 CASH FLATTEN",
                persisted
            ), "08:35 buy must remain submittable when persisted=" + persisted);

            expect(MacroTenAmOrderGate.orderSubmissionPermitted(
                MacroTenAmOrderGate.WINDOW_TIER1_0835,
                MacroTenAmOrderGate.SIGNAL_SELL_0835,
                "09:25 CASH FLATTEN",
                persisted
            ), "08:35 sell must remain submittable when persisted=" + persisted);
        }

        if (failures > 0) {
            System.err.println(failures + " gate assertion(s) failed");
            System.exit(1);
        }
        System.out.println("MacroTenAmOrderGateTest passed");
    }

    private static void expect(boolean actual, String message) {
        if (!actual) {
            failures++;
            System.err.println("FAIL: " + message);
        }
    }
}
