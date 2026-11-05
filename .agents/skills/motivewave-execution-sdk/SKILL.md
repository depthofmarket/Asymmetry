---
name: motivewave-execution-sdk
description: "Builds, compiles, packages, and deploys Java custom studies for MotiveWave (JDK 25). Enforces instrument-specific volatility calibrations, non-repainting execution tags, and hot-reload troubleshooting."
---

# MotiveWave Execution SDK Skill (`motivewave-execution-sdk`)

Use this skill whenever authoring, compiling, packaging, or debugging MotiveWave Java custom studies (`src/motivewave/`), resolving chart bracket issues, or updating extension JARs.

## Instrument-Specific Volatility Calibrations
Never use a single hardcoded volatility parameter across all futures contracts. The study must detect the contract symbol and apply:
- **MES / ES / SPY**: Daily Volatility $\sigma = 0.72\%$ ($\approx 58\%$ of NQ)
- **MNQ / NQ / QQQ**: Daily Volatility $\sigma = 1.25\%$
- **MGC / GC / GLD**: Daily Volatility $\sigma = 0.95\%$

## Compilation & Packaging Workflow
1. Verify Java compiler version:
   ```bash
   javac -version # Must be JDK 25 or compatible
   ```
2. Compile source files:
   ```bash
   javac -cp "lib/*:/Applications/MotiveWave.app/Contents/Java/*" -d build/classes src/motivewave/*.java
   ```
3. Package extension JAR:
   ```bash
   jar cf build/LucidPropEnsemble.jar -C build/classes .
   ```
4. Deploy to MotiveWave extensions directory:
   ```bash
   cp build/LucidPropEnsemble.jar "/Users/novo/MotiveWave Extensions/LucidPropEnsemble.jar"
   ```

## Critical MotiveWave JVM ClassLoader Rule
MotiveWave caches loaded Java `.class` bytecodes in memory. When a newly compiled JAR is placed into `/Users/novo/MotiveWave Extensions/`, MotiveWave **DOES NOT** hot-reload the updated classes automatically.
To apply changes:
1. Restart the MotiveWave application.
2. Verify in chart header that only **ONE** instance of the study is loaded per chart tab (remove duplicate instances to avoid overlapping bracket lines).
