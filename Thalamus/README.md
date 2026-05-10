# Thalamus
### *The Ingestion Lobe*

**Role**: Entry point for market data. Fetches, normalizes, and resamples 1-minute bars into the Triple-Pulse rhythm consumed by Soul.

## Ownership

- Fetches raw 1m bars from Alpaca (historical or live stream)
- Normalizes all data to the canonical OHLCV schema
- Drives SmartGland to resample 1m bars into 5m Triple-Pulse tuples
- Passes pulse DataFrames to OpticalTract via `spray()`

## Anti-Ownership

- Does not calculate indicators or environment confidence
- Does not dictate pulse cadence authority (Soul owns sequencing)
- Does not authorize execution or interact with broker adapters

## SmartGland (`Thalamus/gland/service.py`)

Resamples raw 1m bars into 5m aggregates and emits three pulse types per window:

| Pulse | Timing | Trigger |
|---|---|---|
| SEED | ≥ 2.25 min elapsed | first 1m bar whose close-time ≥ 2.25m from window open |
| ACTION | ≥ 4.5 min elapsed | first 1m bar whose close-time ≥ 4.5m from window open |
| MINT | window boundary crossed | first bar of the *next* 5m window, or clock-aligned at exact boundary in live mode |

Key parameters:
- `window_minutes = 5`
- `context_size = 200` — rolling buffer of finalized 5m bars attached to every pulse DataFrame

Clock-aligned MINT: in live mode (`_live_mode=True`) the gland checks `now_utc >= window_end` on each ingest call and fires MINT immediately at the boundary rather than waiting for the first bar of the next window (~1 min late).

`_agg_window()` aggregates accumulated 1m bars into a single OHLCV row: open=first, high=max, low=min, close=last, volume=sum.

`_wrap_with_context()` prepends the rolling `context_df` to the current aggregate so downstream lobes always receive a full history window.

## Thalamus relay (`Thalamus/relay/service.py`)

Main class: `Thalamus`

**`warmup_context(symbols, is_crypto)`**
Pulls 1000 minutes of 1m historical bars from Alpaca before the live stream connects. Feeds them through `gland.ingest()` to populate `context_df` with ~200 5m bars. After warmup, resets `raw_list=[]`, `current_window_start=None`, `_live_mode=True` so the live stream opens a clean window.

**`drip_pulse(raw_df)`**
Main live entry point. Called per incoming 1m bar. Normalizes the bar, optionally saves to DuckPond, feeds to `gland.ingest()`, and calls `optical_tract.spray()` for each pulse emitted.

**`pulse(symbols, ...)`**
Historical fetch: pulls a range of bars from Alpaca or the SQLite database and sprays them.

**`get_latest_bar(symbol, is_crypto, retries=3)`**
Fetches the single latest 1m bar. Retries up to 3 times with linear backoff (1.5s, 3s). Rebuilds the Alpaca client on each retry to flush exhausted connection pools.

## Normalization Contract

`CANONICAL_COLS = ["open", "high", "low", "close", "volume", "symbol"]`

`_normalize_bars()` enforces:
- DatetimeIndex or `ts`/`timestamp` column required; coerced to UTC
- All OHLCV fields numeric; NaN → `INGEST_NUMERIC_INVALID`
- `volume >= 0` enforced
- `symbol` non-blank string
- Duplicate timestamps: last row kept
- Output always sorted ascending by timestamp

Any invariant violation raises `IngestionContractError(code, message)`.
