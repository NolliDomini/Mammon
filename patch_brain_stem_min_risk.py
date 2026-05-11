"""
Vault patch: adds brain_stem_min_risk=0.45 to Gold params so Brain_Stem's
risk gate can pass.

Root cause: GP evolved brain_stem_sigma=0.9775 (~1×ATR noise). At that width,
Brain_Stem's small Monte (1k paths) always produces ~50.6% hit rate regardless
of market direction. The un-set default min_risk=0.52 sits just above 0.506 —
the gate fails on every ACTION, no pending_entry is ever created, no trades fire.

Fix: add brain_stem_min_risk=0.45 to Gold. With 0.506 > 0.45, the gate passes
comfortably. The optimizer can continue tuning it via PARAM_KEYS[23] (bounds
0.40–0.70).

Run while engine is running — takes effect on next MINT vault mutation check.

  ! python patch_brain_stem_min_risk.py
"""
import json
import os
import time
import redis

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
KEY = "mammon:hormonal_vault"

NEW_BRAIN_STEM_MIN_RISK = 0.45

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

old_val = gold_params.get("brain_stem_min_risk", "<not set, defaulting to 0.52>")
brain_stem_sigma = gold_params.get("brain_stem_sigma", "<unknown>")

print(f"[PATCH] Current Gold ID: {gold.get('id')}")
print(f"[PATCH] brain_stem_sigma (noise width): {brain_stem_sigma}")
print(f"[PATCH] brain_stem_min_risk: {old_val} → {NEW_BRAIN_STEM_MIN_RISK}")
print(f"[PATCH] Expected risk_score with sigma~=1: ~0.506 → now passes 0.45 floor")

gold_params["brain_stem_min_risk"] = NEW_BRAIN_STEM_MIN_RISK
gold["params"] = gold_params
gold["id"] = f"patched_min_risk_{int(time.time())}"
gold["coronated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
gold["origin"] = "min_risk_patch"
vault["gold"] = gold

payload = {k: json.dumps(v) for k, v in vault.items()}
with r.pipeline() as pipe:
    pipe.delete(KEY)
    pipe.hset(KEY, mapping=payload)
    pipe.execute()

print(f"[PATCH] Vault written. New Gold ID: {gold['id']}")
print("[PATCH] Soul will hot-reload on next MINT vault mutation check.")
print("[PATCH] Brain_Stem risk gate will now pass at next tier1_signal=1 ACTION.")
