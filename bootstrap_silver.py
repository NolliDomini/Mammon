"""
One-shot Silver bootstrap: seeds the vault with 2 Silver entries so the
Pituitary GP can fire on the very next 4th-MINT cycle.

Run this AFTER restarting the engine (or while it's running — it only touches Redis).
"""
import json
import os
import time
import redis

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
KEY = "mammon:hormonal_vault"

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)
r.ping()

raw = r.hgetall(KEY)
vault = {k: json.loads(v) for k, v in raw.items()}

gold = vault.get("gold", {})
gold_params = gold.get("params", {})
# Use 0.50 as baseline regardless of vault's fitness_snapshot — GP-derived gold may
# have fitness=0.0 if trained on unscaled data, and we don't want that to poison Silver.
BASELINE_FITNESS = 0.50

if not gold_params:
    print("[BOOTSTRAP] No Gold params found — aborting.")
    exit(1)

print(f"[BOOTSTRAP] Gold ID: {gold.get('id')} (using baseline fitness={BASELINE_FITNESS})")

silver_raw = vault.get("silver", [])
if isinstance(silver_raw, str):
    silver_raw = json.loads(silver_raw)
if not isinstance(silver_raw, list):
    silver_raw = []

existing = len(silver_raw)
print(f"[BOOTSTRAP] Clearing {existing} existing Silver entries and seeding fresh.")
silver_raw = []  # Always start clean so stale 0.0-fitness entries don't poison GP.

now = time.strftime("%Y-%m-%dT%H:%M:%S")

# Entry 1: exact Gold clone as the baseline reference
entry1 = {
    "id": f"silver_bootstrap_baseline_{int(time.time())}",
    "params": dict(gold_params),
    "fitness": BASELINE_FITNESS,
    "regime_id": "GLOBAL",
    "source": "bootstrap_baseline",
    "minted_at": now,
}

# Entry 2: slightly lower ADX weight, slightly higher ATR — the regime we already validated works
p2 = dict(gold_params)
p2["council_w_adx"] = max(0.05, float(p2.get("council_w_adx", 0.20)) - 0.05)
p2["council_w_atr"] = min(0.50, float(p2.get("council_w_atr", 0.25)) + 0.05)
entry2 = {
    "id": f"silver_bootstrap_low_adx_{int(time.time())+1}",
    "params": p2,
    "fitness": BASELINE_FITNESS * 0.98,
    "regime_id": "GLOBAL",
    "source": "bootstrap_low_adx",
    "minted_at": now,
}

silver_raw.extend([entry1, entry2])

# Write back — using pipeline for atomicity
payload = {k: json.dumps(v) for k, v in vault.items()}
payload["silver"] = json.dumps(silver_raw)

with r.pipeline() as pipe:
    pipe.delete(KEY)
    pipe.hset(KEY, mapping=payload)
    pipe.execute()

print(f"[BOOTSTRAP] Silver seeded: {len(silver_raw)} entries total.")
print(f"  {entry1['id']} (fitness={entry1['fitness']:.4f})")
print(f"  {entry2['id']} (fitness={entry2['fitness']:.4f})")
print("[BOOTSTRAP] GP will fire on the next 4th-MINT cycle.")
