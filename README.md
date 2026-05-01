# Mammon — Neural-Inspired Algorithmic Trading Engine

Python engine modeled on brain anatomy. Trades crypto via Alpaca using a 5-minute bar cycle (SEED → ACTION → MINT) with a self-optimizing genetic parameter system.

## Architecture

Each "lobe" is a Python service that reads/writes a shared `BrainFrame` object. The `Orchestrator` (Soul) drives all lobes each pulse.

```
Thalamus (ingest) → OpticalTract (fan-out) → Orchestrator
  → Right_Hemisphere (Donchian breakout / tier1_signal)
  → Council (ATR + ADX + Spread → environment confidence)
  → PonsExecutionCost (friction estimate)
  → Left_Hemisphere (TurtleMonte → monte_score)
  → QuantizedGeometricWalk (regime seed)
  → Corpus/Callosum (blend → tier_score)
  → Medulla/Gatekeeper (policy approval)
  → Medulla/AllocationGland (qty sizing)
  → Brain_Stem/Trigger (ARM at ACTION, FIRE at MINT)
  → Hippocampus/Amygdala (persist synapse_mint)
  → Hippocampus/Crawler (GP param evolution)
  → Hospital/VolumeFurnace (inline optimizer)
```

## Docker Stack

| Service | Port | Description |
|---|---|---|
| dashboard | 5000 | Flask API + web UI |
| mcp | 5001 | MCP sidecar (Claude tool access) |
| redis | 6379 | Hot vault + BrainFrame state |
| timescaledb | 5432 | Time-series money tables |

## Key Databases

| Alias | Path | Contents |
|---|---|---|
| synapse | `Hippocampus/Archivist/Ecosystem_Synapse.db` | `synapse_mint` pulse tape |
| money | `runtime/.tmp_test_local/compat_librarian.db` | Orders, fills, PnL |
| params | `Hippocampus/data/ecosystem_params.duckdb` | Param lineage |
| fornix | `Hospital/Memory_care/duck.db` | Market tape + batch optimizer |

## Entry Points

- `dashboard.py` — Flask web server, engine lifecycle (`/api/start`, `/api/stop`)
- `boot.py` — Schema validation and DB initialization (run once on first deploy)

## Files

- `dashboard.py` — Flask API, engine thread, UI serving
- `boot.py` — Schema guard and DB bootstrapper
- `Hippocampus/hormonal_vault.json` — Runtime GP parameter vault (not committed)
