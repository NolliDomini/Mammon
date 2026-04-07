from __future__ import annotations

import uuid
from pathlib import Path

import dashboard
import Hippocampus.schema_guard as schema_guard
from Hippocampus.tests_v2.harness.dashboard_harness import auth_headers, prep_client
from Hippocampus.ui_read_model import UIReadModel


def _ui_db():
    root = Path(__file__).resolve().parents[3] / "runtime" / ".tmp_test_local"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"ui_chaos_{uuid.uuid4().hex}.db"


def test_ui_projection_db_fault_inject_writes_deadletter(monkeypatch):
    ui = UIReadModel(db_path=_ui_db())
    original_write_only = ui.librarian.write_only
    fault_injected = {"hit": False}

    def flaky_write(sql, params=None):
        if (not fault_injected["hit"]) and ("ui_pulse_events" in str(sql)):
            fault_injected["hit"] = True
            raise RuntimeError("database is locked")
        return original_write_only(sql, params)

    monkeypatch.setattr(ui.librarian, "write_only", flaky_write)
    ui.project_pulse(ts=1730000000.0, symbol="BTC/USD", pulse_type="ACTION", mode="DRY_RUN", source="chaos")

    dead = ui.librarian.read_only(
        "SELECT source_event_type FROM ui_projection_deadletter ORDER BY ts DESC LIMIT 20"
    )
    assert any(str(r.get("source_event_type")) == "project_pulse" for r in dead)


def test_api_start_handles_precheck_instability_without_false_running(monkeypatch):
    client = prep_client(monkeypatch)

    def _raise_instability():
        raise RuntimeError("upstream provider timeout token=abc123")

    monkeypatch.setattr(schema_guard, "run_schema_smoke_check", _raise_instability)
    resp = client.post("/api/start", headers=auth_headers(), json={"symbols": ["BTC/USD"], "mode": "PAPER"})
    assert resp.status_code == 500
    payload = resp.get_json() or {}
    assert payload.get("error") == "schema_guard_failed"
    assert dashboard.state.running is False
    assert dashboard.state.thread is None
