import time

import dashboard
from Hippocampus.tests_v2.harness.dashboard_harness import auth_headers, prep_client


def _dummy_engine_loop(symbols, is_crypto_map):
    # Keep loop alive briefly until stop flips state.running = False.
    while dashboard.state.running:
        time.sleep(0.002)


def test_rapid_start_stop_cycles_no_orphan_running(monkeypatch):
    client = prep_client(monkeypatch)
    monkeypatch.setattr(dashboard, "_engine_loop", _dummy_engine_loop)
    monkeypatch.setitem(dashboard.RATE_LIMITS, "control", (1000, 60))

    for _ in range(20):
        r_start = client.post("/api/start", headers=auth_headers(), json={"symbols": ["BTC/USD"]})
        assert r_start.status_code in {200, 400}
        r_stop = client.post("/api/stop", headers=auth_headers(), json={})
        assert r_stop.status_code == 200
        assert dashboard.state.running is False
        if dashboard.state.thread is not None:
            dashboard.state.thread.join(timeout=0.1)

    assert dashboard.state.running is False
