# Deep Dive: Corpus Callosum + Gatekeeper — Signal Synthesis & Final Approval

These two modules form the last two steps before Brain Stem. Callosum blends the signal into a single score; Gatekeeper makes the binary go/no-go decision and sets sizing.

---

## Corpus Callosum

### Purpose
Synthesizes `monte_score` (Left Hemisphere) and `tier1_signal` (Right Hemisphere) into a single `tier_score` written to `frame.risk`.

### Formula
```
raw  = (monte_score × w_monte) + (tier1_signal × w_right)
tier_score = clamp(raw, 0.0, 1.0)
```

**Default weights** (from Gold params):
| Weight | Default | Effect |
|---|---|---|
| `callosum_w_monte` | 1.0 | Monte score full weight |
| `callosum_w_right` | 0.0 | Tier1 signal **currently zero** |

At defaults, `tier_score = monte_score`. Callosum is a passthrough unless `callosum_w_right > 0`.

### Output
Writes `frame.risk.tier_score`. Returns a `TierPacket` (tier_id=1, signal_type="AMBUSH").

### Non-Obvious
- `callosum_w_adx` and `callosum_w_weak` exist in config and are logged to `callosum_mint` table but **not used in the formula** — vestigial from an earlier design.
- The `Cerebellum/gatekeeper/service.py` is a one-liner re-export of `Medulla.gatekeeper` — Gatekeeper actually lives in Medulla.

---

## Gatekeeper

### Purpose
The **policy authority**. Makes the final binary `ready_to_fire` decision, writes `frame.command`, returns a `FiringSolution`. Only runs on ACTION pulse.

### Decision Logic
```
tier_pass   = tier_score  > gatekeeper_min_monte   (default 0.30 in live profile)
council_pass = council_score > gatekeeper_min_council (default 0.44 in live profile)

if tier_pass AND council_pass → APPROVED
elif not tier_pass            → INHIBIT_THRESHOLD_TIER
else                          → INHIBIT_THRESHOLD_COUNCIL
```

Any of these short-circuits to INHIBIT before threshold check:
- Non-ACTION pulse → `INHIBIT_PULSE_ILLEGAL`
- Invalid mode → `INHIBIT_MODE_GATE`
- NaN inputs → `INHIBIT_SAFETY_GATE`

### Sizing
```python
sizing_mult = gatekeeper_sizing_mult  (from config, default 1.0, clamped 0–1)
           = 0.0 if not approved
```

Sizing is flat — confidence doesn't scale the size. `final_confidence = (tier_score + council_score) / 2` is recorded but doesn't affect sizing.

### Writes to `frame.command`
| Field | Value |
|---|---|
| `ready_to_fire` | `True` if approved |
| `approved` | `1` or `0` |
| `reason` | Decision string |
| `final_confidence` | `(tier + council) / 2` |
| `sizing_mult` | Flat config value or 0 |

### Threshold Mode-Keying
Thresholds can be mode-specific: `gatekeeper_min_monte_paper`, `gatekeeper_min_monte_live`, etc. Falls back to base key, then default.

---

## Full ACTION Decision Chain (summary)

```
Right Hemisphere  → frame.structure.tier1_signal (0 or 1)
Left Hemisphere   → frame.risk.monte_score (0–1)
Corpus Callosum   → frame.risk.tier_score = monte_score × 1.0  (at defaults)
Gatekeeper        → frame.command.ready_to_fire
                    using: tier_score > 0.30 AND council_score > 0.44
Brain Stem Gate 1 → risk_score > 0.30    (own Small Monte, biased by prior)
Brain Stem Gate 2 → entry_z <= 0.8       (own Valuation Monte)
Brain Stem Gate 3 → prior > 0.5          (blended conviction)
Brain Stem Gate 4 → council >= 0.44      (fail-safe re-check)
```

The system has **dual independent gating** — Gatekeeper approves on threshold, then Brain Stem runs its own Monte on top.

---

## Open Questions / Risks

- **Callosum is effectively a passthrough** at `w_right=0` — tier1_signal contributes nothing to tier_score. The breakout signal from Right Hemisphere only gates whether the ACTION path runs at all (via Soul), not the score quality.
- **Flat sizing** means position size never scales with conviction — a 0.31 tier_score and a 0.99 tier_score produce the same order size.
- **Gatekeeper thresholds are duplicated in Brain Stem config** (`gatekeeper_min_monte`, `gatekeeper_min_council`) — both lobes read the same Gold param keys. If they diverge, the system can approve at Gatekeeper and reject at Brain Stem (or vice versa).
- **`evaluate()` legacy API** remains on Gatekeeper — different threshold logic from `decide()`. If anything still calls `evaluate()`, it uses a different approval path with potentially different outcomes.

---

## Deep Investigation Findings

### Finding 1: Callosum Dead Weights — Two of Four Optimization Dimensions Are Inert

`Corpus/callosum/service.py` — `_read_weights()` returns only two values:
```python
w_monte = config.get("callosum_w_monte", 1.0)
w_right = config.get("callosum_w_right", 0.0)
return w_monte, w_right
```

The blend formula uses only these two:
```python
raw_score = (monte_score * w_monte) + (signal_strength * w_right)
```

`callosum_w_adx` and `callosum_w_weak` appear **only** in `_log_score()`, the DB audit insert:
```python
self.librarian.write("callosum_mint", {
    ...
    "adx_val":     0.5,   # hardcoded — not from frame
    "weakness_val": 0.5,  # hardcoded — not from frame
    "w_adx":       config.get("callosum_w_adx", 0.0),
    "w_weak":      config.get("callosum_w_weak", 0.0),
})
```

The Gold params include `callosum_w_adx` and `callosum_w_weak`. Pituitary's GP optimizer spends two PARAM_KEYS dimensions evolving these weights. They are logged to the DB with hardcoded `0.5` input values and have zero effect on the blend. The optimizer is tuning parameters that do nothing.

---

### Finding 2: `confidence_score` Ghost Attribute on `CommandSlot`

`Medulla/gatekeeper/service.py` line 111 sets:
```python
frame.command.confidence_score = final_conf
```

`CommandSlot` (the BrainFrame command dataclass) has no `confidence_score` field. Python adds this as a dynamic instance attribute — no error is raised. Nothing downstream reads `frame.command.confidence_score`. The value is a duplicate of `final_confidence` (which IS a CommandSlot field and IS read by some paths). The ghost attribute is written every ACTION pulse and immediately orphaned.

---

### Finding 3: `gatekeeper_min_monte` Is Checked Twice Against Different Simulations

The threshold `gatekeeper_min_monte` (default `0.30`) is applied independently at two gates:

| Gate | Where | Simulation | Input |
|---|---|---|---|
| Gatekeeper `decide()` | `Medulla/gatekeeper/service.py` | TurtleMonte 30k-path output (`frame.risk.tier_score`) | `tier_score > gatekeeper_min_monte` |
| Brain Stem `_run_risk_gate()` | `Brain_Stem/trigger/service.py` | Own 1k-path mini Monte (prior-biased) | `risk_score >= gatekeeper_min_monte` |

Same param key, different Monte Carlo simulations. Brain Stem's Risk Gate biases the noise distribution using prior conviction (`brain_stem_bias`), producing a directionally tilted score. A candidate can pass Gatekeeper's unbiased check and fail Brain Stem's conviction-adjusted check, or vice versa. The dual-gate design is intentional (second opinion) but the threshold conflation creates an implicit dependency between two independent simulations.
