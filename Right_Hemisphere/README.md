# 📐 Right Hemisphere
### *The Structure Painter*

**Role**: The engine for technical breakout analysis.

## Ownership
The Right Hemisphere is exclusively responsible for evaluating market structure and breakout signals.

*   **Snapping Turtle (Tier 1)**: Computes zero-copy writes to `BrainFrame.structure`.
*   **Donchian Breakouts**: Evaluates price against `active_hi` and `active_lo` boundaries defined by the current `active_gear` (rolling window).
*   **Signal Output**: Generates the deterministic `tier1_signal` (1 or 0) for downstream synthesis.

## Anti-Ownership (What it does NOT do)
*   Does **not** compute survival probabilities or risk metrics (Left Hemisphere).
*   Does **not** make final execution policy decisions (Medulla).
*   Does **not** track persistent historical memory (Hippocampus).

## Core Invariants
*   Must "fail safe" (force `tier1_signal = 0`) if history is insufficient or data is malformed.
*   Must emit deterministic status codes for structural resets.