# Deep Dive: WardManager — Boot-Time Redis Hygiene

## 1. Purpose & Role
WardManager is a **single-shot boot-time janitor**. Its only job is to purge stale BrainFrame keys from Redis when the Soul Orchestrator starts, preventing state from a previous session contaminating the new one.

It is 28 lines of code. Its importance is disproportionate to its size.

---

## 2. When Does It Run?

Once — at Soul Orchestrator `__init__()`, before any vault load or lobe instantiation:

```python
# V3.1 BRAINTICK: Clean ward on boot
WardManager().janitor_sweep()
```

It is not called again during the session. It is instantiated as a throw-away object — no persistent reference is kept.

---

## 3. What It Deletes

```
janitor_sweep()
  → redis_conn.keys("mammon:brain_frame:*")
  → if any keys found: redis_conn.delete(*keys)
```

BrainFrame keys in Redis follow the pattern:
```
mammon:brain_frame:{MODE}:{SYMBOL}
e.g. mammon:brain_frame:LIVE:AAPL
```

These are written by BrainFrame's Redis persistence methods (in `service-TheBrain.py`) during live operation. Without WardManager, a BrainFrame snapshot from a prior session with stale `tier1_signal`, `monte_score`, or `approved` state could persist in Redis and be read by the newly booted Soul before the first real pulse overwrites it.

---

## 4. The Risk It Prevents

The live Soul pipeline reads BrainFrame state from Redis as a hot cache. On restart:

- If a prior session left `tier1_signal=1` and `approved=1` in Redis for a symbol
- And the new session reads that state before the first MINT pulse
- Brain Stem could read a stale ARM signal and misfire

WardManager's sweep ensures Redis is blank-slate at boot — all lobes start from cold defaults.

---

## 5. Dependencies

| Dependency | Direction | Purpose |
|---|---|---|
| `MultiTransportLibrarian` | outbound | `get_redis_connection()` |
| Redis | write | `KEYS` scan + bulk `DEL` |
| `Soul.__init__` | inbound | Single call site |

---

## 6. Non-Obvious Behavior

- **`redis.keys("mammon:brain_frame:*")` is O(N) on all Redis keys.** In a Redis instance shared with other systems or with many namespaces, this scans every key in the database. On a large Redis instance this is a blocking operation that can stall startup by hundreds of milliseconds.
- **Exception is silently swallowed.** If Redis is unavailable at boot (network issue, Redis not started), `janitor_sweep` prints a warning and returns. Soul proceeds without the sweep — if stale keys exist from a prior session, they remain. This is probably the right trade-off (don't block boot), but the stale-state risk is real and unlogged beyond the warning.
- **No TTL is set after deletion** — the delete is permanent. `service-TheBrain.py` shows Pineal also touches BrainFrame keys to set TTLs on keys with no expiry. WardManager's blanket delete removes this need at boot.
- **Deletes ALL BrainFrame keys for ALL symbols and modes.** There is no per-symbol or per-mode scoping. If multiple Soul instances share a Redis namespace (e.g., a live instance and a paper-trading instance running concurrently), one Soul's boot will wipe the other's active BrainFrames mid-session.
- **Instantiated as throw-away.** `WardManager()` is constructed and immediately used — no reference stored on `self`. The object is GC'd after `__init__` returns. This is fine since `janitor_sweep` is stateless, but means there is no way to call it again without constructing a new instance.

---

## 7. Open Questions / Risks

- **Shared Redis namespace.** If any future multi-symbol or multi-instance deployment shares a Redis host, WardManager's wildcard delete becomes a footgun. A namespace scoping convention (e.g., per-instance prefix) would be needed before scaling horizontally.
- **No confirmation that the sweep succeeded.** The print log says how many keys were deleted, but there is no assertion that the keys are actually gone afterward. A Redis cluster with partial deletes would report success while leaving stale fragments.
- **Boot ordering dependency.** If Redis is slow to come up (containerized deployment), `janitor_sweep` may fail silently and Soul proceeds with potentially stale state. A startup health check for Redis connectivity before Soul init would close this gap.
