# 🧠 MAMMON NEURAL INTEGRATION (v2.1)
### *The Industrial-Grade Algorithmic Trading Engine*

Mammon is an advanced, modular trading system designed for high-fidelity replication of technical strategies. It replaces monolithic logic with a **"Lobe-Based" Architecture**, mirroring the functional specialization of a biological brain to ensure deterministic execution, vectorized performance, and autonomous evolution.

---

## 📜 I. THE MAMMON CONSTITUTION
*Every byte of code in this repository is governed by these Five Prime Directives:*

1.  **Root Sovereignty**: All operations, data storage, and execution logic occur strictly within the project root.
2.  **Source Fidelity**: The logic mathematically replicates the **Canon** (`mammon.json`). Any deviation for "improvement" is a violation of protocol unless explicitly versioned.
3.  **Modular Cognition**: The system is composed of distinct, testable neurological subsystems (Lobes).
4.  **Fail-Safe Default**: On any ambiguity, data gap, or unhandled exception, the system defaults to **NEUTRAL/NO-ACTION**.
5.  **Simulation First**: Execution defaults to "Paper Mode". Real-money execution requires an intentional, multi-gate configuration override.

---

## 🧩 II. ANATOMY OF THE BRAIN (THE LOBES)

The codebase is partitioned into specialized "Lobes," each owning a specific segment of the decision chain:

### 📡 Thalamus (Ingestion)
*   **Role**: The entry point for the "Electricity" (Market Data).
*   **Ownership**: Source fetching, normalization, and pulse material generation.
*   **Key Component**: `SmartGland` — Transforms raw 1m bars into the canonical Triple-Pulse rhythm.

### ⚙️ Cerebellum & Soul (Orchestration)
*   **Role**: The System Governor and Cadence Authority.
*   **Ownership**: Pulse sequencing, lobe execution order, and shared `BrainFrame` lifecycle.
*   **Key Component**: `Council` — Computes environment confidence (ATR, ADX, Volume, VWAP).

### 📐 Right Hemisphere (Structure)
*   **Role**: The Painter of Technical Breakouts.
*   **Ownership**: Donchian breakouts and level detection.
*   **Key Component**: `Snapping Turtle` — Performs zero-copy writes to `BrainFrame.structure`.

### 🎲 Left Hemisphere (Risk)
*   **Role**: The Painter of Trajectories.
*   **Ownership**: Regime-aware priors (mu, sigma) and survival simulations.
*   **Key Component**: `TurtleMonte` — Runs high-speed, 3-lane vectorized Monte Carlo paths.

### 🌉 Corpus (Synthesis)
*   **Role**: The Bridge between Hemispheres.
*   **Ownership**: Signal blending (`Callosum`) and synchronous internal broadcast (`Optical Tract`).

### ⚖️ Medulla (Policy)
*   **Role**: The Final Command Authority.
*   **Ownership**: Decision gates (`Gatekeeper`) and mode-isolated money ledgers (`TreasuryGland`).

### 🏹 Brain Stem (Execution)
*   **Role**: The Execution Edge.
*   **Ownership**: Broker adapter routing and the **Three-Gate Entry Protocol** (Risk, Valuation, Conviction).

### 🏛️ Hippocampus (Memory)
*   **Role**: The Persistence Authority.
*   **Ownership**: DuckDB Data Lake (`DuckPond`), Async SQL Scribing (`Telepathy`), and Historical Replay (`Fornix`).

### 🏥 Hospital (Calibration)
*   **Role**: The Evolutionary Core.
*   **Ownership**: Parameter discovery and the **Stage A-H Evolutionary Pipeline**.
*   **Key Component**: `Volume Furnace` — Discovers fitness peaks for the current market regime.

### 🧬 Pituitary (Evolution)
*   **Role**: The Master Hormonal Controller.
*   **Ownership**: Genetic parameter optimization (Platinum/Gold/Silver tiers) and Bayesian searches via the `DiamondGland`.

---

## ⚡ III. OPERATIONAL CADENCE: THE TRIPLE-PULSE
Mammon does not "loop"; it **pulses**. Every 5-minute window is divided into three deterministic phases:

1.  **SEED (+2.25m)**: Awareness phase. Lobes ingest data and prime simulations.
2.  **ACTION (+4.5m)**: Execution phase. Intents are armed and the Gatekeeper evaluates policy.
3.  **MINT (Rollover)**: Finalization phase. Trades are fired, state is persisted, and the "Synapse Ticket" is minted to the database.

### Runtime Note (2026-04-19)
Current DRY_RUN operations use a scalper-oriented Gold profile:
- `gold.id = scalp_v1_20260419`
- lowered gate thresholds (`gatekeeper_min_monte=0.30`, `gatekeeper_min_council=0.44`)
- faster structure window (`active_gear=3`)
- conservative execution caps (`max_notional_per_order`, `max_open_positions`, `max_daily_realized_loss`)

Execution authority boundaries remain strict:
- **Gatekeeper + Brain Stem** decide trade eligibility and execution lifecycle.
- **Pineal** is cleanup/finalization only (not a trading gate).
- **Volume Furnace** runs optimizer cadence and promotion telemetry; it does not directly place orders.
- Dashboard close-to-stop behavior is opt-in via `MAMMON_STOP_ON_WINDOW_CLOSE=1` (default `0` for long-running sessions).
- Engine lifecycle forensics are exposed via `GET /api/state` (`last_exit_*`, `last_exception_*`) and `GET /api/engine/lifecycle`.
- Structured diagnostic MNER events are written to `runtime/logs/mner.jsonl` and available at `GET /api/mner/tail`.
- Canonical MNER registry source is `Hippocampus/Context/00_READ_FIRST_CANON/SCHEMA_KEYS/error_registry.json`.

---

## 🛡️ IV. LEGES MAMMON (THE LAWS)
The system operates under strict behavioral invariants:
*   **Inhibitor-First**: The system looks for reasons *not* to trade (Inhibitors) before seeking reasons to trade.
*   **Stale Data Kill**: Any pulse older than 30 seconds is automatically rejected by the `enforce_pulse_gate()`.
*   **Zero-Copy State**: The `BrainFrame` is the single source of truth for a pulse; modules write directly to their assigned slots.
*   **MNER Tracing**: Every failure is logged with a Mammon Neural Error Registry signature: `[LOBE]-[LEVEL]-[PIECE]-[ID]`.

---

## 🛠️ V. INSTALLATION & BOOTSTRAP

### 1. Environment Requirements
*   **Python 3.12+**
*   **Alpaca Markets API** (Trading/Data)
*   **PostgreSQL/TimescaleDB** (Audit Ledger)
*   **DuckDB** (Analytical Data Lake)

### 2. Quick Start
```bash
# 1. Clone and enter root
cd Mammon_Clean

# 2. Setup environment
cp .env.example .env
# Edit .env with your ALPACA_API_KEY and API_SECRET

# 3. Install dependencies
pip install -r requirements.txt

# 4. Execute System Handshake
python boot.py
```

### 3. The Boot Handshake
`boot.py` performs a mandatory 5-point readiness check:
1.  **Environment**: Validates all secrets and host variables.
2.  **Transports**: Verifies connectivity to SQL and analytical gateways.
3.  **Librarian**: Checks database connection pools and schema health.
4.  **Schema Guard**: Runs a "Smoke Check" for any structural drift.
5.  **Engine Integrity**: Verifies that core Phase 1 engines (Spread, Pons, Alloc) are loadable.

---

## 🧪 VI. DEVELOPMENT STANDARDS: THE IRON LOCK-ON
Contributors must adhere to **Protocol v4.0**:
1.  **Single-Target Invariant**: Implement EXACTLY ONE checklist item per turn.
2.  **Triple-Read Handshake**: Read Checklist -> Trace Code -> Execute.
3.  **Schema Fidelity**: Copy field names and types character-for-character from the `mammon.json` Canon.
4.  **Post-Action Handshake**: Every change must be verified by `py_compile` and a checklist update.

---
*Est. 2026 | Built for Precision, Stability, and the Pursuit of the Absolute Fitness Peak.*
