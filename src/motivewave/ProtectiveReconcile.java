package com.motivewave.platform.study.custom;

import com.motivewave.platform.sdk.common.Coordinate;
import com.motivewave.platform.sdk.common.DataContext;
import com.motivewave.platform.sdk.common.DataSeries;
import com.motivewave.platform.sdk.common.Enums$Priority;
import com.motivewave.platform.sdk.common.Enums$StrategyState;
import com.motivewave.platform.sdk.draw.Figure;
import com.motivewave.platform.sdk.draw.Label;
import com.motivewave.platform.sdk.order_mgmt.Order;
import com.motivewave.platform.sdk.order_mgmt.OrderContext;
import com.motivewave.platform.sdk.study.RuntimeDescriptor;
import com.motivewave.platform.sdk.study.Study;

import java.util.function.Consumer;

import java.awt.Color;
import java.awt.Font;
import java.awt.Toolkit;

/**
 * Shared fill-protection state machine for the MotiveWave studies.
 * Order identity, modification requests, and broker-confirmed quantities stay distinct.
 * The installed SDK has no native OCO, reduce-only, or atomic-replace API, so a working
 * order whose cancellation is pending is never modified.
 */
public final class ProtectiveReconcile {
    public static final String SIGNAL = "LUCID_PROTECTION_UNRESOLVED";
    private static final long ALERT_INTERVAL_NANOS = 300_000_000_000L;

    private ProtectiveReconcile() {}

    public enum Decision {
        FLAT,
        COVERED,
        REQUESTED,
        AWAITING,
        WITHHELD_CANCEL,
        WITHHELD_FLATTEN_WORKING,
        WITHHELD_UNSAFE,
        STOP_MISSING,
        REQUEST_FAILED,
        IDLE
    }

    public static final class State {
        public int generation = 0;
        public int pendingGeneration = -1;
        public int positionAtRequest = Integer.MIN_VALUE;
        public int lastObservedPosition = Integer.MIN_VALUE;
        public int lastReconciledAbsQty = Integer.MIN_VALUE;
        public int confirmedStopQty = -1;
        public int requestedStopQty = -1;
        public int requestedTargetQty = -1;
        public double requestedStopPrice = Double.NaN;
        public double requestedTargetPrice = Double.NaN;
        public boolean stopRequested = false;
        public boolean targetRequested = false;
        public boolean pending = false;
        public boolean positionLag = false;
        public final int[] seenFilled = new int[] {-1, -1, -1, -1};
        public Label label;
        public long alertLastNanos = 0L;
        public String alertKey = "";
        public String lastError = "";
    }

    public static void declare(RuntimeDescriptor rd) {
        if (rd == null || rd.getSignal(SIGNAL) != null) return;
        rd.declareSignal(SIGNAL, "Protective coverage unresolved — operator action required");
        var signal = rd.getSignal(SIGNAL);
        if (signal != null) signal.setPriority(Enums$Priority.URGENT);
    }

    public static boolean isTrackedFill(Order order, Order entry, String entryId, Order stop, String stopId,
                                        Order target, String targetId, Order flatten, String flattenId) {
        return same(order, entry) || matchesId(order, entryId)
            || same(order, stop) || matchesId(order, stopId)
            || same(order, target) || matchesId(order, targetId)
            || same(order, flatten) || matchesId(order, flattenId);
    }

    public static boolean same(Order left, Order right) {
        if (left == null || right == null) return false;
        if (left == right) return true;
        try {
            String leftId = left.getOrderId();
            String rightId = right.getOrderId();
            return leftId != null && !leftId.isEmpty() && leftId.equals(rightId);
        } catch (RuntimeException e) {
            return false;
        }
    }

    public static boolean matchesId(Order order, String storedId) {
        if (order == null || storedId == null || storedId.isEmpty()) return false;
        try {
            return storedId.equals(order.getOrderId());
        } catch (RuntimeException e) {
            return false;
        }
    }

    public static boolean isWorking(Order order) {
        if (order == null) return false;
        try {
            return order.isActive() && !order.isCancelled() && !order.isFilled();
        } catch (RuntimeException e) {
            return false;
        }
    }

    /**
     * @return true when the position API has not yet reflected this fill.
     *         Repeated callbacks for the same filled quantity are idempotent.
     */
    public static boolean noteFill(State state, Order order, Order entry, Order stop, Order target, Order flatten, int position) {
        int slot = slotOf(order, entry, stop, target, flatten);
        if (slot < 0) return false;
        int filled = filledQty(order);
        int previous = state.seenFilled[slot];
        boolean fresh = previous < 0 ? (filled > 0 || isFilledFlag(order)) : filled > previous;
        if (!fresh) return state.positionLag;
        state.seenFilled[slot] = Math.max(filled, 0);
        state.generation++;
        state.pendingGeneration = -1;
        state.stopRequested = false;
        state.targetRequested = false;
        state.pending = true;
        boolean entryNotReflected = slot == 0 && position == 0 && filled > 0;
        boolean positionUnchanged = state.lastObservedPosition != Integer.MIN_VALUE
            && position == state.lastObservedPosition
            && position != 0;
        if (entryNotReflected || positionUnchanged) {
            state.positionLag = true;
            return true;
        }
        state.positionLag = false;
        state.lastObservedPosition = position;
        return false;
    }

    public static void markFlat(State state) {
        state.positionLag = false;
        state.pending = false;
        state.stopRequested = false;
        state.targetRequested = false;
        state.pendingGeneration = -1;
        state.confirmedStopQty = 0;
        state.lastReconciledAbsQty = 0;
        state.lastObservedPosition = 0;
    }

    public static Decision reconcile(OrderContext ctx, State state, Order pendingCancel, Order entry, Order stop,
                                     Order target, Order flatten, boolean flattenWorking, float desiredStop,
                                     float desiredTarget, boolean havePrices) {
        if (ctx == null || state == null) return Decision.IDLE;
        int position;
        try {
            position = ctx.getPosition();
        } catch (RuntimeException e) {
            state.pending = true;
            state.lastError = e.getMessage();
            return Decision.WITHHELD_UNSAFE;
        }
        int absQty = Math.abs(position);
        if (absQty == 0) {
            if (state.positionLag) return Decision.AWAITING;
            markFlat(state);
            return Decision.FLAT;
        }
        state.positionLag = false;
        state.lastObservedPosition = position;

        if (pendingCancel != null) {
            state.pending = true;
            return Decision.WITHHELD_CANCEL;
        }
        if (flattenWorking || isWorking(flatten)) {
            state.pending = true;
            return Decision.WITHHELD_FLATTEN_WORKING;
        }
        if (!isWorking(stop)) {
            state.pending = true;
            state.confirmedStopQty = -1;
            return Decision.STOP_MISSING;
        }
        if (same(pendingCancel, stop) || same(pendingCancel, target) || same(pendingCancel, entry)) {
            state.pending = true;
            return Decision.WITHHELD_CANCEL;
        }

        double tick = 0.25;
        try {
            if (ctx.getInstrument() != null && ctx.getInstrument().getTickSize() > 0) {
                tick = ctx.getInstrument().getTickSize();
            }
        } catch (RuntimeException ignored) {
        }

        if (state.stopRequested || state.targetRequested) {
            if (position == state.positionAtRequest && state.pendingGeneration == state.generation
                    && stopMatchesRequest(stop, state, tick)
                    && (!state.targetRequested || targetMatchesRequest(target, state, tick))) {
                acceptConfirmed(state, absQty);
                return Decision.COVERED;
            }
            if (position == state.positionAtRequest && state.pendingGeneration == state.generation) {
                state.pending = true;
                return Decision.AWAITING;
            }
            state.stopRequested = false;
            state.targetRequested = false;
            state.pendingGeneration = -1;
        }

        boolean targetWorking = isWorking(target);
        boolean stopQtyMismatch = safeQty(stop) != absQty;
        boolean stopPriceMismatch = havePrices && !priceNear(stop.getStopPrice(), desiredStop, tick);
        boolean targetMismatch = targetWorking && (safeQty(target) != absQty
            || (havePrices && !priceNear(target.getLimitPrice(), desiredTarget, tick)));
        if (!stopQtyMismatch && !stopPriceMismatch && !targetMismatch) {
            acceptConfirmed(state, absQty);
            return Decision.COVERED;
        }
        if (!havePrices && (stop.getStopPrice() == null || (targetWorking && target.getLimitPrice() == null))) {
            state.pending = true;
            return Decision.WITHHELD_UNSAFE;
        }
        float stopPrice = havePrices ? desiredStop : stop.getStopPrice();
        float targetPrice = havePrices ? desiredTarget
            : (targetWorking && target.getLimitPrice() != null ? target.getLimitPrice() : desiredTarget);
        if (isWorking(entry) && !targetWorking) {
            state.pending = true;
            return Decision.WITHHELD_UNSAFE;
        }

        state.pendingGeneration = state.generation;
        state.positionAtRequest = position;
        state.requestedStopQty = absQty;
        state.requestedTargetQty = absQty;
        state.requestedStopPrice = stopPrice;
        state.requestedTargetPrice = targetPrice;
        state.lastError = "";
        try {
            if (same(pendingCancel, stop)) return Decision.WITHHELD_CANCEL;
            stop.setAdjStopPrice(stopPrice);
            stop.setAdjQuantity(absQty);
            ctx.submitOrders(stop);
            state.stopRequested = true;
            if (targetWorking) {
                if (same(pendingCancel, target)) {
                    state.stopRequested = false;
                    state.pending = true;
                    return Decision.WITHHELD_CANCEL;
                }
                target.setAdjLimitPrice(targetPrice);
                target.setAdjQuantity(absQty);
                ctx.submitOrders(target);
                state.targetRequested = true;
            }
        } catch (RuntimeException e) {
            state.stopRequested = false;
            state.targetRequested = false;
            state.pendingGeneration = -1;
            state.pending = true;
            state.lastError = e.getMessage() != null ? e.getMessage() : e.getClass().getSimpleName();
            return Decision.REQUEST_FAILED;
        }
        state.pending = true;
        return Decision.REQUESTED;
    }

    public static boolean confirmStop(State state, Order order, int position, double tick) {
        if (state == null || !state.stopRequested || order == null) return false;
        if (state.pendingGeneration != state.generation || position != state.positionAtRequest) return false;
        if (!stopMatchesRequest(order, state, tick)) return false;
        state.stopRequested = false;
        state.confirmedStopQty = state.requestedStopQty;
        if (!state.targetRequested) acceptConfirmed(state, Math.abs(position));
        return true;
    }

    public static boolean confirmTarget(State state, Order order, int position, double tick) {
        if (state == null || !state.targetRequested || order == null) return false;
        if (state.pendingGeneration != state.generation || position != state.positionAtRequest) return false;
        if (!targetMatchesRequest(order, state, tick)) return false;
        state.targetRequested = false;
        if (!state.stopRequested) acceptConfirmed(state, Math.abs(position));
        return true;
    }

    public static void raise(Study study, OrderContext ctx, State state, Consumer<Figure> addFigure,
                             Consumer<Figure> removeFigure, String event, String detail) {
        if (study == null || state == null) return;
        study.setState(Enums$StrategyState.INACTIVE);
        declare(study.getRuntimeDescriptor());
        refreshLabel(ctx, state, event, addFigure, removeFigure);
        String key = event + "|" + detail;
        long now = System.nanoTime();
        if (key.equals(state.alertKey) && state.alertLastNanos != 0L
                && now - state.alertLastNanos < ALERT_INTERVAL_NANOS) {
            return;
        }
        state.alertLastNanos = now;
        state.alertKey = key;
        study.error("OPERATOR_ACTION_REQUIRED " + event + " " + detail);
        try {
            Toolkit.getDefaultToolkit().beep();
        } catch (RuntimeException ignored) {
        }
        triggerSignal(study, ctx);
    }

    public static void clear(Study study, State state, Consumer<Figure> removeFigure, boolean restoreActive) {
        if (state == null) return;
        if (removeFigure != null && state.label != null) {
            try {
                removeFigure.accept(state.label);
            } catch (RuntimeException ignored) {
            }
        }
        state.label = null;
        state.alertKey = "";
        if (restoreActive && study != null) study.setState(Enums$StrategyState.ACTIVE);
    }

    private static void acceptConfirmed(State state, int absQty) {
        state.pending = false;
        state.stopRequested = false;
        state.targetRequested = false;
        state.confirmedStopQty = absQty;
        state.lastReconciledAbsQty = absQty;
        state.positionLag = false;
    }

    private static boolean stopMatchesRequest(Order stop, State state, double tick) {
        if (!isWorking(stop) || safeQty(stop) != state.requestedStopQty) return false;
        Float price = stop.getStopPrice();
        return priceNear(price, state.requestedStopPrice, tick);
    }

    private static boolean targetMatchesRequest(Order target, State state, double tick) {
        if (!isWorking(target) || safeQty(target) != state.requestedTargetQty) return false;
        return priceNear(target.getLimitPrice(), state.requestedTargetPrice, tick);
    }

    private static boolean priceNear(Float observed, double requested, double tick) {
        return observed != null && Float.isFinite(observed) && Double.isFinite(requested)
            && Math.abs(observed.doubleValue() - requested) <= Math.max(tick, 1e-6) / 2.0;
    }

    private static int safeQty(Order order) {
        try {
            return order.getQuantity();
        } catch (RuntimeException e) {
            return Integer.MIN_VALUE;
        }
    }

    private static int filledQty(Order order) {
        try {
            return Math.max(0, order.getFilled());
        } catch (RuntimeException e) {
            return 0;
        }
    }

    private static boolean isFilledFlag(Order order) {
        try {
            return order.isFilled();
        } catch (RuntimeException e) {
            return false;
        }
    }

    private static int slotOf(Order order, Order entry, Order stop, Order target, Order flatten) {
        if (same(order, entry)) return 0;
        if (same(order, stop)) return 1;
        if (same(order, target)) return 2;
        if (same(order, flatten)) return 3;
        return -1;
    }

    private static void refreshLabel(OrderContext ctx, State state, String event,
                                     Consumer<Figure> addFigure, Consumer<Figure> removeFigure) {
        try {
            if (state.label != null && removeFigure != null) removeFigure.accept(state.label);
            long time = ctx != null ? ctx.getCurrentTime() : System.currentTimeMillis();
            double price = 0.0;
            if (ctx != null && ctx.getInstrument() != null && ctx.getPosition() != 0) {
                price = ctx.getAvgEntryPrice();
            }
            Label label = new Label(new Coordinate(time, price), "PROTECTION UNRESOLVED: " + event);
            label.setPosition(com.motivewave.platform.sdk.common.Enums$Position.TOP);
            label.getText().setTextColor(Color.WHITE);
            label.getText().setBackground(new Color(153, 27, 27));
            label.getText().setFont(new Font("SansSerif", Font.BOLD, 12));
            if (addFigure != null) addFigure.accept(label);
            state.label = label;
        } catch (RuntimeException ignored) {
            state.label = null;
        }
    }

    private static void triggerSignal(Study study, OrderContext ctx) {
        try {
            if (ctx == null) return;
            DataContext data = ctx.getDataContext();
            if (data == null || data.getDataSeries() == null) return;
            DataSeries series = data.getDataSeries();
            int index = series.size() - 1;
            if (index >= 0) series.setSignalTriggered(index, SIGNAL, true);
        } catch (RuntimeException ignored) {
        }
    }
}
