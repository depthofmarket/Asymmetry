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
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

@StudyHeader(
    namespace = "com.motivewave.platform.study.custom",
    id = "GOLD_FIX_BREAKOUT_ALGO_V1",
    name = "Lucid 25K — 3. Gold London Fix (10:15 ET)",
    desc = "10:15 ET Post-LBMA PM Fix Breakout on Gold (MGC/GC) with 3-Way Barrier (Prior VAH, IB60 High, London High), $250 Risk Budget, 11:00 Exit, Live CQG Bracket Execution, and Live Trade Tracker",
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
public class LucidGoldFixBreakoutStudy extends Study {

    private static final Font LINE_FONT = new Font("SansSerif", Font.BOLD, 10);

    // Settings Keys
    private static final String MIN_RETURN_PCT = "minReturnPct";
    private static final String MIN_LONG_CLOSE_LOC = "minLongCloseLoc";
    private static final String REWARD_RISK_RATIO = "rewardRiskRatio";
    private static final String RISK_BUDGET_DOLLARS = "riskBudgetDollars";
    private static final String RATCHET_TIER_OVERRIDE = "ratchetTierOverride";
    private static final String MIN_STOP_POINTS = "minStopPoints";
    private static final String MAX_STOP_POINTS = "maxStopPoints";
    private static final String REQUIRE_OUTSIDE_PRIOR_VA = "requireOutsidePriorVA";
    private static final String REQUIRE_OUTSIDE_LONDON_RANGE = "requireOutsideLondonRange";
    private static final String REQUIRE_OUTSIDE_IB60 = "requireOutsideIB60";
    private static final String ENABLE_SOUND_ALERT = "enableSoundAlert";
    private static final String SHOW_LEVEL_LINES = "showLevelLines";
    private static final String HIDE_LINES_WHEN_LIVE = "hideLinesWhenLive";
    private static final String SHOW_NO_SETUP_MARKER = "showNoSetupMarker";
    private static final String ENABLE_LIVE_AUTOTRADE = "enableLiveAutoTrade";

    private static final ZoneId NY_ZONE = ZoneId.of("America/New_York");

    // Signal Keys
    private static final String SIGNAL_BUY = "LUCID_GOLD_BUY";

    // Session State Tracking
    private final Map<LocalDate, ComexRthProfile> rthProfilesByDate = new HashMap<>();
    private final Map<LocalDate, LondonRange> londonByDate = new HashMap<>();
    private final Map<LocalDate, Ib60Range> ibByDate = new HashMap<>();
    private final Map<LocalDate, Fix15Range> fixByDate = new HashMap<>();
    private final Set<LocalDate> processedDays = new HashSet<>();
    private final Map<LocalDate, ActiveTrade> tradesByDate = new HashMap<>();
    // IAF Session Cooldown Lock: strictly enforces <= 1 automated trade per session
    private static final Set<LocalDate> DAILY_SUBMITTED_DATES = java.util.concurrent.ConcurrentHashMap.newKeySet();
    private static final Set<LocalDate> RESTART_POSITION_REPORTED = java.util.concurrent.ConcurrentHashMap.newKeySet();

    private static class ActiveTrade {
        LocalDate date;
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
        boolean orderSubmitted = false;
        boolean entryFilled = false;
        boolean bracketsSubmitted = false;
        boolean bracketSetupAttempted = false;
        boolean flattenSubmitted = false;
        boolean flattenPending = false;
        boolean flattenCancelBlocked = false;
        boolean restartCoverageReported = false;
        String flattenEvent = "";
        String flattenReason = "";
        Order entryOrder;
        Order slOrder;
        Order tpOrder;
        Order flattenOrder;
        Order flattenCancelPendingOrder;
        String entryOrderId;
        String slOrderId;
        String tpOrderId;
        String flattenOrderId;
        Line slLine;
        Line tpLine;
        Line entryLine;
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

    private static class ComexRthProfile {
        double high = Double.NEGATIVE_INFINITY;
        double low = Double.POSITIVE_INFINITY;
        double volume = 0.0;
        final Map<Long, Double> volumeByTick = new HashMap<>();
        double vah = Double.NaN;
        double val = Double.NaN;
        double poc = Double.NaN;
        boolean computed = false;

        void addBar(double h, double l, double c, long vol, double tickSize) {
            high = Math.max(high, h);
            low = Math.min(low, l);
            volume += vol;

            long lowTick = Math.round(l / tickSize);
            long highTick = Math.round(h / tickSize);
            long tickCount = highTick - lowTick + 1;

            if (tickCount <= 1) {
                long tickKey = Math.round(c / tickSize);
                volumeByTick.put(tickKey, volumeByTick.getOrDefault(tickKey, 0.0) + (double) vol);
            } else {
                double volPerTick = (double) vol / tickCount;
                for (long t = lowTick; t <= highTick; t++) {
                    volumeByTick.put(t, volumeByTick.getOrDefault(t, 0.0) + volPerTick);
                }
            }
        }

        void computeValueArea(double tickSize) {
            if (computed || volumeByTick.isEmpty() || volume <= 0) return;

            long bestTick = 0;
            double maxVol = -1.0;
            for (Map.Entry<Long, Double> e : volumeByTick.entrySet()) {
                if (e.getValue() > maxVol) {
                    maxVol = e.getValue();
                    bestTick = e.getKey();
                }
            }
            poc = bestTick * tickSize;

            double targetVol = volume * 0.70;
            double currentVol = maxVol;
            long upTick = bestTick + 1;
            long downTick = bestTick - 1;

            while (currentVol < targetVol) {
                double upVol = volumeByTick.getOrDefault(upTick, 0.0);
                double downVol = volumeByTick.getOrDefault(downTick, 0.0);

                if (upVol == 0.0 && downVol == 0.0) {
                    if (upTick * tickSize > high && downTick * tickSize < low) break;
                    upTick++;
                    downTick--;
                    continue;
                }

                if (upVol >= downVol) {
                    currentVol += upVol;
                    upTick++;
                } else {
                    currentVol += downVol;
                    downTick--;
                }
            }

            vah = (upTick - 1) * tickSize;
            val = (downTick + 1) * tickSize;
            computed = true;
        }
    }

    private static class LondonRange {
        double high = Double.NEGATIVE_INFINITY;
        double low = Double.POSITIVE_INFINITY;

        void addBar(double h, double l) {
            high = Math.max(high, h);
            low = Math.min(low, l);
        }
    }

    private static class Ib60Range {
        double high = Double.NEGATIVE_INFINITY;
        double low = Double.POSITIVE_INFINITY;

        void addBar(double h, double l) {
            high = Math.max(high, h);
            low = Math.min(low, l);
        }
    }

    private static class Fix15Range {
        double open = Double.NaN;
        double high = Double.NEGATIVE_INFINITY;
        double low = Double.POSITIVE_INFINITY;
        double close = Double.NaN;
        boolean complete = false;

        void addBar(double o, double h, double l, double c) {
            if (Double.isNaN(open)) open = o;
            high = Double.isInfinite(high) ? h : Math.max(high, h);
            low = Double.isInfinite(low) ? l : Math.min(low, l);
            close = c;
            complete = true;
        }
    }

    @Override
    public void initialize(Defaults defaults) {
        SettingsDescriptor sd = createSD();
        SettingTab tab = sd.addTab("Lucid 25K Gold Fix (10:15)");
        SettingGroup group = tab.addGroup("Breakout & Risk Management");

        group.addRow(new DoubleDescriptor(MIN_RETURN_PCT, "Min 15m Fix Return (0.1125% = 0.001125)", 0.001125, 0.0001, 0.0050, 0.0001));
        group.addRow(new DoubleDescriptor(MIN_LONG_CLOSE_LOC, "Min Long Close Location (0.70)", 0.70, 0.50, 0.95, 0.05));
        group.addRow(new DoubleDescriptor(REWARD_RISK_RATIO, "Target Reward / Risk Ratio (1.50x)", 1.5, 0.5, 3.0, 0.1));
        group.addRow(new DoubleDescriptor(RISK_BUDGET_DOLLARS, "Risk Budget / Trade ($250 for Lucid 25K)", 250.0, 50.0, 500.0, 10.0));
        group.addRow(new IntegerDescriptor(RATCHET_TIER_OVERRIDE, "Ratchet Sizing Override (0=Auto-Sync Daemon State, 1/2/3/4 Micros)", 0, 0, 4, 1));
        group.addRow(new DoubleDescriptor(MIN_STOP_POINTS, "Min Stop Distance Points (Gold 3.0)", 3.0, 1.0, 10.0, 0.5));
        group.addRow(new DoubleDescriptor(MAX_STOP_POINTS, "Max Stop Distance Points (Gold 18.0)", 18.0, 10.0, 35.0, 1.0));
        group.addRow(new BooleanDescriptor(REQUIRE_OUTSIDE_PRIOR_VA, "Require Breakout Above Prior Day VAH", true));
        group.addRow(new BooleanDescriptor(REQUIRE_OUTSIDE_LONDON_RANGE, "Require Breakout Above London Session High", true));
        group.addRow(new BooleanDescriptor(REQUIRE_OUTSIDE_IB60, "Require Breakout Above COMEX IB60 High", true));
        group.addRow(new BooleanDescriptor(ENABLE_SOUND_ALERT, "Enable Sound Alert & Notification", true));
        group.addRow(new BooleanDescriptor(SHOW_LEVEL_LINES, "Show SL / TP / Entry / 11:00 Exit Lines", true));
        group.addRow(new BooleanDescriptor(HIDE_LINES_WHEN_LIVE, "Hide Custom Lines When Live Auto-Trade Active (Use Native Orders)", true));
        group.addRow(new BooleanDescriptor(SHOW_NO_SETUP_MARKER, "Show 'No Setup' Reason Marker at 10:15", false));
        group.addRow(new BooleanDescriptor(ENABLE_LIVE_AUTOTRADE, "Enable Live Auto-Trading (CQG Execution)", true));

        setSettingsDescriptor(sd);

        RuntimeDescriptor rd = createRD();
        rd.declareSignal(SIGNAL_BUY, "Gold LBMA PM Fix Buy (10:15 ET)");
        setRuntimeDescriptor(rd);
    }

    @Override
    protected void calculate(int index, DataContext ctx) {
        DataSeries series = ctx.getDataSeries();
        if (series == null || index < 0 || index >= series.size()) return;

        if (index == 0) {
            clearFigures();
            rthProfilesByDate.clear();
            londonByDate.clear();
            ibByDate.clear();
            fixByDate.clear();
            processedDays.clear();
            tradesByDate.clear();
        }

        long barStartTime = series.getStartTime(index);
        ZonedDateTime zdt = Instant.ofEpochMilli(barStartTime).atZone(NY_ZONE);
        int hour = zdt.getHour();
        int min = zdt.getMinute();
        int mOfDay = hour * 60 + min;
        LocalDate today = zdt.toLocalDate();

        double high = series.getHigh(index);
        double low = series.getLow(index);
        double open = series.getOpen(index);
        double close = series.getClose(index);
        long volume = series.getVolume(index);

        double tickSize = 0.10; // Gold standard tick size
        if (series.getInstrument() != null) {
            tickSize = Math.max(0.01, series.getInstrument().getTickSize());
        }

        // 1. Accumulate Prior COMEX RTH Session Profile (08:20 - 13:30 ET = 500 to 810 mins)
        if (mOfDay >= 500 && mOfDay <= 810) {
            ComexRthProfile prof = rthProfilesByDate.computeIfAbsent(today, d -> new ComexRthProfile());
            prof.addBar(high, low, close, volume, tickSize);
        }

        // Finalize prior completed sessions
        for (Map.Entry<LocalDate, ComexRthProfile> entry : rthProfilesByDate.entrySet()) {
            if (entry.getKey().isBefore(today) && !entry.getValue().computed) {
                entry.getValue().computeValueArea(tickSize);
            }
        }

        // 2. Track London Session Range (03:00 - 08:19 ET = 180 to 499 mins)
        if (mOfDay >= 180 && mOfDay < 500) {
            LondonRange lon = londonByDate.computeIfAbsent(today, d -> new LondonRange());
            lon.addBar(high, low);
        }

        // 3. Track COMEX IB60 Range (08:20 - 09:19 ET = 500 to 559 mins)
        if (mOfDay >= 500 && mOfDay < 560) {
            Ib60Range ib = ibByDate.computeIfAbsent(today, d -> new Ib60Range());
            ib.addBar(high, low);
        }

        // 4. Track LBMA PM Fix Window (10:00 - 10:14 ET = 600 to 614 mins)
        if (mOfDay >= 600 && mOfDay < 615) {
            Fix15Range fix = fixByDate.computeIfAbsent(today, d -> new Fix15Range());
            fix.addBar(open, high, low, close);
        }

        // 5. Evaluate Signal on the first bar at or after 10:15:00 ET sharp
        if (mOfDay >= 615 && !processedDays.contains(today)) {
            processedDays.add(today);

            LocalDate priorDay = null;
            for (LocalDate d : rthProfilesByDate.keySet()) {
                if (d.isBefore(today)) {
                    if (priorDay == null || d.isAfter(priorDay)) {
                        priorDay = d;
                    }
                }
            }

            ComexRthProfile priorProf = (priorDay != null) ? rthProfilesByDate.get(priorDay) : null;
            if (priorProf != null && !priorProf.computed) {
                priorProf.computeValueArea(tickSize);
            }

            LondonRange lon = londonByDate.get(today);
            Ib60Range ib = ibByDate.get(today);
            Fix15Range fix = fixByDate.get(today);

            if (fix != null && fix.complete && !Double.isNaN(fix.open)) {
                double fixRange = fix.high - fix.low;
                double fixRetPct = (fix.close - fix.open) / fix.open;
                double fixCloseLoc = (fixRange > 0.0) ? (fix.close - fix.low) / fixRange : 0.5;

                double minRet = getSettings().getDouble(MIN_RETURN_PCT, 0.001125);
                double minLongLoc = getSettings().getDouble(MIN_LONG_CLOSE_LOC, 0.70);
                double rrRatio = getSettings().getDouble(REWARD_RISK_RATIO, 1.5);
                double riskBudget = getSettings().getDouble(RISK_BUDGET_DOLLARS, 250.0);
                int ratchetOverride = getSettings().getInteger(RATCHET_TIER_OVERRIDE, 0);
                double minStopPts = getSettings().getDouble(MIN_STOP_POINTS, 3.0);
                double maxStopPts = getSettings().getDouble(MAX_STOP_POINTS, 18.0);
                boolean reqVA = getSettings().getBoolean(REQUIRE_OUTSIDE_PRIOR_VA, true);
                boolean reqLon = getSettings().getBoolean(REQUIRE_OUTSIDE_LONDON_RANGE, true);
                boolean reqIB = getSettings().getBoolean(REQUIRE_OUTSIDE_IB60, true);
                boolean soundAlert = getSettings().getBoolean(ENABLE_SOUND_ALERT, true);
                boolean showLines = getSettings().getBoolean(SHOW_LEVEL_LINES, true);
                boolean hideWhenLive = getSettings().getBoolean(HIDE_LINES_WHEN_LIVE, true);
                boolean isLive = getSettings().getBoolean(ENABLE_LIVE_AUTOTRADE, false);
                if (hideWhenLive && isLive) {
                    showLines = false;
                }

                double priorVah = (priorProf != null && !Double.isNaN(priorProf.vah)) ? priorProf.vah : Double.NaN;
                double lonHigh = (lon != null && !Double.isInfinite(lon.high)) ? lon.high : Double.NaN;
                double ib60High = (ib != null && !Double.isInfinite(ib.high)) ? ib.high : Double.NaN;

                boolean vaPass = !reqVA || (!Double.isNaN(priorVah) && fix.close > priorVah);
                boolean lonPass = !reqLon || (!Double.isNaN(lonHigh) && fix.close > lonHigh);
                boolean ibPass = !reqIB || (!Double.isNaN(ib60High) && fix.close > ib60High);

                boolean isLong = (fixRetPct >= minRet) && (fixCloseLoc >= minLongLoc) && vaPass && lonPass && ibPass;

                String sym = (series.getInstrument() != null) ? series.getInstrument().getSymbol().toUpperCase() : "GC";
                boolean isFullGC = sym.equals("GC") && !sym.contains("MGC");
                double ptVal = isFullGC ? 10.00 : 1.00; // $1.00 per point on MGC ($0.10 per 0.10 tick)
                String microSym = isFullGC ? "GC" : "MGC";

                if (isLong) {
                    double stopPts = Math.min(maxStopPts, Math.max(minStopPts, fixRange));

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
                    double stopPrice = entryPrice - stopPts;
                    double targetPts = stopPts * rrRatio;
                    double targetPrice = entryPrice + targetPts;
                    double actualRiskDollars = stopPts * ptVal * contracts;
                    double actualRewardDollars = targetPts * ptVal * contracts;

                    long entryTime = barStartTime;                 // 10:15:00 ET
                    long exitTime = entryTime + (45 * 60 * 1000L); // 11:00:00 ET

                    ActiveTrade trade = new ActiveTrade();
                    trade.date = today;
                    trade.entryPrice = entryPrice;
                    trade.stopPrice = stopPrice;
                    trade.targetPrice = targetPrice;
                    trade.entryTime = entryTime;
                    trade.maxExitTime = exitTime;
                    trade.contracts = contracts;
                    trade.microSym = microSym;
                    trade.ptVal = ptVal;
                    trade.closed = false;

                    Coordinate coord = new Coordinate(entryTime, low - (stopPts * 0.10));
                    MarkerInfo info = new MarkerInfo(Enums$MarkerType.ARROW, Enums$Size.MEDIUM, new Color(0, 204, 102), new Color(0, 204, 102), true);
                    Marker marker = new Marker(coord, Enums$Position.BOTTOM, info);
                    marker.setTextValue(String.format("GOLD BUY %dx %s @ %.2f", contracts, microSym, entryPrice));
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
                        exitLine.setText("11:00 FLATTEN", LINE_FONT);
                        if (exitLine.getText() != null) {
                            exitLine.getText().setShowBorder(false);
                            exitLine.getText().setBackground(null);
                        }
                        addFigure(exitLine);
                    }

                    ctx.signal(index, SIGNAL_BUY, String.format("GOLD FIX BUY %dx %s @ %.2f (SL: %.2f, TP: %.2f)", contracts, microSym, entryPrice, stopPrice, targetPrice), entryPrice);

                    tradesByDate.put(today, trade);

                    if (soundAlert) {
                        Toolkit.getDefaultToolkit().beep();
                    }
                } else if (getSettings().getBoolean(SHOW_NO_SETUP_MARKER, true)) {
                    StringBuilder reason = new StringBuilder("NO GOLD FIX TRADE: ");
                    if (fixRetPct < minRet) {
                        reason.append(String.format("Weak Fix Return (%+.2f%% vs req >= +%.2f%%)", fixRetPct * 100.0, minRet * 100.0));
                    } else if (fixCloseLoc < minLongLoc) {
                        reason.append(String.format("Upper Wick Reject (CloseLoc: %.2f vs req >= %.2f)", fixCloseLoc, minLongLoc));
                    } else if (!vaPass) {
                        reason.append(String.format("Inside Prior VAH (%.2f vs close %.2f)", priorVah, fix.close));
                    } else if (!ibPass) {
                        reason.append(String.format("Inside COMEX IB60 High (%.2f vs close %.2f)", ib60High, fix.close));
                    } else if (!lonPass) {
                        reason.append(String.format("Inside London High (%.2f vs close %.2f)", lonHigh, fix.close));
                    } else {
                        reason.append("3-Way barrier criteria not met");
                    }

                    Coordinate coord = new Coordinate(barStartTime, high + (tickSize * 4));
                    MarkerInfo info = new MarkerInfo(Enums$MarkerType.CIRCLE, Enums$Size.MEDIUM, new Color(100, 100, 100), Color.WHITE, Color.LIGHT_GRAY, true);
                    Marker marker = new Marker(coord, Enums$Position.TOP, info);
                    marker.setTextValue(reason.toString());
                    addFigure(marker);
                }
            }
        }

        // 6. Bar-by-Bar Active Trade Lifecycle & Outcome Tracker (Non-Repainting)
        ActiveTrade activeTrade = tradesByDate.get(today);
        if (activeTrade != null && !activeTrade.closed && barStartTime > activeTrade.entryTime) {
            boolean exitTriggered = false;
            double exitPrice = 0.0;
            String outcomeText = "";
            Color outcomeColor = Color.GREEN;

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
            } else if (barStartTime >= activeTrade.maxExitTime || (mOfDay >= 660)) { // 11:00 ET = 660 mins
                exitTriggered = true;
                exitPrice = close;
                double pts = exitPrice - activeTrade.entryPrice;
                double netDollars = pts * activeTrade.ptVal * activeTrade.contracts;
                outcomeText = String.format("TIME EXIT (11:00): %.2f (%+.2f pts | %s$%.2f)",
                    exitPrice, pts, netDollars >= 0 ? "+" : "-", Math.abs(netDollars));
                outcomeColor = Color.CYAN;
            }

            if (exitTriggered) {
                activeTrade.closed = true;
                if (activeTrade.slLine != null) activeTrade.slLine.setEnd(barStartTime, activeTrade.stopPrice);
                if (activeTrade.tpLine != null) activeTrade.tpLine.setEnd(barStartTime, activeTrade.targetPrice);
                if (activeTrade.entryLine != null) activeTrade.entryLine.setEnd(barStartTime, activeTrade.entryPrice);

                double markerY = exitPrice + (tickSize * 6);
                Coordinate coord = new Coordinate(barStartTime, markerY);
                MarkerInfo info = new MarkerInfo(Enums$MarkerType.CIRCLE, Enums$Size.LARGE, outcomeColor, outcomeColor, true);
                Marker marker = new Marker(coord, Enums$Position.TOP, info);
                marker.setTextValue(outcomeText);
                if (marker.getText() != null) {
                    marker.getText().setShowBorder(false);
                    marker.getText().setBackground(null);
                }
                addFigure(marker);
            }
        }
    }

    // =========================================================================
    // MOTIVEWAVE STRATEGY & AUTOMATED ORDER EXECUTION LIFECYCLE (CQG / RITHMIC)
    // =========================================================================

    @Override
    public void onActivate(OrderContext ctx) {
        setState(Enums$StrategyState.ACTIVE);
        logExecutionEvent("STRATEGY_ACTIVATED", "LucidGoldFixBreakout",
            ctx != null ? ctx.getInstrument().getSymbol() : "MGC",
            "ACTIVE", 0.0, 0.0, 0.0, 0, "Strategy armed by user in MotiveWave");
    }

    @Override
    public void onSignal(OrderContext ctx, Object signal) {
        if (ctx == null) return;
        if (!getSettings().getBoolean(ENABLE_LIVE_AUTOTRADE, true)) return;
        executeAutoTradeIfArmed(ctx, signal);
    }

    @Override
    public void onBarClose(OrderContext ctx) {
        if (ctx == null) return;
        boolean liveAuthorized = getSettings().getBoolean(ENABLE_LIVE_AUTOTRADE, true);

        long now = ctx.getCurrentTime();
        LocalDate today = Instant.ofEpochMilli(now).atZone(NY_ZONE).toLocalDate();

        // 1. If flat and no trade submitted today, check if an unsubmitted trade signal exists for today
        if (ctx.getPosition() == 0 && liveAuthorized) {
            if (DAILY_SUBMITTED_DATES.contains(today)) return; // Session cooldown locked
            ActiveTrade trade = tradesByDate.get(today);
            if (trade != null && !trade.orderSubmitted && !trade.closed && now >= trade.entryTime && now < trade.maxExitTime) {
                executeAutoTradeIfArmed(ctx, SIGNAL_BUY);
            }
        }

        // 2. Reconcile restart state / Automated Hard Session Close Flatten at 11:00 ET
        if (ctx.getPosition() != 0) {
            DAILY_SUBMITTED_DATES.add(today);
            File lockFile = getDailyLockFile("gold_london_fix_s3", today);
            if (lockFile != null && !lockFile.exists()) {
                try {
                    if (!lockFile.createNewFile()) {
                        logExecutionEvent("RESTART_DAILY_LOCK_NOT_CREATED", "LucidGoldFixBreakout",
                            ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                            "BLOCKED", 0.0, 0.0, 0.0, Math.abs(ctx.getPosition()), "Lock already exists or could not be created.");
                    }
                } catch (Exception e) {
                    logExecutionEvent("RESTART_DAILY_LOCK_CREATE_FAILED", "LucidGoldFixBreakout",
                        ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                        "BLOCKED", 0.0, 0.0, 0.0, Math.abs(ctx.getPosition()), e.getMessage());
                }
            }

            ActiveTrade trade = tradesByDate.get(today);
            if (trade == null && RESTART_POSITION_REPORTED.add(today)) {
                logExecutionEvent("RESTART_POSITION_UNRECONCILED", "LucidGoldFixBreakout",
                    ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                    "BLOCKED", 0.0, 0.0, 0.0, Math.abs(ctx.getPosition()),
                    "Position is open but no active trade/order identities were recovered; preserve existing broker orders and do not recreate protection.");
            } else if (trade != null && !trade.restartCoverageReported
                    && (trade.slOrder == null || !trade.slOrder.isActive() || trade.slOrder.isCancelled())) {
                trade.restartCoverageReported = true;
                logExecutionEvent("RESTART_PROTECTIVE_COVERAGE_UNVERIFIED", "LucidGoldFixBreakout",
                    ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                    "BLOCKED", 0.0, trade.stopPrice, trade.targetPrice, Math.abs(ctx.getPosition()),
                    "Position is open but no working stop is confirmed; preserve broker state and do not recreate protection automatically.");
            }
            if (trade != null && trade.flattenPending && !trade.flattenSubmitted) {
                submitMarketFlatten(ctx, trade, trade.flattenEvent, trade.flattenReason);
            }
            if (trade != null && trade.bracketsSubmitted && trade.attachedBracketQty != Math.abs(ctx.getPosition())) {
                int contracts = Math.abs(ctx.getPosition());
                boolean syncConfirmed = false;
                try {
                    if (trade.slOrder == null || !trade.slOrder.isActive() || trade.slOrder.isCancelled()
                            || trade.slOrder.isFilled()) {
                        throw new IllegalStateException("Protective stop is not active.");
                    }
                    trade.slOrder.setAdjQuantity(contracts);
                    ctx.submitOrders(trade.slOrder);
                    if (trade.tpOrder != null && trade.tpOrder.isActive() && !trade.tpOrder.isCancelled()
                            && !trade.tpOrder.isFilled()) {
                        trade.tpOrder.setAdjQuantity(contracts);
                        ctx.submitOrders(trade.tpOrder);
                    }
                    Float stopPrice = trade.slOrder.getStopPrice();
                    boolean stopConfirmed = trade.slOrder.isActive()
                        && trade.slOrder.getQuantity() == contracts && stopPrice != null
                        && Math.abs(stopPrice - trade.stopPrice) <= ctx.getInstrument().getTickSize() / 2.0;
                    boolean targetConfirmed = trade.tpOrder == null || !trade.tpOrder.isActive()
                        || (trade.tpOrder.getQuantity() == contracts && trade.tpOrder.getLimitPrice() != null
                            && Math.abs(trade.tpOrder.getLimitPrice() - trade.targetPrice)
                                <= ctx.getInstrument().getTickSize() / 2.0);
                    syncConfirmed = stopConfirmed && targetConfirmed;
                    if (syncConfirmed) trade.attachedBracketQty = contracts;
                } catch (RuntimeException e) {
                    logExecutionEvent("BRACKET_QTY_SYNC_EXCEPTION", "LucidGoldFixBreakout",
                        ctx.getInstrument().getSymbol(), "BLOCKED", 0.0, trade.stopPrice,
                        trade.targetPrice, contracts, e.getMessage());
                }
                if (!syncConfirmed) {
                    submitMarketFlatten(ctx, trade, "BRACKET_QTY_SYNC_UNCONFIRMED",
                        "Protective stop or active target quantity does not match the live position.");
                }
            }

            long barTime = ctx.getCurrentTime();
            ZonedDateTime zdt = Instant.ofEpochMilli(barTime).atZone(NY_ZONE);
            int hour = zdt.getHour();
            int min = zdt.getMinute();

            if (hour > 11 || (hour == 11 && min >= 0)) {
                if (trade != null) {
                    if (trade.tpOrder != null && trade.tpOrder.isActive()) ctx.cancelOrders(trade.tpOrder);
                    submitMarketFlatten(ctx, trade, "TIME_EXIT_FLATTEN", "11:00 ET session close boundary reached");
                } else {
                    logExecutionEvent("RESTART_POSITION_UNRECONCILED", "LucidGoldFixBreakout",
                        ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                        "BLOCKED", 0.0, 0.0, 0.0, Math.abs(ctx.getPosition()),
                        "Position is open but no active trade/order identities were recovered; do not recreate brackets.");
                }
            }
        }
    }

    private synchronized void executeAutoTradeIfArmed(OrderContext ctx, Object signal) {
        if (ctx.getPosition() != 0) return; // Prevent double-entry / pyramiding

        long now = ctx.getCurrentTime();
        LocalDate today = Instant.ofEpochMilli(now).atZone(NY_ZONE).toLocalDate();

        // Strict Single-Trade-Per-Day Enforcement with Persistent Disk Lock (IAF Cooldown Lock)
        File lockFile = getDailyLockFile("gold_london_fix_s3", today);
        if (DAILY_SUBMITTED_DATES.contains(today) || (lockFile != null && lockFile.exists())) {
            DAILY_SUBMITTED_DATES.add(today);
            logExecutionEvent("ORDER_BLOCKED_SESSION_COOLDOWN", "LucidGoldFixBreakout",
                ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                "BLOCKED", 0.0, 0.0, 0.0, 0,
                "Single trade per session lock active for " + today + ". Additional entries blocked.");
            return;
        }

        // Gateway-level circuit breaker check
        DaemonRiskState riskState = loadDaemonRiskState();
        if (riskState.circuitBreakerHit) {
            logExecutionEvent("CIRCUIT_BREAKER_BLOCKED", "LucidGoldFixBreakout", ctx.getInstrument().getSymbol(),
                "BLOCKED", 0.0, 0.0, 0.0, 0, "Daily soft-stop -$600 reached in demo parity state");
            return;
        }

        ActiveTrade trade = tradesByDate.get(today);
        if (trade == null || trade.orderSubmitted || trade.closed) return;

        int contracts = resolveContracts(ctx, trade.contracts);
        if (contracts <= 0) {
            logExecutionEvent("ORDER_BLOCKED_UNVERIFIED_ACCOUNT", "LucidGoldFixBreakout",
                ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                "BLOCKED", 0.0, 0.0, 0.0, 0,
                "Account context unverified or sizing returned zero; order entry blocked (fail-closed).");
            return;
        }
        trade.contracts = contracts;

        float stopPrice = ctx.getInstrument().round((float) trade.stopPrice);
        float targetPrice = ctx.getInstrument().round((float) trade.targetPrice);

        setStopPrice(stopPrice);
        setTargetPrice(targetPrice);

        // Atomic lock acquisition before submitting order to broker
        if (lockFile != null) {
            try {
                if (!lockFile.createNewFile()) {
                    DAILY_SUBMITTED_DATES.add(today);
                    logExecutionEvent("ORDER_BLOCKED_SESSION_COOLDOWN", "LucidGoldFixBreakout",
                        ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                        "BLOCKED", 0.0, 0.0, 0.0, 0, "Atomic lock acquisition failed for " + today);
                    return;
                }
            } catch (Exception e) {
                DAILY_SUBMITTED_DATES.add(today);
                logExecutionEvent("ORDER_BLOCKED_SESSION_COOLDOWN", "LucidGoldFixBreakout",
                    ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                    "BLOCKED", 0.0, 0.0, 0.0, 0, "Lock file creation failed: " + e.getMessage());
                return;
            }
        }
        DAILY_SUBMITTED_DATES.add(today);

        // Gold London Fix is a Long Breakout strategy
        Order entry = ctx.createMarketOrder(Enums$OrderAction.BUY, contracts);
        trade.entryOrder = entry;
        trade.orderSubmitted = true;
        trade.entryOrderId = entry != null ? entry.getOrderId() : null;
        ctx.submitOrders(entry);

        logExecutionEvent("ORDER_SUBMITTED", "LucidGoldFixBreakout", ctx.getInstrument().getSymbol(),
            "BUY", trade.entryPrice, stopPrice, targetPrice, contracts,
            "Market entry submitted. Brackets pending fill confirmation. Daily cooldown locked.");
    }

    @Override
    public void onOrderFilled(OrderContext ctx, Order order) {
        if (ctx == null || order == null) return;
        long now = ctx.getCurrentTime();
        LocalDate today = Instant.ofEpochMilli(now).atZone(NY_ZONE).toLocalDate();
        ActiveTrade trade = tradesByDate.get(today);

        logExecutionEvent("ORDER_FILLED", "LucidGoldFixBreakout", ctx.getInstrument().getSymbol(),
            order.getAction().toString(), order.getAvgFillPrice(), 0.0, 0.0, order.getQuantity(),
            "Order filled: id=" + order.getOrderId() + " pos=" + ctx.getPosition());

        boolean isTrackedEntry = (trade != null) && (trade.entryOrderId != null && trade.entryOrderId.equals(order.getOrderId()));
        if (trade != null && trade.flattenSubmitted
                && (order == trade.flattenOrder || (trade.flattenOrderId != null && trade.flattenOrderId.equals(order.getOrderId())))) {
            if (order.isActive() || (!order.isFilled() && !order.isCancelled())) {
                logExecutionEvent("FLATTEN_FILL_STATUS_UNCERTAIN_DUPLICATE_SUPPRESSED",
                    "LucidGoldFixBreakout", ctx.getInstrument().getSymbol(), "WAIT", 0.0,
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
                logExecutionEvent("FLATTEN_PARTIAL_FILL_REMAINS_OPEN", "LucidGoldFixBreakout", ctx.getInstrument().getSymbol(),
                    "FLATTEN", 0.0, trade.stopPrice, trade.targetPrice, Math.abs(ctx.getPosition()),
                    "Flatten order filled partially; remaining position is still open.");
                submitMarketFlatten(ctx, trade, trade.flattenEvent, trade.flattenReason);
            }
            return;
        }
        if (trade != null && trade.flattenPending && ctx.getPosition() != 0
                && (order == trade.entryOrder || (trade.entryOrderId != null && trade.entryOrderId.equals(order.getOrderId()))
                    || order == trade.slOrder || order == trade.tpOrder)) {
            submitMarketFlatten(ctx, trade, trade.flattenEvent, trade.flattenReason);
            return;
        }
        if (ctx.getPosition() != 0 && trade != null && !trade.bracketSetupAttempted && isTrackedEntry) {
            trade.entryFilled = true;
            int contracts = Math.abs(ctx.getPosition());
            double actualFill = ctx.getAvgEntryPrice() > 0 ? ctx.getAvgEntryPrice()
                : (order.getAvgFillPrice() > 0 ? order.getAvgFillPrice() : trade.entryPrice);
            double riskDist = Math.abs(trade.entryPrice - trade.stopPrice);
            double targetDist = Math.abs(trade.targetPrice - trade.entryPrice);
            trade.initialRiskDist = riskDist;
            trade.initialTargetDist = targetDist;
            float stopPrice = ctx.getInstrument().round((float) (actualFill - riskDist));
            float targetPrice = ctx.getInstrument().round((float) (actualFill + targetDist));
            trade.actualEntryFill = actualFill;
            trade.stopPrice = stopPrice;
            trade.targetPrice = targetPrice;
            submitInitialBrackets(ctx, trade, contracts, actualFill, stopPrice, targetPrice);
        } else if (ctx.getPosition() != 0 && trade != null && trade.bracketsSubmitted && isTrackedEntry) {
            int contracts = Math.abs(ctx.getPosition());
            double actualFill = ctx.getAvgEntryPrice() > 0 ? ctx.getAvgEntryPrice()
                : (order.getAvgFillPrice() > 0 ? order.getAvgFillPrice() : trade.actualEntryFill);
            double riskDist = Double.isFinite(trade.initialRiskDist) ? trade.initialRiskDist : Math.abs(trade.entryPrice - trade.stopPrice);
            double targetDist = Double.isFinite(trade.initialTargetDist) ? trade.initialTargetDist : Math.abs(trade.targetPrice - trade.entryPrice);
            float stopPrice = ctx.getInstrument().round((float) (actualFill - riskDist));
            float targetPrice = ctx.getInstrument().round((float) (actualFill + targetDist));
            try {
                if (trade.slOrder == null || !trade.slOrder.isActive() || trade.slOrder.isCancelled()) {
                    throw new IllegalStateException("Protective stop is not active.");
                }
                trade.slOrder.setAdjStopPrice(stopPrice);
                trade.slOrder.setAdjQuantity(contracts);
                ctx.submitOrders(trade.slOrder);
                if (trade.tpOrder != null && trade.tpOrder.isActive() && !trade.tpOrder.isCancelled()) {
                    trade.tpOrder.setAdjLimitPrice(targetPrice);
                    trade.tpOrder.setAdjQuantity(contracts);
                    ctx.submitOrders(trade.tpOrder);
                }
                Float confirmedStop = trade.slOrder.getStopPrice();
                boolean stopConfirmed = trade.slOrder.isActive() && trade.slOrder.getQuantity() == contracts
                    && confirmedStop != null && Math.abs(confirmedStop - stopPrice)
                        <= ctx.getInstrument().getTickSize() / 2.0;
                boolean targetConfirmed = trade.tpOrder == null || !trade.tpOrder.isActive()
                    || (trade.tpOrder.getQuantity() == contracts && trade.tpOrder.getLimitPrice() != null
                        && Math.abs(trade.tpOrder.getLimitPrice() - targetPrice)
                            <= ctx.getInstrument().getTickSize() / 2.0);
                if (!stopConfirmed || !targetConfirmed) {
                    throw new IllegalStateException("Updated protective order quantity/price was not confirmed.");
                }
                trade.actualEntryFill = actualFill;
                trade.entryPrice = actualFill;
                trade.stopPrice = stopPrice;
                trade.targetPrice = targetPrice;
                trade.attachedBracketQty = contracts;
                logExecutionEvent("PARTIAL_FILL_SYNC_CONFIRMED", "LucidGoldFixBreakout",
                    ctx.getInstrument().getSymbol(), order.getAction().toString(), actualFill,
                    trade.stopPrice, trade.targetPrice, contracts,
                    "Protective stop and active target quantity/price match current position.");
            } catch (RuntimeException e) {
                submitMarketFlatten(ctx, trade, "PARTIAL_FILL_BRACKET_SYNC_FAILED", e.getMessage());
            }
        } else if (ctx.getPosition() == 0) {
            ctx.cancelOrders();
            if (trade != null) {
                trade.closed = true;
                trade.flattenPending = false;
            }
            logExecutionEvent("POSITION_FLAT", "LucidGoldFixBreakout", ctx.getInstrument().getSymbol(),
                "FLAT", 0.0, 0.0, 0.0, 0, "Position closed, unfulfilled bracket orders cancelled.");
        }
    }

    private void submitInitialBrackets(OrderContext ctx, ActiveTrade trade, int contracts,
        double actualFill, float stopPrice, float targetPrice) {
        if (trade.bracketSetupAttempted) return;
        trade.bracketSetupAttempted = true;
        trade.bracketsSubmitted = false;
        trade.attachedBracketQty = 0;
        Enums$OrderAction exitAction = Enums$OrderAction.SELL;
        Order sl = null;
        Order tp = null;
        try {
            sl = ctx.createStopOrder(exitAction, Enums$TIF.GTC, contracts, stopPrice);
        } catch (RuntimeException e) {
            logExecutionEvent("PROTECTIVE_STOP_CREATION_FAILED", "LucidGoldFixBreakout",
                ctx.getInstrument().getSymbol(), exitAction.toString(), actualFill, stopPrice,
                targetPrice, contracts, e.getMessage());
        }
        try {
            tp = ctx.createLimitOrder(exitAction, Enums$TIF.GTC, contracts, targetPrice);
        } catch (RuntimeException e) {
            logExecutionEvent("PROFIT_TARGET_CREATION_FAILED_OPTIONAL", "LucidGoldFixBreakout",
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
                logExecutionEvent("PROTECTIVE_STOP_SUBMISSION_STATUS_UNKNOWN", "LucidGoldFixBreakout",
                    ctx.getInstrument().getSymbol(), exitAction.toString(), actualFill, stopPrice,
                    targetPrice, contracts, e.getMessage());
            }
        }
        if (tp != null) {
            try {
                ctx.submitOrders(tp);
            } catch (RuntimeException e) {
                logExecutionEvent("PROFIT_TARGET_SUBMISSION_FAILED_OPTIONAL", "LucidGoldFixBreakout",
                    ctx.getInstrument().getSymbol(), exitAction.toString(), actualFill, stopPrice,
                    targetPrice, contracts, e.getMessage());
            }
        }
        Float confirmedStop = sl != null ? sl.getStopPrice() : null;
        double tickSize = ctx.getInstrument() != null ? ctx.getInstrument().getTickSize() : 0.01;
        boolean stopConfirmed = sl != null && sl.isActive() && !sl.isCancelled() && !sl.isFilled()
            && sl.getQuantity() == contracts && confirmedStop != null
            && Math.abs(confirmedStop - stopPrice) <= tickSize / 2.0;
        if (stopConfirmed) {
            trade.bracketsSubmitted = true;
            trade.attachedBracketQty = contracts;
            logExecutionEvent("PROTECTIVE_STOP_ACTIVE_STATE_VERIFIED", "LucidGoldFixBreakout",
                ctx.getInstrument().getSymbol(), exitAction.toString(), actualFill, stopPrice,
                targetPrice, contracts, "ORDER_ID=" + sl.getOrderId() + "|stop anchored to fill=" + actualFill);
        } else if (ctx.getPosition() != 0) {
            submitMarketFlatten(ctx, trade, "INITIAL_PROTECTIVE_STOP_UNCONFIRMED_EMERGENCY_FLATTEN",
                "Stop creation/submission did not yield an active order with the full open quantity and requested price.");
        }
        if (tp == null) {
            logExecutionEvent("PROFIT_TARGET_UNAVAILABLE_STOP_RETAINED", "LucidGoldFixBreakout",
                ctx.getInstrument().getSymbol(), exitAction.toString(), actualFill, stopPrice,
                targetPrice, contracts, "Target is optional; protective stop status is tracked independently.");
        }
    }

    @Override
    public void onOrderRejected(OrderContext ctx, Order order) {
        if (order == null) return;
        long now = ctx != null ? ctx.getCurrentTime() : System.currentTimeMillis();
        LocalDate today = Instant.ofEpochMilli(now).atZone(NY_ZONE).toLocalDate();
        ActiveTrade trade = tradesByDate.get(today);
        if (trade != null && (order == trade.flattenCancelPendingOrder
                || (trade.flattenCancelPendingOrder != null && trade.flattenCancelPendingOrder.getOrderId() != null
                    && trade.flattenCancelPendingOrder.getOrderId().equals(order.getOrderId())))) {
            if (order.isActive()) {
                trade.flattenCancelBlocked = true;
                logExecutionEvent("FLATTEN_CANCEL_REJECTED_ORDER_STILL_ACTIVE_OPERATOR_ACTION_REQUIRED",
                    "LucidGoldFixBreakout", ctx != null && ctx.getInstrument() != null
                        ? ctx.getInstrument().getSymbol() : "UNKNOWN", "WAIT", 0.0, trade.stopPrice,
                    trade.targetPrice, ctx != null ? Math.abs(ctx.getPosition()) : 0,
                    "ORDER_ID=" + order.getOrderId());
                return;
            }
            trade.flattenCancelPendingOrder = null;
            trade.flattenCancelBlocked = false;
        }
        if (trade != null && trade.flattenSubmitted
                && (order == trade.flattenOrder || (trade.flattenOrderId != null && trade.flattenOrderId.equals(order.getOrderId())))) {
            if (order.isActive()) {
                logExecutionEvent("FLATTEN_REJECTION_STATUS_UNCERTAIN_OPERATOR_ACTION_REQUIRED",
                    "LucidGoldFixBreakout", ctx != null && ctx.getInstrument() != null
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
            logExecutionEvent("FLATTEN_ORDER_REJECTED", "LucidGoldFixBreakout",
                ctx != null && ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                order.getAction().toString(), 0.0, trade.stopPrice, trade.targetPrice,
                ctx != null ? Math.abs(ctx.getPosition()) : 0, "REJECTED_ORDER_ID=" + order.getOrderId());
            return;
        }
        if (trade != null && (order == trade.entryOrder
                || (trade.entryOrderId != null && trade.entryOrderId.equals(order.getOrderId())))) {
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
            logExecutionEvent("ENTRY_ORDER_REJECTED", "LucidGoldFixBreakout",
                ctx != null && ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                order.getAction().toString(), 0.0, trade.stopPrice, trade.targetPrice,
                ctx != null ? Math.abs(ctx.getPosition()) : 0, "ENTRY_REJECTED:" + order.getOrderId());
            return;
        }
        if (trade != null && (order == trade.slOrder
                || (trade.slOrderId != null && trade.slOrderId.equals(order.getOrderId())))) {
            if (!order.isActive()) trade.slOrder = null;
            if (ctx != null && ctx.getPosition() != 0) {
                submitMarketFlatten(ctx, trade, "PROTECTIVE_STOP_REJECTED_EMERGENCY_FLATTEN", "Protective stop rejected while position open");
            }
        } else if (trade != null && (order == trade.tpOrder
                || (trade.tpOrderId != null && trade.tpOrderId.equals(order.getOrderId())))) {
            if (order.isActive() && ctx != null && ctx.getPosition() != 0) {
                submitMarketFlatten(ctx, trade, "TARGET_REJECTION_STATUS_UNCERTAIN_FLATTEN",
                    "Rejected target still reports active; cancel tracked exits before flattening.");
                return;
            }
            if (!order.isActive()) trade.tpOrder = null;
            logExecutionEvent("PROFIT_TARGET_REJECTED_STOP_RETAINED", "LucidGoldFixBreakout",
                ctx != null && ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                order.getAction().toString(), 0.0, trade.stopPrice, trade.targetPrice,
                ctx != null ? Math.abs(ctx.getPosition()) : 0, "TARGET_REJECTED:" + order.getOrderId());
            if (ctx != null && ctx.getPosition() != 0 && (trade.slOrder == null || !trade.slOrder.isActive())) {
                submitMarketFlatten(ctx, trade, "TARGET_REJECTED_WITHOUT_STOP_FLATTEN", "Target rejected and stop is not confirmed working");
            }
        }
        logExecutionEvent("ORDER_REJECTED", "LucidGoldFixBreakout",
            ctx != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
            order.getAction().toString(), 0.0, 0.0, 0.0, order.getQuantity(),
            "Order REJECTED by broker: id=" + order.getOrderId() + " type=" + order.getType());
    }

    @Override
    public void onOrderCancelled(OrderContext ctx, Order order) {
        if (order == null) return;
        long now = ctx != null ? ctx.getCurrentTime() : System.currentTimeMillis();
        LocalDate today = Instant.ofEpochMilli(now).atZone(NY_ZONE).toLocalDate();
        ActiveTrade trade = tradesByDate.get(today);
        if (trade != null && (order == trade.flattenCancelPendingOrder
                || (trade.flattenCancelPendingOrder != null && trade.flattenCancelPendingOrder.getOrderId() != null
                    && trade.flattenCancelPendingOrder.getOrderId().equals(order.getOrderId())))) {
            trade.flattenCancelPendingOrder = null;
            trade.flattenCancelBlocked = false;
        }
        if (trade != null && trade.flattenSubmitted
                && (order == trade.flattenOrder || (trade.flattenOrderId != null && trade.flattenOrderId.equals(order.getOrderId())))) {
            trade.flattenSubmitted = false;
            trade.flattenOrder = null;
            trade.flattenOrderId = null;
            if (ctx != null && ctx.getPosition() == 0) trade.closed = true;
            else trade.flattenPending = true;
            logExecutionEvent("FLATTEN_ORDER_CANCELLED", "LucidGoldFixBreakout",
                ctx != null && ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                order.getAction().toString(), 0.0, trade.stopPrice, trade.targetPrice,
                ctx != null ? Math.abs(ctx.getPosition()) : 0, "CANCELLED_ORDER_ID=" + order.getOrderId());
            return;
        }
        if (trade != null && order == trade.entryOrder) {
            trade.entryOrder = null;
            if (ctx != null && trade.flattenPending) submitMarketFlatten(ctx, trade, trade.flattenEvent, trade.flattenReason);
            return;
        }
        if (trade != null && (order == trade.slOrder
                || (trade.slOrderId != null && trade.slOrderId.equals(order.getOrderId())))) {
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
        if (trade != null && order == trade.tpOrder) {
            trade.tpOrder = null;
            if (ctx != null && trade.flattenPending) submitMarketFlatten(ctx, trade, trade.flattenEvent, trade.flattenReason);
        }
        logExecutionEvent("ORDER_CANCELLED", "LucidGoldFixBreakout",
            ctx != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
            order.getAction().toString(), 0.0, 0.0, 0.0, order.getQuantity(),
            "Order cancelled: id=" + order.getOrderId());
    }

    @Override
    public void onPositionClosed(OrderContext ctx) {
        if (ctx == null || ctx.getPosition() != 0) return;
        ctx.cancelOrders();
        long now = ctx != null ? ctx.getCurrentTime() : System.currentTimeMillis();
        LocalDate today = Instant.ofEpochMilli(now).atZone(NY_ZONE).toLocalDate();
        ActiveTrade trade = tradesByDate.get(today);
        if (trade != null) {
            trade.closed = true;
            trade.flattenSubmitted = false;
            trade.flattenOrder = null;
            trade.flattenOrderId = null;
            trade.flattenPending = false;
        }
        logExecutionEvent("POSITION_CLOSED_CONFIRMED", "LucidGoldFixBreakout",
            ctx != null && ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
            "FLAT", 0.0, 0.0, 0.0, 0, "Broker confirmed position closed.");
    }

    @Override
    public void onDeactivate(OrderContext ctx) {
        setState(Enums$StrategyState.INACTIVE);
        if (ctx != null) {
            if (ctx.getPosition() == 0) {
                ctx.cancelOrders();
            } else {
                logExecutionEvent("STRATEGY_DEACTIVATED_POSITION_REMAINS_OPEN", "LucidGoldFixBreakout",
                    ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "MGC",
                    "FLAT", 0.0, 0.0, 0.0, 0,
                    "Position open (" + ctx.getPosition() + "); protective orders preserved to prevent naked position exposure.");
            }
        }
        logExecutionEvent("STRATEGY_DEACTIVATED", "LucidGoldFixBreakout",
            ctx != null ? ctx.getInstrument().getSymbol() : "MGC",
            "INACTIVE", 0.0, 0.0, 0.0, 0, "Strategy deactivated by user");
    }

    private void submitMarketFlatten(OrderContext ctx, ActiveTrade trade, String event, String reason) {
        if (ctx == null || trade == null) return;
        if (ctx.getPosition() == 0) {
            trade.flattenPending = false;
            trade.closed = true;
            return;
        }
        trade.flattenPending = true;
        if (trade.flattenEvent.isEmpty()) {
            trade.flattenEvent = event;
            trade.flattenReason = reason;
        }
        if (trade.flattenSubmitted) return;
        if (trade.flattenCancelBlocked) {
            logExecutionEvent("FLATTEN_OPERATOR_ACTION_REQUIRED", "LucidGoldFixBreakout",
                ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                "WAIT", 0.0, trade.stopPrice, trade.targetPrice, Math.abs(ctx.getPosition()),
                "A tracked order cancellation was rejected or had unknown status; no market exit submitted.");
            return;
        }
        Order[] workingOrders = {trade.entryOrder, trade.tpOrder, trade.slOrder};
        for (Order workingOrder : workingOrders) {
            if (workingOrder == null || workingOrder.isCancelled() || workingOrder.isFilled()) continue;
            if (workingOrder == trade.slOrder) {
                int positionBeforeStopCancel = ctx.getPosition();
                if (positionBeforeStopCancel == 0) {
                    trade.flattenOrder = null;
                    trade.flattenPending = false;
                    trade.closed = true;
                    return;
                }
                trade.flattenCancelBlocked = true;
                logExecutionEvent("FLATTEN_NON_ATOMIC_TRANSITION_OPERATOR_ACTION_REQUIRED",
                    "LucidGoldFixBreakout", ctx.getInstrument() != null
                        ? ctx.getInstrument().getSymbol() : "UNKNOWN", "BLOCKED", 0.0,
                    trade.stopPrice, trade.targetPrice, Math.abs(positionBeforeStopCancel),
                    trade.flattenReason + "|PROTECTIVE_STOP_RETAINED|SDK_HAS_NO_REDUCE_ONLY_OR_ATOMIC_REPLACE");
                return;
            }
            if (trade.flattenCancelPendingOrder == workingOrder) return;
            trade.flattenCancelPendingOrder = workingOrder;
            try {
                ctx.cancelOrders(workingOrder);
                logExecutionEvent(workingOrder == trade.slOrder
                        ? "FLATTEN_WAITING_FOR_PROTECTIVE_STOP_CANCELLATION"
                        : "FLATTEN_WAITING_FOR_ENTRY_OR_TARGET_CANCELLATION", "LucidGoldFixBreakout",
                    ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                    "WAIT", 0.0, trade.stopPrice, trade.targetPrice, Math.abs(ctx.getPosition()),
                    trade.flattenReason + "|ORDER_ID=" + workingOrder.getOrderId());
            } catch (RuntimeException e) {
                trade.flattenCancelBlocked = true;
                logExecutionEvent("FLATTEN_CANCEL_STATUS_UNKNOWN_OPERATOR_ACTION_REQUIRED", "LucidGoldFixBreakout",
                    ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                    "WAIT", 0.0, trade.stopPrice, trade.targetPrice, Math.abs(ctx.getPosition()),
                    trade.flattenReason + "|ORDER_ID=" + workingOrder.getOrderId() + "|ERROR=" + e.getMessage());
            }
            return;
        }
        int currentPosition = ctx.getPosition();
        if (currentPosition == 0) {
            trade.flattenPending = false;
            trade.closed = true;
            return;
        }
        trade.flattenCancelBlocked = true;
        logExecutionEvent("FLATTEN_NON_ATOMIC_TRANSITION_OPERATOR_ACTION_REQUIRED",
            "LucidGoldFixBreakout",
            ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
            "BLOCKED", 0.0, trade.stopPrice, trade.targetPrice, Math.abs(currentPosition),
            trade.flattenReason + "|ALL_TRACKED_ORDERS_TERMINAL|NO_MARKET_EXIT_SUBMITTED|OPERATOR_MUST_RECONCILE_POSITION");
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
