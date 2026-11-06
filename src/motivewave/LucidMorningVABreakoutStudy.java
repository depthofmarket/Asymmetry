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
import java.time.Instant;
import java.time.LocalDate;
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

    private static class ActiveTrade {
        LocalDate date;
        boolean isLong;
        double entryPrice;
        double stopPrice;
        double targetPrice;
        long entryTime;
        long maxExitTime;
        int contracts;
        String microSym;
        double ptVal;
        boolean closed = false;
        boolean orderSubmitted = false;
        boolean entryFilled = false;
        boolean bracketsSubmitted = false;
        String entryOrderId;
        String slOrderId;
        String tpOrderId;
        Line slLine;
        Line tpLine;
        Line entryLine;
    }

    private static class DaemonRiskState {
        int recommendedMicros = 2;
        double trailingCushion = 1000.0;
        double currentDatePnl = 0.0;
        boolean circuitBreakerHit = false;
        boolean emergencyDelever = false;
        boolean finishLineShield = false;
        boolean garchDecileHalving = false;
        double peakBalance = 25000.0;
        double trailingFloor = 24000.0;
    }

    private static DaemonRiskState loadDaemonRiskState() {
        DaemonRiskState state = new DaemonRiskState();
        File f = new File(System.getProperty("user.home"), "trading_strategy/nq-scalper-backtest/results/forward_test/demo_parity_state.json");
        if (!f.exists() || !f.canRead()) {
            return state;
        }
        try {
            String content = new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8);
            Matcher mMicros = Pattern.compile("\"recommended_micros\"\\s*:\\s*(\\d+)").matcher(content);
            if (mMicros.find()) {
                state.recommendedMicros = Integer.parseInt(mMicros.group(1));
            }
            Matcher mCushion = Pattern.compile("\"trailing_cushion\"\\s*:\\s*([-+]?[0-9]*\\.?[0-9]+)").matcher(content);
            if (mCushion.find()) {
                state.trailingCushion = Double.parseDouble(mCushion.group(1));
            }
            Matcher mPnl = Pattern.compile("\"current_date_pnl\"\\s*:\\s*([-+]?[0-9]*\\.?[0-9]+)").matcher(content);
            if (mPnl.find()) {
                state.currentDatePnl = Double.parseDouble(mPnl.group(1));
            }
            Matcher mShield = Pattern.compile("\"finish_line_shield\"\\s*:\\s*(true|false)").matcher(content);
            if (mShield.find()) {
                state.finishLineShield = Boolean.parseBoolean(mShield.group(1));
            }
            Matcher mGarch = Pattern.compile("\"garch_decile_halving\"\\s*:\\s*(true|false)").matcher(content);
            if (mGarch.find()) {
                state.garchDecileHalving = Boolean.parseBoolean(mGarch.group(1));
            }
            Matcher mDelever = Pattern.compile("\"defensive_delever\"\\s*:\\s*(true|false)").matcher(content);
            if (mDelever.find()) {
                state.emergencyDelever = Boolean.parseBoolean(mDelever.group(1));
            }
            Matcher mPeak = Pattern.compile("\"peak_balance\"\\s*:\\s*([-+]?[0-9]*\\.?[0-9]+)").matcher(content);
            if (mPeak.find()) {
                state.peakBalance = Double.parseDouble(mPeak.group(1));
            }
            Matcher mFloor = Pattern.compile("\"trailing_floor\"\\s*:\\s*([-+]?[0-9]*\\.?[0-9]+)").matcher(content);
            if (mFloor.find()) {
                state.trailingFloor = Double.parseDouble(mFloor.group(1));
            }
            if (state.currentDatePnl <= -600.0) {
                state.circuitBreakerHit = true;
            }
            if (state.trailingCushion < 400.0 || state.emergencyDelever || state.finishLineShield || state.garchDecileHalving) {
                state.recommendedMicros = 1;
            }
        } catch (Exception ignored) {
        }
        return state;
    }

    private static double persistedPeakBalance = 25000.00;
    private static double persistedTrailingFloor = 24000.00;

    public static double getPersistedPeakBalance() {
        return persistedPeakBalance;
    }

    public static double getPersistedTrailingFloor() {
        return persistedTrailingFloor;
    }

    public static void setPersistedRiskState(double peak, double floor) {
        persistedPeakBalance = peak;
        persistedTrailingFloor = floor;
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
            persistedPeakBalance = Math.max(persistedPeakBalance, Math.max(riskState.peakBalance, balance));

            double floor = Math.max(24000.00, persistedPeakBalance - 1000.00);
            if (persistedPeakBalance >= 26100.00 || riskState.trailingFloor >= 25100.00) {
                floor = 25100.00;
            }
            persistedTrailingFloor = Math.max(persistedTrailingFloor, Math.max(riskState.trailingFloor, floor));

            double profit = balance - 25000.00;
            double cushion = balance - persistedTrailingFloor;

            if (profit >= 1150.00) return 1;
            if (cushion < 400.00) return 1;
            if (profit >= 550.00) return 4;
            if (profit >= 200.00) return 3;
            return 2;
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
                    int tierMicros = riskState.recommendedMicros;
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
        if (!getSettings().getBoolean(ENABLE_LIVE_AUTOTRADE, true)) return;

        // 1. If flat, check if an unsubmitted trade signal exists for today
        if (ctx.getPosition() == 0) {
            long now = ctx.getCurrentTime();
            LocalDate today = Instant.ofEpochMilli(now).atZone(NY_ZONE).toLocalDate();
            ActiveTrade trade = tradesByDate.get(today);
            if (trade != null && !trade.orderSubmitted && !trade.closed && now >= trade.entryTime && now < trade.maxExitTime) {
                executeAutoTradeIfArmed(ctx, trade.isLong ? SIGNAL_BUY : SIGNAL_SELL);
            }
        }

        // 2. Automated Time-Based Flattens if currently in a live position
        if (ctx.getPosition() != 0) {
            long barTime = ctx.getCurrentTime();
            ZonedDateTime zdt = Instant.ofEpochMilli(barTime).atZone(NY_ZONE);
            int hour = zdt.getHour();
            int min = zdt.getMinute();
            LocalDate today = zdt.toLocalDate();
            boolean newsGuard = getSettings().getBoolean(ENABLE_10AM_NEWS_GUARD, true);
            boolean isNews = is10amNewsDay(today);

            // 10:15 ET Hard Max Time Exit
            if (hour > 10 || (hour == 10 && min >= 15)) {
                ctx.cancelOrders();
                ctx.closeAtMarket();
                logExecutionEvent("TIME_EXIT_FLATTEN", "LucidMorningVABreakout", ctx.getInstrument().getSymbol(),
                    "FLAT", 0.0, 0.0, 0.0, 0, "10:15 ET session boundary reached, position flattened.");
            }
            // 09:59 ET News Guard Flatten if Red-Folder Day
            else if (newsGuard && isNews && hour == 9 && min >= 59) {
                ctx.cancelOrders();
                ctx.closeAtMarket();
                logExecutionEvent("NEWS_GUARD_FLATTEN", "LucidMorningVABreakout", ctx.getInstrument().getSymbol(),
                    "FLAT", 0.0, 0.0, 0.0, 0, "09:59 ET Tier-1 Red Folder News Guard triggered, position flattened.");
            }
        }
    }

    private synchronized void executeAutoTradeIfArmed(OrderContext ctx, Object signal) {
        if (ctx.getPosition() != 0) return; // Prevent double-entry / pyramiding

        // Gateway-level circuit breaker check
        DaemonRiskState riskState = loadDaemonRiskState();
        if (riskState.circuitBreakerHit) {
            logExecutionEvent("CIRCUIT_BREAKER_BLOCKED", "LucidMorningVABreakout", ctx.getInstrument().getSymbol(),
                "BLOCKED", 0.0, 0.0, 0.0, 0, "Daily soft-stop -$600 reached in demo parity state");
            return;
        }

        long now = ctx.getCurrentTime();
        LocalDate today = Instant.ofEpochMilli(now).atZone(NY_ZONE).toLocalDate();
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

        Enums$OrderAction entryAction = isLong ? Enums$OrderAction.BUY : Enums$OrderAction.SELL;
        Order entry = ctx.createMarketOrder(entryAction, contracts);
        ctx.submitOrders(entry);
        trade.orderSubmitted = true;
        trade.entryOrderId = entry != null ? entry.getOrderId() : null;

        logExecutionEvent("ORDER_SUBMITTED", "LucidMorningVABreakout", ctx.getInstrument().getSymbol(),
            entryAction.toString(), trade.entryPrice, stopPrice, targetPrice, contracts,
            "Market entry submitted. Brackets pending fill confirmation.");
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

        // Case A: Entry order filled -> Submit linked Stop Loss & Profit Target brackets to CQG
        if (ctx.getPosition() != 0 && trade != null && !trade.bracketsSubmitted) {
            trade.entryFilled = true;
            int contracts = Math.abs(ctx.getPosition());
            float stopPrice = ctx.getInstrument().round((float) trade.stopPrice);
            float targetPrice = ctx.getInstrument().round((float) trade.targetPrice);
            Enums$OrderAction exitAction = trade.isLong ? Enums$OrderAction.SELL : Enums$OrderAction.BUY;

            Order sl = ctx.createStopOrder(exitAction, Enums$TIF.GTC, contracts, stopPrice);
            Order tp = ctx.createLimitOrder(exitAction, Enums$TIF.GTC, contracts, targetPrice);
            ctx.submitOrders(sl, tp);
            trade.bracketsSubmitted = true;
            trade.slOrderId = sl != null ? sl.getOrderId() : null;
            trade.tpOrderId = tp != null ? tp.getOrderId() : null;

            logExecutionEvent("BRACKETS_SUBMITTED", "LucidMorningVABreakout", ctx.getInstrument().getSymbol(),
                exitAction.toString(), 0.0, stopPrice, targetPrice, contracts,
                "Attached Stop (" + stopPrice + ") and Target (" + targetPrice + ") submitted to broker.");
        }
        // Case B: Stop Loss or Profit Target filled -> Position flattened
        else if (ctx.getPosition() == 0) {
            ctx.cancelOrders();
            if (trade != null) trade.closed = true;
            logExecutionEvent("POSITION_FLAT", "LucidMorningVABreakout", ctx.getInstrument().getSymbol(),
                "FLAT", 0.0, 0.0, 0.0, 0, "Position closed, unfulfilled bracket orders cancelled.");
        }
    }

    @Override
    public void onOrderRejected(OrderContext ctx, Order order) {
        if (order == null) return;
        logExecutionEvent("ORDER_REJECTED", "LucidMorningVABreakout",
            ctx != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
            order.getAction().toString(), 0.0, 0.0, 0.0, order.getQuantity(),
            "Order REJECTED by broker: id=" + order.getOrderId() + " type=" + order.getType());
    }

    @Override
    public void onOrderCancelled(OrderContext ctx, Order order) {
        if (order == null) return;
        logExecutionEvent("ORDER_CANCELLED", "LucidMorningVABreakout",
            ctx != null ? ctx.getInstrument().getSymbol() : "UNKNOWN",
            order.getAction().toString(), 0.0, 0.0, 0.0, order.getQuantity(),
            "Order cancelled: id=" + order.getOrderId());
    }

    @Override
    public void onPositionClosed(OrderContext ctx) {
        if (ctx != null) {
            ctx.cancelOrders();
        }
    }

    @Override
    public void onDeactivate(OrderContext ctx) {
        setState(Enums$StrategyState.INACTIVE);
        if (ctx != null) {
            ctx.cancelOrders();
        }
        logExecutionEvent("STRATEGY_DEACTIVATED", "LucidMorningVABreakout",
            ctx != null ? ctx.getInstrument().getSymbol() : "MNQ",
            "INACTIVE", 0.0, 0.0, 0.0, 0, "Strategy deactivated by user");
    }

    private static synchronized void logExecutionEvent(String event, String studyId, String symbol,
        String action, double price, double sl, double tp, int contracts, String reason) {
        try {
            String home = System.getProperty("user.home");
            File dir = new File(home, "trading_strategy/nq-scalper-backtest/results/forward_test");
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
