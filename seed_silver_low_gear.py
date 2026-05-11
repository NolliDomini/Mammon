"""
Seeds Silver with low active_gear variants so the optimizer's Bayesian
exploiter has signal to explore the V-catching gear range (10–25 bars).

Without these, the gene pool only has gear=36 (Gold) and gear=50 (Silver),
and the Bayesian stage will never converge on shorter-lookback breakouts.

Run while the engine is running — takes effect on the next furnace cycle.

  ! python seed_silver_low_gear.py
"""
import json
import os
import time
import redis

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
KEY = "mammon:hormonal_vault"

# Gear values to seed — spread across the V-catching range.
# The optimizer will backtest and re-score these; 0.50 is just enough
# fitness for GP to consider them during crossover.
GEAR_SEEDS = [10, 15, 20, 25]
SEED_FITNESS = 0.50

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

silver = vault.get("silver", [])
if isinstance(silver, str):
    silver = json.loads(silver)
if not isinstance(silver, list):
    silver = []

print(f"[SEED] Current Silver count: {len(silver)}")
now = time.strftime("%Y-%m-%dT%H:%M:%S")
ts = int(time.time())

new_entries = []
for gear in GEAR_SEEDS:
    p = dict(gold_params)
    p["active_gear"] = gear
    entry = {
        "id": f"silver_low_gear_{gear}_{ts}",
        "params": p,
        "fitness": SEED_FITNESS,
        "regime_id": "GLOBAL",
        "source": "low_gear_seed",
        "minted_at": now,
    }
    silver.append(entry)
    new_entries.append(entry)
    ts += 1

vault["silver"] = silver

payload = {k: json.dumps(v) for k, v in vault.items()}
with r.pipeline() as pipe:
    pipe.delete(KEY)
    pipe.hset(KEY, mapping=payload)
    pipe.execute()

print(f"[SEED] Added {len(new_entries)} low-gear Silver entries:")
for e in new_entries:
    print(f"  gear={e['params']['active_gear']}  id={e['id']}")
print(f"[SEED] Silver pool now: {len(silver)} entries")
print("[SEED] Furnace will exploit these on the next Bayesian cycle.")
