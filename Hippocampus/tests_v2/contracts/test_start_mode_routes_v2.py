from __future__ import annotations

import dashboard
import Hippocampus.schema_guard as schema_guard
from Hippocampus.tests_v2.harness.dashboard_harness import auth_headers, prep_client


def _join_thread_if_any():
    if dashboard.state.thread is not None:
        dashboard.state.thread.join(timeout=0.2)


def _patch_start_prechecks(monkeypatch):
    monkeypatch.setattr(schema_guard, "run_schema_smoke_check", lambda: {"ok": True})
    monkeypatch.setattr(
        dashboard,
        "_wait_for_alpaca_sync",
        lambda timeout_seconds=12.0, tolerance_seconds=2.5: (
            True,
            {"snapshot": {"remote_ts_utc": "2026-02-21T00:00:00Z"}, "delta_seconds": 0.0},
        ),
    )


def test_api_start_mode_paper(monkeypatch):
    client = prep_client(monkeypatch)
    monkeypatch.setattr(dashboard, "_engine_loop", lambda symbols, is_crypto_map: None)
    _patch_start_prechecks(monkeypatch)

    resp = client.post("/api/start", headers=auth_headers(), json={"symbols": ["BTC/USD"], "mode": "PAPER"})
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["mode"] == "PAPER"
    assert dashboard.state.mode == "PAPER"

    stop = client.post("/api/stop", headers=auth_headers(), json={})
    assert stop.status_code == 200
    _join_thread_if_any()


def test_api_start_mode_backtest(monkeypatch):
    client = prep_client(monkeypatch)
    monkeypatch.setattr(dashboard, "_engine_loop", lambda symbols, is_crypto_map: None)
    _patch_start_prechecks(monkeypatch)

    resp = client.post("/api/start", headers=auth_headers(), json={"symbols": ["BTC/USD"], "mode": "BACKTEST"})
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["mode"] == "BACKTEST"
    assert dashboard.state.mode == "BACKTEST"

    stop = client.post("/api/stop", headers=auth_headers(), json={})
    assert stop.status_code == 200
    _join_thread_if_any()


def test_api_start_mode_live_with_unlock(monkeypatch):
    client = prep_client(monkeypatch)
    monkeypatch.setattr(dashboard, "_engine_loop", lambda symbols, is_crypto_map: None)
    _patch_start_prechecks(monkeypatch)

    arm = client.post("/api/mode/live-unlock/arm", headers=auth_headers(admin=True), json={"reason": "test-live-start"})
    assert arm.status_code == 200
    token = arm.get_json()["token"]

    start = client.post(
        "/api/start",
        headers=auth_headers(),
        json={"symbols": ["BTC/USD"], "mode": "LIVE", "live_unlock_token": token},
    )
    assert start.status_code == 200
    payload = start.get_json()
    assert payload["mode"] == "LIVE"
    assert dashboard.state.mode == "LIVE"

    stop = client.post("/api/stop", headers=auth_headers(), json={})
    assert stop.status_code == 200
    _join_thread_if_any()


def test_live_precheck_requires_armed_kill_switch_without_false_running(monkeypatch):
    client = prep_client(monkeypatch)
    monkeypatch.setattr(dashboard, "_engine_loop", lambda symbols, is_crypto_map: None)
    _patch_start_prechecks(monkeypatch)

    dashboard.state.kill_switch = "DISARMED"
    resp = client.post(
        "/api/start",
        headers=auth_headers(),
        json={"symbols": ["BTC/USD"], "mode": "LIVE", "live_unlock_token": "unused"},
    )
    assert resp.status_code == 423
    payload = resp.get_json()
    assert payload["error"] == "live_requires_armed_kill_switch"
    assert dashboard.state.running is False
    assert dashboard.state.thread is None


def test_stop_bypasses_control_rate_limit(monkeypatch):
    client = prep_client(monkeypatch)
    monkeypatch.setattr(dashboard, "_engine_loop", lambda symbols, is_crypto_map: None)
    _patch_start_prechecks(monkeypatch)
    monkeypatch.setitem(dashboard.RATE_LIMITS, "control", (1, 60))

    start = client.post("/api/start", headers=auth_headers(), json={"symbols": ["BTC/USD"], "mode": "PAPER"})
    assert start.status_code == 200

    limited = client.post("/api/start", headers=auth_headers(), json={"symbols": ["ETH/USD"], "mode": "PAPER"})
    assert limited.status_code == 429
    assert limited.get_json()["error"] == "rate_limited"

    stop = client.post("/api/stop", headers=auth_headers(), json={})
    assert stop.status_code == 200
    _join_thread_if_any()
