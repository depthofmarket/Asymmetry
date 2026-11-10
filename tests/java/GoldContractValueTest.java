package com.motivewave.platform.study.custom;

public final class GoldContractValueTest {
    public static void main(String[] args) {
        expect("MGC", GoldContractValue.contractRoot("MGC"));
        expect("MGC", GoldContractValue.contractRoot("CME:MGCH25"));
        expect("MGC", GoldContractValue.contractRoot("NYMEX:MGCZ4"));
        expect("GC", GoldContractValue.contractRoot("GC"));
        expect("GC", GoldContractValue.contractRoot("CME:GCG5"));
        expect(null, GoldContractValue.contractRoot("GOLD"));
        expect(null, GoldContractValue.contractRoot("QO"));
        expect(null, GoldContractValue.contractRoot("MGCX"));
        expect(null, GoldContractValue.contractRoot(null));

        check(10.0, GoldContractValue.confirmedPointValue("CME:MGC", null, null, Double.NaN));
        check(10.0, GoldContractValue.confirmedPointValue("MGC", "MGC", "MGC", 10.0));
        check(100.0, GoldContractValue.confirmedPointValue("GC", null, null, 0.0));
        check(100.0, GoldContractValue.confirmedPointValue("CME:GC", "GC", null, 100.0));
        if (!Double.isNaN(GoldContractValue.confirmedPointValue("MES", null, null, 5.0))) {
            throw new AssertionError("MES was classified as gold");
        }
        if (!Double.isNaN(GoldContractValue.confirmedPointValue("MGC", "GC", null, 10.0))) {
            throw new AssertionError("conflicting roots were accepted");
        }
        if (!Double.isNaN(GoldContractValue.confirmedPointValue("MGC", null, null, 1.0))) {
            throw new AssertionError("stale $1 MGC point value was accepted");
        }

        check(10.0, GoldContractValue.grossPnl(1.0, 10.0, 1, true));
        check(1.0, GoldContractValue.grossPnl(0.10, 10.0, 1, true));
        check(10.0, GoldContractValue.grossPnl(-1.0, 10.0, 1, false));
        check(1.0, GoldContractValue.grossPnl(-0.10, 10.0, 1, false));
        check(100.0, GoldContractValue.grossPnl(1.0, 100.0, 1, true));
        check(10.0, GoldContractValue.grossPnl(0.10, 100.0, 1, true));
        check(100.0, GoldContractValue.grossPnl(-1.0, 100.0, 1, false));
        check(10.0, GoldContractValue.grossPnl(-0.10, 100.0, 1, false));
        System.out.println("passed");
    }

    private static void expect(String expected, String actual) {
        if (expected == null) {
            if (actual != null) {
                throw new AssertionError("expected null, got " + actual);
            }
            return;
        }
        if (!expected.equals(actual)) {
            throw new AssertionError(expected + " != " + actual);
        }
    }

    private static void check(double expected, double actual) {
        if (Double.isNaN(actual) || Math.abs(expected - actual) > 1e-9) {
            throw new AssertionError(expected + " != " + actual);
        }
    }
}
