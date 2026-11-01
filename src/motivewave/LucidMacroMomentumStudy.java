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
    id = "MACRO_MOMENTUM_ALGO_V1",
    name = "Lucid 25K — 2. Macro Momentum (08:35 ET)",
    desc = "08:35 ET Pre-Market Macro Release Momentum on NQ/MNQ (08:30 Spike vs 00:00-08:29 Overnight Range) with $250 Risk Budget, 09:25 Cash Flatten, and Live Trade Tracker",
    menu = "Custom",
    overlay = true,
    signals = true
)
public class LucidMacroMomentumStudy extends Study {

    private static final Font LINE_FONT = new Font("SansSerif", Font.BOLD, 10);

    // Settings Keys
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
    private static final String SHOW_NO_SETUP_MARKER = "showNoSetupMarker";
    private static final String ENABLE_HIGH_VOL_GATE = "enableHighVolGate";
    private static final String MAX_OVN_RANGE_GATE_PTS = "maxOvnRangeGatePts";

    private static final ZoneId NY_ZONE = ZoneId.of("America/New_York");

    // Signal Keys
    private static final String SIGNAL_BUY = "LUCID_MACRO_BUY";
    private static final String SIGNAL_SELL = "LUCID_MACRO_SELL";

    // Session State Tracking
    private final Map<LocalDate, OvernightStats> ovnByDate = new HashMap<>();
    private final Map<LocalDate, SpikeStats> spikeByDate = new HashMap<>();
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
        Line slLine;
        Line tpLine;
        Line entryLine;
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

        group.addRow(new DoubleDescriptor(MIN_VOLUME_MULT, "Min Volume Multiplier (vs Pre-5m Avg)", 2.50, 1.0, 10.0, 0.25));
        group.addRow(new DoubleDescriptor(MIN_LONG_CLOSE_LOC, "Min Long Close Location (0.65)", 0.65, 0.50, 0.95, 0.05));
        group.addRow(new DoubleDescriptor(MAX_SHORT_CLOSE_LOC, "Max Short Close Location (0.35)", 0.35, 0.05, 0.50, 0.05));
        group.addRow(new DoubleDescriptor(REWARD_RISK_RATIO, "Target Reward / Risk Ratio (1.50x)", 1.5, 0.5, 3.0, 0.1));
        group.addRow(new DoubleDescriptor(RISK_BUDGET_DOLLARS, "Risk Budget / Trade ($250 for Lucid 25K)", 250.0, 50.0, 500.0, 10.0));
        group.addRow(new IntegerDescriptor(RATCHET_TIER_OVERRIDE, "Ratchet Sizing Override (0=Auto, 2/3/4 Micros)", 0, 0, 4, 1));
        group.addRow(new DoubleDescriptor(MIN_STOP_POINTS, "Min Stop Distance Points (NQ 20.0)", 20.0, 5.0, 50.0, 1.0));
        group.addRow(new DoubleDescriptor(MAX_STOP_POINTS, "Max Stop Distance Points (NQ 50.0)", 50.0, 20.0, 100.0, 1.0));
        group.addRow(new BooleanDescriptor(ALLOW_LONG, "Allow Macro Longs", true));
        group.addRow(new BooleanDescriptor(ALLOW_SHORT, "Allow Macro Shorts", true));
        group.addRow(new BooleanDescriptor(ENABLE_SOUND_ALERT, "Enable Sound Alert & Notification", true));
        group.addRow(new BooleanDescriptor(SHOW_LEVEL_LINES, "Show SL / TP / Entry / 09:25 Exit Lines", true));
        group.addRow(new BooleanDescriptor(SHOW_NO_SETUP_MARKER, "Show 'No Setup' Reason Marker at 08:35", true));
        group.addRow(new BooleanDescriptor(ENABLE_HIGH_VOL_GATE, "Enable High-Vol Regime Whipsaw Gate (H19 Option 1 Hard Gate)", false));
        group.addRow(new DoubleDescriptor(MAX_OVN_RANGE_GATE_PTS, "Max Overnight Range Cutoff Points (0=Off, NQ 180.0)", 180.0, 0.0, 400.0, 10.0));

        setSettingsDescriptor(sd);

        RuntimeDescriptor rd = createRD();
        rd.declareSignal(SIGNAL_BUY, "Macro Momentum Buy (08:35 ET)");
        rd.declareSignal(SIGNAL_SELL, "Macro Momentum Sell (08:35 ET)");
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

                        int contracts;
                        if (ratchetOverride >= 1 && ratchetOverride <= 4) {
                            contracts = ratchetOverride;
                        } else {
                            contracts = (int) Math.round(riskBudget / (stopPts * ptVal));
                            contracts = Math.max(1, Math.min(4, contracts));
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
                            Coordinate coord = new Coordinate(entryTime, low - (stopPts * 0.15));
                            MarkerInfo info = new MarkerInfo(Enums$MarkerType.ARROW, Enums$Size.LARGE, Color.GREEN, Color.GREEN, true);
                            Marker marker = new Marker(coord, Enums$Position.BOTTOM, info);
                            marker.setTextValue(String.format("MACRO BUY %dx %s @ %.2f | SL: %.2f (-$%.0f) | TP: %.2f (+$%.0f, 1.5R) | FLATTEN: 09:25",
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
                                exitLine.setText("09:25 CASH FLATTEN", LINE_FONT);
                                addFigure(exitLine);
                            }

                            ctx.signal(index, SIGNAL_BUY, String.format("MACRO BUY %dx %s @ %.2f (SL: %.2f, TP: %.2f)", contracts, microSym, entryPrice, stopPrice, targetPrice), entryPrice);
                        } else {
                            Coordinate coord = new Coordinate(entryTime, high + (stopPts * 0.15));
                            MarkerInfo info = new MarkerInfo(Enums$MarkerType.ARROW, Enums$Size.LARGE, Color.RED, Color.RED, true);
                            Marker marker = new Marker(coord, Enums$Position.TOP, info);
                            marker.setTextValue(String.format("MACRO SELL %dx %s @ %.2f | SL: %.2f (-$%.0f) | TP: %.2f (+$%.0f, 1.5R) | FLATTEN: 09:25",
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

                                Line exitLine = new Line(exitTime, targetPrice, exitTime, stopPrice);
                                exitLine.setColor(Color.CYAN);
                                exitLine.setText("09:25 CASH FLATTEN", LINE_FONT);
                                addFigure(exitLine);
                            }

                            ctx.signal(index, SIGNAL_SELL, String.format("MACRO SELL %dx %s @ %.2f (SL: %.2f, TP: %.2f)", contracts, microSym, entryPrice, stopPrice, targetPrice), entryPrice);
                        }

                        tradesByDate.put(today, trade);

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

        // 4. Bar-by-Bar Active Trade Lifecycle & Outcome Tracker (Non-Repainting)
        ActiveTrade activeTrade = tradesByDate.get(today);
        if (activeTrade != null && !activeTrade.closed && barStartTime > activeTrade.entryTime) {
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
                } else if (barStartTime >= activeTrade.maxExitTime || (hour == 9 && min >= 25)) {
                    exitTriggered = true;
                    exitPrice = close;
                    double pts = exitPrice - activeTrade.entryPrice;
                    double netDollars = pts * activeTrade.ptVal * activeTrade.contracts;
                    outcomeText = String.format("CASH FLATTEN (09:25): %.2f (%+.2f pts | %+$%.2f)",
                        exitPrice, pts, netDollars);
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
                } else if (barStartTime >= activeTrade.maxExitTime || (hour == 9 && min >= 25)) {
                    exitTriggered = true;
                    exitPrice = close;
                    double pts = activeTrade.entryPrice - exitPrice;
                    double netDollars = pts * activeTrade.ptVal * activeTrade.contracts;
                    outcomeText = String.format("CASH FLATTEN (09:25): %.2f (%+.2f pts | %+$%.2f)",
                        exitPrice, pts, netDollars);
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
                addFigure(marker);
            }
        }
    }
}
