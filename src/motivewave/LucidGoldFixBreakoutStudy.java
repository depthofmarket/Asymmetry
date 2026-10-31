package com.motivewave.platform.study.custom;

import com.motivewave.platform.sdk.common.Coordinate;
import com.motivewave.platform.sdk.common.DataContext;
import com.motivewave.platform.sdk.common.DataSeries;
import com.motivewave.platform.sdk.common.Defaults;
import com.motivewave.platform.sdk.common.Enums$MarkerType;
import com.motivewave.platform.sdk.common.Enums$Position;
import com.motivewave.platform.sdk.common.Enums$Size;
import com.motivewave.platform.sdk.common.MarkerInfo;
import com.motivewave.platform.sdk.common.desc.BooleanDescriptor;
import com.motivewave.platform.sdk.common.desc.DoubleDescriptor;
import com.motivewave.platform.sdk.common.desc.IntegerDescriptor;
import com.motivewave.platform.sdk.common.desc.SettingGroup;
import com.motivewave.platform.sdk.common.desc.SettingTab;
import com.motivewave.platform.sdk.common.desc.SettingsDescriptor;
import com.motivewave.platform.sdk.draw.Line;
import com.motivewave.platform.sdk.draw.Marker;
import com.motivewave.platform.sdk.study.RuntimeDescriptor;
import com.motivewave.platform.sdk.study.Study;
import com.motivewave.platform.sdk.study.StudyHeader;

import java.awt.Color;
import java.awt.Font;
import java.awt.Toolkit;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

@StudyHeader(
    namespace = "com.motivewave.platform.study.custom",
    id = "GOLD_FIX_BREAKOUT_ALGO_V1",
    name = "Lucid 25K — 3. Gold London Fix (10:15 ET)",
    desc = "10:15 ET Post-LBMA PM Fix Breakout on Gold (MGC/GC) with 3-Way Barrier (Prior VAH, IB60 High, London High), $250 Risk Budget, 11:00 Exit, and Live Trade Tracker",
    menu = "Custom",
    overlay = true,
    signals = true
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
    private static final String SHOW_NO_SETUP_MARKER = "showNoSetupMarker";

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

    private static class ActiveTrade {
        LocalDate date;
        double entryPrice;
        double stopPrice;
        double targetPrice;
        long entryTime;
        long maxExitTime;
        int contracts;
        String microSym;
        double ptVal;
        boolean closed = false;
        Line slLine;
        Line tpLine;
        Line entryLine;
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
        group.addRow(new IntegerDescriptor(RATCHET_TIER_OVERRIDE, "Ratchet Sizing Override (0=Auto, 2/3/4 Micros)", 0, 0, 4, 1));
        group.addRow(new DoubleDescriptor(MIN_STOP_POINTS, "Min Stop Distance Points (Gold 3.0)", 3.0, 1.0, 10.0, 0.5));
        group.addRow(new DoubleDescriptor(MAX_STOP_POINTS, "Max Stop Distance Points (Gold 18.0)", 18.0, 10.0, 35.0, 1.0));
        group.addRow(new BooleanDescriptor(REQUIRE_OUTSIDE_PRIOR_VA, "Require Breakout Above Prior Day VAH", true));
        group.addRow(new BooleanDescriptor(REQUIRE_OUTSIDE_LONDON_RANGE, "Require Breakout Above London Session High", true));
        group.addRow(new BooleanDescriptor(REQUIRE_OUTSIDE_IB60, "Require Breakout Above COMEX IB60 High", true));
        group.addRow(new BooleanDescriptor(ENABLE_SOUND_ALERT, "Enable Sound Alert & Notification", true));
        group.addRow(new BooleanDescriptor(SHOW_LEVEL_LINES, "Show SL / TP / Entry / 11:00 Exit Lines", true));
        group.addRow(new BooleanDescriptor(SHOW_NO_SETUP_MARKER, "Show 'No Setup' Reason Marker at 10:15", true));

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

                    int contracts;
                    if (ratchetOverride >= 1 && ratchetOverride <= 4) {
                        contracts = ratchetOverride;
                    } else {
                        contracts = (int) Math.round(riskBudget / (stopPts * ptVal));
                        contracts = Math.max(1, Math.min(4, contracts));
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

                    Coordinate coord = new Coordinate(entryTime, low - (stopPts * 0.15));
                    MarkerInfo info = new MarkerInfo(Enums$MarkerType.ARROW, Enums$Size.LARGE, Color.GREEN, Color.GREEN, true);
                    Marker marker = new Marker(coord, Enums$Position.BOTTOM, info);
                    marker.setTextValue(String.format("GOLD FIX BUY %dx %s @ %.2f | SL: %.2f (-$%.0f) | TP: %.2f (+$%.0f, 1.5R) | MAX: 11:00",
                        contracts, microSym, entryPrice, stopPrice, actualRiskDollars, targetPrice, actualRewardDollars));
                    addFigure(marker);

                    if (showLines) {
                        Line slLine = new Line(entryTime, stopPrice, exitTime, stopPrice);
                        slLine.setColor(Color.RED);
                        slLine.setText(String.format("STOP LOSS: %.2f (-$%.0f)", stopPrice, actualRiskDollars), LINE_FONT);
                        addFigure(slLine);
                        trade.slLine = slLine;

                        Line tpLine = new Line(entryTime, targetPrice, exitTime, targetPrice);
                        tpLine.setColor(Color.GREEN);
                        tpLine.setText(String.format("PROFIT TARGET 1.5R: %.2f (+$%.0f)", targetPrice, actualRewardDollars), LINE_FONT);
                        addFigure(tpLine);
                        trade.tpLine = tpLine;

                        Line entryLine = new Line(entryTime, entryPrice, exitTime, entryPrice);
                        entryLine.setColor(Color.WHITE);
                        entryLine.setText(String.format("ENTRY: %.2f (%dx %s)", entryPrice, contracts, microSym), LINE_FONT);
                        addFigure(entryLine);
                        trade.entryLine = entryLine;

                        Line exitLine = new Line(exitTime, stopPrice, exitTime, targetPrice);
                        exitLine.setColor(Color.CYAN);
                        exitLine.setText("11:00 MAX TIME EXIT", LINE_FONT);
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
                outcomeText = String.format("TIME EXIT (11:00): %.2f (%+.2f pts | %+$%.2f)",
                    exitPrice, pts, netDollars);
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
                addFigure(marker);
            }
        }
    }
}
