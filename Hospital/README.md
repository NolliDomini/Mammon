# 🏥 Hospital
### *The Evolutionary Core*

**Role**: The parameter calibration and discovery engine.

## Ownership
The Hospital runs the computationally intensive optimizer loops.

*   **Volume Furnace (OptimizerV2)**: Executes the high-capacity parameter discovery pipeline to find fitness peaks for the current market regime.
*   **Stage A-H Pipeline**: Handles LHS exploration, vectorized Monte scoring, Bayesian exploitation, and final promotion gating.
*   **Cadence-Gated Calibration**: Ignites every 3rd `MINT` pulse in live modes to prevent pulse collisions and computational drag.
*   **Vectorized Fitness Scoring**: Calculates the `robust_score` blending survival, stability, expectancy, and slippage cost.

## Anti-Ownership (What it does NOT do)
*   Does **not** execute live trades on the market.
*   Does **not** hold long-lived in-memory state (uses an ephemeral state policy).
*   Does **not** permanently persist parameter changes (Pituitary manages the Hormonal Vault).

## Core Invariants
*   Must enforce the **Diversity Floor** to prevent genetic collapse/over-fitting.
*   Must enforce the **Risk Gate** (slash scores falling below 0.5) to ensure mathematically "Safe" parameters.