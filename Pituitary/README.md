# 🧬 Pituitary
### *The Master Hormonal Controller*

**Role**: The authority for system-wide genetic parameter evolution.

## Ownership
The Pituitary manages the system's parameter tiers and safe operational boundaries.

*   **23-D Genetic Vector**: Manages the fundamental unit of evolution (active gears, weights, thresholds, scalars).
*   **Gaussian Process (GP) Mutation**: Runs the mutation cycle every 4th `MINT` to derive the optimal "Gold" parameter set.
*   **Hormonal Hierarchy**: Tracks Platinum (candidates), Gold (active reference), Silver (synapse winners), and Bronze (historical genealogy) tiers.
*   **DiamondGland (Bayesian Governor)**: Performs deep searches on historical synapse data to update system Safety Rails.
*   **Hormonal Vault**: Manages `hormonal_vault.json`, the single source of truth for the system's genetics.

## Anti-Ownership (What it does NOT do)
*   Does **not** run the brute-force Monte Carlo simulations (Hospital).
*   Does **not** execute physical trades or track intent lifecycles.

## Core Invariants
*   **Integrity Gate (Piece 14)**: Mandatory pre-coronation check ensuring completeness and bounded correctness of any mutated parameter vector before it becomes Gold.
*   **Safety Rail Clench**: Prevents the installation of parameters that violate mathematically discovered safe bounds.