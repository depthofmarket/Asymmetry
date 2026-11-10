package com.motivewave.platform.study.custom;

/**
 * Fail-closed gate for the rejected 10:00 ET Tier-2 macro window (H45).
 *
 * This is not a user setting. A saved, default, or manually forced
 * {@code enable10amWindow=true} value cannot make {@link #orderSubmissionPermitted}
 * return true for that window or for its signal ids.
 */
public final class MacroTenAmOrderGate {
    public static final String WINDOW_TIER1_0835 = "TIER1_0835";
    public static final String WINDOW_TIER2_1000 = "TIER2_1000_REJECTED";

    public static final String SIGNAL_BUY_0835 = "LUCID_MACRO_BUY";
    public static final String SIGNAL_SELL_0835 = "LUCID_MACRO_SELL";
    public static final String SIGNAL_BUY_10AM = "LUCID_MACRO_BUY_10AM";
    public static final String SIGNAL_SELL_10AM = "LUCID_MACRO_SELL_10AM";

    public static final String FLATTEN_LABEL_10AM = "10:35 CASH FLATTEN";

    private MacroTenAmOrderGate() {
    }

    public static boolean isRejectedTenAmSignal(String signal) {
        if (signal == null || signal.isEmpty()) {
            return false;
        }
        return SIGNAL_BUY_10AM.equals(signal)
            || SIGNAL_SELL_10AM.equals(signal)
            || signal.contains("10AM")
            || signal.contains("10:35")
            || signal.contains("10:05");
    }

    public static boolean isRejectedTenAmWindow(String windowId, String flattenLabel) {
        if (WINDOW_TIER2_1000.equals(windowId)) {
            return true;
        }
        return FLATTEN_LABEL_10AM.equals(flattenLabel);
    }

    /**
     * @param persistedOrManualEnable the value stored in MotiveWave settings.
     *        It is accepted so callers must pass it, and it is ignored.
     */
    public static boolean orderSubmissionPermitted(
        String windowId,
        String signal,
        String flattenLabel,
        boolean persistedOrManualEnable
    ) {
        if (isRejectedTenAmWindow(windowId, flattenLabel) || isRejectedTenAmSignal(signal)) {
            return false;
        }
        return WINDOW_TIER1_0835.equals(windowId)
            || SIGNAL_BUY_0835.equals(signal)
            || SIGNAL_SELL_0835.equals(signal);
    }
}
