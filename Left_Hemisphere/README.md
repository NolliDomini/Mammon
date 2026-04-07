# 🎲 Left Hemisphere
### *The Risk Trajectory Painter*

**Role**: The engine for risk evaluation and survival simulations.

## Ownership
The Left Hemisphere handles stochastic analysis to determine the safety of an execution environment.

*   **Regime Painting (`QuantizedGeometricWalk`)**: Categorizes market state and paints risk priors (mu, sigma, jump probability) onto `BrainFrame.risk`.
*   **Vectorized Risk Engine (`TurtleMonte`)**: Runs high-speed Monte Carlo survival simulations.
*   **Volatility Lanes**: Simulates paths across Worst (2.0x), Neutral (1.0x), and Best (0.5x) multipliers to calculate a weighted `monte_score`.
*   **Shock Injection**: Discharges historical return shocks for realistic volatility modeling.

## Anti-Ownership (What it does NOT do)
*   Does **not** evaluate structural price breakouts (Right Hemisphere).
*   Does **not** orchestrate system pulse cadence (Cerebellum).
*   Does **not** execute live market orders (Brain Stem).

## Core Invariants
*   Must "fail safe" (force `monte_score = 0.0` and reset survival lanes) if invalid gears, prices, or stop levels are detected.