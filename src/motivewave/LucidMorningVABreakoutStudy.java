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
    id = "VA_BREAKOUT_ALGO_V2",
    name = "VA Breakout Algo (v2.0)",
    desc = "09:45 ET Breakout outside Prior Day Value Area with $250 Volatility Risk Budgeting, 1.5x R:R Target, and 10:00 AM News Guard",
    menu = "Custom",
    overlay = true,
    signals = true
)
public class LucidMorningVABreakoutStudy extends Study {

    private static final Font LINE_FONT = new Font("SansSerif", Font.BOLD, 10);

    // Settings Keys
    private static final String MIN_RETURN_PCT = "minReturnPct";
    private static final String MIN_LONG_CLOSE_LOC = "minLongCloseLoc";
    private static final String MAX_SHORT_CLOSE_LOC = "maxShortCloseLoc";
    private static final String REWARD_RISK_RATIO = "rewardRiskRatio";
    private static final String RISK_BUDGET_DOLLARS = "riskBudgetDollars";
    private static final String ENABLE_10AM_NEWS_GUARD = "enable10amNewsGuard";
    private static final String ENABLE_SOUND_ALERT = "enableSoundAlert";
    private static final String SHOW_LEVEL_LINES = "showLevelLines";
    private static final String SHOW_NO_SETUP_MARKER = "showNoSetupMarker";

    private static final ZoneId NY_ZONE = ZoneId.of("America/New_York");

    // Signal Keys
    private static final String SIGNAL_BUY = "LUCID_BUY_BREAKOUT";
    private static final String SIGNAL_SELL = "LUCID_SELL_BREAKOUT";

    // Session State Tracking
    private final Map<LocalDate, SessionProfile> profilesByDate = new HashMap<>();
    private final Map<LocalDate, OpeningRange15> orByDate = new HashMap<>();
    private final Set<LocalDate> processedDays = new HashSet<>();

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
        boolean complete = false;
    }

    @Override
    public void initialize(Defaults defaults) {
        SettingsDescriptor sd = createSD();
        SettingTab tab = sd.addTab("VA Breakout Algo (v2.0)");
        SettingGroup group = tab.addGroup("Breakout & Risk Management");

        group.addRow(new DoubleDescriptor(MIN_RETURN_PCT, "Min 15m Return (0.10% = 0.0010)", 0.0010, 0.0001, 0.0050, 0.0001));
        group.addRow(new DoubleDescriptor(MIN_LONG_CLOSE_LOC, "Min Long Close Location (0.65)", 0.65, 0.50, 0.95, 0.05));
        group.addRow(new DoubleDescriptor(MAX_SHORT_CLOSE_LOC, "Max Short Close Location (0.35)", 0.35, 0.05, 0.50, 0.05));
        group.addRow(new DoubleDescriptor(REWARD_RISK_RATIO, "Target Reward / Risk Ratio (1.50x)", 1.5, 0.5, 3.0, 0.1));
        group.addRow(new DoubleDescriptor(RISK_BUDGET_DOLLARS, "Risk Budget / Trade ($250 for Lucid 25K)", 250.0, 50.0, 500.0, 10.0));
        group.addRow(new BooleanDescriptor(ENABLE_10AM_NEWS_GUARD, "Show 10:00 AM News Guard Warning", true));
        group.addRow(new BooleanDescriptor(ENABLE_SOUND_ALERT, "Enable Sound Alert & Notification", true));
        group.addRow(new BooleanDescriptor(SHOW_LEVEL_LINES, "Show SL / TP / 10:15 Exit Lines", true));
        group.addRow(new BooleanDescriptor(SHOW_NO_SETUP_MARKER, "Show 'No Setup' Marker at 09:45", true));

        setSettingsDescriptor(sd);

        RuntimeDescriptor rd = createRD();
        rd.declareSignal(SIGNAL_BUY, "VA Breakout Buy (v2.0)");
        rd.declareSignal(SIGNAL_SELL, "VA Breakout Sell (v2.0)");
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

        // 2. Track 09:30 - 09:44 Opening Range (compatible with 1m, 3m, 5m, 15m)
        if (hour == 9 && min == 30) {
            OpeningRange15 or = orByDate.computeIfAbsent(today, d -> new OpeningRange15());
            or.open930 = open;
            or.high15 = high;
            or.low15 = low;
            or.close944 = close;
            or.complete = true;
        } else if (hour == 9 && min > 30 && min < 45) {
            OpeningRange15 or = orByDate.computeIfAbsent(today, d -> new OpeningRange15());
            if (Double.isNaN(or.open930)) {
                or.open930 = open;
            }
            or.high15 = Double.isInfinite(or.high15) ? high : Math.max(or.high15, high);
            or.low15 = Double.isInfinite(or.low15) ? low : Math.min(or.low15, low);
            or.close944 = close; // tracks the latest close leading up to 09:45
            or.complete = true;
        }

        // 3. Evaluate Signal on the first bar at or after 09:45:00 ET sharp
        if (hour == 9 && min >= 45 && !processedDays.contains(today)) {
            OpeningRange15 or = orByDate.get(today);
            if (or == null || !or.complete || Double.isNaN(or.open930)) return;

            // Fire exactly once per session
            processedDays.add(today);

            // Retrieve the most recent completed prior day's RTH profile
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
                    info("NO TRADE: Prior Day Profile Not Found (Load >= 2 days of chart history)");
                }
                return;
            }

            double priorVah = priorProf.vah;
            double priorVal = priorProf.val;

            double orRange = or.high15 - or.low15;
            if (orRange <= 0.0) return;

            double retPct = (or.close944 - or.open930) / or.open930;
            double closeLoc = (or.close944 - or.low15) / orRange;

            double minRet = getSettings().getDouble(MIN_RETURN_PCT, 0.0010);
            double minLongLoc = getSettings().getDouble(MIN_LONG_CLOSE_LOC, 0.65);
            double maxShortLoc = getSettings().getDouble(MAX_SHORT_CLOSE_LOC, 0.35);
            double rrRatio = getSettings().getDouble(REWARD_RISK_RATIO, 1.5);
            double riskBudget = getSettings().getDouble(RISK_BUDGET_DOLLARS, 250.0);
            boolean newsGuard = getSettings().getBoolean(ENABLE_10AM_NEWS_GUARD, true);
            boolean soundAlert = getSettings().getBoolean(ENABLE_SOUND_ALERT, true);
            boolean showLines = getSettings().getBoolean(SHOW_LEVEL_LINES, true);

            // Instrument recognition (NQ vs ES)
            String sym = (series.getInstrument() != null) ? series.getInstrument().getSymbol().toUpperCase() : "NQ";
            boolean isES = sym.contains("ES") || sym.contains("MES");
            double minStop = 15.0;
            double maxStop = isES ? 35.0 : 60.0;
            double ptVal = isES ? 5.00 : 2.00;
            String microSym = isES ? "MES" : "MNQ";

            // Full Opening Range Invalidation Stop (clamped between limits)
            double stopPts = Math.min(maxStop, Math.max(minStop, orRange));

            // Dynamic Volatility Risk Budgeting: $250 Dollar Risk / (Stop_Pts * Point_Val)
            int contracts = (int) Math.round(riskBudget / (stopPts * ptVal));
            contracts = Math.max(1, Math.min(4, contracts)); // Clamped 1 to 4 Micros

            // Core Breakout Acceptance Rules
            boolean isLong = (retPct >= minRet) && (closeLoc >= minLongLoc) && (or.close944 > priorVah);
            boolean isShort = (retPct <= -minRet) && (closeLoc <= maxShortLoc) && (or.close944 < priorVal);

            if (isLong || isShort) {
                // Exact execution happens on the open of the 09:45 bar
                double entryPrice = open;
                double stopPrice = isLong ? (entryPrice - stopPts) : (entryPrice + stopPts);
                double targetPts = stopPts * rrRatio;
                double targetPrice = isLong ? (entryPrice + targetPts) : (entryPrice - targetPts);
                double actualRiskDollars = stopPts * ptVal * contracts;
                double actualRewardDollars = targetPts * ptVal * contracts;

                long entryTime = barStartTime;                 // 09:45:00 ET
                long newsTime = entryTime + (15 * 60 * 1000L); // 10:00:00 ET
                long exitTime = entryTime + (30 * 60 * 1000L); // 10:15:00 ET

                if (isLong) {
                    Coordinate coord = new Coordinate(entryTime, low - (stopPts * 0.15));
                    MarkerInfo info = new MarkerInfo(Enums$MarkerType.ARROW, Enums$Size.LARGE, Color.GREEN, Color.GREEN, true);
                    Marker marker = new Marker(coord, Enums$Position.BOTTOM, info);
                    marker.setTextValue(String.format("BUY %dx %s @ %.2f | SL: %.2f (-$%.0f) | TP: %.2f (+$%.0f, 1.5R) | NEWS EXIT: 09:59 | MAX: 10:15",
                        contracts, microSym, entryPrice, stopPrice, actualRiskDollars, targetPrice, actualRewardDollars));
                    addFigure(marker);

                    if (showLines) {
                        Line slLine = new Line(entryTime, stopPrice, exitTime, stopPrice);
                        slLine.setColor(Color.RED);
                        slLine.setText(String.format("STOP LOSS: %.2f (-$%.0f)", stopPrice, actualRiskDollars), LINE_FONT);
                        addFigure(slLine);

                        Line tpLine = new Line(entryTime, targetPrice, exitTime, targetPrice);
                        tpLine.setColor(Color.GREEN);
                        tpLine.setText(String.format("PROFIT TARGET 1.5R: %.2f (+$%.0f)", targetPrice, actualRewardDollars), LINE_FONT);
                        addFigure(tpLine);

                        if (newsGuard) {
                            Line newsLine = new Line(newsTime, stopPrice, newsTime, targetPrice);
                            newsLine.setColor(Color.ORANGE);
                            newsLine.setText("10:00 AM NEWS GUARD: Flatten @ 09:59 if Red-Folder Data", LINE_FONT);
                            addFigure(newsLine);
                        }

                        Line exitLine = new Line(exitTime, stopPrice, exitTime, targetPrice);
                        exitLine.setColor(Color.CYAN);
                        exitLine.setText("10:15 MAX TIME EXIT", LINE_FONT);
                        addFigure(exitLine);
                    }

                    ctx.signal(index, SIGNAL_BUY, String.format("VA BREAKOUT BUY %dx %s @ %.2f (SL: %.2f, TP: %.2f)", contracts, microSym, entryPrice, stopPrice, targetPrice), entryPrice);
                } else {
                    Coordinate coord = new Coordinate(entryTime, high + (stopPts * 0.15));
                    MarkerInfo info = new MarkerInfo(Enums$MarkerType.ARROW, Enums$Size.LARGE, Color.RED, Color.RED, true);
                    Marker marker = new Marker(coord, Enums$Position.TOP, info);
                    marker.setTextValue(String.format("SELL %dx %s @ %.2f | SL: %.2f (-$%.0f) | TP: %.2f (+$%.0f, 1.5R) | NEWS EXIT: 09:59 | MAX: 10:15",
                        contracts, microSym, entryPrice, stopPrice, actualRiskDollars, targetPrice, actualRewardDollars));
                    addFigure(marker);

                    if (showLines) {
                        Line slLine = new Line(entryTime, stopPrice, exitTime, stopPrice);
                        slLine.setColor(Color.RED);
                        slLine.setText(String.format("STOP LOSS: %.2f (-$%.0f)", stopPrice, actualRiskDollars), LINE_FONT);
                        addFigure(slLine);

                        Line tpLine = new Line(entryTime, targetPrice, exitTime, targetPrice);
                        tpLine.setColor(Color.GREEN);
                        tpLine.setText(String.format("PROFIT TARGET 1.5R: %.2f (+$%.0f)", targetPrice, actualRewardDollars), LINE_FONT);
                        addFigure(tpLine);

                        if (newsGuard) {
                            Line newsLine = new Line(newsTime, stopPrice, newsTime, targetPrice);
                            newsLine.setColor(Color.ORANGE);
                            newsLine.setText("10:00 AM NEWS GUARD: Flatten @ 09:59 if Red-Folder Data", LINE_FONT);
                            addFigure(newsLine);
                        }

                        Line exitLine = new Line(exitTime, targetPrice, exitTime, stopPrice);
                        exitLine.setColor(Color.CYAN);
                        exitLine.setText("10:15 MAX TIME EXIT", LINE_FONT);
                        addFigure(exitLine);
                    }

                    ctx.signal(index, SIGNAL_SELL, String.format("VA BREAKOUT SELL %dx %s @ %.2f (SL: %.2f, TP: %.2f)", contracts, microSym, entryPrice, stopPrice, targetPrice), entryPrice);
                }

                if (soundAlert) {
                    Toolkit.getDefaultToolkit().beep();
                }
            } else if (getSettings().getBoolean(SHOW_NO_SETUP_MARKER, true)) {
                StringBuilder reason = new StringBuilder("NO TRADE: ");
                if (or.close944 <= priorVah && or.close944 >= priorVal) {
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
                info(reason.toString());
            }
        }
    }
}
