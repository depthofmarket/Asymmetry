package com.motivewave.platform.study.custom;

/**
 * CME gold dollar value per 1.00 price move.
 * MGC is 10 troy ounces: $10 per 1.00, $1 per 0.10 tick.
 * GC is 100 troy ounces: $100 per 1.00, $10 per 0.10 tick.
 *
 * Roots are read from MotiveWave symbol, exchange symbol, and underlying.
 * An unrecognized symbol is not treated as MGC.
 */
public final class GoldContractValue {
    public static final double MGC_POINT_VALUE_USD = 10.0;
    public static final double GC_POINT_VALUE_USD = 100.0;
    public static final double TICK_SIZE = 0.10;

    private GoldContractValue() {
    }

    public static String contractRoot(String rawSymbol) {
        String symbol = stripVenue(rawSymbol);
        if (symbol == null) {
            return null;
        }
        if (matchesRoot(symbol, "MGC")) {
            return "MGC";
        }
        if (matchesRoot(symbol, "GC")) {
            return "GC";
        }
        return null;
    }

    /**
     * Returns the CME point value, or NaN when the symbol is unsupported or the
     * supplied MotiveWave point value disagrees with that root.
     */
    public static double confirmedPointValue(
        String symbol,
        String exchangeSymbol,
        String underlying,
        double sdkPointValue
    ) {
        String fromSymbol = contractRoot(symbol);
        String fromExchange = contractRoot(exchangeSymbol);
        String fromUnderlying = contractRoot(underlying);
        if (conflicts(fromSymbol, fromExchange) || conflicts(fromSymbol, fromUnderlying) || conflicts(fromExchange, fromUnderlying)) {
            return Double.NaN;
        }
        String root = fromSymbol != null ? fromSymbol : (fromExchange != null ? fromExchange : fromUnderlying);
        if (root == null) {
            return Double.NaN;
        }
        double expected = "MGC".equals(root) ? MGC_POINT_VALUE_USD : GC_POINT_VALUE_USD;
        if (Double.isFinite(sdkPointValue) && sdkPointValue > 0.0 && Math.abs(sdkPointValue - expected) > 1e-6) {
            return Double.NaN;
        }
        return expected;
    }

    public static double grossPnl(double priceMove, double pointValue, int contracts, boolean longPosition) {
        if (!Double.isFinite(pointValue) || contracts == 0) {
            return Double.NaN;
        }
        double points = longPosition ? priceMove : -priceMove;
        return points * pointValue * contracts;
    }

    private static boolean conflicts(String left, String right) {
        return left != null && right != null && !left.equals(right);
    }

    private static String stripVenue(String rawSymbol) {
        if (rawSymbol == null) {
            return null;
        }
        String symbol = rawSymbol.trim().toUpperCase();
        if (symbol.isEmpty()) {
            return null;
        }
        int colon = symbol.lastIndexOf(':');
        if (colon >= 0 && colon < symbol.length() - 1) {
            symbol = symbol.substring(colon + 1).trim();
        }
        int slash = symbol.lastIndexOf('/');
        if (slash >= 0 && slash < symbol.length() - 1) {
            symbol = symbol.substring(slash + 1).trim();
        }
        return symbol.isEmpty() ? null : symbol;
    }

    private static boolean matchesRoot(String symbol, String root) {
        if (!symbol.startsWith(root)) {
            return false;
        }
        if (symbol.length() == root.length()) {
            return true;
        }
        char next = symbol.charAt(root.length());
        if (next == '#' || next == '.' || next == '_' || next == '-' || next == ' ' || next == '/') {
            return true;
        }
        String remainder = symbol.substring(root.length());
        return remainder.matches("^[FGHJKMNQUVXZ]\\d{1,4}([._\\s#-].*)?$")
            || remainder.matches("^\\d{2,4}([._\\s#-].*)?$");
    }
}
