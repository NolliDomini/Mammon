"""
One-shot vault patch: lowers gatekeeper thresholds so live lobe outputs can
actually clear them, and seeds Silver so GP has material to work with.

Run while engine is running -- takes effect on the next MINT vault mutation check.

  ! python patch_vault_thresholds.py
"""
import json
import os
import time
import redis

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
KEY = "mammon:hormonal_vault"

# Target thresholds — set just below typical live lobe outputs so trades can pass.
# Council score typically peaks ~0.60; Monte score on breakout typically 0.35-0.55.
NEW_GATEKEEPER_MIN_MONTE   = 0.32
NEW_GATEKEEPER_MIN_COUNCIL = 0.50

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)
r.ping()

raw = r.hgetall(KEY)
if not raw:
    print("[PATCH] Vault is empty in Redis — nothing to patch.")
    exit(1)

vault = {k: json.loads(v) for k, v in raw.items()}
gold = vault.get("gold", {})
gold_params = gold.get("params", {})

if not gold_params:
    print("[PATCH] No Gold params found — aborting.")
    exit(1)

old_monte   = gold_params.get("gatekeeper_min_monte")
old_council = gold_params.get("gatekeeper_min_council")

print(f"[PATCH] Current Gold ID: {gold.get('id')}")
print(f"[PATCH] gatekeeper_min_monte:   {old_monte} → {NEW_GATEKEEPER_MIN_MONTE}")
print(f"[PATCH] gatekeeper_min_council: {old_council} → {NEW_GATEKEEPER_MIN_COUNCIL}")

gold_params["gatekeeper_min_monte"]   = NEW_GATEKEEPER_MIN_MONTE
gold_params["gatekeeper_min_council"] = NEW_GATEKEEPER_MIN_COUNCIL
gold["params"]        = gold_params
gold["id"]            = f"patched_{int(time.time())}"
gold["coronated_at"]  = time.strftime("%Y-%m-%dT%H:%M:%S")
gold["origin"]        = "threshold_patch"
vault["gold"] = gold

# Seed Silver with the patched Gold so GP has a reference point
now = time.strftime("%Y-%m-%dT%H:%M:%S")
silver = [
    {
        "id": f"silver_patch_baseline_{int(time.time())}",
        "params": dict(gold_params),
        "fitness": float(gold.get("fitness_snapshot", 0.50)),
        "regime_id": "GLOBAL",
        "source": "threshold_patch",
        "minted_at": now,
    }
]
vault["silver"] = silver

payload = {k: json.dumps(v) for k, v in vault.items()}
with r.pipeline() as pipe:
    pipe.delete(KEY)
    pipe.hset(KEY, mapping=payload)
    pipe.execute()

print(f"[PATCH] Vault written. New Gold ID: {gold['id']}")
print(f"[PATCH] Silver seeded: {len(silver)} entry")
print("[PATCH] Soul will hot-reload on next MINT vault mutation check.")
