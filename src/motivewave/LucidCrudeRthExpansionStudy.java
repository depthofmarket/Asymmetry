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
    id = "CRUDE_RTH_EXPANSION_S5",
    name = "Lucid 25K — 5. Crude Oil Post-Fix Range Expansion (10:15 ET)",
    desc = "Post-Fix Morning Consolidation Range Expansion on Micro WTI Crude Oil (MCL, 10:15–12:30 ET) with $0.45 Stop, $0.90 Target (2.0R), +1.0R Breakeven Ratchet, 12:30 ET Flatten, Live CQG Bracket Execution, and Pareto Ratchet Sizing",
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
public class LucidCrudeRthExpansionStudy extends Study {

    private static final Font LINE_FONT = new Font("SansSerif", Font.BOLD, 10);

    // Settings Keys
    private static final String ENABLE_LIVE_AUTOTRADE = "enableLiveAutoTrade";
    private static final String STOP_DOLLARS = "stopDollars";
    private static final String TARGET_DOLLARS = "targetDollars";
    private static final String MIN_BOX_RANGE = "minBoxRange";
    private static final String MAX_BOX_RANGE = "maxBoxRange";
    private static final String ENABLE_SOUND_ALERT = "enableSoundAlert";
    private static final String SHOW_LEVEL_LINES = "showLevelLines";
    private static final String HIDE_LINES_WHEN_LIVE = "hideLinesWhenLive";

    private static final ZoneId NY_ZONE = ZoneId.of("America/New_York");

    // Signal Keys
    private static final String SIGNAL_BUY = "LUCID_CRUDE_BUY";
    private static final String SIGNAL_SELL = "LUCID_CRUDE_SELL";

    // Session State Tracking
    private final Map<LocalDate, MorningBoxStats> boxByDate = new HashMap<>();
    private final Set<LocalDate> processedDays = new HashSet<>();
    private final Map<LocalDate, ActiveTrade> tradesByDate = new HashMap<>();

    // IAF Session Cooldown Lock: strictly enforces <= 1 automated trade per session
    private static final Set<LocalDate> DAILY_SUBMITTED_DATES = java.util.concurrent.ConcurrentHashMap.newKeySet();

    private static class MorningBoxStats {
        double high = Double.NEGATIVE_INFINITY;
        double low = Double.POSITIVE_INFINITY;
        boolean complete = false;

        void addBar(int min, double h, double l) {
            high = Math.max(high, h);
            low = Math.min(low, l);
            if (min == 14) {
                complete = true;
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
        boolean entryFilled = false;
        boolean bracketsSubmitted = false;
        boolean breakevenMoved = false;
        String entryOrderId;
        String slOrderId;
        String tpOrderId;
    }

    // Capital & Sizing Persistence
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

    private static class DaemonRiskState {
        double peakBalance = 25000.00;
        double trailingFloor = 24000.00;
    }

    private static DaemonRiskState loadDaemonRiskState() {
        DaemonRiskState state = new DaemonRiskState();
        try {
            File stateFile = new File("/Users/novo/trading_strategy/nq-scalper-backtest/results/forward_test/account_state.json");
            if (!stateFile.exists()) return state;
            String json = new String(Files.readAllBytes(stateFile.toPath()), StandardCharsets.UTF_8);

            Matcher mPeak = Pattern.compile("\"peak_balance\"\\s*:\\s*([0-9.]+)").matcher(json);
            if (mPeak.find()) state.peakBalance = Double.parseDouble(mPeak.group(1));

            Matcher mFloor = Pattern.compile("\"trailing_floor\"\\s*:\\s*([0-9.]+)").matcher(json);
            if (mFloor.find()) state.trailingFloor = Double.parseDouble(mFloor.group(1));
        } catch (Exception ignored) {}
        return state;
    }

    public static int resolveContracts(OrderContext ctx, int fallbackContracts) {
        if (ctx == null) return 0;
        try {
            double cash = ctx.getCashBalance();
            double real = ctx.getRealizedPnL();
            double unreal = ctx.getUnrealizedPnL();
            double balance = cash + real + unreal;
            if (!Double.isFinite(balance) || balance <= 10000.0) return 0;

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

    @Override
    public void initialize(Defaults defaults) {
        SettingsDescriptor sd = createSD();
        SettingTab tab = sd.addTab("Parameters");

        SettingGroup gTrade = tab.addGroup("Strategy Parameters");
        gTrade.addRow(new BooleanDescriptor(ENABLE_LIVE_AUTOTRADE, "Enable Live Auto-Trade", true));
        gTrade.addRow(new DoubleDescriptor(STOP_DOLLARS, "Stop Loss ($/bbl)", 0.45, 0.10, 2.00, 0.05));
        gTrade.addRow(new DoubleDescriptor(TARGET_DOLLARS, "Profit Target ($/bbl)", 0.90, 0.20, 4.00, 0.05));
        gTrade.addRow(new DoubleDescriptor(MIN_BOX_RANGE, "Min Box Range ($)", 0.30, 0.10, 1.00, 0.05));
        gTrade.addRow(new DoubleDescriptor(MAX_BOX_RANGE, "Max Box Range ($)", 1.20, 0.50, 3.00, 0.05));

        SettingGroup gDisplay = tab.addGroup("Display & Alerts");
        gDisplay.addRow(new BooleanDescriptor(ENABLE_SOUND_ALERT, "Enable Sound Alert", true));
        gDisplay.addRow(new BooleanDescriptor(SHOW_LEVEL_LINES, "Show Level Lines", true));
        gDisplay.addRow(new BooleanDescriptor(HIDE_LINES_WHEN_LIVE, "Hide Lines When Live", false));

        setSettingsDescriptor(sd);

        RuntimeDescriptor rd = createRD();
        rd.declareSignal(SIGNAL_BUY, "Crude RTH Breakout BUY");
        rd.declareSignal(SIGNAL_SELL, "Crude RTH Breakout SELL");
        setRuntimeDescriptor(rd);
    }

    @Override
    public int getMinBars() {
        return 60;
    }

    @Override
    protected void calculate(int index, DataContext ctx) {
        DataSeries series = ctx.getDataSeries();
        if (series == null || index < 1) return;

        long barTime = series.getStartTime(index);
        ZonedDateTime nyBar = Instant.ofEpochMilli(barTime).atZone(NY_ZONE);
        LocalDate today = nyBar.toLocalDate();
        int hour = nyBar.getHour();
        int min = nyBar.getMinute();

        double o = series.getOpen(index);
        double h = series.getHigh(index);
        double l = series.getLow(index);
        double c = series.getClose(index);

        MorningBoxStats box = boxByDate.computeIfAbsent(today, k -> new MorningBoxStats());

        // Track 09:30–10:14 ET Morning Consolidation Box
        if ((hour == 9 && min >= 30) || (hour == 10 && min < 15)) {
            box.addBar(min, h, l);
        }

        // Active Trade Management
        ActiveTrade trade = tradesByDate.get(today);
        if (trade != null && !trade.closed) {
            // Breakeven ratchet (+1.0R excursion)
            if (!trade.breakevenMoved) {
                if (trade.isLong && h >= trade.entryPrice + 0.45) {
                    trade.stopPrice = trade.entryPrice + 0.02; // lock +2 ticks
                    trade.breakevenMoved = true;
                } else if (!trade.isLong && l <= trade.entryPrice - 0.45) {
                    trade.stopPrice = trade.entryPrice - 0.02; // lock +2 ticks
                    trade.breakevenMoved = true;
                }
            }

            // Mandatory flatten at 12:30 ET
            if (hour > 12 || (hour == 12 && min >= 30)) {
                trade.closed = true;
                if (ctx instanceof OrderContext) {
                    OrderContext octx = (OrderContext) ctx;
                    octx.cancelOrders();
                    octx.closeAtMarket();
                }
            }
        }

        // Breakout Entry Window: 10:15–11:15 ET
        if (box.complete && !processedDays.contains(today) && !DAILY_SUBMITTED_DATES.contains(today)) {
            boolean inEntryWindow = (hour == 10 && min >= 15) || (hour == 11 && min <= 15);
            if (!inEntryWindow) return;

            double boxRange = box.high - box.low;
            double minBox = getSettings().getDouble(MIN_BOX_RANGE, 0.30);
            double maxBox = getSettings().getDouble(MAX_BOX_RANGE, 1.20);

            if (boxRange < minBox || boxRange > maxBox) return;

            // Bar close breakout
            if (c > box.high) {
                processedDays.add(today);
                triggerSignal(index, ctx, SIGNAL_BUY, true, c);
            } else if (c < box.low) {
                processedDays.add(today);
                triggerSignal(index, ctx, SIGNAL_SELL, false, c);
            }
        }
    }

    private void triggerSignal(int index, DataContext ctx, String signalKey, boolean isLong, double closePrice) {
        DataSeries series = ctx.getDataSeries();
        long barTime = series.getStartTime(index);
        LocalDate today = Instant.ofEpochMilli(barTime).atZone(NY_ZONE).toLocalDate();

        double stopDist = getSettings().getDouble(STOP_DOLLARS, 0.45);
        double targetDist = getSettings().getDouble(TARGET_DOLLARS, 0.90);

        double entryPrice = closePrice;
        double stopPrice = isLong ? (entryPrice - stopDist) : (entryPrice + stopDist);
        double targetPrice = isLong ? (entryPrice + targetDist) : (entryPrice - targetDist);

        ActiveTrade trade = new ActiveTrade();
        trade.date = today;
        trade.isLong = isLong;
        trade.entryPrice = entryPrice;
        trade.stopPrice = stopPrice;
        trade.targetPrice = targetPrice;
        trade.entryTime = barTime;
        trade.contracts = 2; // base ratchet tier 1
        tradesByDate.put(today, trade);

        Coordinate c = new Coordinate(barTime, entryPrice);
        Color markColor = isLong ? new Color(0, 204, 102) : new Color(220, 20, 60);
        MarkerInfo info = new MarkerInfo(Enums$MarkerType.ARROW, Enums$Size.MEDIUM, markColor, markColor, true);
        Marker marker = new Marker(c, isLong ? Enums$Position.BOTTOM : Enums$Position.TOP, info);
        marker.setTextValue(isLong ? "Crude Breakout BUY" : "Crude Breakout SELL");
        addFigure(marker);

        if (getSettings().getBoolean(ENABLE_SOUND_ALERT, true)) {
            Toolkit.getDefaultToolkit().beep();
        }

        if (getSettings().getBoolean(ENABLE_LIVE_AUTOTRADE, true) && ctx instanceof OrderContext) {
            executeAutoTradeIfArmed((OrderContext) ctx, signalKey, trade);
        }
    }

    private synchronized void executeAutoTradeIfArmed(OrderContext ctx, String signalKey, ActiveTrade trade) {
        LocalDate today = trade.date;
        if (DAILY_SUBMITTED_DATES.contains(today)) return;

        int contracts = resolveContracts(ctx, trade.contracts);
        if (contracts <= 0) {
            logExecutionEvent("ORDER_BLOCKED_UNVERIFIED_ACCOUNT", "LucidCrudeRthExpansion",
                ctx.getInstrument() != null ? ctx.getInstrument().getSymbol() : "MCL",
                "BLOCKED", 0.0, 0.0, 0.0, 0,
                "Account context unverified or sizing returned zero; order entry blocked (fail-closed).");
            return;
        }
        trade.contracts = contracts;

        float stopPrice = ctx.getInstrument().round((float) trade.stopPrice);
        float targetPrice = ctx.getInstrument().round((float) trade.targetPrice);

        setStopPrice(stopPrice);
        setTargetPrice(targetPrice);

        Order entry = ctx.createMarketOrder(trade.isLong ? Enums$OrderAction.BUY : Enums$OrderAction.SELL, contracts);
        ctx.submitOrders(entry);

        DAILY_SUBMITTED_DATES.add(today);
        trade.orderSubmitted = true;
        trade.entryOrderId = entry != null ? entry.getOrderId() : null;

        logExecutionEvent("ORDER_SUBMITTED", "LucidCrudeRthExpansion", ctx.getInstrument().getSymbol(),
            trade.isLong ? "BUY" : "SELL", trade.entryPrice, stopPrice, targetPrice, contracts,
            "Market entry submitted. Brackets pending fill confirmation. Daily cooldown locked.");
    }

    @Override
    public void onOrderFilled(OrderContext ctx, Order order) {
        if (ctx == null || order == null) return;
        long now = ctx.getCurrentTime();
        LocalDate today = Instant.ofEpochMilli(now).atZone(NY_ZONE).toLocalDate();
        ActiveTrade trade = tradesByDate.get(today);

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
        } else if (ctx.getPosition() == 0) {
            ctx.cancelOrders();
            if (trade != null) trade.closed = true;
        }
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
