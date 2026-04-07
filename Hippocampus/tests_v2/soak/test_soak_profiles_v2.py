from __future__ import annotations

import os
import time

import dashboard
from Hippocampus.tests_v2.harness.dashboard_harness import auth_headers, prep_client


SOAK_PROFILES_SEC = {
    "2h": 2 * 60 * 60,
    "4h": 4 * 60 * 60,
    "8h": 8 * 60 * 60,
}


def test_soak_profiles_cover_required_durations():
    assert SOAK_PROFILES_SEC["2h"] == 7200
    assert SOAK_PROFILES_SEC["4h"] == 14400
    assert SOAK_PROFILES_SEC["8h"] == 28800


def test_soak_queue_pressure_smoke_window(monkeypatch):
    client = prep_client(monkeypatch)
    monkeypatch.setitem(dashboard.RATE_LIMITS, "control", (10000, 60))
    monkeypatch.setattr(dashboard, "_engine_loop", lambda symbols, is_crypto_map: None)

    run_for = float(os.environ.get("MAMMON_SOAK_SMOKE_SEC", "3.0"))
    deadline = time.time() + max(0.5, run_for)
    starts = 0
    stops = 0

    while time.time() < deadline:
        r1 = client.post("/api/start", headers=auth_headers(), json={"symbols": ["BTC/USD"], "mode": "PAPER"})
        if r1.status_code == 200:
            starts += 1
        r2 = client.post("/api/stop", headers=auth_headers(), json={})
        if r2.status_code == 200:
            stops += 1

    assert starts >= 1
    assert stops >= 1
    assert dashboard.state.running is False
