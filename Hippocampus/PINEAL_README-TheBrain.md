# Pineal

Status: Active runtime module (updated 2026-02-27)

Purpose:
- Performs retention and hygiene jobs across persistence layers.

Primary entrypoint:
- `Hippocampus/pineal/service.py`

Notes:
- Time cutoffs should use datetime-aware timestamp handling for DB deletes.
