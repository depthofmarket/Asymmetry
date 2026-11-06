package com.motivewave.platform.study.custom;

import com.motivewave.platform.sdk.common.Coordinate;
import com.motivewave.platform.sdk.common.DataContext;
import com.motivewave.platform.sdk.common.DataSeries;
import com.motivewave.platform.sdk.common.Defaults;
import com.motivewave.platform.sdk.common.Enums$MarkerType;
import com.motivewave.platform.sdk.common.Enums$OrderAction;
import com.motivewave.platform.sdk.common.Enums$Position;
import com.motivewave.platform.sdk.common.Enums$Size;
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
    showTradeOptions = true,
    supportsTradeLots = true,
    supportsPosition = true
)
public class LucidMacroMomentumStudy extends Study {

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
        double stopPrice;
        double targetPrice;
        long entryTime;
        long maxExitTime;
        int contracts;
        String microSym;
        double ptVal;
        boolean closed = false;
        boolean orderSubmitted = false;
        Line slLine;
        Line tpLine;
        Line entryLine;
        String flattenLabel = "09:25 CASH FLATTEN";
    }

    private static class DaemonRiskState {
        int recommendedMicros = 2;
        double trailingCushion = 1000.0;
        double currentDatePnl = 0.0;
        boolean circuitBreakerHit = false;
        boolean emergencyDelever = false;
        boolean finishLineShield = false;
        boolean garchDecileHalving = false;
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

    public static int resolveContracts(OrderContext ctx, int fallbackContracts) {
        if (ctx == null) return fallbackContracts;
        try {
            double cash = ctx.getCashBalance();
            double real = ctx.getRealizedPnL();
            double unreal = ctx.getUnrealizedPnL();
            double balance = cash + real + unreal;
            if (balance > 15000.0) {
                double profit = balance - 25000.00;
                double hwm = Math.max(25000.00, balance);
                double floor = Math.max(24000.00, hwm - 1000.00);
                if (hwm >= 26100.00) {
                    floor = 25100.00;
                }
                double cushion = balance - floor;

                if (profit >= 1150.00) return 1;
                if (cushion < 400.00) return 1;
                if (profit >= 550.00) return 4;
                if (profit >= 200.00) return 3;
                return 2;
            }
        } catch (Exception ignored) {
        }
        return fallbackContracts;
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

        group.addRow(new BooleanDescriptor(ENABLE_LIVE_AUTOTRADE, "Enable Live Auto-Trading (CQG Execution)", false));
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
        group.addRow(new BooleanDescriptor(ENABLE_10AM_WINDOW, "Enable 10:00 AM Macro Catalyst Window (ISM/JOLTS)", true));

        setSettingsDescriptor(sd);

        RuntimeDescriptor rd = createRD();
        rd.declareSignal(SIGNAL_BUY, "Macro Momentum Buy (08:35 ET)");
        rd.declareSignal(SIGNAL_SELL, "Macro Momentum Sell (08:35 ET)");
        rd.declareSignal(SIGNAL_BUY_10AM, "10:00 AM Macro Momentum Buy (10:05 ET)");
        rd.declareSignal(SIGNAL_SELL_10AM, "10:00 AM Macro Momentum Sell (10:05 ET)");
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
                        int contracts = riskState.recommendedMicros;
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

        // 4. Evaluate 10:00 AM Catalyst Signal on the first bar at or after 10:05:00 ET sharp
        if (getSettings().getBoolean(ENABLE_10AM_WINDOW, true) && hour == 10 && min >= 5 && !processed10amDays.contains(today)) {
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
                        int contracts = riskState.recommendedMicros;
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
                            outcomeText = String.format("CASH FLATTEN (%s): %.2f (%+.2f pts | %+$%.2f)",
                                activeTrade.flattenLabel, exitPrice, pts, netDollars);
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
                            outcomeText = String.format("CASH FLATTEN (%s): %.2f (%+.2f pts | %+$%.2f)",
                                activeTrade.flattenLabel, exitPrice, pts, netDollars);
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
        // Armed on strategy activation
    }

    @Override
    public void onSignal(OrderContext ctx, Object signal) {
        if (ctx == null) return;
        if (!getSettings().getBoolean(ENABLE_LIVE_AUTOTRADE, false)) return;
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
        if (!getSettings().getBoolean(ENABLE_LIVE_AUTOTRADE, false)) return;

        long now = ctx.getCurrentTime();
        LocalDate today = Instant.ofEpochMilli(now).atZone(NY_ZONE).toLocalDate();
        List<ActiveTrade> dayTrades = tradesByDate.get(today);
        if (dayTrades == null) return;

        // 1. If flat, check if an unsubmitted trade signal exists for today
        if (ctx.getPosition() == 0) {
            for (ActiveTrade trade : dayTrades) {
                if (!trade.orderSubmitted && !trade.closed && now >= trade.entryTime) {
                    executeAutoTradeIfArmed(ctx, trade.isLong ? SIGNAL_BUY : SIGNAL_SELL, trade);
                    break;
                }
            }
        }

        // 2. Automated Hard Pre-Cash Flatten at maxExitTime (09:25 or 10:35 ET)
        if (ctx.getPosition() != 0) {
            for (ActiveTrade trade : dayTrades) {
                if (trade.orderSubmitted && !trade.closed && now >= trade.maxExitTime) {
                    ctx.cancelOrders();
                    ctx.closeAtMarket();
                    trade.closed = true;
                }
            }
        }
    }

    private synchronized void executeAutoTradeIfArmed(OrderContext ctx, Object signal, ActiveTrade trade) {
        if (ctx.getPosition() != 0) return; // Prevent double-entry / pyramiding

        // Gateway-level circuit breaker check
        DaemonRiskState riskState = loadDaemonRiskState();
        if (riskState.circuitBreakerHit) return;

        if (trade == null || trade.orderSubmitted || trade.closed) return;

        int contracts = resolveContracts(ctx, trade.contracts);
        if (contracts <= 0) contracts = 1;

        float stopPrice = ctx.getInstrument().round((float) trade.stopPrice);
        float targetPrice = ctx.getInstrument().round((float) trade.targetPrice);

        boolean isLong = trade.isLong;
        if (signal != null) {
            String sigStr = signal.toString();
            if (sigStr.contains("BUY") || SIGNAL_BUY.equals(sigStr) || SIGNAL_BUY_10AM.equals(sigStr)) isLong = true;
            else if (sigStr.contains("SELL") || SIGNAL_SELL.equals(sigStr) || SIGNAL_SELL_10AM.equals(sigStr)) isLong = false;
        }

        if (isLong) {
            Order entry = ctx.createMarketOrder(Enums$OrderAction.BUY, contracts);
            Order sl = ctx.createStopOrder(Enums$OrderAction.SELL, Enums$TIF.GTC, contracts, stopPrice);
            Order tp = ctx.createLimitOrder(Enums$OrderAction.SELL, Enums$TIF.GTC, contracts, targetPrice);
            ctx.submitOrders(entry, sl, tp);
            trade.orderSubmitted = true;
        } else {
            Order entry = ctx.createMarketOrder(Enums$OrderAction.SELL, contracts);
            Order sl = ctx.createStopOrder(Enums$OrderAction.BUY, Enums$TIF.GTC, contracts, stopPrice);
            Order tp = ctx.createLimitOrder(Enums$OrderAction.BUY, Enums$TIF.GTC, contracts, targetPrice);
            ctx.submitOrders(entry, sl, tp);
            trade.orderSubmitted = true;
        }
    }

    @Override
    public void onPositionClosed(OrderContext ctx) {
        if (ctx != null) {
            ctx.cancelOrders();
        }
    }

    @Override
    public void onOrderFilled(OrderContext ctx, Order order) {
        if (ctx != null && ctx.getPosition() == 0) {
            ctx.cancelOrders();
        }
    }

    @Override
    public void onDeactivate(OrderContext ctx) {
        if (ctx != null) {
            ctx.cancelOrders();
        }
    }
}
