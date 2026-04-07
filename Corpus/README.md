# 🌉 Corpus
### *The Neural Bridge*

**Role**: The transport and synthesis layer between the hemispheres and the core.

## Ownership
The Corpus acts as the integration bus and scoring synthesizer.

*   **Callosum (Deterministic Tier Synthesis)**: The authority for blending risk (Left) and structure (Right) signals. Computes the composite `tier_score` and writes it to the `BrainFrame`.
*   **Optical Tract (Broadcast Substrate)**: A synchronous Observer-pattern bus. Performs high-speed fan-out (`spray(df)`) of pulse data to all registered system subscribers.
*   **Fault-Tolerant Delivery**: Captures subscriber failures in telemetry without aborting the global broadcast cycle.

## Anti-Ownership (What it does NOT do)
*   Does **not** generate original technical signals or risk probabilities.
*   Does **not** handle final policy approval or broker execution.

## Core Invariants
*   Must adhere to a strict soft-latency budget (e.g., 50ms) for internal payload fan-out.
*   Must isolate subscriber failures to prevent cascading system collapse.