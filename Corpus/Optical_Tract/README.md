# Optical Tract

## Purpose
Optical Tract is a lightweight broadcast bus for pulse dataframes.

Primary runtime file:
- `Corpus/Optical_Tract/spray.py`

## Contract
Publisher-side:
- caller invokes `spray(data: pd.DataFrame)`

Subscriber-side:
- each subscriber must implement `on_data_received(data)`

Current behavior:
- broadcasts payload to all subscribers in registration order
- does not transform payload
- returns structured delivery telemetry (`subscriber_count`, `delivered_count`, `failed_count`, `errors`)
- delivery policy is synchronous with a 50ms soft budget per spray cycle (tracked in telemetry, not hard-kill enforced)

## Legacy Compatibility
Some legacy subscribers use:
- `on_data_received(pulse_type, data)`

Use explicit adapter:
- `Corpus.Optical_Tract.adapters.LegacyTwoArgSubscriberAdapter`

Transport no longer guesses signatures at runtime.

## Operational Invariants
- no silent mutation of input dataframe
- failures in one subscriber do not stop fan-out to other subscribers
- subscriber registration should be explicit and observable
- latency impact is observable via `total_delivery_ms` and `max_subscriber_ms`

## Testing Expectations
Minimum coverage:
- subscriber registration
- delivery fan-out to multiple subscribers
- error visibility when a subscriber has incompatible signature
