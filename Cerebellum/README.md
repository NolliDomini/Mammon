# ⚙️ Cerebellum & Soul
### *The System Governor*

**Role**: The Cadence Authority and Environmental Intelligence Center.

## Ownership
The Cerebellum acts as the central orchestrator (Soul) and the environment evaluator (Council).

*   **Soul Orchestration**: Enforces the deterministic Triple-Pulse rhythm (`SEED`, `ACTION`, `MINT`) and strict execution order of all downstream lobes.
*   **BrainFrame**: Owns the zero-copy single source of truth data container. The entire state of a pulse is managed here.
*   **Pulse Gating**: Implements the 30-second "kill window" for `MINT` pulses to prevent execution on stale data.
*   **Council (Environment)**: Computes the environment confidence score based on ATR (Volatility), ADX (Trend), Volume, and VWAP distance.

## Anti-Ownership (What it does NOT do)
*   Does **not** execute broker orders (Brain Stem).
*   Does **not** evaluate technical breakouts (Right Hemisphere) or risk simulations (Left Hemisphere).
*   Does **not** manage money ledgers (Medulla).

## Core Invariants
*   No module outside Soul may author runtime pulse transitions.
*   All downstream lobes must use `enforce_pulse_gate()` to reject stale or out-of-sequence pulses.