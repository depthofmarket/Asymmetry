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
    id = "VA_BREAKOUT_ALGO_V2",
    name = "Lucid 25K — 1. Morning VA Breakout (09:45 ET)",
    desc = "09:45 ET Breakout outside Prior Day Value Area with $250 Volatility Risk Budgeting, 1.5x R:R Target, 10:00 AM News Guard, Live CQG Bracket Execution, and Live Trade Tracker",
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
public class LucidMorningVABreakoutStudy extends Study {

    private static final Font LINE_FONT = new Font("SansSerif", Font.BOLD, 10);
    private static final java.awt.BasicStroke DASHED_STROKE = new java.awt.BasicStroke(1.0f, java.awt.BasicStroke.CAP_BUTT, java.awt.BasicStroke.JOIN_MITER, 10.0f, new float[]{3.0f, 3.0f}, 0.0f);
    private static final java.awt.BasicStroke SOLID_STROKE = new java.awt.BasicStroke(1.5f);
    private static final Color BADGE_BG = new Color(15, 20, 26, 210);

    private static void styleLine(Line line, Color color, java.awt.Stroke stroke, String text, Font font, Color textColor, Color bgColor) {
        if (line == null) return;
        line.setColor(color);
        if (stroke != null) line.setStroke(stroke);
        if (text != null && font != null) {
            line.setText(text, font);
            com.motivewave.platform.sdk.draw.Text t = line.getText();
            if (t != null) {
                t.setShowBorder(false);
                t.setShowOutline(false);
                if (bgColor != null) t.setBackground(bgColor);
                if (textColor != null) t.setTextColor(textColor);
            }
        }
    }

    private static void styleMarker(Marker marker, String text, Color bgColor, Color textColor) {
        if (marker == null) return;
        if (text != null) {
            marker.setTextValue(text);
            com.motivewave.platform.sdk.draw.Text t = marker.getText();
            if (t != null) {
                t.setFont(LINE_FONT);
                t.setShowBorder(false);
                t.setShowOutline(false);
                if (bgColor != null) t.setBackground(bgColor);
                if (textColor != null) t.setTextColor(textColor);
            }
        }
    }

    // Settings Keys
    private static final String ENABLE_LIVE_AUTOTRADE = "enableLiveAutoTrade";
    private static final String MIN_RETURN_PCT = "minReturnPct";
    private static final String MIN_LONG_CLOSE_LOC = "minLongCloseLoc";
    private static final String MAX_SHORT_CLOSE_LOC = "maxShortCloseLoc";
    private static final String REWARD_RISK_RATIO = "rewardRiskRatio";
    private static final String RISK_BUDGET_DOLLARS = "riskBudgetDollars";
    private static final String RATCHET_TIER_OVERRIDE = "ratchetTierOverride";
    private static final String ENABLE_PAIR_SPLIT = "enablePairSplit";
    private static final String ENABLE_10AM_NEWS_GUARD = "enable10amNewsGuard";
    private static final String ENABLE_SOUND_ALERT = "enableSoundAlert";
    private static final String SHOW_LEVEL_LINES = "showLevelLines";
    private static final String HIDE_LINES_WHEN_LIVE = "hideLinesWhenLive";
    private static final String SHOW_TIME_EXIT_LINES = "showTimeExitLines";
    private static final String SHOW_NO_SETUP_MARKER = "showNoSetupMarker";
    private static final String SHOW_MVT_DP_LINES = "showMvtDpLines";
    private static final String ENABLE_GARCH_EXHAUSTION_GATE = "enableGarchExhaustionGate";
    private static final String GARCH_DAILY_VOL_PCT = "garchDailyVolPct";
    private static final String GARCH_EXHAUSTION_DP = "garchExhaustionDp";

    private static final ZoneId NY_ZONE = ZoneId.of("America/New_York");

    // Signal Keys
    private static final String SIGNAL_BUY = "LUCID_BUY_BREAKOUT";
    private static final String SIGNAL_SELL = "LUCID_SELL_BREAKOUT";

    // Session State Tracking
    private final Map<LocalDate, SessionProfile> profilesByDate = new HashMap<>();
    private final Map<LocalDate, OpeningRange15> orByDate = new HashMap<>();
    private final Set<LocalDate> processedDays = new HashSet<>();
    private final Map<LocalDate, ActiveTrade> tradesByDate = new HashMap<>();
    // IAF Session Cooldown Lock: strictly enforces <= 1 automated trade per session
    private static final Set<LocalDate> DAILY_SUBMITTED_DATES = java.util.concurrent.ConcurrentHashMap.newKeySet();
    private static final Set<LocalDate> RESTART_POSITION_REPORTED = java.util.concurrent.ConcurrentHashMap.newKeySet();

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
        boolean orderSubmitted = false;
        boolean entryFilled = false;
        boolean bracketsSubmitted = false;
        boolean flattenSubmitted = false;
        boolean flattenPending = false;
        boolean restartCoverageReported = false;
        String flattenEvent = "";
        String flattenReason = "";
        Order entryOrder;
        Order slOrder;
        Order tpOrder;
        Order flattenOrder;
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

    private static class SessionProfile {
        double rthHigh = Double.NEGATIVE_INFINITY;
        double rthLow = Double.POSITIVE_INFINITY;
        double rthVolume = 0.0;
        final Map<Long, Double> volumeByTick = new HashMap<>();
        double vah = Double.NaN;
        double val = Double.NaN;
        double poc = Double.NaN;
        boolean computed = false;

        void addBar(double high, double low, double close, long volume, double tickSize) {
            rthHigh = Math.max(rthHigh, high);
            rthLow = Math.min(rthLow, low);
            rthVolume += volume;

            long lowTick = Math.round(low / tickSize);
            long highTick = Math.round(high / tickSize);
            long tickCount = highTick - lowTick + 1;

            if (tickCount <= 1) {
                long tickKey = Math.round(close / tickSize);
                volumeByTick.put(tickKey, volumeByTick.getOrDefault(tickKey, 0.0) + (double) volume);
            } else {
                double volPerTick = (double) volume / tickCount;
                for (long t = lowTick; t <= highTick; t++) {
                    volumeByTick.put(t, volumeByTick.getOrDefault(t, 0.0) + volPerTick);
                }
            }
        }

        void computeValueArea(double tickSize) {
            if (computed || volumeByTick.isEmpty() || rthVolume <= 0) return;

            long bestTick = 0;
            double maxVol = -1.0;
            for (Map.Entry<Long, Double> e : volumeByTick.entrySet()) {
                if (e.getValue() > maxVol) {
                    maxVol = e.getValue();
                    bestTick = e.getKey();
                }
            }
            poc = bestTick * tickSize;

            double targetVol = rthVolume * 0.70;
            double currentVol = maxVol;
            long upTick = bestTick + 1;
            long downTick = bestTick - 1;

            while (currentVol < targetVol) {
                double upVol = volumeByTick.getOrDefault(upTick, 0.0);
                double downVol = volumeByTick.getOrDefault(downTick, 0.0);

                if (upVol == 0.0 && downVol == 0.0) {
                    if (upTick * tickSize > rthHigh && downTick * tickSize < rthLow) break;
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

    private static class OpeningRange15 {
        double open930 = Double.NaN;
        double high15 = Double.NEGATIVE_INFINITY;
        double low15 = Double.POSITIVE_INFINITY;
        double close944 = Double.NaN;
        double cumVolume = 0.0;
        double cumPriceVolume = 0.0;
        long startTime = 0;
        boolean complete = false;

        double getVwap() {
            return (cumVolume > 0.0) ? (cumPriceVolume / cumVolume) : close944;
        }
    }

    private static boolean is10amNewsDay(LocalDate date) {
        int day = date.getDayOfMonth();
        int dow = date.getDayOfWeek().getValue(); // 1=Mon .. 7=Sun
        if (dow == 3 && day <= 7) return true; // ISM Services (1st Wed)
        if (dow == 2 && day >= 24) return true; // CB Consumer Confidence (last Tue)
        if (dow == 5 && ((day >= 8 && day <= 14) || (day >= 22 && day <= 28))) return true; // UMich (2nd/4th Fri)
        if (day <= 3 && dow <= 4) return true; // ISM Mfg (1st business day)
        if ((day >= 3 && day <= 5) && (dow >= 1 && dow <= 3)) return true; // JOLTS (1st business Wed)
        return false;
    }

    @Override
    public void initialize(Defaults defaults) {
        SettingsDescriptor sd = createSD();
        SettingTab tab = sd.addTab("Lucid 25K VA Breakout (09:45)");
        SettingGroup group = tab.addGroup("Breakout & Risk Management");

        group.addRow(new BooleanDescriptor(ENABLE_LIVE_AUTOTRADE, "Enable Live Auto-Trading (CQG Execution)", true));
        group.addRow(new DoubleDescriptor(MIN_RETURN_PCT, "Min 15m Return (0.10% = 0.0010)", 0.0010, 0.0001, 0.0050, 0.0001));
        group.addRow(new DoubleDescriptor(MIN_LONG_CLOSE_LOC, "Min Long Close Location (0.60)", 0.60, 0.50, 0.95, 0.05));
        group.addRow(new DoubleDescriptor(MAX_SHORT_CLOSE_LOC, "Max Short Close Location (0.40)", 0.40, 0.05, 0.50, 0.05));
        group.addRow(new DoubleDescriptor(REWARD_RISK_RATIO, "Target Reward / Risk Ratio (1.50x)", 1.5, 0.5, 3.0, 0.1));
        group.addRow(new DoubleDescriptor(RISK_BUDGET_DOLLARS, "Risk Budget / Trade ($250 for Lucid 25K)", 250.0, 50.0, 500.0, 10.0));
        group.addRow(new IntegerDescriptor(RATCHET_TIER_OVERRIDE, "Ratchet Sizing Override (0=Auto-Sync Daemon State, 1/2/3/4 Micros)", 0, 0, 4, 1));
        group.addRow(new BooleanDescriptor(ENABLE_PAIR_SPLIT, "Split Sizing Across NQ/ES Pair (e.g. 1 MNQ + 1 MES in Tier 1)", false));
        group.addRow(new BooleanDescriptor(ENABLE_10AM_NEWS_GUARD, "Enable 10:00 AM News Guard Flatten", true));
        group.addRow(new BooleanDescriptor(ENABLE_SOUND_ALERT, "Enable Sound Alert & Notification", true));
        group.addRow(new BooleanDescriptor(SHOW_LEVEL_LINES, "Show SL / TP / Entry Bracket Lines", true));
        group.addRow(new BooleanDescriptor(HIDE_LINES_WHEN_LIVE, "Hide Custom Lines When Live Auto-Trade Active (Use Native Orders)", true));
        group.addRow(new BooleanDescriptor(SHOW_TIME_EXIT_LINES, "Show Time Boundary Lines (10:00 News Guard & 10:15 Exit)", false));
        group.addRow(new BooleanDescriptor(SHOW_NO_SETUP_MARKER, "Show 'No Setup' Reason Marker (Diagnostic)", false));

        SettingGroup garchGroup = tab.addGroup("AntiAchismo GARCH MVT & Desvio Padrao Envelopes");
        garchGroup.addRow(new BooleanDescriptor(SHOW_MVT_DP_LINES, "Show MVT 0 (VWAP) & DP +/- 1, 2, 2.5 Bands (Clean Default: Off)", false));
        garchGroup.addRow(new BooleanDescriptor(ENABLE_GARCH_EXHAUSTION_GATE, "Enable GARCH Exhaustion Gate (> 2.50 DP)", true));
        garchGroup.addRow(new DoubleDescriptor(GARCH_DAILY_VOL_PCT, "GARCH Daily Volatility % (Auto: NQ 1.25% / ES 0.72%)", 1.25, 0.20, 5.00, 0.05));
        garchGroup.addRow(new DoubleDescriptor(GARCH_EXHAUSTION_DP, "Exhaustion Cutoff in Desvio Padrao (2.50 DP)", 2.50, 1.50, 4.00, 0.10));

        setSettingsDescriptor(sd);

        RuntimeDescriptor rd = createRD();
        rd.declareSignal(SIGNAL_BUY, "VA Breakout Buy (09:45 ET)");
        rd.declareSignal(SIGNAL_SELL, "VA Breakout Sell (09:45 ET)");
        setRuntimeDescriptor(rd);
    }

    @Override
    protected void calculate(int index, DataContext ctx) {
        DataSeries series = ctx.getDataSeries();
        if (series == null || index < 0 || index >= series.size()) return;

        // Reset state on initial bar of full chart recalculation
        if (index == 0) {
            clearFigures();
            profilesByDate.clear();
            orByDate.clear();
            processedDays.clear();
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

        double tickSize = 0.25; // standard NQ/ES tick size
        if (series.getInstrument() != null) {
            tickSize = Math.max(0.01, series.getInstrument().getTickSize());
        }

        // 1. Accumulate RTH Session Profile (09:30 - 16:00 ET)
        if ((hour > 9 || (hour == 9 && min >= 30)) && hour < 16) {
            SessionProfile prof = profilesByDate.computeIfAbsent(today, d -> new SessionProfile());
            prof.addBar(high, low, close, volume, tickSize);
        }

        // Finalize prior completed sessions
        for (Map.Entry<LocalDate, SessionProfile> entry : profilesByDate.entrySet()) {
            if (entry.getKey().isBefore(today) && !entry.getValue().computed) {
                entry.getValue().computeValueArea(tickSize);
            }
        }

        // 2. Track 09:30 - 09:44 Opening Range
        if (hour == 9 && min == 30) {
            OpeningRange15 or = orByDate.computeIfAbsent(today, d -> new OpeningRange15());
            or.open930 = open;
            or.high15 = high;
            or.low15 = low;
            or.close944 = close;
            or.startTime = barStartTime;
            or.cumVolume = (double) volume;
            or.cumPriceVolume = ((high + low + close) / 3.0) * (double) volume;
            or.complete = true;
        } else if (hour == 9 && min > 30 && min < 45) {
            OpeningRange15 or = orByDate.computeIfAbsent(today, d -> new OpeningRange15());
            if (Double.isNaN(or.open930)) {
                or.open930 = open;
                or.startTime = barStartTime;
            }
            or.high15 = Double.isInfinite(or.high15) ? high : Math.max(or.high15, high);
            or.low15 = Double.isInfinite(or.low15) ? low : Math.min(or.low15, low);
            or.close944 = close;
            or.cumVolume += (double) volume;
            or.cumPriceVolume += ((high + low + close) / 3.0) * (double) volume;
            or.complete = true;
        }

        // 3. Evaluate Signal on the first bar at or after 09:45:00 ET sharp
        if (hour == 9 && min >= 45 && !processedDays.contains(today)) {
            OpeningRange15 or = orByDate.get(today);
            if (or != null && or.complete && !Double.isNaN(or.open930)) {
                processedDays.add(today);

                LocalDate priorDay = null;
                for (LocalDate d : profilesByDate.keySet()) {
                    if (d.isBefore(today)) {
                        if (priorDay == null || d.isAfter(priorDay)) {
                            priorDay = d;
                        }
                    }
                }

                SessionProfile priorProf = (priorDay != null) ? profilesByDate.get(priorDay) : null;
                if (priorProf != null && !priorProf.computed) {
                    priorProf.computeValueArea(tickSize);
                }

                boolean hasPriorVA = (priorProf != null && !Double.isNaN(priorProf.vah) && !Double.isNaN(priorProf.val));
                if (!hasPriorVA) {
                    if (getSettings().getBoolean(SHOW_NO_SETUP_MARKER, true)) {
                        Coordinate coord = new Coordinate(barStartTime, high + (tickSize * 4));
                        MarkerInfo info = new MarkerInfo(Enums$MarkerType.CIRCLE, Enums$Size.MEDIUM, new Color(100, 100, 100), Color.WHITE, Color.LIGHT_GRAY, true);
                        Marker marker = new Marker(coord, Enums$Position.TOP, info);
                        marker.setTextValue("NO TRADE: Prior Day Profile Not Found (Load >= 2 days of chart history)");
                        addFigure(marker);
                    }
                    return;
                }

                double priorVah = priorProf.vah;
                double priorVal = priorProf.val;

                double orRange = or.high15 - or.low15;
                if (orRange > 0.0) {
                    double retPct = (or.close944 - or.open930) / or.open930;
                    double closeLoc = (or.close944 - or.low15) / orRange;

                    double minRet = getSettings().getDouble(MIN_RETURN_PCT, 0.0010);
                    double minLongLoc = getSettings().getDouble(MIN_LONG_CLOSE_LOC, 0.60);
                    double maxShortLoc = getSettings().getDouble(MAX_SHORT_CLOSE_LOC, 0.40);
                    double rrRatio = getSettings().getDouble(REWARD_RISK_RATIO, 1.5);
                    double riskBudget = getSettings().getDouble(RISK_BUDGET_DOLLARS, 250.0);
                    int ratchetOverride = getSettings().getInteger(RATCHET_TIER_OVERRIDE, 0);
                    boolean newsGuard = getSettings().getBoolean(ENABLE_10AM_NEWS_GUARD, true);
                    boolean soundAlert = getSettings().getBoolean(ENABLE_SOUND_ALERT, true);
                    boolean showLines = getSettings().getBoolean(SHOW_LEVEL_LINES, true);
                    boolean hideWhenLive = getSettings().getBoolean(HIDE_LINES_WHEN_LIVE, true);
                    boolean isLive = getSettings().getBoolean(ENABLE_LIVE_AUTOTRADE, false);
                    if (hideWhenLive && isLive) {
                        showLines = false;
                    }

                    String sym = (series.getInstrument() != null) ? series.getInstrument().getSymbol().toUpperCase() : "NQ";
                    boolean isES = sym.contains("ES") || sym.contains("MES");
                    double minStop = 15.0;
                    double maxStop = isES ? 35.0 : 60.0;
                    double ptVal = isES ? 5.00 : 2.00;
                    String microSym = isES ? "MES" : "MNQ";

                    double stopPts = Math.min(maxStop, Math.max(minStop, orRange));

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

                    // 2. Dynamic Contract Sizing with Pair Allocation & Cushion De-leveraging
                    int tierMicros = riskState.verified ? riskState.recommendedMicros : 2;
                    if (ratchetOverride >= 1 && ratchetOverride <= 4) {
                        tierMicros = ratchetOverride;
                    }

                    boolean pairSplit = getSettings().getBoolean(ENABLE_PAIR_SPLIT, true);
                    int contracts;
                    if (pairSplit) {
                        if (isES) {
                            int cNq = Math.max(1, tierMicros / 2);
                            contracts = Math.max(1, tierMicros - cNq);
                        } else { // NQ
                            contracts = Math.max(1, tierMicros / 2);
                        }
                    } else {
                        contracts = tierMicros;
                    }

                    boolean isLong = (retPct >= minRet) && (closeLoc >= minLongLoc) && (or.close944 > priorVah);
                    boolean isShort = (retPct <= -minRet) && (closeLoc <= maxShortLoc) && (or.close944 < priorVal);

                    // AntiAchismo GARCH MVT & Desvio Padrao Calculations
                    double userVol = getSettings().getDouble(GARCH_DAILY_VOL_PCT, 1.25);
                    double dailyVolPct = isES && (Math.abs(userVol - 1.25) < 1e-4) ? 0.72 : userVol;
                    double sigmaOpen = or.close944 * (dailyVolPct / 100.0) * Math.sqrt(15.0 / 390.0);
                    double mvt0 = or.getVwap();
                    double dp1Pos = mvt0 + (1.0 * sigmaOpen);
                    double dp2Pos = mvt0 + (2.0 * sigmaOpen);
                    double dp25Pos = mvt0 + (2.5 * sigmaOpen);
                    double dp1Neg = mvt0 - (1.0 * sigmaOpen);
                    double dp2Neg = mvt0 - (2.0 * sigmaOpen);
                    double dp25Neg = mvt0 - (2.5 * sigmaOpen);
                    double zScore = (or.close944 - mvt0) / Math.max(sigmaOpen, 1e-4);

                    boolean showMvtLines = getSettings().getBoolean(SHOW_MVT_DP_LINES, false);
                    if (showMvtLines) {
                        long lineStart = (or.startTime > 0) ? or.startTime : (barStartTime - (15 * 60 * 1000L));
                        long lineEnd = barStartTime + (45 * 60 * 1000L); // Spans 09:30 to 10:30 ET

                        // MVT 0 (VWAP) - Golden Yellow
                        Line mvtLine = new Line(lineStart, mvt0, lineEnd, mvt0);
                        mvtLine.setColor(new Color(255, 215, 0));
                        mvtLine.setText(String.format("MVT 0 (VWAP): %.2f", mvt0), LINE_FONT);
                        addFigure(mvtLine);

                        // DP +1.0 - Light Green
                        Line dp1PosLine = new Line(lineStart, dp1Pos, lineEnd, dp1Pos);
                        dp1PosLine.setColor(new Color(144, 238, 144));
                        dp1PosLine.setText(String.format("DP +1.0: %.2f", dp1Pos), LINE_FONT);
                        addFigure(dp1PosLine);

                        // DP +2.0 (Target) - Bright Green
                        Line dp2PosLine = new Line(lineStart, dp2Pos, lineEnd, dp2Pos);
                        dp2PosLine.setColor(new Color(0, 204, 0));
                        dp2PosLine.setText(String.format("DP +2.0 TARGET: %.2f", dp2Pos), LINE_FONT);
                        addFigure(dp2PosLine);

                        // DP +2.5 (Exhaustion) - Hot Pink / Magenta
                        Line dp25PosLine = new Line(lineStart, dp25Pos, lineEnd, dp25Pos);
                        dp25PosLine.setColor(new Color(255, 105, 180));
                        dp25PosLine.setText(String.format("DP +2.5 EXHAUSTION: %.2f", dp25Pos), LINE_FONT);
                        addFigure(dp25PosLine);

                        // DP -1.0 - Light Coral
                        Line dp1NegLine = new Line(lineStart, dp1Neg, lineEnd, dp1Neg);
                        dp1NegLine.setColor(new Color(240, 128, 128));
                        dp1NegLine.setText(String.format("DP -1.0: %.2f", dp1Neg), LINE_FONT);
                        addFigure(dp1NegLine);

                        // DP -2.0 (Target) - Crimson
                        Line dp2NegLine = new Line(lineStart, dp2Neg, lineEnd, dp2Neg);
                        dp2NegLine.setColor(new Color(220, 20, 60));
                        dp2NegLine.setText(String.format("DP -2.0 TARGET: %.2f", dp2Neg), LINE_FONT);
                        addFigure(dp2NegLine);

                        // DP -2.5 (Exhaustion) - Hot Pink / Magenta
                        Line dp25NegLine = new Line(lineStart, dp25Neg, lineEnd, dp25Neg);
                        dp25NegLine.setColor(new Color(255, 105, 180));
                        dp25NegLine.setText(String.format("DP -2.5 EXHAUSTION: %.2f", dp25Neg), LINE_FONT);
                        addFigure(dp25NegLine);
                    }

                    boolean enableGarchGate = getSettings().getBoolean(ENABLE_GARCH_EXHAUSTION_GATE, true);
                    double garchExhaustionDp = getSettings().getDouble(GARCH_EXHAUSTION_DP, 2.50);
                    boolean isExhausted = (isLong && zScore > garchExhaustionDp) || (isShort && zScore < -garchExhaustionDp);

                    if (isExhausted && enableGarchGate) {
                        isLong = false;
                        isShort = false;
                    }

                    if (isLong || isShort) {
                        double entryPrice = open;
                        double stopPrice = isLong ? (entryPrice - stopPts) : (entryPrice + stopPts);
                        double targetPts = stopPts * rrRatio;
                        double targetPrice = isLong ? (entryPrice + targetPts) : (entryPrice - targetPts);
                        double actualRiskDollars = stopPts * ptVal * contracts;
                        double actualRewardDollars = targetPts * ptVal * contracts;

                        long entryTime = barStartTime;                 // 09:45:00 ET
                        long newsTime = entryTime + (15 * 60 * 1000L); // 10:00:00 ET
                        long exitTime = entryTime + (30 * 60 * 1000L); // 10:15:00 ET

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

                        boolean showTimeLines = getSettings().getBoolean(SHOW_TIME_EXIT_LINES, false);

                        if (isLong) {
                            Coordinate coord = new Coordinate(entryTime, low - (stopPts * 0.10));
                            MarkerInfo info = new MarkerInfo(Enums$MarkerType.ARROW, Enums$Size.MEDIUM, new Color(0, 204, 102), new Color(0, 204, 102), true);
                            Marker marker = new Marker(coord, Enums$Position.BOTTOM, info);
                            marker.setTextValue(String.format("BUY %dx %s @ %.2f", contracts, microSym, entryPrice));
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

                                if (showTimeLines) {
                                    if (newsGuard && is10amNewsDay(today)) {
                                        Line newsLine = new Line(newsTime, stopPrice, newsTime, targetPrice);
                                        newsLine.setColor(new Color(255, 140, 0, 180));
                                        newsLine.setStroke(new java.awt.BasicStroke(1.0f, java.awt.BasicStroke.CAP_BUTT, java.awt.BasicStroke.JOIN_MITER, 10.0f, new float[]{3.0f, 3.0f}, 0.0f));
                                        newsLine.setText("10:00 NEWS GUARD", LINE_FONT);
                                        if (newsLine.getText() != null) {
                                            newsLine.getText().setShowBorder(false);
                                            newsLine.getText().setBackground(null);
                                        }
                                        addFigure(newsLine);
                                    }

                                    Line exitLine = new Line(exitTime, stopPrice, exitTime, targetPrice);
                                    exitLine.setColor(new Color(0, 206, 209, 180));
                                    exitLine.setStroke(new java.awt.BasicStroke(1.0f, java.awt.BasicStroke.CAP_BUTT, java.awt.BasicStroke.JOIN_MITER, 10.0f, new float[]{3.0f, 3.0f}, 0.0f));
                                    exitLine.setText("10:15 MAX EXIT", LINE_FONT);
                                    if (exitLine.getText() != null) {
                                        exitLine.getText().setShowBorder(false);
                                        exitLine.getText().setBackground(null);
                                    }
                                    addFigure(exitLine);
                                }
                            }

                            ctx.signal(index, SIGNAL_BUY, String.format("VA BREAKOUT BUY %dx %s @ %.2f (SL: %.2f, TP: %.2f)", contracts, microSym, entryPrice, stopPrice, targetPrice), entryPrice);
                        } else {
                            Coordinate coord = new Coordinate(entryTime, high + (stopPts * 0.10));
                            MarkerInfo info = new MarkerInfo(Enums$MarkerType.ARROW, Enums$Size.MEDIUM, new Color(220, 20, 60), new Color(220, 20, 60), true);
                            Marker marker = new Marker(coord, Enums$Position.TOP, info);
                            marker.setTextValue(String.format("SELL %dx %s @ %.2f", contracts, microSym, entryPrice));
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

                                if (showTimeLines) {
                                    if (newsGuard && is10amNewsDay(today)) {
                                        Line newsLine = new Line(newsTime, stopPrice, newsTime, targetPrice);
                                        newsLine.setColor(new Color(255, 140, 0, 180));
                                        newsLine.setStroke(new java.awt.BasicStroke(1.0f, java.awt.BasicStroke.CAP_BUTT, java.awt.BasicStroke.JOIN_MITER, 10.0f, new float[]{3.0f, 3.0f}, 0.0f));
                                        newsLine.setText("10:00 NEWS GUARD", LINE_FONT);
                                        if (newsLine.getText() != null) {
                                            newsLine.getText().setShowBorder(false);
                                            newsLine.getText().setBackground(null);
                                        }
                                        addFigure(newsLine);
                                    }

                                    Line exitLine = new Line(exitTime, targetPrice, exitTime, stopPrice);
                                    exitLine.setColor(new Color(0, 206, 209, 180));
                                    exitLine.setStroke(new java.awt.BasicStroke(1.0f, java.awt.BasicStroke.CAP_BUTT, java.awt.BasicStroke.JOIN_MITER, 10.0f, new float[]{3.0f, 3.0f}, 0.0f));
                                    exitLine.setText("10:15 MAX EXIT", LINE_FONT);
                                    if (exitLine.getText() != null) {
                                        exitLine.getText().setShowBorder(false);
                                        exitLine.getText().setBackground(null);
                                    }
                                    addFigure(exitLine);
                                }
                            }

                            ctx.signal(index, SIGNAL_SELL, String.format("VA BREAKOUT SELL %dx %s @ %.2f (SL: %.2f, TP: %.2f)", contracts, microSym, entryPrice, stopPrice, targetPrice), entryPrice);
                        }

                        tradesByDate.put(today, trade);

                        if (soundAlert) {
                            Toolkit.getDefaultToolkit().beep();
                        }
                    } else if (getSettings().getBoolean(SHOW_NO_SETUP_MARKER, true)) {
                        StringBuilder reason = new StringBuilder("NO TRADE: ");
                        if (isExhausted) {
                            reason.append(String.format("GARCH MVT Exhaustion (Z = %+.2f DP exceeds +/-%.2f DP cutoff)", zScore, garchExhaustionDp));
                        } else if (or.close944 <= priorVah && or.close944 >= priorVal) {
                            reason.append(String.format("Inside Prior VA [VAL: %.2f | VAH: %.2f | Close: %.2f]", priorVal, priorVah, or.close944));
                        } else if (Math.abs(retPct) < minRet) {
                            reason.append(String.format("Weak Momentum (Return: %+.2f%% vs req +/-%.2f%%)", retPct * 100.0, minRet * 100.0));
                        } else if (retPct > 0 && closeLoc < minLongLoc) {
                            reason.append(String.format("Upper Wick Reject (CloseLoc: %.2f vs req >= %.2f)", closeLoc, minLongLoc));
                        } else if (retPct < 0 && closeLoc > maxShortLoc) {
                            reason.append(String.format("Lower Wick Reject (CloseLoc: %.2f vs req <= %.2f)", closeLoc, maxShortLoc));
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

        // 4. Bar-by-Bar Active Trade Lifecycle & Outcome Tracker (Non-Repainting)
        ActiveTrade activeTrade = tradesByDate.get(today);
        if (activeTrade != null && !activeTrade.closed && barStartTime > activeTrade.entryTime) {
            boolean exitTriggered = false;
            double exitPrice = 0.0;
            String outcomeText = "";
            Color outcomeColor = Color.GREEN;
            boolean newsGuard = getSettings().getBoolean(ENABLE_10AM_NEWS_GUARD, true);
            boolean isNewsDay = is10amNewsDay(today);

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
                } else if (newsGuard && isNewsDay && (hour == 9 && min >= 59)) {
                    exitTriggered = true;
                    exitPrice = close;
                    double pts = exitPrice - activeTrade.entryPrice;
                    double netDollars = pts * activeTrade.ptVal * activeTrade.contracts;
                    outcomeText = String.format("NEWS FLATTEN (09:59): %.2f (%+.2f pts | %s$%.2f)",
                        exitPrice, pts, netDollars >= 0 ? "+" : "-", Math.abs(netDollars));
                    outcomeColor = Color.ORANGE;
                } else if (barStartTime >= activeTrade.maxExitTime || (hour == 10 && min >= 15)) {
                    exitTriggered = true;
                    exitPrice = close;
                    double pts = exitPrice - activeTrade.entryPrice;
                    double netDollars = pts * activeTrade.ptVal * activeTrade.contracts;
                    outcomeText = String.format("TIME EXIT (10:15): %.2f (%+.2f pts | %s$%.2f)",
                        exitPrice, pts, netDollars >= 0 ? "+" : "-", Math.abs(netDollars));
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
                } else if (newsGuard && isNewsDay && (hour == 9 && min >= 59)) {
                    exitTriggered = true;
                    exitPrice = close;
                    double pts = activeTrade.entryPrice - exitPrice;
                    double netDollars = pts * activeTrade.ptVal * activeTrade.contracts;
                    outcomeText = String.format("NEWS FLATTEN (09:59): %.2f (%+.2f pts | %s$%.2f)",
                        exitPrice, pts, netDollars >= 0 ? "+" : "-", Math.abs(netDollars));
                    outcomeColor = Color.ORANGE;
                } else if (barStartTime >= activeTrade.maxExitTime || (hour == 10 && min >= 15)) {
                    exitTriggered = true;
                    exitPrice = close;
                    double pts = activeTrade.entryPrice - exitPrice;
                    double netDollars = pts * activeTrade.ptVal * activeTrade.contracts;
                    outcomeText = String.format("TIME EXIT (10:15): %.2f (%+.2f pts | %s$%.2f)",
                        exitPrice, pts, netDollars >= 0 ? "+" : "-", Math.abs(netDollars));
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

    // =========================================================================
    // MOTIVEWAVE STRATEGY & AUTOMATED ORDER EXECUTION LIFECYCLE (CQG / RITHMIC)
    // =========================================================================

    @Override
    public void onActivate(OrderContext ctx) {
        setState(Enums$StrategyState.ACTIVE);
        logExecutionEvent("STRATEGY_ACTIVATED", "LucidMorningVABreakout",
            ctx != null ? ctx.getInstrument().getSymbol() : "MNQ",
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
            if (trade == null && RESTART_POSITION_REPORTED.add(today)) {
                logExecutionEvent("RESTART_POSITION_UNRECONCILED", "LucidMorningVABreakout",
                    ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                    "BLOCKED", 0.0, 0.0, 0.0, Math.abs(ctx.getPosition()),
                    "No active trade or order identities were recovered; do not recreate protective orders.");
            } else if (trade != null && !trade.restartCoverageReported
                    && (trade.slOrder == null || !trade.slOrder.isActive())) {
                trade.restartCoverageReported = true;
                logExecutionEvent("RESTART_PROTECTIVE_COVERAGE_UNVERIFIED", "LucidMorningVABreakout",
                    ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                    "BLOCKED", 0.0, trade.stopPrice, trade.targetPrice, Math.abs(ctx.getPosition()),
                    "Position is open but no working stop is confirmed; do not recreate protection automatically.");
            }
            if (trade != null && !trade.orderSubmitted && !trade.closed && now >= trade.entryTime && now < trade.maxExitTime) {
                executeAutoTradeIfArmed(ctx, trade.isLong ? SIGNAL_BUY : SIGNAL_SELL);
            }
        }

        // 2. Reconcile restart state / Automated Time-Based Flattens if currently in a live position
        if (ctx.getPosition() != 0) {
            DAILY_SUBMITTED_DATES.add(today);
            File lockFile = getDailyLockFile("morning_va_breakout_s1", today);
            if (lockFile != null && !lockFile.exists()) {
                try {
                    if (!lockFile.createNewFile()) {
                        logExecutionEvent("RESTART_DAILY_LOCK_NOT_CREATED", "LucidMorningVABreakout",
                            ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                            "BLOCKED", 0.0, 0.0, 0.0, Math.abs(ctx.getPosition()), "Lock already exists or could not be created.");
                    }
                } catch (Exception e) {
                    logExecutionEvent("RESTART_DAILY_LOCK_CREATE_FAILED", "LucidMorningVABreakout",
                        ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                        "BLOCKED", 0.0, 0.0, 0.0, Math.abs(ctx.getPosition()), e.getMessage());
                }
            }

            ActiveTrade trade = tradesByDate.get(today);
            if (trade != null && trade.flattenPending && !trade.flattenSubmitted) {
                submitMarketFlatten(ctx, trade, trade.flattenEvent, trade.flattenReason);
            }
            if (trade != null && trade.bracketsSubmitted && trade.attachedBracketQty != Math.abs(ctx.getPosition())) {
                int contracts = Math.abs(ctx.getPosition());
                if (trade.slOrder != null && trade.slOrder.isActive()) {
                    trade.slOrder.setAdjQuantity(contracts);
                    if (trade.tpOrder != null && trade.tpOrder.isActive()) {
                        trade.tpOrder.setAdjQuantity(contracts);
                        ctx.submitOrders(trade.slOrder, trade.tpOrder);
                    } else {
                        ctx.submitOrders(trade.slOrder);
                    }
                    trade.attachedBracketQty = contracts;
                    logExecutionEvent("BRACKET_QTY_SYNCED", "LucidMorningVABreakout", ctx.getInstrument().getSymbol(),
                        "SYNC", 0.0, trade.stopPrice, trade.targetPrice, contracts, "Bracket quantity reconciled to position");
                }
            }

            long barTime = ctx.getCurrentTime();
            ZonedDateTime zdt = Instant.ofEpochMilli(barTime).atZone(NY_ZONE);
            int hour = zdt.getHour();
            int min = zdt.getMinute();
            boolean newsGuard = getSettings().getBoolean(ENABLE_10AM_NEWS_GUARD, true);
            boolean isNews = is10amNewsDay(today);

            // 10:15 ET Hard Max Time Exit
            if (hour > 10 || (hour == 10 && min >= 15)) {
                if (trade != null) {
                    if (trade.tpOrder != null && trade.tpOrder.isActive()) ctx.cancelOrders(trade.tpOrder);
                    submitMarketFlatten(ctx, trade, "TIME_EXIT_FLATTEN", "10:15 ET session boundary reached");
                } else {
                    logExecutionEvent("RESTART_POSITION_UNRECONCILED", "LucidMorningVABreakout",
                        ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                        "BLOCKED", 0.0, 0.0, 0.0, Math.abs(ctx.getPosition()),
                        "Position is open but no active trade/order identities were recovered; do not recreate brackets.");
                }
            }
            // 09:59 ET News Guard Flatten if Red-Folder Day
            else if (newsGuard && isNews && hour == 9 && min >= 59) {
                if (trade != null) {
                    if (trade.tpOrder != null && trade.tpOrder.isActive()) ctx.cancelOrders(trade.tpOrder);
                    submitMarketFlatten(ctx, trade, "NEWS_GUARD_FLATTEN", "09:59 ET Tier-1 Red Folder News Guard triggered");
                } else {
                    logExecutionEvent("RESTART_POSITION_UNRECONCILED", "LucidMorningVABreakout",
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
        File lockFile = getDailyLockFile("morning_va_breakout_s1", today);
        if (DAILY_SUBMITTED_DATES.contains(today) || (lockFile != null && lockFile.exists())) {
            DAILY_SUBMITTED_DATES.add(today);
            logExecutionEvent("ORDER_BLOCKED_SESSION_COOLDOWN", "LucidMorningVABreakout",
                ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                "BLOCKED", 0.0, 0.0, 0.0, 0,
                "Single trade per session lock active for " + today + ". Additional entries blocked.");
            return;
        }

        // Gateway-level circuit breaker check
        DaemonRiskState riskState = loadDaemonRiskState();
        if (riskState.circuitBreakerHit) {
            logExecutionEvent("CIRCUIT_BREAKER_BLOCKED", "LucidMorningVABreakout", ctx.getInstrument().getSymbol(),
                "BLOCKED", 0.0, 0.0, 0.0, 0, "Daily soft-stop -$600 reached in demo parity state");
            return;
        }

        ActiveTrade trade = tradesByDate.get(today);
        if (trade == null || trade.orderSubmitted || trade.closed) return;

        int contracts = resolveContracts(ctx, trade.contracts);
        if (contracts <= 0) {
            logExecutionEvent("ORDER_BLOCKED_UNVERIFIED_ACCOUNT", "LucidMorningVABreakout",
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
            if (sigStr.contains("BUY") || SIGNAL_BUY.equals(sigStr)) isLong = true;
            else if (sigStr.contains("SELL") || SIGNAL_SELL.equals(sigStr)) isLong = false;
        }
        trade.isLong = isLong;

        setStopPrice(stopPrice);
        setTargetPrice(targetPrice);

        // Atomic lock acquisition before submitting order to broker
        if (lockFile != null) {
            try {
                if (!lockFile.createNewFile()) {
                    DAILY_SUBMITTED_DATES.add(today);
                    logExecutionEvent("ORDER_BLOCKED_SESSION_COOLDOWN", "LucidMorningVABreakout",
                        ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                        "BLOCKED", 0.0, 0.0, 0.0, 0, "Atomic lock acquisition failed for " + today);
                    return;
                }
            } catch (Exception e) {
                DAILY_SUBMITTED_DATES.add(today);
                logExecutionEvent("ORDER_BLOCKED_SESSION_COOLDOWN", "LucidMorningVABreakout",
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
        ctx.submitOrders(entry);

        logExecutionEvent("ORDER_SUBMITTED", "LucidMorningVABreakout", ctx.getInstrument().getSymbol(),
            entryAction.toString(), trade.entryPrice, stopPrice, targetPrice, contracts,
            "Market entry submitted. Brackets pending fill confirmation. Daily cooldown locked.");
    }

    @Override
    public void onOrderFilled(OrderContext ctx, Order order) {
        if (ctx == null || order == null) return;
        long now = ctx.getCurrentTime();
        LocalDate today = Instant.ofEpochMilli(now).atZone(NY_ZONE).toLocalDate();
        ActiveTrade trade = tradesByDate.get(today);

        logExecutionEvent("ORDER_FILLED", "LucidMorningVABreakout", ctx.getInstrument().getSymbol(),
            order.getAction().toString(), order.getAvgFillPrice(), 0.0, 0.0, order.getQuantity(),
            "Order filled: id=" + order.getOrderId() + " pos=" + ctx.getPosition());

        boolean isTrackedEntry = (trade != null) && (trade.entryOrderId != null && trade.entryOrderId.equals(order.getOrderId()));

        if (trade != null && trade.flattenSubmitted
                && (order == trade.flattenOrder || (trade.flattenOrderId != null && trade.flattenOrderId.equals(order.getOrderId())))) {
            trade.flattenSubmitted = false;
            trade.flattenOrder = null;
            trade.flattenOrderId = null;
            if (ctx.getPosition() == 0) {
                trade.closed = true;
                trade.flattenPending = false;
                trade.restartCoverageReported = false;
            } else {
                logExecutionEvent("FLATTEN_PARTIAL_FILL_REMAINS_OPEN", "LucidMorningVABreakout", ctx.getInstrument().getSymbol(),
                    "FLATTEN", 0.0, trade.stopPrice, trade.targetPrice, Math.abs(ctx.getPosition()),
                    "Flatten order filled partially; remaining position is still open.");
                submitMarketFlatten(ctx, trade, trade.flattenEvent, trade.flattenReason);
            }
            return;
        }
        if (trade != null && trade.flattenPending && ctx.getPosition() != 0
                && (order == trade.entryOrder || (trade.entryOrderId != null && trade.entryOrderId.equals(order.getOrderId())))) {
            submitMarketFlatten(ctx, trade, trade.flattenEvent, trade.flattenReason);
            return;
        }
        if (trade != null && trade.flattenPending && ctx.getPosition() != 0
                && (order == trade.slOrder || order == trade.tpOrder)) {
            submitMarketFlatten(ctx, trade, trade.flattenEvent, trade.flattenReason);
            return;
        }

        // Case A: Entry order filled -> Submit linked Stop Loss & Profit Target brackets anchored to actual fill
        if (ctx.getPosition() != 0 && trade != null && !trade.bracketsSubmitted && isTrackedEntry) {
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

            Enums$OrderAction exitAction = trade.isLong ? Enums$OrderAction.SELL : Enums$OrderAction.BUY;

            Order sl = ctx.createStopOrder(exitAction, Enums$TIF.GTC, contracts, stopPrice);
            Order tp = ctx.createLimitOrder(exitAction, Enums$TIF.GTC, contracts, targetPrice);
            ctx.submitOrders(sl, tp);
            trade.bracketsSubmitted = true;
            trade.slOrder = sl;
            trade.tpOrder = tp;
            trade.attachedBracketQty = contracts;
            trade.slOrderId = sl != null ? sl.getOrderId() : null;
            trade.tpOrderId = tp != null ? tp.getOrderId() : null;

            logExecutionEvent("BRACKETS_SUBMITTED", "LucidMorningVABreakout", ctx.getInstrument().getSymbol(),
                exitAction.toString(), actualFill, stopPrice, targetPrice, contracts,
                "Attached Stop (" + stopPrice + ") and Target (" + targetPrice + ") submitted to broker anchored to fill=" + actualFill);
        }
        // Case A.2: Partial fill update on existing position -> Reconcile working bracket quantities
        else if (ctx.getPosition() != 0 && trade != null && trade.bracketsSubmitted && isTrackedEntry) {
            int contracts = Math.abs(ctx.getPosition());
            double actualFill = ctx.getAvgEntryPrice() > 0 ? ctx.getAvgEntryPrice()
                : (order.getAvgFillPrice() > 0 ? order.getAvgFillPrice() : trade.actualEntryFill);
            double riskDist = Double.isFinite(trade.initialRiskDist) ? trade.initialRiskDist : Math.abs(trade.entryPrice - trade.stopPrice);
            double targetDist = Double.isFinite(trade.initialTargetDist) ? trade.initialTargetDist : Math.abs(trade.targetPrice - trade.entryPrice);
            if (actualFill > 0 && trade.slOrder != null && trade.slOrder.isActive()) {
                float stopPrice = ctx.getInstrument().round((float) (trade.isLong ? actualFill - riskDist : actualFill + riskDist));
                float targetPrice = ctx.getInstrument().round((float) (trade.isLong ? actualFill + targetDist : actualFill - targetDist));
                trade.actualEntryFill = actualFill;
                trade.stopPrice = stopPrice;
                trade.targetPrice = targetPrice;
                try {
                    trade.slOrder.setAdjStopPrice(stopPrice);
                    trade.slOrder.setAdjQuantity(contracts);
                    if (trade.tpOrder != null && trade.tpOrder.isActive()) {
                        trade.tpOrder.setAdjLimitPrice(targetPrice);
                        trade.tpOrder.setAdjQuantity(contracts);
                        ctx.submitOrders(trade.slOrder, trade.tpOrder);
                    } else {
                        ctx.submitOrders(trade.slOrder);
                    }
                } catch (RuntimeException e) {
                    submitMarketFlatten(ctx, trade, "PARTIAL_FILL_BRACKET_SYNC_FAILED", e.getMessage());
                }
                trade.attachedBracketQty = contracts;
                logExecutionEvent("PARTIAL_FILL_SYNC", "LucidMorningVABreakout", ctx.getInstrument().getSymbol(),
                    order.getAction().toString(), order.getAvgFillPrice(), trade.stopPrice, trade.targetPrice, contracts,
                    "Cumulative average fill and bracket prices/quantity reconciled to position=" + contracts);
            } else if (contracts > 0) {
                submitMarketFlatten(ctx, trade, "PARTIAL_FILL_WITHOUT_CONFIRMED_STOP", "Open position has no confirmed protective stop");
            }
        }
        // Case B: Stop Loss or Profit Target filled -> Position flattened
        else if (ctx.getPosition() == 0) {
            ctx.cancelOrders();
            if (trade != null) {
                trade.closed = true;
                trade.flattenPending = false;
            }
            logExecutionEvent("POSITION_FLAT", "LucidMorningVABreakout", ctx.getInstrument().getSymbol(),
                "FLAT", 0.0, 0.0, 0.0, 0, "Position closed, unfulfilled bracket orders cancelled.");
        }
    }

    @Override
    public void onOrderRejected(OrderContext ctx, Order order) {
        if (order == null) return;
        long now = ctx != null ? ctx.getCurrentTime() : System.currentTimeMillis();
        LocalDate today = Instant.ofEpochMilli(now).atZone(NY_ZONE).toLocalDate();
        ActiveTrade trade = tradesByDate.get(today);
        if (trade != null && trade.flattenSubmitted
                && (order == trade.flattenOrder || (trade.flattenOrderId != null && trade.flattenOrderId.equals(order.getOrderId())))) {
            trade.flattenSubmitted = false;
            trade.flattenOrder = null;
            trade.flattenOrderId = null;
            if (ctx != null && ctx.getPosition() == 0) trade.closed = true;
            else trade.flattenPending = true;
            logExecutionEvent("FLATTEN_ORDER_REJECTED", "LucidMorningVABreakout",
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
                if (trade.slOrder != null && trade.slOrder.isActive()) {
                    int contracts = Math.abs(ctx.getPosition());
                    trade.slOrder.setAdjQuantity(contracts);
                    if (trade.tpOrder != null && trade.tpOrder.isActive()) {
                        trade.tpOrder.setAdjQuantity(contracts);
                        ctx.submitOrders(trade.slOrder, trade.tpOrder);
                    } else {
                        ctx.submitOrders(trade.slOrder);
                    }
                    if (ctx != null && trade.flattenPending) submitMarketFlatten(ctx, trade, trade.flattenEvent, trade.flattenReason);
                } else {
                    submitMarketFlatten(ctx, trade, "PARTIAL_ENTRY_REJECTED_EMERGENCY_FLATTEN", "Entry rejected with an open position and no confirmed stop");
                }
            }
            logExecutionEvent("ENTRY_ORDER_REJECTED", "LucidMorningVABreakout",
                ctx != null && ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                order.getAction().toString(), 0.0, trade.stopPrice, trade.targetPrice,
                ctx != null ? Math.abs(ctx.getPosition()) : 0, "ENTRY_REJECTED:" + order.getOrderId());
            return;
        }
        if (trade != null && (order == trade.slOrder
                || (trade.slOrderId != null && trade.slOrderId.equals(order.getOrderId())))) {
            trade.slOrder = null;
            if (ctx != null && ctx.getPosition() != 0) {
                submitMarketFlatten(ctx, trade, "PROTECTIVE_STOP_REJECTED_EMERGENCY_FLATTEN", "Protective stop rejected while position open");
            }
        } else if (trade != null && (order == trade.tpOrder
                || (trade.tpOrderId != null && trade.tpOrderId.equals(order.getOrderId())))) {
            trade.tpOrder = null;
            logExecutionEvent("PROFIT_TARGET_REJECTED_STOP_RETAINED", "LucidMorningVABreakout",
                ctx != null && ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                order.getAction().toString(), 0.0, trade.stopPrice, trade.targetPrice,
                ctx != null ? Math.abs(ctx.getPosition()) : 0, "TARGET_REJECTED:" + order.getOrderId());
            if (ctx != null && ctx.getPosition() != 0 && (trade.slOrder == null || !trade.slOrder.isActive())) {
                submitMarketFlatten(ctx, trade, "TARGET_REJECTED_WITHOUT_STOP_FLATTEN", "Target rejected and stop is not confirmed working");
            }
        }
        logExecutionEvent("ORDER_REJECTED", "LucidMorningVABreakout",
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
        if (trade != null && trade.flattenSubmitted
                && (order == trade.flattenOrder || (trade.flattenOrderId != null && trade.flattenOrderId.equals(order.getOrderId())))) {
            trade.flattenSubmitted = false;
            trade.flattenOrder = null;
            trade.flattenOrderId = null;
            if (ctx != null && ctx.getPosition() == 0) trade.closed = true;
            else trade.flattenPending = true;
            logExecutionEvent("FLATTEN_ORDER_CANCELLED", "LucidMorningVABreakout",
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
        }
        if (trade != null && order == trade.tpOrder) {
            trade.tpOrder = null;
            if (ctx != null && trade.flattenPending) submitMarketFlatten(ctx, trade, trade.flattenEvent, trade.flattenReason);
        }
        logExecutionEvent("ORDER_CANCELLED", "LucidMorningVABreakout",
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
        logExecutionEvent("POSITION_CLOSED_CONFIRMED", "LucidMorningVABreakout",
            ctx != null && ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
            "FLAT", 0.0, 0.0, 0.0, 0, "Broker confirmed position closed.");
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

        Order[] workingOrders = {trade.entryOrder, trade.slOrder, trade.tpOrder};
        for (Order workingOrder : workingOrders) {
            if (workingOrder == null || workingOrder.isCancelled() || workingOrder.isFilled()) continue;
            try {
                ctx.cancelOrders(workingOrder);
                logExecutionEvent("FLATTEN_WAITING_FOR_ORDER_CANCELLATION", "LucidMorningVABreakout",
                    ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                    "WAIT", 0.0, trade.stopPrice, trade.targetPrice, Math.abs(ctx.getPosition()),
                    trade.flattenReason + "|ORDER_ID=" + workingOrder.getOrderId());
            } catch (RuntimeException e) {
                logExecutionEvent("FLATTEN_CANCEL_STATUS_UNKNOWN", "LucidMorningVABreakout",
                    ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                    "WAIT", 0.0, trade.stopPrice, trade.targetPrice, Math.abs(ctx.getPosition()),
                    trade.flattenReason + "|ORDER_ID=" + workingOrder.getOrderId() + "|ERROR=" + e.getMessage());
            }
            return;
        }
        int quantity = Math.abs(ctx.getPosition());
        Enums$OrderAction action = ctx.getPosition() > 0 ? Enums$OrderAction.SELL : Enums$OrderAction.BUY;
        Order flatten = ctx.createMarketOrder(action, quantity);
        if (flatten == null) {
            logExecutionEvent(trade.flattenEvent + "_ORDER_CREATION_FAILED", "LucidMorningVABreakout",
                ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                "BLOCKED", 0.0, trade.stopPrice, trade.targetPrice, quantity, trade.flattenReason);
            return;
        }
        trade.flattenOrder = flatten;
        trade.flattenOrderId = flatten.getOrderId();
        trade.flattenSubmitted = true;
        try {
            ctx.submitOrders(flatten);
            logExecutionEvent(trade.flattenEvent + "_SUBMITTED", "LucidMorningVABreakout",
                ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                action.toString(), 0.0, trade.stopPrice, trade.targetPrice, quantity,
                trade.flattenReason + "|ORDER_ID=" + trade.flattenOrderId);
        } catch (RuntimeException e) {
            logExecutionEvent(trade.flattenEvent + "_SUBMISSION_STATUS_UNKNOWN", "LucidMorningVABreakout",
                ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
                action.toString(), 0.0, trade.stopPrice, trade.targetPrice, quantity,
                trade.flattenReason + "|ORDER_ID=" + trade.flattenOrderId + "|ERROR=" + e.getMessage());
        }
    }

    @Override
    public void onDeactivate(OrderContext ctx) {
        setState(Enums$StrategyState.INACTIVE);
        if (ctx != null) {
            if (ctx.getPosition() == 0) {
                ctx.cancelOrders();
            } else {
                logExecutionEvent("STRATEGY_DEACTIVATED_POSITION_REMAINS_OPEN", "LucidMorningVABreakout",
                    ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "MNQ",
                    "FLAT", 0.0, 0.0, 0.0, 0,
                    "Position open (" + ctx.getPosition() + "); protective orders preserved to prevent naked position exposure.");
            }
        }
        logExecutionEvent("STRATEGY_DEACTIVATED", "LucidMorningVABreakout",
            ctx != null ? ctx.getInstrument().getSymbol() : "MNQ",
            "INACTIVE", 0.0, 0.0, 0.0, 0, "Strategy deactivated by user");
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
