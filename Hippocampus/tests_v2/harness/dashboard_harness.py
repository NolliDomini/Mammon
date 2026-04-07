from __future__ import annotations

import dashboard


API_TOKEN = "tests-v2-api"
ADMIN_TOKEN = "tests-v2-admin"


def auth_headers(*, admin: bool = False) -> dict:
    token = ADMIN_TOKEN if admin else API_TOKEN
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def reset_dashboard_state():
    s = dashboard.state
    s.running = False
    s.thread = None
    s.symbols = []
    s.active_symbol = None
    s.pulse_type = None
    s.last_signal = None
    s.signal_log = []
    s.bars_processed = 0
    s.started_at = None
    s.live_to_pond = False
    s.fornix_running = False
    s.fornix_thread = None
    s.fornix_instance = None
    s.fornix_progress = 0
    s.fornix_status = "Idle"
    s.fornix_bars_sec = 0
    s.fornix_symbol = ""
    s.fornix_mints = 0
    s.fornix_signals = 0
    s.fornix_eta = 0
    s.last_midnight_fornix_date = None
    s.last_warmup_date = None
    s.warmup_running = False
    s.warmup_status = "Idle"
    s.warmup_started_at = None
    s.warmup_ends_at = None
    s.mode = "DRY_RUN"
    s.trading_enabled = True
    s.params_frozen = False
    s.kill_switch = "ARMED"


def prep_client(monkeypatch):
    dashboard.API_BEARER_TOKEN = API_TOKEN
    dashboard.ADMIN_BEARER_TOKEN = ADMIN_TOKEN
    dashboard._rate_buckets.clear()
    dashboard._treasury = None
    dashboard._ui_read_model = None
    reset_dashboard_state()
    return dashboard.app.test_client()

