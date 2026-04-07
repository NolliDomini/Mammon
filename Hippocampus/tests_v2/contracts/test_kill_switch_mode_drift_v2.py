from __future__ import annotations

import dashboard
from Hippocampus.tests_v2.harness.dashboard_harness import auth_headers, prep_client


class _ModeAwareStub:
    def __init__(self):
        self.modes = []

    def set_execution_mode(self, mode: str):
        self.modes.append(str(mode))


def test_kill_switch_trip_reset_while_running_has_no_mode_drift(monkeypatch):
    client = prep_client(monkeypatch)
    monkeypatch.setitem(dashboard.RATE_LIMITS, "control", (1000, 60))

    orch = _ModeAwareStub()
    trig = _ModeAwareStub()
    dashboard.state.orchestrator = orch
    dashboard.state.trigger = trig
    dashboard.state.running = True
    dashboard.state.mode = "PAPER"
    dashboard.state.requested_mode = "PAPER"

    trip = client.post("/api/risk/kill-switch", headers=auth_headers(admin=True), json={"action": "trip"})
    assert trip.status_code == 200
    assert dashboard.state.mode == "LOCKED"
    assert orch.modes[-1] == "LOCKED"
    assert trig.modes[-1] == "LOCKED"

    reset = client.post("/api/risk/kill-switch", headers=auth_headers(admin=True), json={"action": "reset"})
    assert reset.status_code == 200
    assert dashboard.state.mode == "DRY_RUN"
    assert orch.modes[-1] == "DRY_RUN"
    assert trig.modes[-1] == "DRY_RUN"
