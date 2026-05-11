"""
Seeds Silver with bidirectional exploration entries across all 24 optimizer
dimensions so the Bayesian surrogate (Stage G) has gradient signal in both
directions for every parameter.

For each of the 24 PARAM_KEYS we add two Silver entries:
  - one with that param moved halfway toward its MIN bound
  - one with that param moved halfway toward its MAX bound
All other params held at Gold values. Result: 48 Silver entries covering the
full search space directionally.

Run while the engine is running — vault write is atomic via Redis pipeline.

  ! python seed_silver_exploration.py
"""
import json
import os
import time
import numpy as np
import redis

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
KEY = "mammon:hormonal_vault"

# ── 24-D definition (must match bounds/service.py exactly) ────────────
PARAM_KEYS = [
    "active_gear",
    "monte_noise_scalar",
    "monte_w_worst", "monte_w_neutral", "monte_w_best",
    "council_w_atr", "council_w_adx", "council_w_vol", "council_w_vwap",
    "gatekeeper_min_monte", "gatekeeper_min_council",
    "callosum_w_monte", "callosum_w_right",
    "brain_stem_w_turtle", "brain_stem_w_council",
    "brain_stem_sigma", "brain_stem_bias",
    "brain_stem_entry_max_z",
    "brain_stem_mean_dev_cancel_sigma",
    "brain_stem_stale_price_cancel_bps",
    "brain_stem_mean_rev_target_sigma",
    "stop_loss_mult", "breakeven_mult",
    "brain_stem_min_risk",
]

MINS = np.array([
    5,    0.05,
    0.0, 0.0, 0.0,
    0.0, 0.0, 0.0, 0.0,
    0.1, 0.1,
    0.0, 0.0,
    0.0, 0.0,
    0.05, 0.0,
    0.2, 0.0, 0.0, 0.0,
    1.5, 1.0,
    0.40,
], dtype=float)

MAXS = np.array([
    60,   2.0,
    1.0, 1.0, 1.0,
    1.0, 1.0, 1.0, 1.0,
    0.9, 0.9,
    1.0, 1.0,
    1.0, 1.0,
    1.0, 0.5,
    3.0, 5.0, 250.0, 5.0,
    12.0, 10.0,
    0.70,
], dtype=float)

# Default values for params that may be missing from Gold
DEFAULTS = {k: float((lo + hi) / 2) for k, lo, hi in zip(PARAM_KEYS, MINS, MAXS)}
DEFAULTS["brain_stem_min_risk"] = 0.52


def normalize_weights(row: np.ndarray) -> np.ndarray:
    s = row.copy()
    for sl in [slice(2, 5), slice(5, 9), slice(11, 13), slice(13, 15)]:
        total = np.sum(s[sl]) + 1e-9
        s[sl] /= total
    return s


def row_to_params(row: np.ndarray) -> dict:
    return {k: float(v) for k, v in zip(PARAM_KEYS, row.tolist())}


# ── Connect & load vault ───────────────────────────────────────────────
r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)
r.ping()

raw = r.hgetall(KEY)
if not raw:
    print("[SEED] Vault empty — aborting.")
    exit(1)

vault = {k: json.loads(v) for k, v in raw.items()}
gold_params = vault.get("gold", {}).get("params", {})
if not gold_params:
    print("[SEED] No Gold params — aborting.")
    exit(1)

# Build Gold as a 24-D numpy row, filling missing keys from DEFAULTS
gold_row = np.array([
    float(gold_params.get(k, DEFAULTS[k])) for k in PARAM_KEYS
], dtype=float)
gold_row = normalize_weights(gold_row)

print(f"[SEED] Gold basis: {dict(zip(PARAM_KEYS, gold_row.tolist()))}")
print()

silver = vault.get("silver", [])
if isinstance(silver, str):
    silver = json.loads(silver)
if not isinstance(silver, list):
    silver = []

existing = len(silver)
print(f"[SEED] Existing Silver entries: {existing}")

# ── Generate 2 entries per dimension ──────────────────────────────────
now = time.strftime("%Y-%m-%dT%H:%M:%S")
ts = int(time.time())
new_entries = []

for i, key in enumerate(PARAM_KEYS):
    gold_val = gold_row[i]
    lo, hi = MINS[i], MAXS[i]

    # Direction: toward min (midpoint between gold and min bound)
    val_lo = (gold_val + lo) / 2.0
    row_lo = gold_row.copy()
    row_lo[i] = val_lo
    row_lo = normalize_weights(row_lo)
    new_entries.append({
        "id": f"seed_explore_{key}_lo_{ts}",
        "params": row_to_params(row_lo),
        "fitness": 0.50,
        "regime_id": "GLOBAL",
        "source": "bidirectional_seed",
        "minted_at": now,
        "_dim": i,
        "_dir": "lo",
    })
    ts += 1

    # Direction: toward max (midpoint between gold and max bound)
    val_hi = (gold_val + hi) / 2.0
    row_hi = gold_row.copy()
    row_hi[i] = val_hi
    row_hi = normalize_weights(row_hi)
    new_entries.append({
        "id": f"seed_explore_{key}_hi_{ts}",
        "params": row_to_params(row_hi),
        "fitness": 0.50,
        "regime_id": "GLOBAL",
        "source": "bidirectional_seed",
        "minted_at": now,
        "_dim": i,
        "_dir": "hi",
    })
    ts += 1

    gold_v = gold_row[i]
    print(f"  [{i:02d}] {key:<38}  gold={gold_v:.4f}  lo_seed={val_lo:.4f}  hi_seed={val_hi:.4f}")

# Strip internal book-keeping fields before writing
for e in new_entries:
    e.pop("_dim", None)
    e.pop("_dir", None)

silver.extend(new_entries)
vault["silver"] = silver

payload = {k: json.dumps(v) for k, v in vault.items()}
with r.pipeline() as pipe:
    pipe.delete(KEY)
    pipe.hset(KEY, mapping=payload)
    pipe.execute()

print()
print(f"[SEED] Added {len(new_entries)} entries (2 per dimension × 24 dims).")
print(f"[SEED] Silver pool now: {len(silver)} entries.")
print("[SEED] Bayesian stage (Stage G) will use these on the next furnace cycle.")
