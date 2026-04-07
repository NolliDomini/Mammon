# MAMMON SYSTEM CONSTITUTION
### Established: 2026-02-09
### Version: 1.0.0

## 1. PRIME DIRECTIVES

1.  **Root Sovereignty**: All operations, logic, data storage, and execution must occur strictly within the project root (resolved dynamically via `Path(__file__).resolve()`). Accessing or modifying files outside this directory is a violation of protocol.
2.  **Source Fidelity**: The `mammon.json` (Pine Script V3.3) is the Canon. The Brain's logic must mathematically replicate the Canon's behavior. Any deviation for "improvement" must be explicitly authorized and versioned.
3.  **Modular Cognition**: The system shall not be a monolith. It must be composed of distinct, testable neurological subsystems (e.g., Turtle Cortex, Jetstream Lobe, Momentum Ganglia).

## 2. DATA HYGIENE & PERSISTENCE

1.  **Single Source of Truth**: Configuration data is derived solely from the Canon (`mammon.json`). It is never duplicated manually.
2.  **Artifacts & State**: 
    *   Operational state must be serializable (JSON/Pickle).
    *   Logs must be structured and timestamped.
    *   Floating-point arithmetic must be handled with financial precision (avoiding standard float drift where possible).
3.  **Series vs. Event**: The system must explicitly distinguish between **Vectorized Processing** (historical analysis) and **Event-Driven Processing** (tick-by-tick live emulation). Data structures must support both without code duplication.

## 3. DEVELOPMENT STANDARDS

1.  **Atomic Evolution**: We build components in isolation.
    *   *Phase 1*: Skeleton (Configuration & State parsers).
    *   *Phase 2*: Organs (Indicator logic implementation).
    *   *Phase 3*: Synapses (Signal interaction and scoring).
    *   *Phase 4*: Consciousness (Execution and risk management).
2.  **Documentation Policy**: The `Context` folder is the living documentation. 
    *   `CONSTITUTION.md`: The rules.
    *   `ARCHITECTURAL_MAP.md`: The structure.
    *   `DECISION_LOG.md`: Why we did what we did.
3.  **Testing Mandate**: A unit of logic is not "complete" until it has a corresponding verification test that proves it behaves like the Pine Script original.

## 4. SAFETY PROTOCOLS

1.  **Fail-Safe Default**: In the event of missing data, ambiguous signals, or unhandled exceptions, the system defaults to **NEUTRAL/NO-ACTION**.
2.  **Simulation First**: All execution defaults to "Paper Mode". Real-money execution requires an intentional, explicit configuration override.

## 5. GLOSSARY OF TERMS

*   **Canon**: The original `mammon.json` source file.
*   **Brain**: The Python-based runtime environment we are building.
*   **Signal**: A raw output from an indicator (e.g., `turtle_long`).
*   **Score**: The weighted integer value derived from signals.
*   **Gate**: A boolean logic check that permits or denies an action (e.g., `Pyramid Gate`).
