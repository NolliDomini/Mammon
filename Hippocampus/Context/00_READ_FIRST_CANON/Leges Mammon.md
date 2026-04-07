# Leges Mammon
## Engine Law (What Does What)
Date: 2026-02-20
Status: Active runtime law

---

## I. Mission Law
Mammon is a pulse-driven decision engine.

Its only job is to:
1. Convert market data into structured risk-aware intent.
2. Authorize or inhibit intent under strict policy.
3. Execute approved intent under mode and safety gates.
4. Persist every critical state transition for audit and learning.

---

## II. Pulse Law
The engine runs on canonical pulse cadence from SmartGland:
- `SEED` at `+2.25m`
- `ACTION` at `+4.5m`
- `MINT` on 5m rollover

Operational effects:
- `SEED`: readiness and non-execution cycle work.
- `ACTION`: only pulse where approval-to-fire path may arm.
- `MINT`: lifecycle close/finalization and state minting.

No lobe may act outside pulse contract.

---

## III. Signal and Context Law
### Price-Structure Function
Right Hemisphere produces structure signals from price geometry.

### Environment Function
Council produces market-context confidence and indicator state.

### Risk Function
Left Hemisphere produces Monte-based survival/risk state.

### Synthesis Function
Callosum converts structure + risk into `tier_score` for policy.

---

## IV. Policy and Execution Law
### Policy Function
Gatekeeper is final approval authority.

It writes command intent using:
- `tier_score`
- environment confidence
- pulse legality
- configured thresholds

### Execution Function
Brain Stem executes/cancels intent lifecycle under:
- policy approval
- runtime mode
- trade-enable gate
- execution safety checks

Execution must end in explicit terminal state:
- `FILLED`
- `CANCELED`
- `REJECTED`
- `TIMEOUT`

### Anti-Pyramid Law
Pyramid doctrine is removed from active engine law.

Active engine law is single-intent lifecycle discipline under policy gates, not additive pyramid stacking doctrine.

---

## V. Memory and Replay Law
### Persistence Function
Hippocampus owns memory gateways and audit writes.

Required rules:
- no direct ad-hoc DB writers outside Archivist gateways
- schema and writes remain mode/audit safe

### Synapse Mint Function
Amygdala mints synapse tickets on `MINT` only.

### Historical Replay Function
Fornix replays history through canonical runtime contracts, not alternate strategy logic.

### Memory Hygiene Function
Pineal owns archive/finalize/wipe policy for replay staging and retention cleanup.

---

## VI. Mode and Safety Law
Execution legality is mode-governed.

Required:
- runtime mode must propagate consistently to policy/execution/ledger paths
- illegal transitions and lock states must inhibit fire
- kill-switch and operator hard gates override fire eligibility

---

## VII. Optimization Law
Optimizer systems may search parameter space, but cannot bypass runtime policy/execution contracts.

Promotion hierarchy must remain auditable:
- candidate exploration
- ranking and promotion
- controlled runtime adoption

---

## VIII. Tier Appendix (At End by Law)
### Tier 1 (Active)
- Snapping Turtle structure signal path in production flow.

### Other Tiers (Deferred/Conditional)
- Any additional tier logic is subordinate to the same pulse, policy, mode, and persistence laws.
- No tier has independent authority to bypass Gatekeeper, mode gates, or execution safety.
- Activation of any non-Tier-1 path must be explicitly governed by current checklist and tests.

---

## IX. Canon References
- `ARCHITECTURE_OWNERSHIP.md`
- `Hippocampus/Plans/MASTER_MAMMON_CHECKLIST.md`
- `Hippocampus/README.md`
