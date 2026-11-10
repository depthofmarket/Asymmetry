package com.motivewave.platform.study.custom;

import com.motivewave.platform.sdk.common.Coordinate;
import com.motivewave.platform.sdk.common.DataContext;
import com.motivewave.platform.sdk.common.DataSeries;
import com.motivewave.platform.sdk.common.Defaults;
import com.motivewave.platform.sdk.common.Enums$MarkerType;
import com.motivewave.platform.sdk.common.Enums$OrderAction;
import com.motivewave.platform.sdk.common.Enums$Position;
import com.motivewave.platform.sdk.common.Enums$Size;
import com.motivewave.platform.sdk.common.Enums$StrategyState;
import com.motivewave.platform.sdk.common.Enums$TIF;
import com.motivewave.platform.sdk.common.MarkerInfo;
import com.motivewave.platform.sdk.common.desc.BooleanDescriptor;
import com.motivewave.platform.sdk.common.desc.DoubleDescriptor;
import com.motivewave.platform.sdk.common.desc.IntegerDescriptor;
import com.motivewave.platform.sdk.common.desc.SettingGroup;
import com.motivewave.platform.sdk.common.desc.SettingTab;
import com.motivewave.platform.sdk.common.desc.SettingsDescriptor;
import com.motivewave.platform.sdk.draw.Line;
import com.motivewave.platform.sdk.draw.Marker;
import com.motivewave.platform.sdk.order_mgmt.Order;
import com.motivewave.platform.sdk.order_mgmt.OrderContext;
import com.motivewave.platform.sdk.study.RuntimeDescriptor;
import com.motivewave.platform.sdk.study.Study;
import com.motivewave.platform.sdk.study.StudyHeader;

import java.awt.Color;
import java.awt.Font;
import java.awt.Toolkit;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.time.Instant;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

@StudyHeader(
    namespace = "com.motivewave.platform.study.custom",
    id = "MACRO_MOMENTUM_ALGO_V1",
    name = "Lucid 25K — 2. Macro Momentum (08:35 ET)",
    desc = "08:35 ET Pre-Market Macro Release Momentum on NQ/MNQ (08:30 Spike vs 00:00-08:29 Overnight Range) with $250 Risk Budget, 09:25 Cash Flatten, Live CQG Bracket Execution, and Live Trade Tracker",
    menu = "Custom",
    overlay = true,
    signals = true,
    strategy = true,
    autoEntry = true,
    manualEntry = false,
    supportsEnterOnActivate = false,
    supportsUnrealizedPL = true,
    supportsRealizedPL = true,
    supportsTotalPL = true,
    showTradeOptions = true,
    supportsTradeLots = true,
    supportsPosition = true
)
public class LucidMacroMomentumStudy extends Study {
    private static final long FLATTEN_CANCEL_ACK_TIMEOUT_NANOS = 30_000_000_000L;
    private static final long FLATTEN_OPERATOR_ALERT_INTERVAL_NANOS = 300_000_000_000L;

    private static final Font LINE_FONT = new Font("SansSerif", Font.BOLD, 10);

    // Settings Keys
    private static final String ENABLE_LIVE_AUTOTRADE = "enableLiveAutoTrade";
    private static final String MIN_VOLUME_MULT = "minVolumeMult";
    private static final String MIN_LONG_CLOSE_LOC = "minLongCloseLoc";
    private static final String MAX_SHORT_CLOSE_LOC = "maxShortCloseLoc";
    private static final String REWARD_RISK_RATIO = "rewardRiskRatio";
    private static final String RISK_BUDGET_DOLLARS = "riskBudgetDollars";
    private static final String RATCHET_TIER_OVERRIDE = "ratchetTierOverride";
    private static final String MIN_STOP_POINTS = "minStopPoints";
    private static final String MAX_STOP_POINTS = "maxStopPoints";
    private static final String ALLOW_LONG = "allowLong";
    private static final String ALLOW_SHORT = "allowShort";
    private static final String ENABLE_SOUND_ALERT = "enableSoundAlert";
    private static final String SHOW_LEVEL_LINES = "showLevelLines";
    private static final String HIDE_LINES_WHEN_LIVE = "hideLinesWhenLive";
    private static final String SHOW_NO_SETUP_MARKER = "showNoSetupMarker";
    private static final String ENABLE_HIGH_VOL_GATE = "enableHighVolGate";
    private static final String MAX_OVN_RANGE_GATE_PTS = "maxOvnRangeGatePts";
    private static final String ENABLE_10AM_WINDOW = "enable10amWindow";

    private static final ZoneId NY_ZONE = ZoneId.of("America/New_York");

    // Signal Keys
    private static final String SIGNAL_BUY = "LUCID_MACRO_BUY";
    private static final String SIGNAL_SELL = "LUCID_MACRO_SELL";
    private static final String SIGNAL_BUY_10AM = "LUCID_MACRO_BUY_10AM";
    private static final String SIGNAL_SELL_10AM = "LUCID_MACRO_SELL_10AM";

    // Session State Tracking
    private final Map<LocalDate, OvernightStats> ovnByDate = new HashMap<>();
    private final Map<LocalDate, SpikeStats> spikeByDate = new HashMap<>();
    private final Map<LocalDate, RthPriorStats> rthByDate = new HashMap<>();
    private final Map<LocalDate, SpikeStats> spike10ByDate = new HashMap<>();
    private final Set<LocalDate> processedDays = new HashSet<>();
    private final Set<LocalDate> processed10amDays = new HashSet<>();
    private final Map<LocalDate, List<ActiveTrade>> tradesByDate = new HashMap<>();
    // IAF Session Cooldown Lock: strictly enforces <= 1 automated trade per session
    private static final Set<LocalDate> DAILY_SUBMITTED_DATES = java.util.concurrent.ConcurrentHashMap.newKeySet();
    private static final Set<LocalDate> RESTART_POSITION_REPORTED = java.util.concurrent.ConcurrentHashMap.newKeySet();

    private static class RthPriorStats {
        double high = Double.NEGATIVE_INFINITY;
        double low = Double.POSITIVE_INFINITY;
        long preRollVolume = 0;
        int preRollBars = 0;

        void addBar(int hour, int min, double h, double l, long vol) {
            high = Math.max(high, h);
            low = Math.min(low, l);
            if (hour == 9 && min >= 40 && min < 60) {
                preRollVolume += vol;
                preRollBars++;
            }
        }
    }

    private static class ActiveTrade {
        LocalDate date;
        boolean isLong;
        double entryPrice;
        double actualEntryFill = Double.NaN;
        double initialRiskDist = Double.NaN;
        double initialTargetDist = Double.NaN;
        double stopPrice;
        double targetPrice;
        long entryTime;
        long maxExitTime;
        int contracts;
        int attachedBracketQty = 0;
        String microSym;
        double ptVal;
        boolean closed = false;
        /** H45: 10:00 Tier-2 trades are never eligible for broker submission. */
        boolean rejectedTenAmWindow = false;
        boolean orderSubmitted = false;
        boolean entryFilled = false;
        boolean bracketsSubmitted = false;
        boolean bracketSetupAttempted = false;
        boolean flattenSubmitted = false;
        boolean flattenPending = false;
        boolean flattenCancelBlocked = false;
        boolean flattenCancelTimedOut = false;
        long flattenCancelPendingSinceNanos = 0L;
        long flattenOperatorAlertLastNanos = 0L;
        String flattenOperatorAlertKey = "";
        boolean restartCoverageReported = false;
        String flattenEvent = "";
        String flattenReason = "";
        Order entryOrder;
        Order slOrder;
        Order tpOrder;
        Order flattenOrder;
        Order flattenCancelPendingOrder;
        final ProtectiveReconcile.State reconcile = new ProtectiveReconcile.State();
        String entryOrderId;
        String slOrderId;
        String tpOrderId;
        String flattenOrderId;
        Line slLine;
        Line tpLine;
        Line entryLine;
        String flattenLabel = "09:25 CASH FLATTEN";
    }

    public static final String CANONICAL_STATE_FILENAME = "demo_parity_state.json";
    public static final String FORWARD_TEST_DIR_SETTING = "forwardTestDir";
    public static final String FORWARD_TEST_DIR_PROP = "asymmetry.forwardTestDir";
    public static final String FORWARD_TEST_DIR_ENV = "ASYMMETRY_FORWARD_TEST_DIR";
    public static final long DEFAULT_MAX_STATE_AGE_MS = 86_400_000L; // 24 hours

    private static double persistedPeakBalance = 25000.00;
    private static double persistedTrailingFloor = 24000.00;
    private static boolean persistedFloorLocked = false;
    private static String configuredForwardTestDir = null;
    private static String configuredStateFilePath = null;
    private static long maxStateAgeMs = DEFAULT_MAX_STATE_AGE_MS;
    private static String lastAccountStateError = "";

    public static double getPersistedPeakBalance() {
        return persistedPeakBalance;
    }

    public static double getPersistedTrailingFloor() {
        return persistedTrailingFloor;
    }

    public static boolean isPersistedFloorLocked() {
        return persistedFloorLocked;
    }

    public static void setPersistedRiskState(double peak, double floor) {
        persistedPeakBalance = peak;
        persistedTrailingFloor = floor;
        persistedFloorLocked = (peak >= 26100.00 || floor >= 25100.00);
    }

    public static void setConfiguredForwardTestDir(String dirPath) {
        configuredForwardTestDir = dirPath;
    }

    public static void setConfiguredStateFilePath(String filePath) {
        configuredStateFilePath = filePath;
    }

    public static void setMaxStateAgeMs(long maxAgeMs) {
        maxStateAgeMs = maxAgeMs > 0 ? maxAgeMs : DEFAULT_MAX_STATE_AGE_MS;
    }

    public static String getLastAccountStateError() {
        return lastAccountStateError;
    }

    public static class DaemonRiskState {
        public boolean verified = false;
        public String verificationError = "";
        public double balance = Double.NaN;
        public double peakBalance = Double.NaN;
        public double trailingFloor = Double.NaN;
        public double trailingCushion = Double.NaN;
        public double currentDatePnl = Double.NaN;
        public int recommendedMicros = 0;
        public boolean floorLocked = false;
        public boolean circuitBreakerHit = false;
        public boolean emergencyDelever = false;
        public boolean finishLineShield = false;
        public boolean garchDecileHalving = false;
        public String updatedAt = "";
    }

    public static File resolveCanonicalStateFile() {
        if (configuredStateFilePath != null && !configuredStateFilePath.trim().isEmpty()) {
            return new File(configuredStateFilePath.trim());
        }
        String dir = configuredForwardTestDir;
        if (dir == null || dir.trim().isEmpty()) {
            dir = System.getProperty(FORWARD_TEST_DIR_PROP);
        }
        if (dir == null || dir.trim().isEmpty()) {
            dir = System.getenv(FORWARD_TEST_DIR_ENV);
        }
        if (dir == null || dir.trim().isEmpty()) {
            dir = System.getenv("LUCIDFLEX_FORWARD_TEST_DIR");
        }
        if (dir != null && !dir.trim().isEmpty()) {
            File candidate = new File(dir.trim());
            if (candidate.getName().endsWith(".json")) {
                return candidate;
            }
            return new File(candidate, CANONICAL_STATE_FILENAME);
        }
        File relativeDir = new File("results/forward_test");
        if (relativeDir.exists() && relativeDir.isDirectory()) {
            return new File(relativeDir, CANONICAL_STATE_FILENAME);
        }
        String userHome = System.getProperty("user.home", ".");
        return Paths.get(userHome, "trading_strategy", "nq-scalper-backtest", "results", "forward_test", CANONICAL_STATE_FILENAME).toFile();
    }

    private static File getDailyLockFile(String strategyId, LocalDate today) {
        try {
            File stateFile = resolveCanonicalStateFile();
            File dir = (stateFile != null && stateFile.getParentFile() != null) ? stateFile.getParentFile() : new File("results/forward_test");
            if (!dir.exists()) dir.mkdirs();
            return new File(dir, "." + strategyId + "_" + today + ".lock");
        } catch (Exception e) {
            return new File("results/forward_test", "." + strategyId + "_" + today + ".lock");
        }
    }

    public static DaemonRiskState loadDaemonRiskState() {
        DaemonRiskState state = new DaemonRiskState();
        try {
            File stateFile = resolveCanonicalStateFile();
            if (stateFile == null) {
                state.verificationError = "NULL_STATE_FILE";
                lastAccountStateError = state.verificationError;
                return state;
            }
            if (!CANONICAL_STATE_FILENAME.equals(stateFile.getName())) {
                state.verificationError = "WRONG_FILENAME:" + stateFile.getName();
                lastAccountStateError = state.verificationError;
                return state;
            }
            if (!stateFile.exists() || !stateFile.isFile() || !stateFile.canRead()) {
                state.verificationError = "MISSING_STATE_FILE:" + stateFile.getPath();
                lastAccountStateError = state.verificationError;
                return state;
            }

            String raw = Files.readString(stateFile.toPath(), StandardCharsets.UTF_8).trim();
            if (!isValidJsonStructure(raw)) {
                state.verificationError = "MALFORMED_JSON";
                lastAccountStateError = state.verificationError;
                return state;
            }

            String[] requiredNumericKeys = new String[] {
                "balance",
                "peak_balance",
                "trailing_floor",
                "trailing_cushion",
                "current_date_pnl",
                "recommended_micros"
            };
            for (String reqKey : requiredNumericKeys) {
                if (!hasFiniteJsonNumber(raw, reqKey)) {
                    state.verificationError = "MISSING_OR_NON_FINITE_FIELD:" + reqKey;
                    lastAccountStateError = state.verificationError;
                    return state;
                }
            }

            String updatedAt = extractJsonString(raw, "updated_at");
            if (updatedAt == null || updatedAt.isEmpty()) {
                state.verificationError = "MISSING_TIMESTAMP:updated_at";
                lastAccountStateError = state.verificationError;
                return state;
            }
            long tsMillis = parseIsoTimestampMillis(updatedAt);
            if (tsMillis <= 0L) {
                state.verificationError = "INVALID_TIMESTAMP:" + updatedAt;
                lastAccountStateError = state.verificationError;
                return state;
            }
            long ageMs = System.currentTimeMillis() - tsMillis;
            if (ageMs > maxStateAgeMs) {
                state.verificationError = "STALE_ACCOUNT_STATE:ageMs=" + ageMs;
                lastAccountStateError = state.verificationError;
                return state;
            }
            if (ageMs < -300_000L) {
                state.verificationError = "FUTURE_TIMESTAMP_INVALID:ageMs=" + ageMs;
                lastAccountStateError = state.verificationError;
                return state;
            }

            state.balance = extractJsonDouble(raw, "balance", Double.NaN);
            state.peakBalance = extractJsonDouble(raw, "peak_balance", Double.NaN);
            state.trailingFloor = extractJsonDouble(raw, "trailing_floor", Double.NaN);
            state.trailingCushion = extractJsonDouble(raw, "trailing_cushion", Double.NaN);
            state.currentDatePnl = extractJsonDouble(raw, "current_date_pnl", Double.NaN);
            state.recommendedMicros = (int) Math.round(extractJsonDouble(raw, "recommended_micros", 0.0));
            state.updatedAt = updatedAt;

            if (state.balance <= 0.0 || state.peakBalance < 25000.0 || state.trailingFloor < 24000.0) {
                state.verificationError = "DOMAIN_INVARIANT_VIOLATION";
                lastAccountStateError = state.verificationError;
                return state;
            }
            if (state.peakBalance + 1e-6 < state.balance) {
                state.verificationError = "PEAK_BELOW_BALANCE";
                lastAccountStateError = state.verificationError;
                return state;
            }
            if (state.recommendedMicros < 0 || state.recommendedMicros > 10) {
                state.verificationError = "INVALID_RECOMMENDED_MICROS:" + state.recommendedMicros;
                lastAccountStateError = state.verificationError;
                return state;
            }

            boolean rawFloorLocked = extractJsonBoolean(raw, "floor_locked", false);
            state.floorLocked = rawFloorLocked
                || state.peakBalance >= 26100.00
                || state.trailingFloor >= 25100.00
                || persistedPeakBalance >= 26100.00
                || persistedTrailingFloor >= 25100.00
                || persistedFloorLocked;

            persistedPeakBalance = Math.max(persistedPeakBalance, Math.max(state.peakBalance, state.balance));
            if (state.floorLocked || persistedPeakBalance >= 26100.00) {
                persistedTrailingFloor = 25100.00;
                persistedFloorLocked = true;
                state.trailingFloor = 25100.00;
                state.floorLocked = true;
            } else {
                double calcFloor = Math.max(24000.00, persistedPeakBalance - 1000.00);
                persistedTrailingFloor = Math.max(persistedTrailingFloor, Math.max(state.trailingFloor, calcFloor));
                state.trailingFloor = persistedTrailingFloor;
            }
            state.peakBalance = persistedPeakBalance;
            state.trailingCushion = state.balance - state.trailingFloor;

            String statusStr = extractJsonString(raw, "status");
            if (statusStr == null || (!"ACTIVE".equalsIgnoreCase(statusStr)
                    && !"PASSED".equalsIgnoreCase(statusStr)
                    && !"DAILY_HALTED".equalsIgnoreCase(statusStr)
                    && !"TRAILED_OUT".equalsIgnoreCase(statusStr))) {
                state.verified = false;
                state.verificationError = "UNKNOWN_ACCOUNT_STATUS:" + statusStr;
                lastAccountStateError = state.verificationError;
                return state;
            }

            state.circuitBreakerHit = extractJsonBoolean(raw, "circuit_breaker_hit", false)
                || state.currentDatePnl <= -600.0
                || state.balance <= state.trailingFloor
                || "DAILY_HALTED".equalsIgnoreCase(statusStr)
                || "TRAILED_OUT".equalsIgnoreCase(statusStr)
                || "PASSED".equalsIgnoreCase(statusStr);
            if ("PASSED".equalsIgnoreCase(statusStr) || "DAILY_HALTED".equalsIgnoreCase(statusStr) || "TRAILED_OUT".equalsIgnoreCase(statusStr)) {
                state.recommendedMicros = 0;
            }
            state.emergencyDelever = extractJsonBoolean(raw, "emergency_delever", false)
                || extractJsonBoolean(raw, "defensive_delever", false)
                || state.trailingCushion < 400.0;
            state.finishLineShield = extractJsonBoolean(raw, "finish_line_shield", false)
                || (state.balance - 25000.0 >= 1150.0);
            state.garchDecileHalving = extractJsonBoolean(raw, "garch_decile_halving", false);

            if (state.trailingCushion < 400.0 || state.emergencyDelever || state.finishLineShield || state.garchDecileHalving) {
                state.recommendedMicros = Math.min(state.recommendedMicros > 0 ? state.recommendedMicros : 1, 1);
            }

            state.verified = true;
            state.verificationError = "";
            lastAccountStateError = "";
        } catch (Exception e) {
            state.verified = false;
            state.verificationError = "EXCEPTION:" + e.getMessage();
            lastAccountStateError = state.verificationError;
        }
        return state;
    }

    private static boolean isValidJsonStructure(String raw) {
        if (raw == null || raw.length() < 2) return false;
        if (!raw.startsWith("{") || !raw.endsWith("}")) return false;
        int depth = 0;
        boolean inQuotes = false;
        boolean escaped = false;
        for (int i = 0; i < raw.length(); i++) {
            char ch = raw.charAt(i);
            if (escaped) {
                escaped = false;
                continue;
            }
            if (ch == '\\' && inQuotes) {
                escaped = true;
                continue;
            }
            if (ch == '"') {
                inQuotes = !inQuotes;
                continue;
            }
            if (!inQuotes) {
                if (ch == '{') depth++;
                else if (ch == '}') {
                    depth--;
                    if (depth < 0) return false;
                }
            }
        }
        return !inQuotes && depth == 0;
    }

    private static boolean hasFiniteJsonNumber(String json, String key) {
        String token = "\"" + key + "\"";
        int idx = json.indexOf(token);
        if (idx < 0) return false;
        int colon = json.indexOf(":", idx + token.length());
        if (colon < 0) return false;
        int end = colon + 1;
        while (end < json.length() && Character.isWhitespace(json.charAt(end))) end++;
        if (end >= json.length()) return false;
        char first = json.charAt(end);
        if (first == '"' || first == 't' || first == 'f' || first == 'n') return false;
        int start = end;
        while (end < json.length() && (Character.isDigit(json.charAt(end))
                || json.charAt(end) == '.'
                || json.charAt(end) == '-'
                || json.charAt(end) == '+'
                || json.charAt(end) == 'e'
                || json.charAt(end) == 'E')) {
            end++;
        }
        if (end <= start) return false;
        String numToken = json.substring(start, end).trim();
        try {
            double val = Double.parseDouble(numToken);
            return Double.isFinite(val);
        } catch (Exception e) {
            return false;
        }
    }

    private static double extractJsonDouble(String json, String key, double fallback) {
        try {
            String token = "\"" + key + "\"";
            int idx = json.indexOf(token);
            if (idx < 0) return fallback;
            int colon = json.indexOf(":", idx + token.length());
            if (colon < 0) return fallback;
            int end = colon + 1;
            while (end < json.length() && Character.isWhitespace(json.charAt(end))) end++;
            int start = end;
            while (end < json.length() && (Character.isDigit(json.charAt(end))
                    || json.charAt(end) == '.'
                    || json.charAt(end) == '-'
                    || json.charAt(end) == '+'
                    || json.charAt(end) == 'e'
                    || json.charAt(end) == 'E')) {
                end++;
            }
            double val = Double.parseDouble(json.substring(start, end).trim());
            return Double.isFinite(val) ? val : fallback;
        } catch (Exception e) {
            return fallback;
        }
    }

    private static boolean extractJsonBoolean(String json, String key, boolean fallback) {
        try {
            String token = "\"" + key + "\"";
            int idx = json.indexOf(token);
            if (idx < 0) return fallback;
            int colon = json.indexOf(":", idx + token.length());
            if (colon < 0) return fallback;
            String sub = json.substring(colon + 1, Math.min(json.length(), colon + 15)).trim().toLowerCase();
            if (sub.startsWith("true")) return true;
            if (sub.startsWith("false")) return false;
            return fallback;
        } catch (Exception e) {
            return fallback;
        }
    }

    private static String extractJsonString(String json, String key) {
        String token = "\"" + key + "\"";
        int idx = json.indexOf(token);
        if (idx < 0) return null;
        int colon = json.indexOf(":", idx + token.length());
        if (colon < 0) return null;
        int q1 = json.indexOf('"', colon + 1);
        if (q1 < 0) return null;
        int q2 = json.indexOf('"', q1 + 1);
        if (q2 < 0) return null;
        return json.substring(q1 + 1, q2).trim();
    }

    private static long parseIsoTimestampMillis(String iso) {
        if (iso == null || iso.isEmpty()) return -1L;
        try {
            return Instant.parse(iso).toEpochMilli();
        } catch (Exception e1) {
            try {
                return OffsetDateTime.parse(iso).toInstant().toEpochMilli();
            } catch (Exception e2) {
                return -1L;
            }
        }
    }

    public static int resolveContracts(OrderContext ctx, int fallbackContracts) {
        if (ctx == null) return 0;
        try {
            double cash = ctx.getCashBalance();
            double real = ctx.getRealizedPnL();
            double unreal = ctx.getUnrealizedPnL();
            double balance = cash + real + unreal;
            if (!Double.isFinite(balance) || balance <= 10000.0) {
                return 0;
            }

            DaemonRiskState riskState = loadDaemonRiskState();
            if (riskState == null || !riskState.verified || riskState.circuitBreakerHit) {
                return 0;
            }
            if (riskState.recommendedMicros <= 0) {
                return 0;
            }
            persistedPeakBalance = Math.max(persistedPeakBalance, Math.max(riskState.peakBalance, balance));

            double floor = Math.max(24000.00, persistedPeakBalance - 1000.00);
            if (persistedPeakBalance >= 26100.00 || riskState.trailingFloor >= 25100.00) {
                floor = 25100.00;
            }
            persistedTrailingFloor = Math.max(persistedTrailingFloor, Math.max(riskState.trailingFloor, floor));

            if (balance <= persistedTrailingFloor) {
                return 0;
            }

            double profit = balance - 25000.00;
            double cushion = balance - persistedTrailingFloor;

            // Enforce daemon risk recommendation as hard upper bound and honor fallbackContracts
            int maxAllowed = riskState.recommendedMicros;
            if (fallbackContracts > 0) {
                maxAllowed = Math.min(maxAllowed, fallbackContracts);
            } else if (fallbackContracts <= 0) {
                return 0;
            }
            if (maxAllowed <= 0) {
                return 0;
            }

            // Honor de-leveraging flags, finish-line shield, and low cushion
            if (riskState.emergencyDelever || riskState.finishLineShield || riskState.garchDecileHalving) {
                maxAllowed = Math.min(maxAllowed, 1);
            }
            if (profit >= 1150.00) return 1;
            if (cushion < 400.00) return 1;

            return Math.min(maxAllowed, 10);
        } catch (Exception ignored) {
            return 0;
        }
    }

    private static class OvernightStats {
        double high = Double.NEGATIVE_INFINITY;
        double low = Double.POSITIVE_INFINITY;
        long preRollVolume = 0; // volume in 08:00 - 08:29 window
        int preRollBars = 0;

        void addBar(int hour, int min, double h, double l, long vol) {
            high = Math.max(high, h);
            low = Math.min(low, l);
            if (hour == 8 && min < 30) {
                preRollVolume += vol;
                preRollBars++;
            }
        }
    }

    private static class SpikeStats {
        double open = Double.NaN;
        double high = Double.NEGATIVE_INFINITY;
        double low = Double.POSITIVE_INFINITY;
        double close = Double.NaN;
        long volume = 0;
        boolean complete = false;

        void addBar(double o, double h, double l, double c, long vol) {
            if (Double.isNaN(open)) open = o;
            high = Double.isInfinite(high) ? h : Math.max(high, h);
            low = Double.isInfinite(low) ? l : Math.min(low, l);
            close = c;
            volume += vol;
            complete = true;
        }
    }

    @Override
    public void initialize(Defaults defaults) {
        SettingsDescriptor sd = createSD();
        SettingTab tab = sd.addTab("Lucid 25K Macro Momentum (08:35)");
        SettingGroup group = tab.addGroup("Breakout & Risk Management");

        group.addRow(new BooleanDescriptor(ENABLE_LIVE_AUTOTRADE, "Enable Live Auto-Trading (CQG Execution)", true));
        group.addRow(new DoubleDescriptor(MIN_VOLUME_MULT, "Min Volume Multiplier (vs Pre-5m Avg)", 2.50, 1.0, 10.0, 0.25));
        group.addRow(new DoubleDescriptor(MIN_LONG_CLOSE_LOC, "Min Long Close Location (0.65)", 0.65, 0.50, 0.95, 0.05));
        group.addRow(new DoubleDescriptor(MAX_SHORT_CLOSE_LOC, "Max Short Close Location (0.35)", 0.35, 0.05, 0.50, 0.05));
        group.addRow(new DoubleDescriptor(REWARD_RISK_RATIO, "Target Reward / Risk Ratio (1.50x)", 1.5, 0.5, 3.0, 0.1));
        group.addRow(new DoubleDescriptor(RISK_BUDGET_DOLLARS, "Risk Budget / Trade ($250 for Lucid 25K)", 250.0, 50.0, 500.0, 10.0));
        group.addRow(new IntegerDescriptor(RATCHET_TIER_OVERRIDE, "Ratchet Sizing Override (0=Auto-Sync Daemon State, 1/2/3/4 Micros)", 0, 0, 4, 1));
        group.addRow(new DoubleDescriptor(MIN_STOP_POINTS, "Min Stop Distance Points (NQ 20.0)", 20.0, 5.0, 50.0, 1.0));
        group.addRow(new DoubleDescriptor(MAX_STOP_POINTS, "Max Stop Distance Points (NQ 50.0)", 50.0, 20.0, 100.0, 1.0));
        group.addRow(new BooleanDescriptor(ALLOW_LONG, "Allow Macro Longs", true));
        group.addRow(new BooleanDescriptor(ALLOW_SHORT, "Allow Macro Shorts", true));
        group.addRow(new BooleanDescriptor(ENABLE_SOUND_ALERT, "Enable Sound Alert & Notification", true));
        group.addRow(new BooleanDescriptor(SHOW_LEVEL_LINES, "Show SL / TP / Entry / 09:25 Exit Lines", true));
        group.addRow(new BooleanDescriptor(HIDE_LINES_WHEN_LIVE, "Hide Custom Lines When Live Auto-Trade Active (Use Native Orders)", true));
        group.addRow(new BooleanDescriptor(SHOW_NO_SETUP_MARKER, "Show 'No Setup' Reason Marker at 08:35", false));
        group.addRow(new BooleanDescriptor(ENABLE_HIGH_VOL_GATE, "Enable High-Vol Regime Whipsaw Gate (H19 Option 1 Hard Gate)", false));
        group.addRow(new DoubleDescriptor(MAX_OVN_RANGE_GATE_PTS, "Max Overnight Range Cutoff Points (0=Off, NQ 180.0)", 180.0, 0.0, 400.0, 10.0));
        group.addRow(new BooleanDescriptor(
            ENABLE_10AM_WINDOW,
            "Rejected 10:00 Tier-2 window (H45). Saved or manual true cannot submit orders.",
            false));

        setSettingsDescriptor(sd);

        RuntimeDescriptor rd = createRD();
        rd.declareSignal(SIGNAL_BUY, "Macro Momentum Buy (08:35 ET)");
        rd.declareSignal(SIGNAL_SELL, "Macro Momentum Sell (08:35 ET)");
        rd.declareSignal(SIGNAL_BUY_10AM, "REJECTED 10:00 AM window — orders disabled");
        rd.declareSignal(SIGNAL_SELL_10AM, "REJECTED 10:00 AM window — orders disabled");
        ProtectiveReconcile.declare(rd);
        setRuntimeDescriptor(rd);
    }

    @Override
    protected void calculate(int index, DataContext ctx) {
        DataSeries series = ctx.getDataSeries();
        if (series == null || index < 0 || index >= series.size()) return;

        if (index == 0) {
            clearFigures();
            ovnByDate.clear();
            spikeByDate.clear();
            rthByDate.clear();
            spike10ByDate.clear();
            processedDays.clear();
            processed10amDays.clear();
            tradesByDate.clear();
        }

        long barStartTime = series.getStartTime(index);
        ZonedDateTime zdt = Instant.ofEpochMilli(barStartTime).atZone(NY_ZONE);
        int hour = zdt.getHour();
        int min = zdt.getMinute();
        LocalDate today = zdt.toLocalDate();

        double high = series.getHigh(index);
        double low = series.getLow(index);
        double open = series.getOpen(index);
        double close = series.getClose(index);
        long volume = series.getVolume(index);

        double tickSize = 0.25;
        if (series.getInstrument() != null) {
            tickSize = Math.max(0.01, series.getInstrument().getTickSize());
        }

        // 1. Overnight Range (00:00 - 08:29 ET)
        if (hour < 8 || (hour == 8 && min < 30)) {
            OvernightStats ovn = ovnByDate.computeIfAbsent(today, d -> new OvernightStats());
            ovn.addBar(hour, min, high, low, volume);
        }

        // 2. Release Spike Window (08:30 - 08:34 ET)
        if (hour == 8 && min >= 30 && min < 35) {
            SpikeStats spike = spikeByDate.computeIfAbsent(today, d -> new SpikeStats());
            spike.addBar(open, high, low, close, volume);
        }

        // 3. Prior RTH Baseline Window (09:30 - 09:59 ET)
        if (hour == 9 && min >= 30) {
            RthPriorStats rth = rthByDate.computeIfAbsent(today, d -> new RthPriorStats());
            rth.addBar(hour, min, high, low, volume);
        }

        // 4. 10:00 AM Release Spike Window (10:00 - 10:04 ET)
        if (hour == 10 && min < 5) {
            SpikeStats spike10 = spike10ByDate.computeIfAbsent(today, d -> new SpikeStats());
            spike10.addBar(open, high, low, close, volume);
        }

        // 3. Evaluate Signal on the first bar at or after 08:35:00 ET sharp
        if (hour == 8 && min >= 35 && !processedDays.contains(today)) {
            processedDays.add(today);

            OvernightStats ovn = ovnByDate.get(today);
            SpikeStats spike = spikeByDate.get(today);

            if (ovn != null && spike != null && spike.complete && !Double.isNaN(spike.open)) {
                double spikeRange = spike.high - spike.low;
                double pre5mVol = (ovn.preRollBars >= 10 && ovn.preRollVolume > 0)
                    ? (double) ovn.preRollVolume / ((double) ovn.preRollBars / 5.0)
                    : 1.0;
                double volMult = (double) spike.volume / Math.max(1.0, pre5mVol);

                double minVolMult = getSettings().getDouble(MIN_VOLUME_MULT, 2.50);
                double minLongLoc = getSettings().getDouble(MIN_LONG_CLOSE_LOC, 0.65);
                double maxShortLoc = getSettings().getDouble(MAX_SHORT_CLOSE_LOC, 0.35);
                double rrRatio = getSettings().getDouble(REWARD_RISK_RATIO, 1.5);
                double riskBudget = getSettings().getDouble(RISK_BUDGET_DOLLARS, 250.0);
                int ratchetOverride = getSettings().getInteger(RATCHET_TIER_OVERRIDE, 0);
                double minStopPts = getSettings().getDouble(MIN_STOP_POINTS, 20.0);
                double maxStopPts = getSettings().getDouble(MAX_STOP_POINTS, 50.0);
                boolean allowLong = getSettings().getBoolean(ALLOW_LONG, true);
                boolean allowShort = getSettings().getBoolean(ALLOW_SHORT, true);
                boolean soundAlert = getSettings().getBoolean(ENABLE_SOUND_ALERT, true);
                boolean showLines = getSettings().getBoolean(SHOW_LEVEL_LINES, true);
                boolean hideWhenLive = getSettings().getBoolean(HIDE_LINES_WHEN_LIVE, true);
                boolean isLive = getSettings().getBoolean(ENABLE_LIVE_AUTOTRADE, false);
                if (hideWhenLive && isLive) {
                    showLines = false;
                }
                boolean enableHighVolGate = getSettings().getBoolean(ENABLE_HIGH_VOL_GATE, true);
                double maxOvnRangePts = getSettings().getDouble(MAX_OVN_RANGE_GATE_PTS, 180.0);

                String sym = (series.getInstrument() != null) ? series.getInstrument().getSymbol().toUpperCase() : "NQ";
                boolean isES = sym.contains("ES") || sym.contains("MES");
                double ptVal = isES ? 5.00 : 2.00;
                String microSym = isES ? "MES" : "MNQ";

                if (spikeRange > 0.0) {
                    double spikeCloseLoc = (spike.close - spike.low) / spikeRange;
                    boolean isMacroSpike = volMult >= minVolMult;

                    boolean isLong = allowLong && isMacroSpike && (spike.close > ovn.high) && (spikeCloseLoc >= minLongLoc);
                    boolean isShort = allowShort && isMacroSpike && (spike.close < ovn.low) && (spikeCloseLoc <= maxShortLoc);

                    double ovnRange = ovn.high - ovn.low;
                    boolean isHighVolExhaustion = enableHighVolGate && (maxOvnRangePts > 0.0) && (ovnRange > maxOvnRangePts);

                    if ((isLong || isShort) && isHighVolExhaustion) {
                        if (getSettings().getBoolean(SHOW_NO_SETUP_MARKER, true)) {
                            Coordinate coord = new Coordinate(barStartTime, high + (tickSize * 4));
                            MarkerInfo info = new MarkerInfo(Enums$MarkerType.CIRCLE, Enums$Size.MEDIUM, new Color(220, 20, 60), Color.WHITE, Color.PINK, true);
                            Marker marker = new Marker(coord, Enums$Position.TOP, info);
                            marker.setTextValue(String.format("NO TRADE: High-Vol Regime Whipsaw Filter Active (Ovn Range %.1f > %.1f pts)", ovnRange, maxOvnRangePts));
                            addFigure(marker);
                        }
                    } else if (isLong || isShort) {
                        double stopPts = Math.min(maxStopPts, Math.max(minStopPts, spikeRange * 0.50));

                        // 1. Enforce Daily Loss Circuit Breaker (-$500 Soft Stop)
                        DaemonRiskState riskState = loadDaemonRiskState();
                        if (riskState.circuitBreakerHit) {
                            if (getSettings().getBoolean(SHOW_NO_SETUP_MARKER, true)) {
                                Coordinate coord = new Coordinate(barStartTime, high + (tickSize * 4));
                                MarkerInfo info = new MarkerInfo(Enums$MarkerType.CIRCLE, Enums$Size.MEDIUM, new Color(220, 20, 60), Color.WHITE, Color.PINK, true);
                                Marker marker = new Marker(coord, Enums$Position.TOP, info);
                                marker.setTextValue(String.format("NO TRADE: Daily Loss Circuit Breaker Active (Today: -$%.0f <= -$500)", Math.abs(riskState.currentDatePnl)));
                                addFigure(marker);
                            }
                            return;
                        }

                        // 2. Dynamic Contract Sizing with Cushion De-leveraging
                        int contracts = riskState.verified ? riskState.recommendedMicros : 2;
                        if (ratchetOverride >= 1 && ratchetOverride <= 4) {
                            contracts = ratchetOverride;
                        }

                        double entryPrice = open;
                        double stopPrice = isLong ? (entryPrice - stopPts) : (entryPrice + stopPts);
                        double targetPts = stopPts * rrRatio;
                        double targetPrice = isLong ? (entryPrice + targetPts) : (entryPrice - targetPts);
                        double actualRiskDollars = stopPts * ptVal * contracts;
                        double actualRewardDollars = targetPts * ptVal * contracts;

                        long entryTime = barStartTime;                 // 08:35:00 ET
                        long exitTime = entryTime + (50 * 60 * 1000L); // 09:25:00 ET (Cash Flatten)

                        ActiveTrade trade = new ActiveTrade();
                        trade.date = today;
                        trade.isLong = isLong;
                        trade.entryPrice = entryPrice;
                        trade.stopPrice = stopPrice;
                        trade.targetPrice = targetPrice;
                        trade.entryTime = entryTime;
                        trade.maxExitTime = exitTime;
                        trade.contracts = contracts;
                        trade.microSym = microSym;
                        trade.ptVal = ptVal;
                        trade.closed = false;

                        if (isLong) {
                            Coordinate coord = new Coordinate(entryTime, low - (stopPts * 0.10));
                            MarkerInfo info = new MarkerInfo(Enums$MarkerType.ARROW, Enums$Size.MEDIUM, new Color(0, 204, 102), new Color(0, 204, 102), true);
                            Marker marker = new Marker(coord, Enums$Position.BOTTOM, info);
                            marker.setTextValue(String.format("MACRO BUY %dx %s @ %.2f", contracts, microSym, entryPrice));
                            addFigure(marker);

                            if (showLines) {
                                Line slLine = new Line(entryTime, stopPrice, exitTime, stopPrice);
                                slLine.setColor(new Color(220, 20, 60));
                                slLine.setText(String.format("SL: %.2f (-$%.0f)", stopPrice, actualRiskDollars), LINE_FONT);
                                if (slLine.getText() != null) {
                                    slLine.getText().setShowBorder(false);
                                    slLine.getText().setBackground(null);
                                }
                                addFigure(slLine);
                                trade.slLine = slLine;

                                Line tpLine = new Line(entryTime, targetPrice, exitTime, targetPrice);
                                tpLine.setColor(new Color(0, 204, 102));
                                tpLine.setText(String.format("TP (1.5R): %.2f (+$%.0f)", targetPrice, actualRewardDollars), LINE_FONT);
                                if (tpLine.getText() != null) {
                                    tpLine.getText().setShowBorder(false);
                                    tpLine.getText().setBackground(null);
                                }
                                addFigure(tpLine);
                                trade.tpLine = tpLine;

                                Line entryLine = new Line(entryTime, entryPrice, exitTime, entryPrice);
                                entryLine.setColor(new Color(200, 200, 200, 180));
                                entryLine.setStroke(new java.awt.BasicStroke(1.0f, java.awt.BasicStroke.CAP_BUTT, java.awt.BasicStroke.JOIN_MITER, 10.0f, new float[]{4.0f, 4.0f}, 0.0f));
                                entryLine.setText(String.format("ENTRY: %.2f (%dx %s)", entryPrice, contracts, microSym), LINE_FONT);
                                if (entryLine.getText() != null) {
                                    entryLine.getText().setShowBorder(false);
                                    entryLine.getText().setBackground(null);
                                }
                                addFigure(entryLine);
                                trade.entryLine = entryLine;

                                Line exitLine = new Line(exitTime, stopPrice, exitTime, targetPrice);
                                exitLine.setColor(new Color(0, 206, 209, 180));
                                exitLine.setStroke(new java.awt.BasicStroke(1.0f, java.awt.BasicStroke.CAP_BUTT, java.awt.BasicStroke.JOIN_MITER, 10.0f, new float[]{3.0f, 3.0f}, 0.0f));
                                exitLine.setText("09:25 FLATTEN", LINE_FONT);
                                if (exitLine.getText() != null) {
                                    exitLine.getText().setShowBorder(false);
                                    exitLine.getText().setBackground(null);
                                }
                                addFigure(exitLine);
                            }

                            ctx.signal(index, SIGNAL_BUY, String.format("MACRO BUY %dx %s @ %.2f (SL: %.2f, TP: %.2f)", contracts, microSym, entryPrice, stopPrice, targetPrice), entryPrice);
                        } else {
                            Coordinate coord = new Coordinate(entryTime, high + (stopPts * 0.10));
                            MarkerInfo info = new MarkerInfo(Enums$MarkerType.ARROW, Enums$Size.MEDIUM, new Color(220, 20, 60), new Color(220, 20, 60), true);
                            Marker marker = new Marker(coord, Enums$Position.TOP, info);
                            marker.setTextValue(String.format("MACRO SELL %dx %s @ %.2f", contracts, microSym, entryPrice));
                            addFigure(marker);

                            if (showLines) {
                                Line slLine = new Line(entryTime, stopPrice, exitTime, stopPrice);
                                slLine.setColor(new Color(220, 20, 60));
                                slLine.setText(String.format("SL: %.2f (-$%.0f)", stopPrice, actualRiskDollars), LINE_FONT);
                                if (slLine.getText() != null) {
                                    slLine.getText().setShowBorder(false);
                                    slLine.getText().setBackground(null);
                                }
                                addFigure(slLine);
                                trade.slLine = slLine;

                                Line tpLine = new Line(entryTime, targetPrice, exitTime, targetPrice);
                                tpLine.setColor(new Color(0, 204, 102));
                                tpLine.setText(String.format("TP (1.5R): %.2f (+$%.0f)", targetPrice, actualRewardDollars), LINE_FONT);
                                if (tpLine.getText() != null) {
                                    tpLine.getText().setShowBorder(false);
                                    tpLine.getText().setBackground(null);
                                }
                                addFigure(tpLine);
                                trade.tpLine = tpLine;

                                Line entryLine = new Line(entryTime, entryPrice, exitTime, entryPrice);
                                entryLine.setColor(new Color(200, 200, 200, 180));
                                entryLine.setStroke(new java.awt.BasicStroke(1.0f, java.awt.BasicStroke.CAP_BUTT, java.awt.BasicStroke.JOIN_MITER, 10.0f, new float[]{4.0f, 4.0f}, 0.0f));
                                entryLine.setText(String.format("ENTRY: %.2f (%dx %s)", entryPrice, contracts, microSym), LINE_FONT);
                                if (entryLine.getText() != null) {
                                    entryLine.getText().setShowBorder(false);
                                    entryLine.getText().setBackground(null);
                                }
                                addFigure(entryLine);
                                trade.entryLine = entryLine;

                                Line exitLine = new Line(exitTime, targetPrice, exitTime, stopPrice);
                                exitLine.setColor(new Color(0, 206, 209, 180));
                                exitLine.setStroke(new java.awt.BasicStroke(1.0f, java.awt.BasicStroke.CAP_BUTT, java.awt.BasicStroke.JOIN_MITER, 10.0f, new float[]{3.0f, 3.0f}, 0.0f));
                                exitLine.setText("09:25 FLATTEN", LINE_FONT);
                                if (exitLine.getText() != null) {
                                    exitLine.getText().setShowBorder(false);
                                    exitLine.getText().setBackground(null);
                                }
                                addFigure(exitLine);
                            }

                            ctx.signal(index, SIGNAL_SELL, String.format("MACRO SELL %dx %s @ %.2f (SL: %.2f, TP: %.2f)", contracts, microSym, entryPrice, stopPrice, targetPrice), entryPrice);
                        }

                        tradesByDate.computeIfAbsent(today, d -> new ArrayList<>()).add(trade);

                        if (soundAlert) {
                            Toolkit.getDefaultToolkit().beep();
                        }
                    } else if (getSettings().getBoolean(SHOW_NO_SETUP_MARKER, true)) {
                        StringBuilder reason = new StringBuilder("NO MACRO TRADE: ");
                        if (!isMacroSpike) {
                            reason.append(String.format("Low Volume (%.1fx vs req >= %.1fx)", volMult, minVolMult));
                        } else if (spike.close <= ovn.high && spike.close >= ovn.low) {
                            reason.append(String.format("Inside Overnight Range [Low: %.2f | High: %.2f | Close: %.2f]", ovn.low, ovn.high, spike.close));
                        } else if (spike.close > ovn.high && spikeCloseLoc < minLongLoc) {
                            reason.append(String.format("Long Wick Reject (CloseLoc: %.2f vs req >= %.2f)", spikeCloseLoc, minLongLoc));
                        } else if (spike.close < ovn.low && spikeCloseLoc > maxShortLoc) {
                            reason.append(String.format("Short Wick Reject (CloseLoc: %.2f vs req <= %.2f)", spikeCloseLoc, maxShortLoc));
                        } else {
                            reason.append("Breakout acceptance criteria not met");
                        }

                        Coordinate coord = new Coordinate(barStartTime, high + (tickSize * 4));
                        MarkerInfo info = new MarkerInfo(Enums$MarkerType.CIRCLE, Enums$Size.MEDIUM, new Color(100, 100, 100), Color.WHITE, Color.LIGHT_GRAY, true);
                        Marker marker = new Marker(coord, Enums$Position.TOP, info);
                        marker.setTextValue(reason.toString());
                        addFigure(marker);
                    }
                }
            }
        }

        // 4. Rejected 10:00 Tier-2 window. The gate ignores the saved checkbox.
        // The body remains so a chart can still be inspected, but it is not entered
        // unless order submission is permitted, which the gate never allows.
        boolean tenAmPersistedRequest = getSettings().getBoolean(ENABLE_10AM_WINDOW, true);
        if (MacroTenAmOrderGate.orderSubmissionPermitted(
                MacroTenAmOrderGate.WINDOW_TIER2_1000,
                MacroTenAmOrderGate.SIGNAL_BUY_10AM,
                MacroTenAmOrderGate.FLATTEN_LABEL_10AM,
                tenAmPersistedRequest)
            && hour == 10 && min >= 5 && !processed10amDays.contains(today)) {
            processed10amDays.add(today);
            RthPriorStats rth = rthByDate.get(today);
            SpikeStats spike10 = spike10ByDate.get(today);

            if (rth != null && spike10 != null && spike10.complete && !Double.isNaN(spike10.open)) {
                double spikeRange = spike10.high - spike10.low;
                double pre5mVol = (rth.preRollBars >= 10 && rth.preRollVolume > 0)
                    ? (double) rth.preRollVolume / ((double) rth.preRollBars / 5.0)
                    : 1.0;
                double volMult = (double) spike10.volume / Math.max(1.0, pre5mVol);

                double minVolMult10 = 2.00; // Tier-1 Catalyst threshold
                double minLongLoc = getSettings().getDouble(MIN_LONG_CLOSE_LOC, 0.65);
                double maxShortLoc = getSettings().getDouble(MAX_SHORT_CLOSE_LOC, 0.35);
                double rrRatio = getSettings().getDouble(REWARD_RISK_RATIO, 1.5);
                int ratchetOverride = getSettings().getInteger(RATCHET_TIER_OVERRIDE, 0);
                double minStopPts = getSettings().getDouble(MIN_STOP_POINTS, 20.0);
                double maxStopPts = getSettings().getDouble(MAX_STOP_POINTS, 50.0);
                boolean allowLong = getSettings().getBoolean(ALLOW_LONG, true);
                boolean allowShort = getSettings().getBoolean(ALLOW_SHORT, true);
                boolean soundAlert = getSettings().getBoolean(ENABLE_SOUND_ALERT, true);
                boolean showLines = getSettings().getBoolean(SHOW_LEVEL_LINES, true);
                boolean hideWhenLive = getSettings().getBoolean(HIDE_LINES_WHEN_LIVE, true);
                boolean isLive = getSettings().getBoolean(ENABLE_LIVE_AUTOTRADE, false);
                if (hideWhenLive && isLive) {
                    showLines = false;
                }

                String sym = (series.getInstrument() != null) ? series.getInstrument().getSymbol().toUpperCase() : "NQ";
                boolean isES = sym.contains("ES") || sym.contains("MES");
                double ptVal = isES ? 5.00 : 2.00;
                String microSym = isES ? "MES" : "MNQ";

                if (spikeRange > 0.0) {
                    double spikeCloseLoc = (spike10.close - spike10.low) / spikeRange;
                    boolean isMacroSpike = volMult >= minVolMult10;

                    boolean isLong = allowLong && isMacroSpike && (spike10.close > rth.high) && (spikeCloseLoc >= minLongLoc);
                    boolean isShort = allowShort && isMacroSpike && (spike10.close < rth.low) && (spikeCloseLoc <= maxShortLoc);

                    if (isLong || isShort) {
                        double stopPts = Math.min(maxStopPts, Math.max(minStopPts, spikeRange * 0.50));

                        // 1. Enforce Daily Loss Circuit Breaker (-$500 Soft Stop)
                        DaemonRiskState riskState = loadDaemonRiskState();
                        if (riskState.circuitBreakerHit) {
                            if (getSettings().getBoolean(SHOW_NO_SETUP_MARKER, true)) {
                                Coordinate coord = new Coordinate(barStartTime, high + (tickSize * 4));
                                MarkerInfo info = new MarkerInfo(Enums$MarkerType.CIRCLE, Enums$Size.MEDIUM, new Color(220, 20, 60), Color.WHITE, Color.PINK, true);
                                Marker marker = new Marker(coord, Enums$Position.TOP, info);
                                marker.setTextValue(String.format("NO 10AM TRADE: Daily Loss Circuit Breaker Active (Today: -$%.0f <= -$500)", Math.abs(riskState.currentDatePnl)));
                                addFigure(marker);
                            }
                            return;
                        }

                        // 2. Dynamic Contract Sizing with Cushion De-leveraging
                        int contracts = riskState.verified ? riskState.recommendedMicros : 2;
                        if (ratchetOverride >= 1 && ratchetOverride <= 4) {
                            contracts = ratchetOverride;
                        }

                        double entryPrice = open;
                        double stopPrice = isLong ? (entryPrice - stopPts) : (entryPrice + stopPts);
                        double targetPts = stopPts * rrRatio;
                        double targetPrice = isLong ? (entryPrice + targetPts) : (entryPrice - targetPts);
                        double actualRiskDollars = stopPts * ptVal * contracts;
                        double actualRewardDollars = targetPts * ptVal * contracts;

                        long entryTime = barStartTime;                 // 10:05:00 ET
                        long exitTime = entryTime + (30 * 60 * 1000L); // 10:35:00 ET (Cash Flatten)

                        ActiveTrade trade = new ActiveTrade();
                        trade.date = today;
                        trade.isLong = isLong;
                        trade.entryPrice = entryPrice;
                        trade.stopPrice = stopPrice;
                        trade.targetPrice = targetPrice;
                        trade.entryTime = entryTime;
                        trade.maxExitTime = exitTime;
                        trade.contracts = contracts;
                        trade.microSym = microSym;
                        trade.ptVal = ptVal;
                        trade.closed = false;
                        trade.rejectedTenAmWindow = true;
                        trade.flattenLabel = "10:35 CASH FLATTEN";

                        if (isLong) {
                            Coordinate coord = new Coordinate(entryTime, low - (stopPts * 0.10));
                            MarkerInfo info = new MarkerInfo(Enums$MarkerType.ARROW, Enums$Size.MEDIUM, new Color(0, 204, 102), new Color(0, 204, 102), true);
                            Marker marker = new Marker(coord, Enums$Position.BOTTOM, info);
                            marker.setTextValue(String.format("10AM BUY %dx %s @ %.2f", contracts, microSym, entryPrice));
                            addFigure(marker);

                            if (showLines) {
                                Line slLine = new Line(entryTime, stopPrice, exitTime, stopPrice);
                                slLine.setColor(new Color(220, 20, 60));
                                slLine.setText(String.format("SL: %.2f (-$%.0f)", stopPrice, actualRiskDollars), LINE_FONT);
                                if (slLine.getText() != null) {
                                    slLine.getText().setShowBorder(false);
                                    slLine.getText().setBackground(null);
                                }
                                addFigure(slLine);
                                trade.slLine = slLine;

                                Line tpLine = new Line(entryTime, targetPrice, exitTime, targetPrice);
                                tpLine.setColor(new Color(0, 204, 102));
                                tpLine.setText(String.format("TP (1.5R): %.2f (+$%.0f)", targetPrice, actualRewardDollars), LINE_FONT);
                                if (tpLine.getText() != null) {
                                    tpLine.getText().setShowBorder(false);
                                    tpLine.getText().setBackground(null);
                                }
                                addFigure(tpLine);
                                trade.tpLine = tpLine;

                                Line entryLine = new Line(entryTime, entryPrice, exitTime, entryPrice);
                                entryLine.setColor(new Color(200, 200, 200, 180));
                                entryLine.setStroke(new java.awt.BasicStroke(1.0f, java.awt.BasicStroke.CAP_BUTT, java.awt.BasicStroke.JOIN_MITER, 10.0f, new float[]{4.0f, 4.0f}, 0.0f));
                                entryLine.setText(String.format("ENTRY: %.2f (%dx %s)", entryPrice, contracts, microSym), LINE_FONT);
                                if (entryLine.getText() != null) {
                                    entryLine.getText().setShowBorder(false);
                                    entryLine.getText().setBackground(null);
                                }
                                addFigure(entryLine);
                                trade.entryLine = entryLine;

                                Line exitLine = new Line(exitTime, stopPrice, exitTime, targetPrice);
                                exitLine.setColor(new Color(0, 206, 209, 180));
                                exitLine.setStroke(new java.awt.BasicStroke(1.0f, java.awt.BasicStroke.CAP_BUTT, java.awt.BasicStroke.JOIN_MITER, 10.0f, new float[]{3.0f, 3.0f}, 0.0f));
                                exitLine.setText("10:35 FLATTEN", LINE_FONT);
                                if (exitLine.getText() != null) {
                                    exitLine.getText().setShowBorder(false);
                                    exitLine.getText().setBackground(null);
                                }
                                addFigure(exitLine);
                            }

                            ctx.signal(index, SIGNAL_BUY_10AM, String.format("10AM MACRO BUY %dx %s @ %.2f (SL: %.2f, TP: %.2f)", contracts, microSym, entryPrice, stopPrice, targetPrice), entryPrice);
                        } else {
                            Coordinate coord = new Coordinate(entryTime, high + (stopPts * 0.10));
                            MarkerInfo info = new MarkerInfo(Enums$MarkerType.ARROW, Enums$Size.MEDIUM, new Color(220, 20, 60), new Color(220, 20, 60), true);
                            Marker marker = new Marker(coord, Enums$Position.TOP, info);
                            marker.setTextValue(String.format("10AM SELL %dx %s @ %.2f", contracts, microSym, entryPrice));
                            addFigure(marker);

                            if (showLines) {
                                Line slLine = new Line(entryTime, stopPrice, exitTime, stopPrice);
                                slLine.setColor(new Color(220, 20, 60));
                                slLine.setText(String.format("SL: %.2f (-$%.0f)", stopPrice, actualRiskDollars), LINE_FONT);
                                if (slLine.getText() != null) {
                                    slLine.getText().setShowBorder(false);
                                    slLine.getText().setBackground(null);
                                }
                                addFigure(slLine);
                                trade.slLine = slLine;

                                Line tpLine = new Line(entryTime, targetPrice, exitTime, targetPrice);
                                tpLine.setColor(new Color(0, 204, 102));
                                tpLine.setText(String.format("TP (1.5R): %.2f (+$%.0f)", targetPrice, actualRewardDollars), LINE_FONT);
                                if (tpLine.getText() != null) {
                                    tpLine.getText().setShowBorder(false);
                                    tpLine.getText().setBackground(null);
                                }
                                addFigure(tpLine);
                                trade.tpLine = tpLine;

                                Line entryLine = new Line(entryTime, entryPrice, exitTime, entryPrice);
                                entryLine.setColor(new Color(200, 200, 200, 180));
                                entryLine.setStroke(new java.awt.BasicStroke(1.0f, java.awt.BasicStroke.CAP_BUTT, java.awt.BasicStroke.JOIN_MITER, 10.0f, new float[]{4.0f, 4.0f}, 0.0f));
                                entryLine.setText(String.format("ENTRY: %.2f (%dx %s)", entryPrice, contracts, microSym), LINE_FONT);
                                if (entryLine.getText() != null) {
                                    entryLine.getText().setShowBorder(false);
                                    entryLine.getText().setBackground(null);
                                }
                                addFigure(entryLine);
                                trade.entryLine = entryLine;

                                Line exitLine = new Line(exitTime, targetPrice, exitTime, stopPrice);
                                exitLine.setColor(new Color(0, 206, 209, 180));
                                exitLine.setStroke(new java.awt.BasicStroke(1.0f, java.awt.BasicStroke.CAP_BUTT, java.awt.BasicStroke.JOIN_MITER, 10.0f, new float[]{3.0f, 3.0f}, 0.0f));
                                exitLine.setText("10:35 FLATTEN", LINE_FONT);
                                if (exitLine.getText() != null) {
                                    exitLine.getText().setShowBorder(false);
                                    exitLine.getText().setBackground(null);
                                }
                                addFigure(exitLine);
                            }

                            ctx.signal(index, SIGNAL_SELL_10AM, String.format("10AM MACRO SELL %dx %s @ %.2f (SL: %.2f, TP: %.2f)", contracts, microSym, entryPrice, stopPrice, targetPrice), entryPrice);
                        }

                        tradesByDate.computeIfAbsent(today, d -> new ArrayList<>()).add(trade);

                        if (soundAlert) {
                            Toolkit.getDefaultToolkit().beep();
                        }
                    } else if (getSettings().getBoolean(SHOW_NO_SETUP_MARKER, true)) {
                        StringBuilder reason = new StringBuilder("NO 10AM MACRO TRADE: ");
                        if (!isMacroSpike) {
                            reason.append(String.format("Low Volume (%.1fx vs req >= %.1fx)", volMult, minVolMult10));
                        } else if (spike10.close <= rth.high && spike10.close >= rth.low) {
                            reason.append(String.format("Inside Prior RTH Range [Low: %.2f | High: %.2f | Close: %.2f]", rth.low, rth.high, spike10.close));
                        } else if (spike10.close > rth.high && spikeCloseLoc < minLongLoc) {
                            reason.append(String.format("Long Wick Reject (CloseLoc: %.2f vs req >= %.2f)", spikeCloseLoc, minLongLoc));
                        } else if (spike10.close < rth.low && spikeCloseLoc > maxShortLoc) {
                            reason.append(String.format("Short Wick Reject (CloseLoc: %.2f vs req <= %.2f)", spikeCloseLoc, maxShortLoc));
                        } else {
                            reason.append("Breakout acceptance criteria not met");
                        }

                        Coordinate coord = new Coordinate(barStartTime, high + (tickSize * 4));
                        MarkerInfo info = new MarkerInfo(Enums$MarkerType.CIRCLE, Enums$Size.MEDIUM, new Color(100, 100, 100), Color.WHITE, Color.LIGHT_GRAY, true);
                        Marker marker = new Marker(coord, Enums$Position.TOP, info);
                        marker.setTextValue(reason.toString());
                        addFigure(marker);
                    }
                }
            }
        }

        // 5. Bar-by-Bar Active Trade Lifecycle & Outcome Tracker (Non-Repainting)
        List<ActiveTrade> dayTrades = tradesByDate.get(today);
        if (dayTrades != null) {
            for (ActiveTrade activeTrade : dayTrades) {
                if (!activeTrade.closed && barStartTime > activeTrade.entryTime) {
                    boolean exitTriggered = false;
                    double exitPrice = 0.0;
                    String outcomeText = "";
                    Color outcomeColor = Color.GREEN;

                    if (activeTrade.isLong) {
                        if (high >= activeTrade.targetPrice) {
                            exitTriggered = true;
                            exitPrice = activeTrade.targetPrice;
                            double pts = exitPrice - activeTrade.entryPrice;
                            double netDollars = pts * activeTrade.ptVal * activeTrade.contracts;
                            outcomeText = String.format("TARGET HIT 1.5R: %.2f (+%.2f pts | +$%.2f) @ %02d:%02d",
                                exitPrice, pts, netDollars, hour, min);
                            outcomeColor = Color.GREEN;
                        } else if (low <= activeTrade.stopPrice) {
                            exitTriggered = true;
                            exitPrice = activeTrade.stopPrice;
                            double pts = exitPrice - activeTrade.entryPrice;
                            double netDollars = pts * activeTrade.ptVal * activeTrade.contracts;
                            outcomeText = String.format("STOPPED OUT: %.2f (%.2f pts | -$%.2f) @ %02d:%02d",
                                exitPrice, pts, Math.abs(netDollars), hour, min);
                            outcomeColor = Color.RED;
                        } else if (barStartTime >= activeTrade.maxExitTime) {
                            exitTriggered = true;
                            exitPrice = close;
                            double pts = exitPrice - activeTrade.entryPrice;
                            double netDollars = pts * activeTrade.ptVal * activeTrade.contracts;
                            outcomeText = String.format("CASH FLATTEN (%s): %.2f (%+.2f pts | %s$%.2f)",
                                activeTrade.flattenLabel, exitPrice, pts, netDollars >= 0 ? "+" : "-", Math.abs(netDollars));
                            outcomeColor = Color.CYAN;
                        }
                    } else { // Short trade
                        if (low <= activeTrade.targetPrice) {
                            exitTriggered = true;
                            exitPrice = activeTrade.targetPrice;
                            double pts = activeTrade.entryPrice - exitPrice;
                            double netDollars = pts * activeTrade.ptVal * activeTrade.contracts;
                            outcomeText = String.format("TARGET HIT 1.5R: %.2f (+%.2f pts | +$%.2f) @ %02d:%02d",
                                exitPrice, pts, netDollars, hour, min);
                            outcomeColor = Color.GREEN;
                        } else if (high >= activeTrade.stopPrice) {
                            exitTriggered = true;
                            exitPrice = activeTrade.stopPrice;
                            double pts = activeTrade.entryPrice - exitPrice;
                            double netDollars = pts * activeTrade.ptVal * activeTrade.contracts;
                            outcomeText = String.format("STOPPED OUT: %.2f (-%.2f pts | -$%.2f) @ %02d:%02d",
                                exitPrice, pts, Math.abs(netDollars), hour, min);
                            outcomeColor = Color.RED;
                        } else if (barStartTime >= activeTrade.maxExitTime) {
                            exitTriggered = true;
                            exitPrice = close;
                            double pts = activeTrade.entryPrice - exitPrice;
                            double netDollars = pts * activeTrade.ptVal * activeTrade.contracts;
                            outcomeText = String.format("CASH FLATTEN (%s): %.2f (%+.2f pts | %s$%.2f)",
                                activeTrade.flattenLabel, exitPrice, pts, netDollars >= 0 ? "+" : "-", Math.abs(netDollars));
                            outcomeColor = Color.CYAN;
                        }
                    }

                    if (exitTriggered) {
                        activeTrade.closed = true;
                        if (activeTrade.slLine != null) activeTrade.slLine.setEnd(barStartTime, activeTrade.stopPrice);
                        if (activeTrade.tpLine != null) activeTrade.tpLine.setEnd(barStartTime, activeTrade.targetPrice);
                        if (activeTrade.entryLine != null) activeTrade.entryLine.setEnd(barStartTime, activeTrade.entryPrice);

                        double markerY = activeTrade.isLong ? (exitPrice + (tickSize * 6)) : (exitPrice - (tickSize * 6));
                        Coordinate coord = new Coordinate(barStartTime, markerY);
                        MarkerInfo info = new MarkerInfo(Enums$MarkerType.CIRCLE, Enums$Size.LARGE, outcomeColor, outcomeColor, true);
                        Marker marker = new Marker(coord, activeTrade.isLong ? Enums$Position.TOP : Enums$Position.BOTTOM, info);
                        marker.setTextValue(outcomeText);
                        if (marker.getText() != null) {
                            marker.getText().setShowBorder(false);
                            marker.getText().setBackground(null);
                        }
                        addFigure(marker);
                    }
                }
            }
        }
    }

    // =========================================================================
    // MOTIVEWAVE STRATEGY & AUTOMATED ORDER EXECUTION LIFECYCLE (CQG / RITHMIC)
    // =========================================================================

    @Override
    public void onActivate(OrderContext ctx) {
        setState(Enums$StrategyState.ACTIVE);
        logExecutionEvent("STRATEGY_ACTIVATED", "LucidMacroMomentum",
            ctx != null ? ctx.getInstrument().getSymbol() : "MNQ",
            "ACTIVE", 0.0, 0.0, 0.0, 0, "Strategy armed by user in MotiveWave");
    }

    @Override
    public void onSignal(OrderContext ctx, Object signal) {
        if (ctx == null) return;
        boolean tenAmPersistedRequest = getSettings().getBoolean(ENABLE_10AM_WINDOW, true);
        if (signal != null && !MacroTenAmOrderGate.orderSubmissionPermitted(
                MacroTenAmOrderGate.WINDOW_TIER1_0835,
                String.valueOf(signal),
                null,
                tenAmPersistedRequest)) {
            logExecutionEvent("REJECTED_TIER2_10AM_WINDOW", "LucidMacroMomentum",
                ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                "BLOCKED", 0.0, 0.0, 0.0, 0,
                "10:00 Tier-2 signal cannot submit orders. Saved enable10amWindow=" + tenAmPersistedRequest);
            return;
        }
        if (!getSettings().getBoolean(ENABLE_LIVE_AUTOTRADE, true)) return;
        long now = ctx.getCurrentTime();
        LocalDate today = Instant.ofEpochMilli(now).atZone(NY_ZONE).toLocalDate();
        List<ActiveTrade> dayTrades = tradesByDate.get(today);
        if (dayTrades == null) return;
        for (ActiveTrade trade : dayTrades) {
            if (!trade.orderSubmitted && !trade.closed) {
                executeAutoTradeIfArmed(ctx, signal, trade);
                break;
            }
        }
    }

    @Override
    public void onBarClose(OrderContext ctx) {
        if (ctx == null) return;
        boolean liveAuthorized = getSettings().getBoolean(ENABLE_LIVE_AUTOTRADE, true);

        long now = ctx.getCurrentTime();
        LocalDate today = Instant.ofEpochMilli(now).atZone(NY_ZONE).toLocalDate();
        List<ActiveTrade> dayTrades = tradesByDate.get(today);
        if (dayTrades != null) {
            for (ActiveTrade trade : dayTrades) {
                if (trade.reconcile.positionLag) {
                    verifyAndSyncBracketQuantities(ctx, trade);
                }
                if (trade.flattenPending && !trade.flattenSubmitted) {
                    submitMarketFlatten(ctx, trade, trade.flattenEvent, trade.flattenReason);
                    if (trade.flattenCancelPendingOrder != null || trade.flattenCancelBlocked || trade.closed) {
                        verifyAndSyncBracketQuantities(ctx, trade);
                        return;
                    }
                }
            }
        }
        if (dayTrades == null && ctx.getPosition() == 0) return;

        // 1. If flat and no trade submitted today, check if an unsubmitted trade signal exists for today
        if (ctx.getPosition() == 0 && liveAuthorized && !DAILY_SUBMITTED_DATES.contains(today)) {
            for (ActiveTrade trade : dayTrades) {
                if (!trade.orderSubmitted && !trade.closed && now >= trade.entryTime && now < trade.maxExitTime) {
                    executeAutoTradeIfArmed(ctx, trade.isLong ? SIGNAL_BUY : SIGNAL_SELL, trade);
                    break;
                }
            }
        }

        // 2. Reconcile restart state / Automated Hard Pre-Cash Flatten at maxExitTime (09:25 or 10:35 ET)
        if (ctx.getPosition() != 0) {
            DAILY_SUBMITTED_DATES.add(today);
            File lockFile = getDailyLockFile("macro_momentum_s2", today);
            if (lockFile != null && !lockFile.exists()) {
                try {
                    if (!lockFile.createNewFile()) {
                        logExecutionEvent("RESTART_DAILY_LOCK_NOT_CREATED", "LucidMacroMomentum",
                            ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                            "BLOCKED", 0.0, 0.0, 0.0, Math.abs(ctx.getPosition()), "Lock already exists or could not be created.");
                    }
                } catch (Exception e) {
                    logExecutionEvent("RESTART_DAILY_LOCK_CREATE_FAILED", "LucidMacroMomentum",
                        ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                        "BLOCKED", 0.0, 0.0, 0.0, Math.abs(ctx.getPosition()), e.getMessage());
                }
            }

            if (dayTrades == null) {
                if (RESTART_POSITION_REPORTED.add(today)) {
                    logExecutionEvent("RESTART_POSITION_UNRECONCILED", "LucidMacroMomentum",
                        ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                        "BLOCKED", 0.0, 0.0, 0.0, Math.abs(ctx.getPosition()),
                        "No active trade or order identities were recovered; do not recreate protective orders.");
                }
                return;
            }

            for (ActiveTrade trade : dayTrades) {
                if (!trade.restartCoverageReported && (trade.slOrder == null || !trade.slOrder.isActive())) {
                    trade.restartCoverageReported = true;
                    logExecutionEvent("RESTART_PROTECTIVE_COVERAGE_UNVERIFIED", "LucidMacroMomentum",
                        ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                        "BLOCKED", 0.0, trade.stopPrice, trade.targetPrice, Math.abs(ctx.getPosition()),
                        "Position is open but no working stop is confirmed; do not recreate protection automatically.");
                }
                if (trade.flattenPending && !trade.flattenSubmitted) {
                    submitMarketFlatten(ctx, trade, trade.flattenEvent, trade.flattenReason);
                }
                if (trade.bracketsSubmitted || trade.reconcile.pending || trade.reconcile.positionLag) {
                    verifyAndSyncBracketQuantities(ctx, trade);
                }

                if (trade.orderSubmitted && !trade.closed && now >= trade.maxExitTime) {
                    submitMarketFlatten(ctx, trade, "CASH_FLATTEN", "Cash session boundary reached (" + trade.flattenLabel + ").");
                }
            }
        }
    }

    private synchronized void executeAutoTradeIfArmed(OrderContext ctx, Object signal, ActiveTrade trade) {
        if (ctx == null) return;
        boolean tenAmPersistedRequest = getSettings().getBoolean(ENABLE_10AM_WINDOW, true);
        String windowId = (trade != null && trade.rejectedTenAmWindow)
            ? MacroTenAmOrderGate.WINDOW_TIER2_1000
            : MacroTenAmOrderGate.WINDOW_TIER1_0835;
        String flattenLabel = trade != null ? trade.flattenLabel : null;
        if (!MacroTenAmOrderGate.orderSubmissionPermitted(
                windowId,
                signal == null ? null : String.valueOf(signal),
                flattenLabel,
                tenAmPersistedRequest)) {
            logExecutionEvent("REJECTED_TIER2_10AM_WINDOW", "LucidMacroMomentum",
                ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                "BLOCKED", 0.0, 0.0, 0.0, 0,
                "10:00 Tier-2 order blocked before submission. Saved enable10amWindow=" + tenAmPersistedRequest);
            return;
        }
        if (ctx.getPosition() != 0) return; // Prevent double-entry / pyramiding

        long now = ctx.getCurrentTime();
        LocalDate today = trade != null && trade.date != null ? trade.date : Instant.ofEpochMilli(now).atZone(NY_ZONE).toLocalDate();

        // Strict Single-Trade-Per-Day Enforcement with Persistent Disk Lock (IAF Cooldown Lock)
        File lockFile = getDailyLockFile("macro_momentum_s2", today);
        if (DAILY_SUBMITTED_DATES.contains(today) || (lockFile != null && lockFile.exists())) {
            DAILY_SUBMITTED_DATES.add(today);
            logExecutionEvent("ORDER_BLOCKED_SESSION_COOLDOWN", "LucidMacroMomentum",
                ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                "BLOCKED", 0.0, 0.0, 0.0, 0,
                "Single trade per session lock active for " + today + ". Additional entries blocked.");
            return;
        }

        // Gateway-level circuit breaker check
        DaemonRiskState riskState = loadDaemonRiskState();
        if (riskState.circuitBreakerHit) {
            logExecutionEvent("CIRCUIT_BREAKER_BLOCKED", "LucidMacroMomentum", ctx.getInstrument().getSymbol(),
                "BLOCKED", 0.0, 0.0, 0.0, 0, "Daily soft-stop -$600 reached in demo parity state");
            return;
        }

        if (trade == null || trade.orderSubmitted || trade.closed) return;

        int contracts = resolveContracts(ctx, trade.contracts);
        if (contracts <= 0) {
            logExecutionEvent("ORDER_BLOCKED_UNVERIFIED_ACCOUNT", "LucidMacroMomentum",
                ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                "BLOCKED", 0.0, 0.0, 0.0, 0,
                "Account context unverified or sizing returned zero; order entry blocked (fail-closed).");
            return;
        }
        trade.contracts = contracts;

        float stopPrice = ctx.getInstrument().round((float) trade.stopPrice);
        float targetPrice = ctx.getInstrument().round((float) trade.targetPrice);

        boolean isLong = trade.isLong;
        if (signal != null) {
            String sigStr = signal.toString();
            if (sigStr.contains("BUY") || SIGNAL_BUY.equals(sigStr) || SIGNAL_BUY_10AM.equals(sigStr)) isLong = true;
            else if (sigStr.contains("SELL") || SIGNAL_SELL.equals(sigStr) || SIGNAL_SELL_10AM.equals(sigStr)) isLong = false;
        }
        trade.isLong = isLong;

        setStopPrice(stopPrice);
        setTargetPrice(targetPrice);

        // Atomic lock acquisition before submitting order to broker
        if (lockFile != null) {
            try {
                if (!lockFile.createNewFile()) {
                    DAILY_SUBMITTED_DATES.add(today);
                    logExecutionEvent("ORDER_BLOCKED_SESSION_COOLDOWN", "LucidMacroMomentum",
                        ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                        "BLOCKED", 0.0, 0.0, 0.0, 0, "Atomic lock acquisition failed for " + today);
                    return;
                }
            } catch (Exception e) {
                DAILY_SUBMITTED_DATES.add(today);
                logExecutionEvent("ORDER_BLOCKED_SESSION_COOLDOWN", "LucidMacroMomentum",
                    ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                    "BLOCKED", 0.0, 0.0, 0.0, 0, "Lock file creation failed: " + e.getMessage());
                return;
            }
        }
        DAILY_SUBMITTED_DATES.add(today);

        Enums$OrderAction entryAction = isLong ? Enums$OrderAction.BUY : Enums$OrderAction.SELL;
        Order entry = ctx.createMarketOrder(entryAction, contracts);
        trade.entryOrder = entry;
        trade.orderSubmitted = true;
        trade.entryOrderId = entry != null ? entry.getOrderId() : null;

        List<ActiveTrade> dayTrades = tradesByDate.get(today);
        if (dayTrades != null) {
            for (ActiveTrade t : dayTrades) {
                t.orderSubmitted = true;
            }
        }

        ctx.submitOrders(entry);

        logExecutionEvent("ORDER_SUBMITTED", "LucidMacroMomentum", ctx.getInstrument().getSymbol(),
            entryAction.toString(), trade.entryPrice, stopPrice, targetPrice, contracts,
            "Market entry submitted. Brackets pending fill confirmation. Daily cooldown locked.");
    }

    @Override
    public void onOrderFilled(OrderContext ctx, Order order) {
        if (ctx == null || order == null) return;
        long now = ctx.getCurrentTime();
        LocalDate today = Instant.ofEpochMilli(now).atZone(NY_ZONE).toLocalDate();
        List<ActiveTrade> dayTrades = tradesByDate.get(today);

        logExecutionEvent("ORDER_FILLED", "LucidMacroMomentum", ctx.getInstrument().getSymbol(),
            order.getAction().toString(), order.getAvgFillPrice(), 0.0, 0.0, order.getQuantity(),
            "Order filled: id=" + order.getOrderId() + " pos=" + ctx.getPosition());

        if (dayTrades == null) return;
        for (ActiveTrade trade : dayTrades) {
            if (trade.closed || !ProtectiveReconcile.isTrackedFill(order, trade.entryOrder, trade.entryOrderId, trade.slOrder, trade.slOrderId, trade.tpOrder, trade.tpOrderId, trade.flattenOrder, trade.flattenOrderId)) {
                continue;
            }
            if (ProtectiveReconcile.noteFill(trade.reconcile, order, trade.entryOrder, trade.slOrder, trade.tpOrder, trade.flattenOrder, ctx.getPosition())) {
                reportFlattenOperatorAction(ctx, trade, "POSITION_FILL_NOT_YET_REFLECTED", order, 0L,
                    "Tracked fill is not yet visible on getPosition(); protective reconciliation stays pending.");
                return;
            }
            if (trade.bracketsSubmitted || ProtectiveReconcile.isWorking(trade.slOrder)) {
                verifyAndSyncBracketQuantities(ctx, trade);
            }
            if (!trade.closed && ctx.getPosition() == 0) {
                trade.flattenPending = true;
                if (trade.flattenEvent.isEmpty()) {
                    trade.flattenEvent = "POSITION_FLAT_RESIDUAL_ORDER_CLEANUP";
                    trade.flattenReason = "Position is flat; wait for tracked entry, target, and stop orders to become terminal.";
                }
                submitMarketFlatten(ctx, trade, trade.flattenEvent, trade.flattenReason);
                return;
            }
            if (trade.flattenSubmitted
                    && (order == trade.flattenOrder || (trade.flattenOrderId != null && trade.flattenOrderId.equals(order.getOrderId())))) {
                if (order.isActive() || (!order.isFilled() && !order.isCancelled())) {
                    logExecutionEvent("FLATTEN_FILL_STATUS_UNCERTAIN_DUPLICATE_SUPPRESSED",
                        "LucidMacroMomentum", ctx.getInstrument().getSymbol(), "WAIT", 0.0,
                        trade.stopPrice, trade.targetPrice, Math.abs(ctx.getPosition()),
                        "Flatten order remains active or non-terminal; retaining identity and suppressing another exit.");
                    return;
                }
                trade.flattenSubmitted = false;
                trade.flattenOrder = null;
                trade.flattenOrderId = null;
                if (ctx.getPosition() == 0) {
                    trade.closed = true;
                    trade.flattenPending = false;
                    trade.restartCoverageReported = false;
                } else {
                    logExecutionEvent("FLATTEN_PARTIAL_FILL_REMAINS_OPEN", "LucidMacroMomentum", ctx.getInstrument().getSymbol(),
                        "FLATTEN", 0.0, trade.stopPrice, trade.targetPrice, Math.abs(ctx.getPosition()),
                        "Flatten order filled partially; remaining position is still open.");
                    submitMarketFlatten(ctx, trade, trade.flattenEvent, trade.flattenReason);
                }
                return;
            }
            if (trade.flattenPending && ctx.getPosition() != 0
                    && (order == trade.entryOrder || (trade.entryOrderId != null && trade.entryOrderId.equals(order.getOrderId()))
                        || order == trade.slOrder || order == trade.tpOrder)) {
                submitMarketFlatten(ctx, trade, trade.flattenEvent, trade.flattenReason);
                return;
            }
            boolean isTrackedEntry = (trade.entryOrderId != null && trade.entryOrderId.equals(order.getOrderId()));
            if (ctx.getPosition() != 0 && !trade.bracketSetupAttempted && trade.orderSubmitted && !trade.closed && isTrackedEntry) {
                trade.entryFilled = true;
                int contracts = Math.abs(ctx.getPosition());
                double actualFill = ctx.getAvgEntryPrice() > 0 ? ctx.getAvgEntryPrice()
                    : (order.getAvgFillPrice() > 0 ? order.getAvgFillPrice() : trade.entryPrice);
                double riskDist = Math.abs(trade.entryPrice - trade.stopPrice);
                double targetDist = Math.abs(trade.targetPrice - trade.entryPrice);
                trade.initialRiskDist = riskDist;
                trade.initialTargetDist = targetDist;
                float stopPrice = ctx.getInstrument().round((float) (trade.isLong ? (actualFill - riskDist) : (actualFill + riskDist)));
                float targetPrice = ctx.getInstrument().round((float) (trade.isLong ? (actualFill + targetDist) : (actualFill - targetDist)));
                trade.actualEntryFill = actualFill;
                trade.stopPrice = stopPrice;
                trade.targetPrice = targetPrice;
                submitInitialBrackets(ctx, trade, contracts, actualFill, stopPrice, targetPrice);
                break;
            } else if (ctx.getPosition() != 0 && trade.bracketsSubmitted && trade.orderSubmitted && !trade.closed && isTrackedEntry) {
                if (!ProtectiveReconcile.isWorking(trade.slOrder)) {
                    submitMarketFlatten(ctx, trade, "PARTIAL_FILL_WITHOUT_CONFIRMED_STOP", "Open position has no confirmed protective stop");
                }
                break;
            }
        }

    }

    private void submitInitialBrackets(OrderContext ctx, ActiveTrade trade, int contracts,
            double actualFill, float stopPrice, float targetPrice) {
            if (trade.bracketSetupAttempted) return;
            trade.bracketSetupAttempted = true;
            trade.bracketsSubmitted = false;
            trade.attachedBracketQty = 0;
            Enums$OrderAction exitAction = trade.isLong ? Enums$OrderAction.SELL : Enums$OrderAction.BUY;
            Order sl = null;
            Order tp = null;
            try {
                sl = ctx.createStopOrder(exitAction, Enums$TIF.GTC, contracts, stopPrice);
            } catch (RuntimeException e) {
                logExecutionEvent("PROTECTIVE_STOP_CREATION_FAILED", "LucidMacroMomentum",
                    ctx.getInstrument().getSymbol(), exitAction.toString(), actualFill, stopPrice,
                    targetPrice, contracts, e.getMessage());
            }
            try {
                tp = ctx.createLimitOrder(exitAction, Enums$TIF.GTC, contracts, targetPrice);
            } catch (RuntimeException e) {
                logExecutionEvent("PROFIT_TARGET_CREATION_FAILED_OPTIONAL", "LucidMacroMomentum",
                    ctx.getInstrument().getSymbol(), exitAction.toString(), actualFill, stopPrice,
                    targetPrice, contracts, e.getMessage());
            }
            trade.slOrder = sl;
            trade.tpOrder = tp;
            trade.slOrderId = sl != null ? sl.getOrderId() : null;
            trade.tpOrderId = tp != null ? tp.getOrderId() : null;
            if (sl != null) {
                try {
                    ctx.submitOrders(sl);
                } catch (RuntimeException e) {
                    logExecutionEvent("PROTECTIVE_STOP_SUBMISSION_STATUS_UNKNOWN", "LucidMacroMomentum",
                        ctx.getInstrument().getSymbol(), exitAction.toString(), actualFill, stopPrice,
                        targetPrice, contracts, e.getMessage());
                }
            }
            if (tp != null) {
                try {
                    ctx.submitOrders(tp);
                } catch (RuntimeException e) {
                    logExecutionEvent("PROFIT_TARGET_SUBMISSION_FAILED_OPTIONAL", "LucidMacroMomentum",
                        ctx.getInstrument().getSymbol(), exitAction.toString(), actualFill, stopPrice,
                        targetPrice, contracts, e.getMessage());
                }
            }
            Float confirmedStop = sl != null ? sl.getStopPrice() : null;
            double tickSize = ctx.getInstrument() != null ? ctx.getInstrument().getTickSize() : 0.25;
            boolean stopConfirmed = sl != null && sl.isActive() && !sl.isCancelled() && !sl.isFilled()
                && sl.getQuantity() == contracts && confirmedStop != null
                && Math.abs(confirmedStop - stopPrice) <= tickSize / 2.0;
            if (stopConfirmed) {
                trade.bracketsSubmitted = true;
                trade.attachedBracketQty = contracts;
                logExecutionEvent("PROTECTIVE_STOP_ACTIVE_STATE_VERIFIED", "LucidMacroMomentum",
                    ctx.getInstrument().getSymbol(), exitAction.toString(), actualFill, stopPrice,
                    targetPrice, contracts, "ORDER_ID=" + sl.getOrderId() + "|stop anchored to fill=" + actualFill);
            } else if (ctx.getPosition() != 0) {
                submitMarketFlatten(ctx, trade, "INITIAL_PROTECTIVE_STOP_UNCONFIRMED_EMERGENCY_FLATTEN",
                    "Stop creation/submission did not yield an active order with the full open quantity and requested price.");
            }
            if (tp == null) {
                logExecutionEvent("PROFIT_TARGET_UNAVAILABLE_STOP_RETAINED", "LucidMacroMomentum",
                    ctx.getInstrument().getSymbol(), exitAction.toString(), actualFill, stopPrice,
                    targetPrice, contracts, "Target is optional; protective stop status is tracked independently.");
            }
        }

    @Override
    public void onOrderRejected(OrderContext ctx, Order order) {
        if (order == null) return;
        long now = ctx != null ? ctx.getCurrentTime() : System.currentTimeMillis();
        LocalDate today = Instant.ofEpochMilli(now).atZone(NY_ZONE).toLocalDate();
        List<ActiveTrade> dayTrades = tradesByDate.get(today);
        if (dayTrades != null) {
            for (ActiveTrade trade : dayTrades) {
                if (matchesFlattenCancelPending(trade, order)) {
                    if (order.isCancelled() || order.isFilled()) {
                        clearFlattenCancelPending(trade);
                    } else {
                        trade.flattenCancelBlocked = true;
                        trade.flattenCancelTimedOut = true;
                        reportFlattenOperatorAction(ctx, trade,
                            "FLATTEN_CANCEL_REJECTED_STATUS_UNCERTAIN_OPERATOR_ACTION_REQUIRED",
                            order, Math.max(0L, System.nanoTime() - trade.flattenCancelPendingSinceNanos),
                            "Reject callback is not a terminal cancellation state.");
                        return;
                    }
                }
                if (trade.flattenSubmitted && (order == trade.flattenOrder
                        || (trade.flattenOrderId != null && trade.flattenOrderId.equals(order.getOrderId())))) {
                    if (order.isActive()) {
                        logExecutionEvent("FLATTEN_REJECTION_STATUS_UNCERTAIN_OPERATOR_ACTION_REQUIRED",
                            "LucidMacroMomentum", ctx != null && ctx.getInstrument() != null
                                ? ctx.getInstrument().getSymbol() : "UNKNOWN", order.getAction().toString(),
                            0.0, trade.stopPrice, trade.targetPrice, ctx != null ? Math.abs(ctx.getPosition()) : 0,
                            "Rejected flatten still reports active; duplicate exit suppressed.");
                        return;
                    }
                    trade.flattenSubmitted = false;
                    trade.flattenOrder = null;
                    trade.flattenOrderId = null;
                    if (ctx != null && ctx.getPosition() == 0) trade.closed = true;
                    else trade.flattenPending = true;
                    logExecutionEvent("FLATTEN_ORDER_REJECTED", "LucidMacroMomentum",
                        ctx != null && ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                        order.getAction().toString(), 0.0, trade.stopPrice, trade.targetPrice,
                        ctx != null ? Math.abs(ctx.getPosition()) : 0, "REJECTED_ORDER_ID=" + order.getOrderId());
                    return;
                }
                if (order == trade.entryOrder || (trade.entryOrderId != null && trade.entryOrderId.equals(order.getOrderId()))) {
                    trade.entryOrder = null;
                    if (ctx != null && ctx.getPosition() == 0) {
                        trade.orderSubmitted = false;
                        trade.closed = true;
                    } else if (ctx != null) {
                        trade.orderSubmitted = true;
                        trade.closed = false;
                        submitMarketFlatten(ctx, trade, "PARTIAL_ENTRY_REJECTED_EMERGENCY_FLATTEN",
                            "Entry remainder rejected; reconcile/cancel tracked exits and flatten the confirmed remaining position.");
                    }
                    logExecutionEvent("ENTRY_ORDER_REJECTED", "LucidMacroMomentum",
                        ctx != null && ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                        order.getAction().toString(), 0.0, trade.stopPrice, trade.targetPrice,
                        ctx != null ? Math.abs(ctx.getPosition()) : 0, "ENTRY_REJECTED:" + order.getOrderId());
                    return;
                }
                if (order == trade.slOrder || (trade.slOrderId != null && trade.slOrderId.equals(order.getOrderId()))) {
                    if (!order.isActive()) trade.slOrder = null;
                    if (ctx != null && ctx.getPosition() != 0) {
                        submitMarketFlatten(ctx, trade, "PROTECTIVE_STOP_REJECTED_EMERGENCY_FLATTEN", "Protective stop rejected while position open");
                    }
                    return;
                }
                if (order == trade.tpOrder || (trade.tpOrderId != null && trade.tpOrderId.equals(order.getOrderId()))) {
                    if (order.isActive() && ctx != null && ctx.getPosition() != 0) {
                        submitMarketFlatten(ctx, trade, "TARGET_REJECTION_STATUS_UNCERTAIN_FLATTEN",
                            "Rejected target still reports active; cancel tracked exits before flattening.");
                        return;
                    }
                    if (!order.isActive()) trade.tpOrder = null;
                    logExecutionEvent("PROFIT_TARGET_REJECTED_STOP_RETAINED", "LucidMacroMomentum",
                        ctx != null && ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                        order.getAction().toString(), 0.0, trade.stopPrice, trade.targetPrice,
                        ctx != null ? Math.abs(ctx.getPosition()) : 0, "TARGET_REJECTED:" + order.getOrderId());
                    if (ctx != null && ctx.getPosition() != 0 && (trade.slOrder == null || !trade.slOrder.isActive())) {
                        submitMarketFlatten(ctx, trade, "TARGET_REJECTED_WITHOUT_STOP_FLATTEN", "Target rejected and stop is not confirmed working");
                    }
                    return;
                }
            }
        }
        logExecutionEvent("ORDER_REJECTED", "LucidMacroMomentum",
            ctx != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
            order.getAction().toString(), 0.0, 0.0, 0.0, order.getQuantity(),
            "Order REJECTED by broker: id=" + order.getOrderId() + " type=" + order.getType());
    }

    @Override
    public void onOrderCancelled(OrderContext ctx, Order order) {
        if (order == null) return;
        long now = ctx != null ? ctx.getCurrentTime() : System.currentTimeMillis();
        LocalDate today = Instant.ofEpochMilli(now).atZone(NY_ZONE).toLocalDate();
        List<ActiveTrade> dayTrades = tradesByDate.get(today);
        if (dayTrades != null) {
            for (ActiveTrade trade : dayTrades) {
                if (matchesFlattenCancelPending(trade, order)) {
                    if (order.isCancelled() || order.isFilled()) {
                        clearFlattenCancelPending(trade);
                    } else {
                        trade.flattenCancelBlocked = true;
                        trade.flattenCancelTimedOut = true;
                        reportFlattenOperatorAction(ctx, trade,
                            "FLATTEN_CANCEL_CALLBACK_STATUS_UNCERTAIN_OPERATOR_ACTION_REQUIRED",
                            order, Math.max(0L, System.nanoTime() - trade.flattenCancelPendingSinceNanos),
                            "Cancellation callback did not expose a terminal order state.");
                        return;
                    }
                }
                if (trade.flattenSubmitted && (order == trade.flattenOrder
                        || (trade.flattenOrderId != null && trade.flattenOrderId.equals(order.getOrderId())))) {
                    trade.flattenSubmitted = false;
                    trade.flattenOrder = null;
                    trade.flattenOrderId = null;
                    if (ctx != null && ctx.getPosition() == 0) trade.closed = true;
                    else trade.flattenPending = true;
                    logExecutionEvent("FLATTEN_ORDER_CANCELLED", "LucidMacroMomentum",
                        ctx != null && ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                        order.getAction().toString(), 0.0, trade.stopPrice, trade.targetPrice,
                        ctx != null ? Math.abs(ctx.getPosition()) : 0, "CANCELLED_ORDER_ID=" + order.getOrderId());
                    return;
                }
                if (order == trade.entryOrder) {
                    trade.entryOrder = null;
                    if (ctx != null && trade.flattenPending) submitMarketFlatten(ctx, trade, trade.flattenEvent, trade.flattenReason);
                    return;
                }
                if (order == trade.slOrder || (trade.slOrderId != null && trade.slOrderId.equals(order.getOrderId()))) {
                    trade.slOrder = null;
                    if (trade.flattenPending) {
                        if (ctx != null) submitMarketFlatten(ctx, trade, trade.flattenEvent, trade.flattenReason);
                        return;
                    }
                    if (ctx != null && ctx.getPosition() != 0) {
                        submitMarketFlatten(ctx, trade, "PROTECTIVE_STOP_CANCELLED_EMERGENCY_FLATTEN", "Protective stop cancelled unexpectedly while position open");
                    }
                    return;
                }
                if (order == trade.tpOrder) {
                    trade.tpOrder = null;
                    if (ctx != null && trade.flattenPending) submitMarketFlatten(ctx, trade, trade.flattenEvent, trade.flattenReason);
                    return;
                }
            }
        }
        logExecutionEvent("ORDER_CANCELLED", "LucidMacroMomentum",
            ctx != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
            order.getAction().toString(), 0.0, 0.0, 0.0, order.getQuantity(),
            "Order cancelled: id=" + order.getOrderId());
    }

    @Override
    public void onPositionClosed(OrderContext ctx) {
        if (ctx == null || ctx.getPosition() != 0) return;
        long now = ctx != null ? ctx.getCurrentTime() : System.currentTimeMillis();
        LocalDate today = Instant.ofEpochMilli(now).atZone(NY_ZONE).toLocalDate();
        List<ActiveTrade> dayTrades = tradesByDate.get(today);
        if (dayTrades != null) {
            for (ActiveTrade trade : dayTrades) {
                if (trade.closed) continue;
                trade.flattenPending = true;
                trade.flattenEvent = "POSITION_FLAT_RESIDUAL_ORDER_CLEANUP";
                trade.flattenReason = "Position is flat; tracked working orders require terminal-state confirmation.";
                submitMarketFlatten(ctx, trade, trade.flattenEvent, trade.flattenReason);
            }
        }
        logExecutionEvent("POSITION_CLOSED_CONFIRMED", "LucidMacroMomentum",
            ctx != null && ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
            "FLAT", 0.0, 0.0, 0.0, 0, "Broker reports flat position; tracked order cleanup remains callback-confirmed.");
    }

    @Override
    public void onDeactivate(OrderContext ctx) {
        setState(Enums$StrategyState.INACTIVE);
        if (ctx != null) {
            if (ctx.getPosition() == 0) {
                boolean trackedTrade = false;
                for (List<ActiveTrade> dayTrades : tradesByDate.values()) {
                    for (ActiveTrade trade : dayTrades) {
                        if (trade.closed) continue;
                        trackedTrade = true;
                        trade.flattenPending = true;
                        trade.flattenEvent = "STRATEGY_DEACTIVATION_FLAT_ORDER_CLEANUP";
                        trade.flattenReason = "Flat position; cancel tracked residual orders and await terminal states.";
                        submitMarketFlatten(ctx, trade, trade.flattenEvent, trade.flattenReason);
                    }
                }
                if (!trackedTrade) {
                    logExecutionEvent("DEACTIVATION_UNTRACKED_ORDERS_OPERATOR_ACTION_REQUIRED", "LucidMacroMomentum",
                        ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                        "BLOCKED", 0.0, 0.0, 0.0, 0,
                        "No active trade identities are available; manually verify no working orders remain.");
                }
            } else {
                logExecutionEvent("STRATEGY_DEACTIVATED_POSITION_REMAINS_OPEN", "LucidMacroMomentum",
                    ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "MNQ",
                    "FLAT", 0.0, 0.0, 0.0, 0,
                    "Position open (" + ctx.getPosition() + "); protective orders preserved to prevent naked position exposure.");
            }
        }
        logExecutionEvent("STRATEGY_DEACTIVATED", "LucidMacroMomentum",
            ctx != null ? ctx.getInstrument().getSymbol() : "MNQ",
            "INACTIVE", 0.0, 0.0, 0.0, 0, "Strategy deactivated by user");
    }

    public synchronized void verifyAndSyncBracketQuantities(OrderContext ctx, ActiveTrade trade) {
        if (ctx == null || trade == null) return;
        int position = ctx.getPosition();
        if (position != 0 && !trade.bracketsSubmitted && !ProtectiveReconcile.isWorking(trade.slOrder)) return;
        float desiredStop = (float) trade.stopPrice;
        float desiredTarget = (float) trade.targetPrice;
        boolean havePrices = false;
        double actualFill = Double.NaN;
        var inst = ctx.getInstrument();
        if (inst != null && position != 0) {
            actualFill = ctx.getAvgEntryPrice() > 0 && Float.isFinite(ctx.getAvgEntryPrice())
                ? ctx.getAvgEntryPrice()
                : (Double.isFinite(trade.actualEntryFill) ? trade.actualEntryFill : trade.entryPrice);
            double riskDist = Double.isFinite(trade.initialRiskDist) && trade.initialRiskDist > 0
                ? trade.initialRiskDist : Math.abs(trade.entryPrice - trade.stopPrice);
            double targetDist = Double.isFinite(trade.initialTargetDist) && trade.initialTargetDist > 0
                ? trade.initialTargetDist : Math.abs(trade.targetPrice - trade.entryPrice);
            if (Double.isFinite(actualFill) && actualFill > 0 && riskDist > 0 && targetDist > 0) {
                desiredStop = inst.round((float) (trade.isLong ? actualFill - riskDist : actualFill + riskDist));
                desiredTarget = inst.round((float) (trade.isLong ? actualFill + targetDist : actualFill - targetDist));
                havePrices = true;
            }
        }
        applyReconcileDecision(ctx, trade, position, desiredStop, desiredTarget, havePrices, actualFill);
    }

    private void applyReconcileDecision(OrderContext ctx, ActiveTrade trade, int position,
            float desiredStop, float desiredTarget, boolean havePrices, double actualFill) {
        boolean flattenWorking = trade.flattenSubmitted && ProtectiveReconcile.isWorking(trade.flattenOrder);
        ProtectiveReconcile.Decision decision = ProtectiveReconcile.reconcile(
            ctx, trade.reconcile, trade.flattenCancelPendingOrder, trade.entryOrder, trade.slOrder,
            trade.tpOrder, trade.flattenOrder, flattenWorking, desiredStop, desiredTarget, havePrices);
        int absQty = Math.abs(position);
        switch (decision) {
            case FLAT -> ProtectiveReconcile.clear(this, trade.reconcile, this::removeFigure, false);
            case COVERED -> {
                if (position != 0) {
                    trade.attachedBracketQty = absQty;
                    if (havePrices && Double.isFinite(actualFill) && actualFill > 0) {
                        trade.actualEntryFill = actualFill;
                        trade.entryPrice = actualFill;
                        trade.stopPrice = desiredStop;
                        trade.targetPrice = desiredTarget;
                    }
                }
                ProtectiveReconcile.clear(this, trade.reconcile, this::removeFigure, !trade.flattenPending && !trade.flattenCancelBlocked);
            }
            case REQUESTED, AWAITING, IDLE -> { }
            case WITHHELD_CANCEL, WITHHELD_FLATTEN_WORKING, WITHHELD_UNSAFE, STOP_MISSING, REQUEST_FAILED ->
                ProtectiveReconcile.raise(this, ctx, trade.reconcile, this::addFigure, this::removeFigure, "PROTECTIVE_COVERAGE_UNRESOLVED",
                    decision + "|POS=" + position + "|ERROR=" + trade.reconcile.lastError
                        + "|REQUESTED_NOT_CONFIRMED|MODIFICATION_WITHHELD_WHEN_UNSAFE");
            default -> { }
        }
    }

    @Override
    public void onOrderModified(OrderContext ctx, Order order) {
        if (ctx == null || order == null) return;
        long now = ctx.getCurrentTime();
        LocalDate today = Instant.ofEpochMilli(now).atZone(NY_ZONE).toLocalDate();
        List<ActiveTrade> dayTrades = tradesByDate.get(today);
        if (dayTrades == null) return;
        for (ActiveTrade trade : dayTrades) confirmProtectiveModification(ctx, trade, order);
    }

    private void confirmProtectiveModification(OrderContext ctx, ActiveTrade trade, Order order) {
        if (trade == null || order == null) return;
        boolean trackedStop = ProtectiveReconcile.same(order, trade.slOrder) || ProtectiveReconcile.matchesId(order, trade.slOrderId);
        boolean trackedTarget = ProtectiveReconcile.same(order, trade.tpOrder) || ProtectiveReconcile.matchesId(order, trade.tpOrderId);
        if (!trackedStop && !trackedTarget) return;
        double tick = ctx.getInstrument() != null ? ctx.getInstrument().getTickSize() : 0.25;
        int position = ctx.getPosition();
        boolean stopOk = trackedStop && ProtectiveReconcile.confirmStop(trade.reconcile, order, position, tick);
        boolean targetOk = trackedTarget && ProtectiveReconcile.confirmTarget(trade.reconcile, order, position, tick);
        if (stopOk && order.getStopPrice() != null) trade.stopPrice = order.getStopPrice();
        if (targetOk && order.getLimitPrice() != null) trade.targetPrice = order.getLimitPrice();
        if ((stopOk || targetOk) && !trade.reconcile.pending && position != 0) {
            trade.attachedBracketQty = Math.abs(position);
            ProtectiveReconcile.clear(this, trade.reconcile, this::removeFigure, !trade.flattenPending && !trade.flattenCancelBlocked);
            return;
        }
        if (!stopOk && !targetOk && (trade.reconcile.stopRequested || trade.reconcile.targetRequested || trade.reconcile.pending)) {
            verifyAndSyncBracketQuantities(ctx, trade);
        }
    }

    private void submitMarketFlatten(OrderContext ctx, ActiveTrade trade, String event, String reason) {
        if (ctx == null || trade == null) return;
        trade.flattenPending = true;
        if (trade.flattenEvent.isEmpty()) {
            trade.flattenEvent = event;
            trade.flattenReason = reason;
        }
        if (ctx.getPosition() != 0 && (trade.flattenCancelPendingOrder != null || trade.flattenSubmitted)) {
            verifyAndSyncBracketQuantities(ctx, trade);
        }
        if (trade.flattenSubmitted) return;

        if (checkFlattenCancelPending(ctx, trade)) return;
        if (trade.flattenCancelBlocked && trade.flattenCancelPendingOrder == null) {
            int currentPosition = ctx.getPosition();
            if (currentPosition == 0) {
                trade.flattenCancelBlocked = false;
            } else {
                String coverageFailure = flattenStopCoverageFailure(ctx, trade, currentPosition);
                reportFlattenOperatorAction(ctx, trade, coverageFailure == null
                        ? "FLATTEN_RETAINED_STOP_COVERAGE_CONFIRMED_OPERATOR_ACTION_REQUIRED"
                        : "FLATTEN_RETAINED_STOP_COVERAGE_UNVERIFIED_OPERATOR_ACTION_REQUIRED",
                    trade.slOrder, 0L, (coverageFailure == null ? "STOP_COVERAGE_CONFIRMED" : coverageFailure)
                        + "|PROTECTIVE_STOP_RETAINED|AUTO_FLATTEN_WITHHELD");
                return;
            }
        }
        Order[] workingOrders = {trade.entryOrder, trade.tpOrder, trade.slOrder};
        for (Order workingOrder : workingOrders) {
            if (workingOrder == null || workingOrder.isCancelled() || workingOrder.isFilled()) continue;
            if (workingOrder == trade.slOrder) {
                int positionBeforeStopCancel = ctx.getPosition();
                if (positionBeforeStopCancel != 0) {
                    String coverageFailure = flattenStopCoverageFailure(ctx, trade, positionBeforeStopCancel);
                    boolean covered = coverageFailure == null;
                    reportFlattenOperatorAction(ctx, trade, covered
                            ? "FLATTEN_RETAINED_STOP_COVERAGE_CONFIRMED_OPERATOR_ACTION_REQUIRED"
                            : "FLATTEN_RETAINED_STOP_COVERAGE_UNVERIFIED_OPERATOR_ACTION_REQUIRED",
                        workingOrder, 0L, (covered ? "STOP_COVERAGE_CONFIRMED" : coverageFailure)
                            + "|PROTECTIVE_STOP_RETAINED|AUTO_FLATTEN_WITHHELD|NO_REDUCE_ONLY_OR_ATOMIC_REPLACE");
                    trade.flattenCancelBlocked = true;
                    return;
                }
            }
            if (trade.flattenCancelPendingOrder == workingOrder) return;
            trade.flattenCancelPendingOrder = workingOrder;
            trade.flattenCancelPendingSinceNanos = System.nanoTime();
            trade.flattenCancelTimedOut = false;
            try {
                ctx.cancelOrders(workingOrder);
                logExecutionEvent(workingOrder == trade.slOrder
                        ? "FLATTEN_WAITING_FOR_PROTECTIVE_STOP_CANCELLATION"
                        : "FLATTEN_WAITING_FOR_ENTRY_OR_TARGET_CANCELLATION", "LucidMacroMomentum",
                    ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                    "WAIT", 0.0, trade.stopPrice, trade.targetPrice, Math.abs(ctx.getPosition()),
                    trade.flattenReason + "|ORDER_ID=" + workingOrder.getOrderId());
            } catch (RuntimeException e) {
                trade.flattenCancelBlocked = true;
                trade.flattenCancelTimedOut = true;
                reportFlattenOperatorAction(ctx, trade, "FLATTEN_CANCEL_STATUS_UNKNOWN_OPERATOR_ACTION_REQUIRED",
                    workingOrder, 0L, "Cancel call threw; order state must be reconciled|ERROR=" + e.getMessage());
            }
            return;
        }
        int currentPosition = ctx.getPosition();
        if (currentPosition == 0) {
            trade.flattenPending = false;
            trade.closed = true;
            return;
        }
        String coverageFailure = flattenStopCoverageFailure(ctx, trade, currentPosition);
        trade.flattenCancelBlocked = true;
        reportFlattenOperatorAction(ctx, trade,
            coverageFailure == null ? "FLATTEN_RETAINED_STOP_COVERAGE_CONFIRMED_OPERATOR_ACTION_REQUIRED"
                : "FLATTEN_RETAINED_STOP_COVERAGE_UNVERIFIED_OPERATOR_ACTION_REQUIRED",
            trade.slOrder, 0L, (coverageFailure == null ? "STOP_COVERAGE_CONFIRMED" : coverageFailure)
                + "|ALL_TRACKED_ORDERS_TERMINAL|NO_MARKET_EXIT_SUBMITTED|OPERATOR_MUST_RECONCILE_POSITION");
    }

    private String flattenStopCoverageFailure(OrderContext ctx, ActiveTrade trade, int positionSnapshot) {
        int quantity = Math.abs(positionSnapshot);
        Order stop = trade.slOrder;
        try {
            if (positionSnapshot == 0 || ctx.getPosition() != positionSnapshot) return "POSITION_CHANGED";
            if (stop == null) return "STOP_MISSING";
            String orderId = stop.getOrderId();
            if (trade.slOrderId != null && !trade.slOrderId.isEmpty() && !trade.slOrderId.equals(orderId)) return "STOP_ID_MISMATCH";
            if (!stop.isActive() || stop.isCancelled() || stop.isFilled()) return "STOP_NOT_ACTIVE";
            if (trade.reconcile.positionLag || trade.reconcile.stopRequested || trade.reconcile.targetRequested) return "STOP_QUANTITY_UNCONFIRMED";
            if (trade.reconcile.confirmedStopQty >= 0 && trade.reconcile.confirmedStopQty != quantity) return "STOP_QUANTITY_UNCONFIRMED";
            if (stop.getQuantity() != quantity || trade.attachedBracketQty != quantity) return "STOP_QUANTITY_MISMATCH";
            Float observedPrice = stop.getStopPrice();
            double tickSize = ctx.getInstrument() != null ? ctx.getInstrument().getTickSize() : Double.NaN;
            if (observedPrice == null || !Float.isFinite(observedPrice) || !Double.isFinite(trade.stopPrice)
                    || !Double.isFinite(tickSize) || tickSize <= 0.0) return "STOP_PRICE_UNVERIFIABLE";
            if (Math.abs(observedPrice - trade.stopPrice) > tickSize / 2.0) return "STOP_PRICE_MISMATCH";
            if (ctx.getPosition() != positionSnapshot) return "POSITION_CHANGED_DURING_STOP_CHECK";
            return null;
        } catch (RuntimeException e) {
            return "STOP_STATE_READ_FAILED:" + e.getMessage();
        }
    }

    private boolean checkFlattenCancelPending(OrderContext ctx, ActiveTrade trade) {
        Order pending = trade.flattenCancelPendingOrder;
        if (pending == null) return false;
        if (pending.isCancelled() || pending.isFilled()) {
            trade.flattenCancelPendingOrder = null;
            trade.flattenCancelPendingSinceNanos = 0L;
            trade.flattenCancelBlocked = false;
            trade.flattenCancelTimedOut = false;
            return false;
        }
        long now = System.nanoTime();
        long elapsed = trade.flattenCancelPendingSinceNanos > 0L
            ? Math.max(0L, now - trade.flattenCancelPendingSinceNanos) : 0L;
        if (elapsed >= FLATTEN_CANCEL_ACK_TIMEOUT_NANOS) {
            trade.flattenCancelBlocked = true;
            trade.flattenCancelTimedOut = true;
            reportFlattenOperatorAction(ctx, trade, "FLATTEN_CANCEL_ACK_TIMEOUT_OPERATOR_ACTION_REQUIRED",
                pending, elapsed, "Cancellation acknowledgement timed out; no retry or market exit is safe.");
        }
        return true;
    }

    private void reportFlattenOperatorAction(OrderContext ctx, ActiveTrade trade, String event,
        Order order, long elapsedNanos, String reason) {
        setState(Enums$StrategyState.INACTIVE);
        ProtectiveReconcile.raise(this, ctx, trade.reconcile, this::addFigure, this::removeFigure, event, reason);
        long now = System.nanoTime();
        int position = ctx != null ? ctx.getPosition() : 0;
        Order stop = trade.slOrder;
        Float stopPrice = stop != null ? stop.getStopPrice() : null;
        String details = "OPERATOR_ACTION_REQUIRED|AUTO_FLATTEN_WITHHELD|POSITION=" + position
            + "|PENDING_ORDER_ID=" + (order != null ? order.getOrderId() : "NONE")
            + "|PENDING_ORDER_STATE=" + flattenOrderState(order)
            + "|PENDING_ORDER_ACTIVE=" + (order != null && order.isActive())
            + "|PENDING_ORDER_CANCELLED=" + (order != null && order.isCancelled())
            + "|PENDING_ORDER_FILLED=" + (order != null && order.isFilled())
            + "|CANCEL_WAIT_MS=" + (elapsedNanos / 1_000_000L)
            + "|STOP_ID=" + (stop != null ? stop.getOrderId() : "NONE")
            + "|STOP_STATE=" + flattenOrderState(stop)
            + "|STOP_ACTIVE=" + (stop != null && stop.isActive())
            + "|STOP_CANCELLED=" + (stop != null && stop.isCancelled())
            + "|STOP_FILLED=" + (stop != null && stop.isFilled())
            + "|STOP_QTY=" + (stop != null ? stop.getQuantity() : 0)
            + "|STOP_EXPECTED_QTY=" + Math.abs(position)
            + "|STOP_PRICE=" + stopPrice
            + "|CONFIRMED_STOP_PRICE=" + trade.stopPrice
            + "|REASON=" + reason + "|" + trade.flattenReason
            + "|RECONCILE_POSITION_ENTRY_TARGET_STOP_BEFORE_MANUAL_ACTION";
        String alertKey = event + "|POSITION=" + position + "|PENDING_ID="
            + (order != null ? order.getOrderId() : "NONE") + "|STOP_ID="
            + (stop != null ? stop.getOrderId() : "NONE") + "|STOP_QTY="
            + (stop != null ? stop.getQuantity() : 0) + "|STOP_PRICE=" + stopPrice + "|REASON=" + reason;
        if (alertKey.equals(trade.flattenOperatorAlertKey) && trade.flattenOperatorAlertLastNanos != 0L
                && now - trade.flattenOperatorAlertLastNanos < FLATTEN_OPERATOR_ALERT_INTERVAL_NANOS) return;
        trade.flattenOperatorAlertLastNanos = now;
        trade.flattenOperatorAlertKey = alertKey;
        logExecutionEvent(event, "LucidMacroMomentum",
            ctx != null && ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
            "BLOCKED", stopPrice != null ? stopPrice : 0.0, trade.stopPrice, trade.targetPrice,
            Math.abs(position), details);
    }

    private String flattenOrderState(Order order) {
        if (order == null) return "NONE";
        if (order.isActive()) return "ACTIVE";
        if (order.isCancelled()) return "CANCELLED";
        if (order.isFilled()) return "FILLED";
        return "UNKNOWN";
    }

    private boolean matchesFlattenCancelPending(ActiveTrade trade, Order order) {
        return order != null && trade.flattenCancelPendingOrder != null
            && (order == trade.flattenCancelPendingOrder
                || (trade.flattenCancelPendingOrder.getOrderId() != null
                    && trade.flattenCancelPendingOrder.getOrderId().equals(order.getOrderId())));
    }

    private void clearFlattenCancelPending(ActiveTrade trade) {
        trade.flattenCancelPendingOrder = null;
        trade.flattenCancelPendingSinceNanos = 0L;
        trade.flattenCancelBlocked = false;
        trade.flattenCancelTimedOut = false;
    }

    private static synchronized void logExecutionEvent(String event, String studyId, String symbol,
        String action, double price, double sl, double tp, int contracts, String reason) {
        try {
            File stateFile = resolveCanonicalStateFile();
            File dir = (stateFile != null && stateFile.getParentFile() != null)
                ? stateFile.getParentFile()
                : new File(System.getProperty("user.home", "."), "trading_strategy/nq-scalper-backtest/results/forward_test");
            if (!dir.exists()) dir.mkdirs();
            File alertLog = new File(dir, "motivewave_alerts.log");
            String isoNow = Instant.now().toString();
            String alertLine = String.format("%s,%s,%s,%s,%.2f,%.2f,%.2f,%d,%s%n",
                isoNow, studyId, symbol, action, price, sl, tp, contracts, reason.replace(',', ';'));
            Files.write(alertLog.toPath(), alertLine.getBytes(StandardCharsets.UTF_8),
                java.nio.file.StandardOpenOption.CREATE, java.nio.file.StandardOpenOption.APPEND);
        } catch (Exception ignored) {
        }
    }
}
