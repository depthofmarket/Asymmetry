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
import com.motivewave.platform.sdk.common.FontInfo;
import com.motivewave.platform.sdk.common.Instrument;
import com.motivewave.platform.sdk.common.MarkerInfo;
import com.motivewave.platform.sdk.common.Settings;
import com.motivewave.platform.sdk.common.Util;
import com.motivewave.platform.sdk.common.desc.BooleanDescriptor;
import com.motivewave.platform.sdk.common.desc.ColorDescriptor;
import com.motivewave.platform.sdk.common.desc.DoubleDescriptor;
import com.motivewave.platform.sdk.common.desc.FontDescriptor;
import com.motivewave.platform.sdk.common.desc.IntegerDescriptor;
import com.motivewave.platform.sdk.common.desc.MarkerDescriptor;
import com.motivewave.platform.sdk.common.desc.PathDescriptor;
import com.motivewave.platform.sdk.common.desc.SettingTab;
import com.motivewave.platform.sdk.common.desc.StringDescriptor;
import com.motivewave.platform.sdk.draw.Label;
import com.motivewave.platform.sdk.draw.Line;
import com.motivewave.platform.sdk.draw.Marker;
import com.motivewave.platform.sdk.order_mgmt.Order;
import com.motivewave.platform.sdk.order_mgmt.OrderContext;
import com.motivewave.platform.sdk.study.Plot;
import com.motivewave.platform.sdk.study.Study;
import com.motivewave.platform.sdk.study.StudyHeader;

import java.awt.Color;
import java.awt.Font;
import java.awt.Toolkit;
import java.io.File;
import java.io.FileWriter;
import java.io.PrintWriter;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.time.Instant;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

/**
 * Strategy 4 (Candidate): Asian / Evening Session Liquidity Sweep & Mean Reversion (21:00–23:00 ET).
 *
 * Candidate Governance Invariants:
 * - Classified strictly as StrategyTier.CANDIDATE ("CANDIDATE").
 * - Automated execution defaults to FALSE (@StudyHeader autoEntry = false, ENABLE_LIVE_AUTOTRADE = false).
 * - Missing, null, or invalid settings default fail-closed to disabled.
 * - Study reloads and upgrades sanitize execution settings to remain disabled unless explicitly enabled by user action.
 * - Visual signals, level lines, and sound alerts remain active when automated order execution is disabled.
 *
 * Account-State & Broker Execution Invariants:
 * - Uses canonical 'demo_parity_state.json' in configurable forward-test directory (no hardcoded /Users/novo paths).
 * - Mandatory fail-closed blocking when account state is missing, wrong filename, malformed, missing fields, or stale.
 * - Preserves historical high-water mark and permanent $25,100 floor lock across restarts.
 * - Evaluates signals strictly on completed bars (series.isBarComplete(index)).
 * - Reconciles actual entry fill price from broker order fill and anchors stop/target bracket distances from actual fill.
 * - Modifies working broker stop order in-place via Order.setAdjStopPrice() + OrderContext.submitOrders(slOrder)
 *   without cancelling protective orders; applies protective failure policy if modification is rejected.
 */
@StudyHeader(
    namespace = "com.lucidprop",
    id = "LUCID_ASIAN_EVENING_REVERSION_V1",
    name = "Lucid Asian Evening Reversion (21:15 ET) [CANDIDATE]",
    label = "Asian Rev S4 [CANDIDATE]",
    desc = "Candidate S4: Tokyo/Globex Evening Drift Exhaustion & VWAP Band Mean Reversion (MNQ/MES). Automated trading disabled by default.",
    menu = "Lucid Prop Strategies",
    overlay = true,
    studyOverlay = true,
    signals = true,
    strategy = true,
    autoEntry = false,
    manualEntry = false,
    supportsEnterOnActivate = false,
    supportsUnrealizedPL = true,
    supportsRealizedPL = true,
    supportsTotalPL = true,
    supportsPosition = true,
    showTradeOptions = true,
    supportsTradeLots = true
)
public class LucidAsianEveningReversionStudy extends Study {

    public static final String STRATEGY_TIER = "CANDIDATE";
    public static final String STRATEGY_ID = "asian_evening_reversion_s4";
    public static final boolean DEFAULT_LIVE_AUTOTRADE = false;

    public static final String CANONICAL_STATE_FILENAME = "demo_parity_state.json";
    public static final String FORWARD_TEST_DIR_PROP = "asymmetry.forwardTestDir";
    public static final String FORWARD_TEST_DIR_ENV = "ASYMMETRY_FORWARD_TEST_DIR";
    public static final String FORWARD_TEST_DIR_SETTING = "forwardTestDir";
    public static final long DEFAULT_MAX_STATE_AGE_MS = 86_400_000L; // 24 hours

    public static boolean isAcceptedMnqSymbol(String rawSymbol) {
        if (rawSymbol == null || rawSymbol.trim().isEmpty()) {
            return false;
        }
        String s = rawSymbol.trim().toUpperCase();
        int colonIdx = s.lastIndexOf(':');
        if (colonIdx >= 0 && colonIdx < s.length() - 1) {
            s = s.substring(colonIdx + 1);
        }
        int slashIdx = s.lastIndexOf('/');
        if (slashIdx >= 0 && slashIdx < s.length() - 1) {
            s = s.substring(slashIdx + 1);
        }
        if (!s.startsWith("MNQ")) {
            return false;
        }
        if (s.length() == 3) {
            return true;
        }
        char nextChar = s.charAt(3);
        if (nextChar == '#' || nextChar == '.' || nextChar == '_' || nextChar == '-' || nextChar == ' ' || nextChar == '/') {
            return true;
        }
        String remainder = s.substring(3);
        if (remainder.matches("^[FGHJKMNQUVXZ]\\d{1,4}([._\\s#-].*)?$")) {
            return true;
        }
        if (remainder.matches("^\\d{2,4}([._\\s#-].*)?$")) {
            return true;
        }
        return false;
    }

    // --- Setting Keys ---
    public static final String MIN_OR15_RANGE = "minOr15Range";
    public static final String MAX_OR15_RANGE = "maxOr15Range";
    public static final String MIN_DRIFT_ATR = "minDriftAtr";
    public static final String MAX_DRIFT_ATR = "maxDriftAtr";
    public static final String MIN_RTH_RVOL20 = "minRthRvol20";
    public static final String STOP_PTS = "stopPts";
    public static final String TARGET_PTS = "targetPts";
    public static final String BREAKEVEN_TRIGGER_R = "breakevenTriggerR";
    public static final String BREAKEVEN_LOCK_PTS = "breakevenLockPts";
    public static final String VWAP_ZSCORE_ENTRY = "vwapZscoreEntry";
    public static final String MAX_ADX_5M = "maxAdx5m";
    public static final String MAX_DISPLACEMENT_PTS = "maxDisplacementPts";
    public static final String ENABLE_RATCHET_SIZING = "enableRatchetSizing";
    public static final String BASE_CONTRACTS = "baseContracts";
    public static final String ENABLE_LIVE_AUTOTRADE = "enableLiveAutoTrade";
    public static final String SHOW_LEVEL_LINES = "showLevelLines";
    public static final String SHOW_VWAP_BANDS = "showVwapBands";
    public static final String ENABLE_SOUND_ALERT = "enableSoundAlert";
    public static final String BUY_MARKER = "buyMarker";
    public static final String SELL_MARKER = "sellMarker";
    public static final String TARGET_COLOR = "targetColor";
    public static final String STOP_COLOR = "stopColor";
    public static final String ENTRY_COLOR = "entryColor";
    public static final String VWAP_PATH = "vwapPath";
    public static final String UPPER_BAND_PATH = "upperBandPath";
    public static final String LOWER_BAND_PATH = "lowerBandPath";
    public static final String SIGNAL_FONT = "signalFont";

    // --- Value Series Keys ---
    public enum Values {
        SESSION_VWAP,
        UPPER_BAND_2SD,
        LOWER_BAND_2SD,
        OR15_HIGH,
        OR15_LOW,
        ENTRY_LEVEL,
        STOP_LEVEL,
        TARGET_LEVEL
    }

    // --- Signals ---
    public enum Signals {
        BUY_ASIAN_REVERSION,
        SELL_ASIAN_REVERSION,
        EXIT_TIME_2300
    }

    private static final ZoneId NY_ZONE = ZoneId.of("America/New_York");
    private static final DateTimeFormatter TS_FMT = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    private final Map<LocalDate, OpeningRangeState> or15Map = new HashMap<>();
    private final Map<LocalDate, SessionVwapState> vwapMap = new HashMap<>();
    private final Map<LocalDate, GlobexDriftState> globexMap = new HashMap<>();
    private final Map<LocalDate, ActiveTrade> tradeMap = new HashMap<>();
    private final Map<LocalDate, RthSession> rthSessions = new HashMap<>();
    private final java.util.List<RthSession> completedRthList = new java.util.ArrayList<>();
    private final Set<LocalDate> processedDays = new HashSet<>();
    private final Adx5mState adxState = new Adx5mState();

    // Explicit user opt-in tracking across reloads/upgrades
    private boolean userExplicitlyAuthorizedAutoTrade = false;

    // Static monotonic account state across study reloads inside the JVM
    private static double persistedPeakBalance = 25000.00;
    private static double persistedTrailingFloor = 24000.00;
    private static boolean persistedFloorLocked = false;
    private static String configuredForwardTestDir = null;
    private static String configuredStateFilePath = null;
    private static long maxStateAgeMs = DEFAULT_MAX_STATE_AGE_MS;
    private static String lastAccountStateError = "";

    public static double getPersistedPeakBalance() { return persistedPeakBalance; }
    public static double getPersistedTrailingFloor() { return persistedTrailingFloor; }
    public static boolean isPersistedFloorLocked() { return persistedFloorLocked; }

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

    protected File resolveCanonicalStateFile() {
        if (configuredStateFilePath != null && !configuredStateFilePath.trim().isEmpty()) {
            return new File(configuredStateFilePath.trim());
        }
        String dir = configuredForwardTestDir;
        if ((dir == null || dir.trim().isEmpty()) && getSettings() != null) {
            String settingDir = getSettings().getString(FORWARD_TEST_DIR_SETTING, "");
            if (settingDir != null && !settingDir.trim().isEmpty()) {
                dir = settingDir.trim();
            }
        }
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

    private File getDailyLockFile(String strategyId, LocalDate today) {
        try {
            File stateFile = resolveCanonicalStateFile();
            File dir = (stateFile != null && stateFile.getParentFile() != null) ? stateFile.getParentFile() : new File("results/forward_test");
            if (!dir.exists()) dir.mkdirs();
            return new File(dir, "." + strategyId + "_" + today + ".lock");
        } catch (Exception e) {
            return new File("results/forward_test", "." + strategyId + "_" + today + ".lock");
        }
    }

    protected DaemonRiskState loadDaemonRiskState() {
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

            String raw = Files.readString(stateFile.toPath()).trim();
            if (!isValidJsonStructure(raw)) {
                state.verificationError = "INVALID_JSON";
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
        int nextPos = end;
        while (nextPos < json.length() && Character.isWhitespace(json.charAt(nextPos))) nextPos++;
        if (nextPos < json.length() && json.charAt(nextPos) != ',' && json.charAt(nextPos) != '}') {
            return false;
        }
        try {
            double v = Double.parseDouble(json.substring(start, end));
            return Double.isFinite(v);
        } catch (Exception e) {
            return false;
        }
    }

    private static double extractJsonDouble(String json, String key, double fallback) {
        if (!hasFiniteJsonNumber(json, key)) return fallback;
        String token = "\"" + key + "\"";
        int idx = json.indexOf(token);
        int colon = json.indexOf(":", idx + token.length());
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
        try {
            double val = Double.parseDouble(json.substring(start, end));
            return Double.isFinite(val) ? val : fallback;
        } catch (Exception e) {
            return fallback;
        }
    }

    private static boolean extractJsonBoolean(String json, String key, boolean fallback) {
        String token = "\"" + key + "\"";
        int idx = json.indexOf(token);
        if (idx < 0) return fallback;
        int colon = json.indexOf(":", idx + token.length());
        if (colon < 0) return fallback;
        String sub = json.substring(colon + 1).trim().toLowerCase();
        if (sub.startsWith("true")) return true;
        if (sub.startsWith("false")) return false;
        return fallback;
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

    public static boolean resolveAutoTradeSetting(Object rawValue) {
        if (rawValue instanceof Boolean) {
            return Boolean.TRUE.equals(rawValue);
        }
        return false;
    }

    protected boolean isCandidateAutoTradeAuthorized() {
        if (!"CANDIDATE".equals(STRATEGY_TIER)) {
            return false;
        }
        Settings settings = getSettings();
        if (settings == null) {
            return false;
        }
        Boolean raw = settings.getBoolean(ENABLE_LIVE_AUTOTRADE);
        if (raw == null || !Boolean.TRUE.equals(raw)) {
            return false;
        }
        if (!settings.getBoolean(ENABLE_LIVE_AUTOTRADE, false)) {
            return false;
        }
        return userExplicitlyAuthorizedAutoTrade;
    }

    private static class OpeningRangeState {
        double high = -Double.MAX_VALUE;
        double low = Double.MAX_VALUE;
        double open2100 = Double.NaN;
        int barCount = 0;
        long lastBarTime = -1L;
        boolean complete = false;
    }

    private static class SessionVwapState {
        double cumPV = 0.0;
        double cumP2V = 0.0;
        double cumV = 0.0;
        double vwap = Double.NaN;
        double std = 0.0;
        double upper2SD = Double.NaN;
        double lower2SD = Double.NaN;
        double zscore = 0.0;
        double prevZscore = 0.0;
        double prevClose = Double.NaN;
        long lastBarTime = -1L;
    }

    private static class RthSession {
        LocalDate date;
        double high = Double.NEGATIVE_INFINITY;
        double low = Double.POSITIVE_INFINITY;
        double volume = 0.0;
        boolean completed = false;
    }

    private static class GlobexDriftState {
        double open1800 = Double.NaN;
        double close2114 = Double.NaN;
        double rthAtr14 = Double.NaN;
        double rthRvol20 = Double.NaN;
    }

    private static class Adx5mState {
        double barHigh = -Double.MAX_VALUE;
        double barLow = Double.MAX_VALUE;
        double barClose = Double.NaN;
        double prevHigh = Double.NaN;
        double prevLow = Double.NaN;
        double prevClose = Double.NaN;
        double smTR = 0.0;
        double smPlusDM = 0.0;
        double smMinusDM = 0.0;
        double smDX = 20.0;
        double completedAdx = 20.0;
        int barsCount = 0;
        long lastBarTime = -1L;

        void update1mCompletedBar(long barTime, double h, double l, double c, int min) {
            if (barTime == lastBarTime) return;
            lastBarTime = barTime;
            if (h > barHigh) barHigh = h;
            if (l < barLow) barLow = l;
            barClose = c;

            if (min % 5 == 4) {
                if (!Double.isNaN(prevClose)) {
                    double tr = Math.max(barHigh - barLow, Math.max(Math.abs(barHigh - prevClose), Math.abs(barLow - prevClose)));
                    double upMove = barHigh - prevHigh;
                    double downMove = prevLow - barLow;
                    double plusDM = (upMove > downMove && upMove > 0) ? upMove : 0.0;
                    double minusDM = (downMove > upMove && downMove > 0) ? downMove : 0.0;

                    if (barsCount < 14) {
                        smTR += tr;
                        smPlusDM += plusDM;
                        smMinusDM += minusDM;
                        barsCount++;
                    } else {
                        smTR = smTR - (smTR / 14.0) + tr;
                        smPlusDM = smPlusDM - (smPlusDM / 14.0) + plusDM;
                        smMinusDM = smMinusDM - (smMinusDM / 14.0) + minusDM;
                    }

                    if (smTR > 0) {
                        double plusDI = 100.0 * (smPlusDM / smTR);
                        double minusDI = 100.0 * (smMinusDM / smTR);
                        double diSum = plusDI + minusDI;
                        double dx = (diSum > 0) ? (100.0 * Math.abs(plusDI - minusDI) / diSum) : 0.0;
                        smDX = ((smDX * 13.0) + dx) / 14.0;
                        completedAdx = smDX;
                    }
                }
                prevHigh = barHigh;
                prevLow = barLow;
                prevClose = barClose;
                barHigh = -Double.MAX_VALUE;
                barLow = Double.MAX_VALUE;
            }
        }
    }

    public static class ActiveTrade {
        public boolean isLong;
        public double theoreticalEntryPrice;
        public double entryPrice;
        public double actualEntryFill = Double.NaN;
        public double entrySlippagePts = 0.0;
        public double initialRiskDist;
        public double initialTargetDist;
        public double stopPrice;
        public double pendingStopPrice = Double.NaN;
        public double targetPrice;
        public int requestedQty = 0;
        public int filledQty = 0;
        public int attachedBracketQty = 0;
        public long signalTime;
        public long entryTime;
        public long maxExitTime;
        public boolean closed = false;
        public boolean flattenSubmitted = false;
        public boolean breakevenTriggered = false;
        public boolean breakevenModifySubmitted = false;
        public boolean breakevenApplied = false;
        public boolean breakevenModificationFailed = false;
        public boolean bracketsSubmitted = false;
        public Order entryOrder = null;
        public Order slOrder = null;
        public Order tpOrder = null;
        public String entryOrderId = "";
        public String slOrderId = "";
        public String tpOrderId = "";
    }

    @Override
    public void initialize(Defaults defaults) {
        var sd = createSD();
        SettingTab tab = sd.addTab("Strategy 4 Parameters");

        var grpMode = tab.addGroup("Asian / Evening Reversion Parameters (MNQ)");
        grpMode.addRow(new DoubleDescriptor(MIN_OR15_RANGE, "Min 21:00–21:14 OR Range (Pts)", 6.0, 2.0, 100.0, 0.5));
        grpMode.addRow(new DoubleDescriptor(MAX_OR15_RANGE, "Max 21:00–21:14 OR Range (Pts)", 45.0, 5.0, 300.0, 0.5));
        grpMode.addRow(new DoubleDescriptor(MIN_DRIFT_ATR, "Min Globex 18:00–21:14 Drift (x ATR)", 0.15, 0.05, 1.50, 0.05));
        grpMode.addRow(new DoubleDescriptor(MAX_DRIFT_ATR, "Max Globex 18:00–21:14 Drift (x ATR)", 0.85, 0.20, 3.00, 0.05));
        grpMode.addRow(new DoubleDescriptor(MIN_RTH_RVOL20, "Min Completed Same-Day RTH RVOL(20)", 0.85, 0.10, 5.00, 0.05));
        grpMode.addRow(new DoubleDescriptor(STOP_PTS, "Initial Stop Distance (MNQ Pts)", 35.0, 4.0, 100.0, 0.5));
        grpMode.addRow(new DoubleDescriptor(TARGET_PTS, "Profit Target Distance (MNQ Pts)", 37.5, 4.0, 150.0, 0.5));
        grpMode.addRow(new DoubleDescriptor(BREAKEVEN_TRIGGER_R, "Breakeven Trigger (+R)", 1.0, 0.5, 2.0, 0.1));
        grpMode.addRow(new DoubleDescriptor(BREAKEVEN_LOCK_PTS, "Breakeven Lock Offset (Pts)", 0.50, 0.0, 5.0, 0.25));

        var grpVwap = tab.addGroup("Secondary VWAP Band Gate Parameters");
        grpVwap.addRow(new DoubleDescriptor(VWAP_ZSCORE_ENTRY, "VWAP Band Sigma Threshold (Z)", 2.0, 1.0, 3.5, 0.1));
        grpVwap.addRow(new DoubleDescriptor(MAX_ADX_5M, "Max 5m ADX Trend Ceiling", 30.0, 15.0, 50.0, 1.0));
        grpVwap.addRow(new DoubleDescriptor(MAX_DISPLACEMENT_PTS, "Max Net Displacement Ceiling (Pts)", 40.0, 5.0, 150.0, 1.0));

        var grpRisk = tab.addGroup("LucidFlex 25K Candidate Governance & Sizing");
        grpRisk.addRow(new BooleanDescriptor(ENABLE_RATCHET_SIZING, "Enable Anti-Martingale Ratchet (2->3->4 Micros)", true));
        grpRisk.addRow(new IntegerDescriptor(BASE_CONTRACTS, "Fallback Base Micros", 2, 1, 10, 1));
        grpRisk.addRow(new BooleanDescriptor(ENABLE_LIVE_AUTOTRADE, "Enable Live Auto-Trade (Candidate — Explicit User Opt-In Required)", DEFAULT_LIVE_AUTOTRADE));
        grpRisk.addRow(new StringDescriptor(FORWARD_TEST_DIR_SETTING, "Forward-Test State Directory (Optional Override)", ""));
        grpRisk.addRow(new BooleanDescriptor(SHOW_LEVEL_LINES, "Draw Entry / Stop / Target Lines", true));
        grpRisk.addRow(new BooleanDescriptor(SHOW_VWAP_BANDS, "Plot Session VWAP & ±2.0 SD Bands", true));
        grpRisk.addRow(new BooleanDescriptor(ENABLE_SOUND_ALERT, "Play Audio Beep on Signal", true));

        SettingTab displayTab = sd.addTab("Display & Markers");
        var grpMarkers = displayTab.addGroup("Signals & Colors");
        grpMarkers.addRow(new MarkerDescriptor(BUY_MARKER, "Long Reversion Marker",
            Enums$MarkerType.TRIANGLE, Enums$Size.LARGE,
            new Color(148, 103, 189), Color.WHITE, true, true));
        grpMarkers.addRow(new MarkerDescriptor(SELL_MARKER, "Short Reversion Marker",
            Enums$MarkerType.TRIANGLE, Enums$Size.LARGE,
            new Color(220, 38, 38), Color.WHITE, true, true));
        grpMarkers.addRow(new PathDescriptor(VWAP_PATH, "Session VWAP Line",
            new Color(245, 158, 11), 1.5f, null, true, false, true));
        grpMarkers.addRow(new PathDescriptor(UPPER_BAND_PATH, "VWAP Upper +2.0 SD Band",
            new Color(148, 103, 189), 1.0f, new float[]{4f, 4f}, true, false, true));
        grpMarkers.addRow(new PathDescriptor(LOWER_BAND_PATH, "VWAP Lower -2.0 SD Band",
            new Color(148, 103, 189), 1.0f, new float[]{4f, 4f}, true, false, true));
        grpMarkers.addRow(new ColorDescriptor(ENTRY_COLOR, "Entry Line Color", new Color(148, 103, 189)));
        grpMarkers.addRow(new ColorDescriptor(TARGET_COLOR, "Target Line Color", new Color(16, 185, 129)));
        grpMarkers.addRow(new ColorDescriptor(STOP_COLOR, "Stop Line Color", new Color(239, 68, 68)));
        grpMarkers.addRow(new FontDescriptor(SIGNAL_FONT, "Signal Label Font", new Font("SansSerif", Font.BOLD, 11)));

        var desc = createRD();
        desc.setLabelSettings(STOP_PTS, TARGET_PTS);
        desc.exportValue(new com.motivewave.platform.sdk.common.desc.ValueDescriptor(Values.SESSION_VWAP, "Session VWAP"));
        desc.exportValue(new com.motivewave.platform.sdk.common.desc.ValueDescriptor(Values.UPPER_BAND_2SD, "VWAP +2SD"));
        desc.exportValue(new com.motivewave.platform.sdk.common.desc.ValueDescriptor(Values.LOWER_BAND_2SD, "VWAP -2SD"));
        desc.exportValue(new com.motivewave.platform.sdk.common.desc.ValueDescriptor(Values.ENTRY_LEVEL, "Entry Price"));
        desc.exportValue(new com.motivewave.platform.sdk.common.desc.ValueDescriptor(Values.STOP_LEVEL, "Stop Loss"));
        desc.exportValue(new com.motivewave.platform.sdk.common.desc.ValueDescriptor(Values.TARGET_LEVEL, "Profit Target"));

        desc.declarePath(Values.SESSION_VWAP, VWAP_PATH);
        desc.declarePath(Values.UPPER_BAND_2SD, UPPER_BAND_PATH);
        desc.declarePath(Values.LOWER_BAND_2SD, LOWER_BAND_PATH);

        desc.declareSignal(Signals.BUY_ASIAN_REVERSION, "Asian Evening Reversion Long (21:15 ET)");
        desc.declareSignal(Signals.SELL_ASIAN_REVERSION, "Asian Evening Reversion Short (21:15 ET)");
        desc.declareSignal(Signals.EXIT_TIME_2300, "Mandatory Time Flatten (23:00 ET)");

        if (getSettings() != null) {
            getSettings().setAutoEntry(false);
            getSettings().setBoolean(ENABLE_LIVE_AUTOTRADE, false);
        }
        userExplicitlyAuthorizedAutoTrade = false;
    }

    @Override
    public void onLoad(Defaults defaults) {
        super.onLoad(defaults);
        // Candidate governance: remain disabled across study reloads/upgrades unless explicitly re-enabled by user action
        userExplicitlyAuthorizedAutoTrade = false;
        if (getSettings() != null) {
            getSettings().setAutoEntry(false);
            getSettings().setBoolean(ENABLE_LIVE_AUTOTRADE, false);
        }
    }

    @Override
    public void onSettingsUpdated(DataContext ctx) {
        super.onSettingsUpdated(ctx);
        Settings settings = getSettings();
        if (settings == null) {
            userExplicitlyAuthorizedAutoTrade = false;
            return;
        }
        Boolean raw = settings.getBoolean(ENABLE_LIVE_AUTOTRADE);
        if (raw == null || !Boolean.TRUE.equals(raw)) {
            settings.setBoolean(ENABLE_LIVE_AUTOTRADE, false);
            settings.setAutoEntry(false);
            userExplicitlyAuthorizedAutoTrade = false;
        } else {
            userExplicitlyAuthorizedAutoTrade = true;
        }
    }

    @Override
    public void clearState() {
        super.clearState();
        or15Map.clear();
        vwapMap.clear();
        globexMap.clear();
        tradeMap.clear();
        rthSessions.clear();
        completedRthList.clear();
        processedDays.clear();
    }

    @Override
    protected void calculate(int index, DataContext ctx) {
        DataSeries series = ctx.getDataSeries();
        if (series == null || index < 50) return;

        // Requirement 4: Never evaluate or confirm signals on an unfinished bar
        if (!series.isBarComplete(index)) {
            return;
        }

        long barTime = series.getStartTime(index);
        long barEndTime = series.getEndTime(index);
        ZonedDateTime nyBar = Instant.ofEpochMilli(barTime).atZone(NY_ZONE);
        LocalDate today = nyBar.toLocalDate();
        int hour = nyBar.getHour();
        int min = nyBar.getMinute();

        double o = series.getOpen(index);
        double h = series.getHigh(index);
        double l = series.getLow(index);
        double c = series.getClose(index);
        double v = Math.max(1.0, series.getVolume(index));

        Instrument chartInst = ctx.getInstrument();
        if (chartInst == null || !isAcceptedMnqSymbol(chartInst.getSymbol())) {
            return;
        }

        adxState.update1mCompletedBar(barTime, h, l, c, min);

        // Accumulate completed US RTH sessions (09:00 to 16:00 ET / minutes 540 to 960)
        int m = hour * 60 + min;
        if (m >= 540 && m <= 960) {
            RthSession rth = rthSessions.computeIfAbsent(today, k -> {
                RthSession s = new RthSession();
                s.date = k;
                return s;
            });
            rth.high = Math.max(rth.high, h);
            rth.low = Math.min(rth.low, l);
            rth.volume += v;
            if (m == 960 && series.isBarComplete(index) && !rth.completed) {
                rth.completed = true;
                completedRthList.add(rth);
            }
        } else if (m > 960) {
            RthSession rth = rthSessions.get(today);
            if (rth != null && !rth.completed) {
                rth.completed = true;
                completedRthList.add(rth);
            }
        }

        GlobexDriftState globex = globexMap.computeIfAbsent(today, k -> new GlobexDriftState());
        if (hour == 18 && min == 0 && Double.isNaN(globex.open1800)) {
            globex.open1800 = o;
        }

        // Accumulate 21:00–21:14 ET Opening Range strictly on completed bars
        if (hour == 21 && min >= 0 && min <= 14) {
            OpeningRangeState or15 = or15Map.computeIfAbsent(today, k -> new OpeningRangeState());
            if (or15.lastBarTime != barTime) {
                or15.lastBarTime = barTime;
                if (min == 0 || Double.isNaN(or15.open2100)) {
                    or15.open2100 = o;
                }
                if (h > or15.high) or15.high = h;
                if (l < or15.low) or15.low = l;
                or15.barCount++;
            }
            if (min == 14 && series.isBarComplete(index)) {
                or15.complete = true;
                globex.close2114 = c;
            }
        }

        // Accumulate Expanding Point-in-Time Session VWAP (21:00–23:00 ET) strictly once per completed bar
        boolean inEveningSession = (hour == 21 || hour == 22 || (hour == 23 && min == 0));
        if (inEveningSession) {
            SessionVwapState vwap = vwapMap.computeIfAbsent(today, k -> new SessionVwapState());
            if (vwap.lastBarTime != barTime) {
                vwap.lastBarTime = barTime;
                vwap.prevZscore = vwap.zscore;
                vwap.prevClose = Double.isNaN(vwap.vwap) ? c : vwap.prevClose;

                double tp = (h + l + c) / 3.0;
                vwap.cumPV += tp * v;
                vwap.cumP2V += (tp * tp) * v;
                vwap.cumV += v;

                vwap.vwap = vwap.cumPV / vwap.cumV;
                double variance = Math.max(0.0, (vwap.cumP2V / vwap.cumV) - (vwap.vwap * vwap.vwap));
                vwap.std = Math.sqrt(variance);
                double zEntry = getSettings().getDouble(VWAP_ZSCORE_ENTRY, 2.0);
                vwap.upper2SD = vwap.vwap + zEntry * vwap.std;
                vwap.lower2SD = vwap.vwap - zEntry * vwap.std;
                vwap.zscore = (vwap.std > 1e-6) ? ((c - vwap.vwap) / vwap.std) : 0.0;
            }

            if (getSettings().getBoolean(SHOW_VWAP_BANDS, true)) {
                series.setDouble(index, Values.SESSION_VWAP, vwap.vwap);
                series.setDouble(index, Values.UPPER_BAND_2SD, vwap.upper2SD);
                series.setDouble(index, Values.LOWER_BAND_2SD, vwap.lower2SD);
            }
        }

        // Evaluate Primary Signal at Completed 21:14 ET Bar (for 21:15 ET Execution Opportunity)
        OpeningRangeState or15 = or15Map.get(today);
        if (hour == 21 && min == 14 && series.isBarComplete(index) && or15 != null && or15.complete && !processedDays.contains(today)) {
            double orRange = or15.high - or15.low;
            double minOrRange = getSettings().getDouble(MIN_OR15_RANGE, 6.0);
            double maxOrRange = getSettings().getDouble(MAX_OR15_RANGE, 45.0);

            if (orRange >= minOrRange && orRange <= maxOrRange && !Double.isNaN(globex.open1800) && completedRthList.size() >= 20) {
                RthSession todayRth = rthSessions.get(today);
                if (todayRth != null && todayRth.completed) {
                    double sumRange = 0.0;
                    for (int i = completedRthList.size() - 14; i < completedRthList.size(); i++) {
                        RthSession s = completedRthList.get(i);
                        sumRange += (s.high - s.low);
                    }
                    double rthAtr14 = sumRange / 14.0;

                    double sumVol = 0.0;
                    for (int i = completedRthList.size() - 20; i < completedRthList.size(); i++) {
                        RthSession s = completedRthList.get(i);
                        sumVol += s.volume;
                    }
                    double rthVol20 = sumVol / 20.0;
                    double rthRvol = todayRth.volume / Math.max(1.0, rthVol20);
                    globex.rthAtr14 = rthAtr14;
                    globex.rthRvol20 = rthRvol;

                    double minRvol = getSettings().getDouble(MIN_RTH_RVOL20, 0.85);
                    if (rthRvol >= minRvol) {
                        double drift = globex.close2114 - globex.open1800;
                        double absDrift = Math.abs(drift);
                        double minDriftPts = getSettings().getDouble(MIN_DRIFT_ATR, 0.15) * rthAtr14;
                        double maxDriftPts = getSettings().getDouble(MAX_DRIFT_ATR, 0.85) * rthAtr14;

                        if (absDrift >= minDriftPts && absDrift <= maxDriftPts) {
                            double stopPts = getSettings().getDouble(STOP_PTS, 35.0);
                            double targetPts = getSettings().getDouble(TARGET_PTS, 37.5);
                            long entryOpportunityTime = (barEndTime > barTime) ? barEndTime : (barTime + 60_000L);
                            long sessionFlattenTime = nyBar.withHour(23).withMinute(0).withSecond(0).withNano(0).toInstant().toEpochMilli();

                            if (drift > 0 && c < or15.open2100) {
                                processedDays.add(today);
                                triggerSignal(index, ctx, series, today, false, c, c + stopPts, c - targetPts, stopPts, targetPts, barTime, entryOpportunityTime, sessionFlattenTime, "GLOBEX_DRIFT_EXHAUSTION_SHORT");
                            } else if (drift < 0 && c > or15.open2100) {
                                processedDays.add(today);
                                triggerSignal(index, ctx, series, today, true, c, c - stopPts, c + targetPts, stopPts, targetPts, barTime, entryOpportunityTime, sessionFlattenTime, "GLOBEX_DRIFT_EXHAUSTION_LONG");
                            }
                        }
                    }
                }
            }
        }

        // Update prevClose for Session VWAP
        if (inEveningSession && vwapMap.containsKey(today)) {
            vwapMap.get(today).prevClose = c;
        }

        // Active Trade Lifecycle & Conservative Completed-Bar Conflict / Breakeven Tracking
        ActiveTrade trade = tradeMap.get(today);
        if (trade != null && !trade.closed && barTime >= trade.entryTime) {
            series.setDouble(index, Values.ENTRY_LEVEL, trade.entryPrice);
            series.setDouble(index, Values.STOP_LEVEL, trade.stopPrice);
            series.setDouble(index, Values.TARGET_LEVEL, trade.targetPrice);

            // 1. Check stop and target against the stopPrice active at the start of this bar
            boolean hitStop = trade.isLong ? (l <= trade.stopPrice) : (h >= trade.stopPrice);
            boolean hitTarget = trade.isLong ? (h >= trade.targetPrice) : (l <= trade.targetPrice);

            if (hitStop || hitTarget || (hour == 23 && min == 0) || barTime >= trade.maxExitTime) {
                if (series.size() - 1 > index) {
                    trade.closed = true;
                }
                if (!hitStop && !hitTarget && ((hour == 23 && min == 0) || barTime >= trade.maxExitTime)) {
                    ctx.signal(index, Signals.EXIT_TIME_2300, "S4 Mandatory Time Flatten (23:00 ET)", c);
                }
            } else if (!trade.breakevenTriggered && !trade.breakevenApplied && !trade.breakevenModificationFailed) {
                // 2. Breakeven +1.0R trigger activates only after surviving the bar without hitting stop/target
                double anchorEntry = !Double.isNaN(trade.actualEntryFill) ? trade.actualEntryFill : trade.entryPrice;
                double initialRisk = trade.initialRiskDist > 0 ? trade.initialRiskDist : getSettings().getDouble(STOP_PTS, 35.0);
                double beTrigger = getSettings().getDouble(BREAKEVEN_TRIGGER_R, 1.0) * initialRisk;
                double beLockPts = getSettings().getDouble(BREAKEVEN_LOCK_PTS, 0.50);

                if (trade.isLong && h >= anchorEntry + beTrigger) {
                    trade.breakevenTriggered = true;
                    trade.pendingStopPrice = anchorEntry + beLockPts;
                } else if (!trade.isLong && l <= anchorEntry - beTrigger) {
                    trade.breakevenTriggered = true;
                    trade.pendingStopPrice = anchorEntry - beLockPts;
                }
            }
        }
    }

    private void triggerSignal(
            int index,
            DataContext ctx,
            DataSeries series,
            LocalDate today,
            boolean isLong,
            double theoEntry,
            double stop,
            double target,
            double riskDist,
            double targetDist,
            long signalTime,
            long entryTime,
            long maxExitTime,
            String reason) {

        ActiveTrade trade = new ActiveTrade();
        trade.isLong = isLong;
        trade.theoreticalEntryPrice = theoEntry;
        trade.entryPrice = theoEntry;
        trade.initialRiskDist = riskDist;
        trade.initialTargetDist = targetDist;
        trade.stopPrice = stop;
        trade.targetPrice = target;
        trade.signalTime = signalTime;
        trade.entryTime = entryTime;
        trade.maxExitTime = maxExitTime;
        tradeMap.put(today, trade);

        series.setDouble(index, Values.ENTRY_LEVEL, theoEntry);
        series.setDouble(index, Values.STOP_LEVEL, stop);
        series.setDouble(index, Values.TARGET_LEVEL, target);

        // Requirement 1.3: Always preserve visual markers, level lines, signals, and sound alerts
        var markerDesc = getSettings().getMarker(isLong ? BUY_MARKER : SELL_MARKER);
        String label = (isLong ? "LONG S4 REV @ " : "SHORT S4 REV @ ") + String.format("%.2f", theoEntry);
        if (markerDesc != null && markerDesc.isEnabled()) {
            Coordinate coord = new Coordinate(signalTime, isLong ? series.getLow(index) : series.getHigh(index));
            addFigure(Plot.PRICE, new Marker(coord, isLong ? Enums$Position.BOTTOM : Enums$Position.TOP, markerDesc, label));
        }

        if (getSettings().getBoolean(SHOW_LEVEL_LINES, true)) {
            Color entryCol = getSettings().getColor(ENTRY_COLOR, new Color(148, 103, 189));
            Color stopCol = getSettings().getColor(STOP_COLOR, new Color(239, 68, 68));
            Color targetCol = getSettings().getColor(TARGET_COLOR, new Color(16, 185, 129));
            Line entryLine = new Line(signalTime, theoEntry, maxExitTime, theoEntry);
            entryLine.setColor(entryCol);
            addFigure(Plot.PRICE, entryLine);

            Line slLine = new Line(signalTime, stop, maxExitTime, stop);
            slLine.setColor(stopCol);
            slLine.setStroke(new java.awt.BasicStroke(1.5f, java.awt.BasicStroke.CAP_BUTT, java.awt.BasicStroke.JOIN_MITER, 10.0f, new float[]{4f, 4f}, 0.0f));
            addFigure(Plot.PRICE, slLine);

            Line tpLine = new Line(signalTime, target, maxExitTime, target);
            tpLine.setColor(targetCol);
            tpLine.setStroke(new java.awt.BasicStroke(1.5f, java.awt.BasicStroke.CAP_BUTT, java.awt.BasicStroke.JOIN_MITER, 10.0f, new float[]{4f, 4f}, 0.0f));
            addFigure(Plot.PRICE, tpLine);
        }

        ctx.signal(index, isLong ? Signals.BUY_ASIAN_REVERSION : Signals.SELL_ASIAN_REVERSION,
            String.format("Asian Evening Reversion %s (%s) | Entry: %.2f | SL: %.2f | TP: %.2f",
                isLong ? "LONG" : "SHORT", reason, theoEntry, stop, target),
            theoEntry);

        if (getSettings().getBoolean(ENABLE_SOUND_ALERT, true)) {
            try { Toolkit.getDefaultToolkit().beep(); } catch (Exception ignored) {}
        }

        // Requirement 1: Block automated order submission unless candidate execution is explicitly authorized
        if (!isCandidateAutoTradeAuthorized()) {
            logExecutionToCsv("CANDIDATE_AUTOTRADE_DISABLED", isLong ? "BUY" : "SELL", 0, theoEntry, Double.NaN, 0.0, stop, target, "CANDIDATE_TIER_OPT_IN_DISABLED");
            return;
        }
    }

    @Override
    public void onSignal(OrderContext ctx, Object signal) {
        if (ctx == null) return;
        if (!isCandidateAutoTradeAuthorized()) return;
        DataContext dataCtx = ctx.getDataContext();
        if (dataCtx == null || dataCtx.getDataSeries() == null) return;
        DataSeries series = dataCtx.getDataSeries();
        int lastIdx = series.size() - 1;
        if (lastIdx < 0 || !series.isBarComplete(lastIdx)) return;

        long barTime = series.getStartTime(lastIdx);
        LocalDate today = Instant.ofEpochMilli(barTime).atZone(NY_ZONE).toLocalDate();
        ActiveTrade trade = tradeMap.get(today);
        if (trade == null) return;

        if (signal == Signals.BUY_ASIAN_REVERSION || signal == Signals.SELL_ASIAN_REVERSION) {
            if (trade.closed) return;
            executeAutoTradeIfArmed(ctx, dataCtx, trade);
        } else if (signal == Signals.EXIT_TIME_2300 && ctx.getPosition() != 0) {
            if (!trade.flattenSubmitted) {
                trade.flattenSubmitted = true;
                if (trade.tpOrder != null && trade.tpOrder.isActive()) {
                    ctx.cancelOrders(trade.tpOrder);
                }
                ctx.closeAtMarket();
                logExecutionToCsv("TIME_EXIT_2300_SUBMITTED", trade.isLong ? "SELL" : "BUY", Math.abs(ctx.getPosition()), trade.theoreticalEntryPrice, trade.actualEntryFill, trade.entrySlippagePts, trade.stopPrice, trade.targetPrice, "FLATTEN_SUBMITTED_AT_2300_ET");
            }
        }
    }

    @Override
    public void onBarClose(OrderContext ctx) {
        if (ctx == null) return;
        DataContext dataCtx = ctx.getDataContext();
        if (dataCtx == null || dataCtx.getDataSeries() == null) return;
        DataSeries series = dataCtx.getDataSeries();
        int lastIdx = series.size() - 1;
        if (lastIdx < 0 || !series.isBarComplete(lastIdx)) return;

        long barTime = series.getStartTime(lastIdx);
        ZonedDateTime nyBar = Instant.ofEpochMilli(barTime).atZone(NY_ZONE);
        LocalDate today = nyBar.toLocalDate();
        ActiveTrade trade = tradeMap.get(today);

        // Reconcile restart state: if position exists at broker on restart, ensure daily lock exists
        if (ctx.getPosition() != 0) {
            File lockFile = getDailyLockFile("asian_evening_reversion_s4", today);
            if (lockFile != null && !lockFile.exists()) {
                try { lockFile.createNewFile(); } catch (Exception ignored) {}
            }
        }

        if (trade == null) return;

        // 1. Keep protective bracket quantities synchronized with actual position
        if (ctx.getPosition() != 0 && trade.bracketsSubmitted) {
            verifyAndSyncBracketQuantities(ctx, trade);
        }

        // 2. Modify actual working broker stop order in-place when +1.0R breakeven is triggered
        if (ctx.getPosition() != 0
                && trade.breakevenTriggered
                && !trade.breakevenApplied
                && !trade.breakevenModifySubmitted
                && !trade.breakevenModificationFailed
                && trade.bracketsSubmitted) {
            modifyWorkingStopToBreakeven(ctx, trade);
        }

        // 3. Enforce 23:00 ET time flatten
        if ((nyBar.getHour() == 23 && nyBar.getMinute() >= 0) || barTime >= trade.maxExitTime) {
            if (ctx.getPosition() != 0) {
                if (!trade.flattenSubmitted) {
                    trade.flattenSubmitted = true;
                    int posQty = Math.abs(ctx.getPosition());
                    if (trade.tpOrder != null && trade.tpOrder.isActive()) {
                        ctx.cancelOrders(trade.tpOrder);
                    }
                    ctx.closeAtMarket();
                    // Do not mark trade.closed = true until broker confirms position flat
                    logExecutionToCsv("TIME_EXIT_2300_SUBMITTED", trade.isLong ? "SELL" : "BUY", posQty, trade.theoreticalEntryPrice, trade.actualEntryFill, trade.entrySlippagePts, trade.stopPrice, trade.targetPrice, "ON_BAR_CLOSE_FLATTEN_SUBMITTED");
                }
            } else {
                trade.flattenSubmitted = false;
                trade.closed = true;
            }
        }
    }

    public synchronized boolean modifyWorkingStopToBreakeven(OrderContext ctx, ActiveTrade trade) {
        if (ctx == null || trade == null || !trade.bracketsSubmitted) return false;
        int posQty = Math.abs(ctx.getPosition());
        if (posQty <= 0) return false;

        Instrument inst = ctx.getInstrument();
        if (inst == null) return false;

        if (trade.slOrder == null || !trade.slOrder.isActive() || trade.slOrder.isCancelled() || trade.slOrder.isFilled()) {
            applyProtectiveFailurePolicy(ctx, trade, "STOP_ORDER_INACTIVE_OR_MISSING");
            return false;
        }

        double desiredStop = !Double.isNaN(trade.pendingStopPrice)
            ? trade.pendingStopPrice
            : (trade.isLong
                ? ((!Double.isNaN(trade.actualEntryFill) ? trade.actualEntryFill : trade.entryPrice) + getSettings().getDouble(BREAKEVEN_LOCK_PTS, 0.50))
                : ((!Double.isNaN(trade.actualEntryFill) ? trade.actualEntryFill : trade.entryPrice) - getSettings().getDouble(BREAKEVEN_LOCK_PTS, 0.50)));

        float newStop = inst.round((float) desiredStop);
        boolean improvesProtection = trade.isLong ? (newStop > trade.stopPrice) : (newStop < trade.stopPrice);
        if (!improvesProtection) {
            return false;
        }

        try {
            trade.slOrder.setAdjStopPrice(newStop);
            if (trade.slOrder.getQuantity() != posQty) {
                trade.slOrder.setAdjQuantity(posQty);
            }
            if (trade.tpOrder != null && trade.tpOrder.isActive() && trade.tpOrder.getQuantity() != posQty) {
                trade.tpOrder.setAdjQuantity(posQty);
                ctx.submitOrders(trade.slOrder, trade.tpOrder);
            } else {
                ctx.submitOrders(trade.slOrder);
            }
            trade.breakevenModifySubmitted = true;
            trade.attachedBracketQty = posQty;
            logExecutionToCsv("BREAKEVEN_MODIFY_SUBMITTED", trade.isLong ? "SELL_STOP" : "BUY_STOP", posQty, trade.theoreticalEntryPrice, trade.actualEntryFill, trade.entrySlippagePts, newStop, trade.targetPrice, "IN_PLACE_SET_ADJ_STOP_PRICE");
            return true;
        } catch (Exception e) {
            applyProtectiveFailurePolicy(ctx, trade, "SUBMIT_MODIFICATION_EXCEPTION:" + e.getMessage());
            return false;
        }
    }

    public synchronized void verifyAndSyncBracketQuantities(OrderContext ctx, ActiveTrade trade) {
        if (ctx == null || trade == null || !trade.bracketsSubmitted) return;
        int posQty = Math.abs(ctx.getPosition());
        if (posQty <= 0) return;

        if (trade.slOrder == null || !trade.slOrder.isActive() || trade.slOrder.isCancelled()) {
            applyProtectiveFailurePolicy(ctx, trade, "PROTECTIVE_STOP_MISSING_DURING_POSITION_SYNC");
            return;
        }

        boolean needsUpdate = false;
        if (trade.slOrder.getQuantity() != posQty && trade.slOrder.getAdjQuantity() != posQty) {
            trade.slOrder.setAdjQuantity(posQty);
            needsUpdate = true;
        }
        if (trade.tpOrder != null && trade.tpOrder.isActive()
                && trade.tpOrder.getQuantity() != posQty && trade.tpOrder.getAdjQuantity() != posQty) {
            trade.tpOrder.setAdjQuantity(posQty);
            needsUpdate = true;
        }
        if (needsUpdate) {
            if (trade.tpOrder != null && trade.tpOrder.isActive()) {
                ctx.submitOrders(trade.slOrder, trade.tpOrder);
            } else {
                ctx.submitOrders(trade.slOrder);
            }
            trade.attachedBracketQty = posQty;
            logExecutionToCsv("BRACKET_QTY_SYNCED", trade.isLong ? "LONG" : "SHORT", posQty, trade.theoreticalEntryPrice, trade.actualEntryFill, trade.entrySlippagePts, trade.stopPrice, trade.targetPrice, "PARTIAL_FILL_QTY_RECONCILED");
        }
    }

    private void applyProtectiveFailurePolicy(OrderContext ctx, ActiveTrade trade, String reason) {
        trade.breakevenModifySubmitted = false;
        trade.breakevenApplied = false;
        trade.breakevenModificationFailed = true;

        boolean stopStillActive = (trade.slOrder != null && trade.slOrder.isActive() && !trade.slOrder.isCancelled() && !trade.slOrder.isFilled());
        if (!stopStillActive && ctx != null && ctx.getPosition() != 0) {
            if (!trade.flattenSubmitted) {
                trade.flattenSubmitted = true;
                int posQty = Math.abs(ctx.getPosition());
                if (trade.tpOrder != null && trade.tpOrder.isActive()) {
                    ctx.cancelOrders(trade.tpOrder);
                }
                ctx.closeAtMarket();
                logExecutionToCsv("PROTECTIVE_STOP_FAILURE_EMERGENCY_FLATTEN_SUBMITTED", trade.isLong ? "SELL" : "BUY", posQty, trade.theoreticalEntryPrice, trade.actualEntryFill, trade.entrySlippagePts, trade.stopPrice, trade.targetPrice, reason);
            }
        } else {
            // Original working stop remains active at original stopPrice; do NOT pretend tighter stop is active
            logExecutionToCsv("BREAKEVEN_MODIFICATION_FAILED_ORIGINAL_STOP_RETAINED", trade.isLong ? "LONG" : "SHORT", Math.abs(ctx != null ? ctx.getPosition() : trade.filledQty), trade.theoreticalEntryPrice, trade.actualEntryFill, trade.entrySlippagePts, trade.stopPrice, trade.targetPrice, reason);
        }
    }

    @Override
    public void onDeactivate(OrderContext ctx) {
        setState(Enums$StrategyState.INACTIVE);
        if (ctx != null) {
            if (ctx.getPosition() == 0) {
                ctx.cancelOrders();
            } else {
                logExecutionToCsv("STRATEGY_DEACTIVATED_POSITION_REMAINS_OPEN", "NONE",
                    Math.abs(ctx.getPosition()), 0.0, Double.NaN, 0.0, 0.0, 0.0,
                    "Position open (" + ctx.getPosition() + "); protective orders preserved.");
            }
        }
        logExecutionToCsv("STRATEGY_DEACTIVATED", "NONE", 0, 0.0, Double.NaN, 0.0, 0.0, 0.0, "Strategy deactivated by user");
    }

    @Override
    public void onPositionClosed(OrderContext ctx) {
        if (ctx != null) {
            ctx.cancelOrders();
        }
        for (ActiveTrade trade : tradeMap.values()) {
            trade.flattenSubmitted = false;
            trade.closed = true;
        }
        logExecutionToCsv("POSITION_CLOSED_CONFIRMED", "FLAT", 0, 0.0, Double.NaN, 0.0, 0.0, 0.0, "BROKER_POSITION_FLAT");
    }

    @Override
    public void onOrderModified(OrderContext ctx, Order order) {
        if (ctx == null || order == null) return;
        for (ActiveTrade trade : tradeMap.values()) {
            if (trade.closed) continue;
            if (order == trade.slOrder || (trade.slOrderId != null && !trade.slOrderId.isEmpty() && trade.slOrderId.equals(order.getOrderId()))) {
                Float modStop = order.getStopPrice() != null ? order.getStopPrice() : order.getAdjStopPrice();
                double newPrice = (modStop != null && Float.isFinite(modStop)) ? modStop.doubleValue() : (Double.isNaN(trade.pendingStopPrice) ? trade.stopPrice : trade.pendingStopPrice);
                double tickSize = ctx.getInstrument() != null ? ctx.getInstrument().getTickSize() : 0.25;
                boolean matchesPending = !Double.isNaN(trade.pendingStopPrice) && Math.abs(newPrice - trade.pendingStopPrice) <= (tickSize + 1e-4);
                if (trade.breakevenModifySubmitted && matchesPending) {
                    trade.stopPrice = newPrice;
                    trade.breakevenApplied = true;
                    trade.breakevenModifySubmitted = false;
                    logExecutionToCsv("BREAKEVEN_RATCHET_CONFIRMED", trade.isLong ? "SELL_STOP" : "BUY_STOP", Math.abs(ctx.getPosition()), trade.theoreticalEntryPrice, trade.actualEntryFill, trade.entrySlippagePts, trade.stopPrice, trade.targetPrice, "BROKER_STOP_MODIFIED");
                } else {
                    trade.stopPrice = newPrice;
                    trade.breakevenModifySubmitted = false;
                    logExecutionToCsv("STOP_ORDER_MODIFIED_EXTERNAL", trade.isLong ? "SELL_STOP" : "BUY_STOP", Math.abs(ctx.getPosition()), trade.theoreticalEntryPrice, trade.actualEntryFill, trade.entrySlippagePts, trade.stopPrice, trade.targetPrice, "MOD_PRICE=" + newPrice);
                }
                break;
            }
        }
    }

    @Override
    public void onOrderRejected(OrderContext ctx, Order order) {
        if (ctx == null || order == null) return;
        for (ActiveTrade trade : tradeMap.values()) {
            if (trade.closed) continue;
            if (trade.flattenSubmitted) {
                trade.flattenSubmitted = false;
                logExecutionToCsv("FLATTEN_ORDER_REJECTED", trade.isLong ? "SELL" : "BUY", Math.abs(ctx.getPosition()), trade.theoreticalEntryPrice, trade.actualEntryFill, trade.entrySlippagePts, trade.stopPrice, trade.targetPrice, "FLATTEN_REJECTED:" + order.getOrderId());
            }
            if (order == trade.entryOrder || (trade.entryOrderId != null && !trade.entryOrderId.isEmpty() && trade.entryOrderId.equals(order.getOrderId()))) {
                trade.entryOrder = null;
                trade.closed = true;
                logExecutionToCsv("ENTRY_ORDER_REJECTED", trade.isLong ? "BUY" : "SELL", trade.requestedQty, trade.theoreticalEntryPrice, Double.NaN, 0.0, trade.stopPrice, trade.targetPrice, "ENTRY_REJECTED:" + order.getOrderId());
                break;
            }
            if (order == trade.slOrder || (trade.slOrderId != null && !trade.slOrderId.isEmpty() && trade.slOrderId.equals(order.getOrderId()))
                    || order == trade.tpOrder || (trade.tpOrderId != null && !trade.tpOrderId.isEmpty() && trade.tpOrderId.equals(order.getOrderId()))) {
                applyProtectiveFailurePolicy(ctx, trade, "ON_BRACKET_REJECTED:" + order.getOrderId());
                break;
            }
        }
    }

    @Override
    public void onOrderCancelled(OrderContext ctx, Order order) {
        if (ctx == null || order == null) return;
        for (ActiveTrade trade : tradeMap.values()) {
            if (trade.closed) continue;
            if (order == trade.slOrder && ctx.getPosition() != 0) {
                applyProtectiveFailurePolicy(ctx, trade, "PROTECTIVE_STOP_CANCELLED_UNEXPECTEDLY");
                break;
            }
        }
    }

    private synchronized void executeAutoTradeIfArmed(OrderContext ctx, DataContext dataCtx, ActiveTrade trade) {
        if (ctx == null) return;
        if (!isCandidateAutoTradeAuthorized()) return;
        if (ctx.getPosition() != 0 || trade.bracketsSubmitted || trade.entryOrder != null) return;
        Instrument inst = ctx.getInstrument();
        if (inst == null || !isAcceptedMnqSymbol(inst.getSymbol())) {
            logExecutionToCsv("ORDER_BLOCKED_UNAUTHORIZED_INSTRUMENT", trade.isLong ? "BUY" : "SELL", 0, trade.theoreticalEntryPrice, Double.NaN, 0.0, trade.stopPrice, trade.targetPrice, "INSTRUMENT_NOT_MNQ:" + (inst != null ? inst.getSymbol() : "null"));
            return;
        }

        long now = ctx.getCurrentTime();
        LocalDate today = Instant.ofEpochMilli(now).atZone(NY_ZONE).toLocalDate();
        File lockFile = getDailyLockFile("asian_evening_reversion_s4", today);
        if (lockFile != null) {
            try {
                if (!lockFile.createNewFile()) {
                    logExecutionToCsv("ORDER_BLOCKED_SESSION_COOLDOWN", trade.isLong ? "BUY" : "SELL", 0, trade.theoreticalEntryPrice, Double.NaN, 0.0, trade.stopPrice, trade.targetPrice, "DAILY_LOCK_ACTIVE:" + today);
                    return;
                }
            } catch (Exception e) {
                logExecutionToCsv("ORDER_BLOCKED_SESSION_COOLDOWN", trade.isLong ? "BUY" : "SELL", 0, trade.theoreticalEntryPrice, Double.NaN, 0.0, trade.stopPrice, trade.targetPrice, "LOCK_CREATION_FAILED:" + e.getMessage());
                return;
            }
        }

        int contracts = resolveContracts(ctx, dataCtx);
        if (contracts <= 0) {
            logExecutionToCsv("ORDER_BLOCKED_UNVERIFIED_ACCOUNT", trade.isLong ? "BUY" : "SELL", 0, trade.theoreticalEntryPrice, Double.NaN, 0.0, trade.stopPrice, trade.targetPrice, lastAccountStateError != null && !lastAccountStateError.isEmpty() ? lastAccountStateError : "Fail-closed sizing returned 0");
            return;
        }

        Enums$OrderAction entryAction = trade.isLong ? Enums$OrderAction.BUY : Enums$OrderAction.SELL;
        String orderRef = "LucidS4_Entry_" + trade.signalTime;
        Order entryOrder = ctx.createMarketOrder(inst, orderRef, entryAction, contracts);
        if (entryOrder == null) return;

        trade.entryOrder = entryOrder;
        trade.requestedQty = contracts;
        ctx.submitOrders(entryOrder);
        trade.entryOrderId = entryOrder.getOrderId() != null ? entryOrder.getOrderId() : orderRef;

        logExecutionToCsv("ENTRY_SUBMITTED", entryAction.name(), contracts, trade.theoreticalEntryPrice, Double.NaN, 0.0, trade.stopPrice, trade.targetPrice, orderRef);
    }

    @Override
    public void onOrderFilled(OrderContext ctx, Order order) {
        if (ctx == null || order == null) return;
        Instrument inst = ctx.getInstrument();
        if (inst == null) return;

        for (ActiveTrade trade : tradeMap.values()) {
            if (trade.closed) continue;

            // 1. Check if position reached zero (protective stop, target leg, or flatten market fill)
            if (ctx.getPosition() == 0) {
                ctx.cancelOrders();
                trade.flattenSubmitted = false;
                trade.closed = true;
                String exitTag = (order == trade.slOrder)
                    ? (trade.breakevenApplied ? "EXIT_BREAKEVEN_STOP" : "EXIT_STOP_LOSS")
                    : ((order == trade.tpOrder) ? "EXIT_PROFIT_TARGET" : "EXIT_POSITION_FLAT");
                logExecutionToCsv(exitTag, trade.isLong ? "SELL" : "BUY", order.getFilled(), trade.theoreticalEntryPrice, trade.actualEntryFill, trade.entrySlippagePts, trade.stopPrice, trade.targetPrice, "EXIT_FILL=" + order.getAvgFillPrice());
                return;
            }

            // 1b. Check if protective stop or target leg filled partially
            if (order == trade.slOrder || order == trade.tpOrder) {
                verifyAndSyncBracketQuantities(ctx, trade);
                return;
            }

            // 2. Entry order fill (full or partial): anchor stop and target from actual average fill price
            boolean isTrackedEntry = (order == trade.entryOrder)
                || (trade.entryOrderId != null && !trade.entryOrderId.isEmpty() && trade.entryOrderId.equals(order.getOrderId()));
            if (!isTrackedEntry) continue;

            int posQty = Math.abs(ctx.getPosition());
            if (posQty <= 0) continue;

            double actualFill = Double.NaN;
            if (order.getAvgFillPrice() > 0 && Float.isFinite(order.getAvgFillPrice())) {
                actualFill = order.getAvgFillPrice();
            } else if (ctx.getAvgEntryPrice() > 0 && Float.isFinite(ctx.getAvgEntryPrice())) {
                actualFill = ctx.getAvgEntryPrice();
            } else {
                actualFill = trade.theoreticalEntryPrice;
            }

            double riskDist = trade.initialRiskDist > 0 ? trade.initialRiskDist : getSettings().getDouble(STOP_PTS, 35.0);
            double targetDist = trade.initialTargetDist > 0 ? trade.initialTargetDist : getSettings().getDouble(TARGET_PTS, 37.5);

            trade.actualEntryFill = actualFill;
            trade.entryPrice = actualFill;
            trade.filledQty = posQty;
            trade.entrySlippagePts = trade.isLong
                ? (actualFill - trade.theoreticalEntryPrice)
                : (trade.theoreticalEntryPrice - actualFill);

            float stopF = inst.round((float) (trade.isLong ? (actualFill - riskDist) : (actualFill + riskDist)));
            float targetF = inst.round((float) (trade.isLong ? (actualFill + targetDist) : (actualFill - targetDist)));

            if (!trade.bracketsSubmitted) {
                Enums$OrderAction exitAction = trade.isLong ? Enums$OrderAction.SELL : Enums$OrderAction.BUY;
                String slRef = "LucidS4_SL_" + trade.signalTime;
                String tpRef = "LucidS4_TP_" + trade.signalTime;
                Order slOrder = ctx.createStopOrder(inst, slRef, exitAction, Enums$TIF.GTC, posQty, stopF);
                Order tpOrder = ctx.createLimitOrder(inst, tpRef, exitAction, Enums$TIF.GTC, posQty, targetF);
                if (slOrder != null && tpOrder != null) {
                    trade.slOrder = slOrder;
                    trade.tpOrder = tpOrder;
                    trade.stopPrice = stopF;
                    trade.targetPrice = targetF;
                    trade.attachedBracketQty = posQty;
                    trade.bracketsSubmitted = true;
                    ctx.submitOrders(slOrder, tpOrder);
                    trade.slOrderId = slOrder.getOrderId() != null ? slOrder.getOrderId() : slRef;
                    trade.tpOrderId = tpOrder.getOrderId() != null ? tpOrder.getOrderId() : tpRef;
                    logExecutionToCsv("BRACKETS_SUBMITTED", exitAction.name(), posQty, trade.theoreticalEntryPrice, trade.actualEntryFill, trade.entrySlippagePts, trade.stopPrice, trade.targetPrice, slRef + "|" + tpRef);
                }
            } else {
                // Subsequent partial entry fill: update existing bracket quantities and fill-anchored prices in-place
                if (trade.slOrder != null && trade.slOrder.isActive()) {
                    if (!trade.breakevenApplied) {
                        trade.slOrder.setAdjStopPrice(stopF);
                        trade.stopPrice = stopF;
                    }
                    trade.slOrder.setAdjQuantity(posQty);
                }
                if (trade.tpOrder != null && trade.tpOrder.isActive()) {
                    trade.tpOrder.setAdjLimitPrice(targetF);
                    trade.tpOrder.setAdjQuantity(posQty);
                    trade.targetPrice = targetF;
                }
                ctx.submitOrders(trade.slOrder, trade.tpOrder);
                trade.attachedBracketQty = posQty;
                logExecutionToCsv("PARTIAL_FILL_BRACKETS_ADJUSTED", trade.isLong ? "SELL" : "BUY", posQty, trade.theoreticalEntryPrice, trade.actualEntryFill, trade.entrySlippagePts, trade.stopPrice, trade.targetPrice, "UPDATED_AVG_FILL");
            }
            break;
        }
    }

    protected int resolveContracts(OrderContext ctx, int fallbackContracts) {
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

            int maxAllowed = riskState.recommendedMicros;
            if (fallbackContracts > 0) {
                maxAllowed = Math.min(maxAllowed, fallbackContracts);
            } else if (fallbackContracts <= 0) {
                return 0;
            }
            if (maxAllowed <= 0) {
                return 0;
            }

            if (riskState.emergencyDelever || riskState.finishLineShield || riskState.garchDecileHalving) {
                maxAllowed = Math.min(maxAllowed, 1);
            }
            if (profit >= 1150.00) return 1;
            if (cushion < 400.00) return 1;

            return Math.min(maxAllowed, 10);
        } catch (Exception e) {
            return 0;
        }
    }

    protected int resolveContracts(OrderContext ctx, DataContext dataCtx) {
        int fallback = getSettings().getInteger(BASE_CONTRACTS, 2);
        return resolveContracts(ctx, fallback);
    }

    private void logExecutionToCsv(
            String eventType,
            String action,
            int qty,
            double theoPrice,
            double actualFill,
            double slippagePts,
            double sl,
            double tp,
            String ref) {
        try {
            File stateFile = resolveCanonicalStateFile();
            File dir = (stateFile != null && stateFile.getParentFile() != null)
                ? stateFile.getParentFile()
                : new File(System.getProperty("user.home", "."), "MotiveWave Extensions");
            if (!dir.exists()) dir.mkdirs();
            File logFile = new File(dir, "lucid_execution_log.csv");
            boolean writeHeader = !logFile.exists();
            try (PrintWriter pw = new PrintWriter(new FileWriter(logFile, true))) {
                if (writeHeader) {
                    pw.println("timestamp_et,strategy,tier,event,action,contracts,theo_entry_price,actual_fill_price,slippage_pts,stop_price,target_price,order_ref");
                }
                String nowEt = ZonedDateTime.now(NY_ZONE).format(TS_FMT);
                String fillStr = Double.isNaN(actualFill) ? "NA" : String.format("%.2f", actualFill);
                pw.printf("%s,ASIAN_EVENING_REV_S4,%s,%s,%s,%d,%.2f,%s,%.4f,%.2f,%.2f,%s%n",
                    nowEt, STRATEGY_TIER, eventType, action, qty, theoPrice, fillStr, slippagePts, sl, tp, ref);
            }
        } catch (Exception ignored) {}
    }
}
