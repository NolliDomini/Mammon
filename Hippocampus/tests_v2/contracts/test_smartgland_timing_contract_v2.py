from Thalamus.gland import SmartGland
from Hippocampus.tests_v2.fixtures.factories import synthetic_ohlcv


def test_smartgland_emits_seed_action_mint_in_order():
    gland = SmartGland(window_minutes=5)
    # 7 one-minute bars cross one 5-minute boundary and should emit MINT for first window.
    df = synthetic_ohlcv(start="2026-01-01 12:00:00", periods=7, freq="1min")
    pulses = gland.ingest(df)
    pulse_names = [p[0] for p in pulses]

    assert "SEED" in pulse_names
    assert "ACTION" in pulse_names
    assert "MINT" in pulse_names
    assert pulse_names.index("SEED") < pulse_names.index("ACTION") < pulse_names.index("MINT")


def test_smartgland_window_markers_fire_once_per_window():
    gland = SmartGland(window_minutes=5)
    df = synthetic_ohlcv(start="2026-01-01 13:00:00", periods=12, freq="30s")
    pulses = gland.ingest(df)
    names = [p[0] for p in pulses]

    assert names.count("SEED") <= 1
    assert names.count("ACTION") <= 1
