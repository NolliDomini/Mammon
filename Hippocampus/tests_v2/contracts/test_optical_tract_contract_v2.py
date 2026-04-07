import pandas as pd

from Corpus.Optical_Tract.spray import OpticalTract
from Corpus.Optical_Tract.adapters import LegacyTwoArgSubscriberAdapter


def test_transport_forwards_payload_unchanged_and_tracks_delivery():
    tract = OpticalTract()
    got = []

    class Sub:
        def on_data_received(self, data):
            got.append(data.copy())

    tract.subscribe(Sub())
    df = pd.DataFrame([{"open": 1, "high": 2, "low": 1, "close": 2, "volume": 10, "symbol": "BTC/USD"}])
    summary = tract.spray(df)

    assert len(got) == 1
    pd.testing.assert_frame_equal(got[0], df)
    assert summary["subscriber_count"] == 1
    assert summary["delivered_count"] == 1
    assert summary["failed_count"] == 0
    assert summary["pulse_type"] is None
    assert summary["delivery_mode"] == "synchronous"
    assert summary["delivery_budget_ms"] == 50.0
    assert summary["total_delivery_ms"] >= 0.0
    assert summary["max_subscriber_ms"] >= 0.0


def test_legacy_two_arg_requires_explicit_adapter():
    tract = OpticalTract()
    got = {"legacy": 0}

    class Legacy:
        def on_data_received(self, pulse_type, data):
            got["legacy"] += 1

    df = pd.DataFrame([{"open": 1, "high": 2, "low": 1, "close": 2, "volume": 10, "symbol": "BTC/USD", "pulse_type": "ACTION"}])
    tract.subscribe(Legacy())
    summary_fail = tract.spray(df)
    assert got["legacy"] == 0
    assert summary_fail["failed_count"] == 1
    assert summary_fail["errors"][0]["error_type"] == "TypeError"

    tract = OpticalTract()
    tract.subscribe(LegacyTwoArgSubscriberAdapter(Legacy()))
    summary_ok = tract.spray(df)
    assert summary_ok["failed_count"] == 0


def test_subscriber_failure_does_not_block_fanout_and_order_is_stable():
    tract = OpticalTract()
    called = []

    class Bad:
        def on_data_received(self, data):
            called.append("bad")
            raise RuntimeError("boom")

    class Good:
        def __init__(self, name):
            self.name = name

        def on_data_received(self, data):
            called.append(self.name)

    first = Good("first")
    second = Good("second")
    tract.subscribe(first)
    tract.subscribe(Bad())
    tract.subscribe(second)
    tract.subscribe(second)  # idempotent
    df = pd.DataFrame([{"open": 1, "high": 2, "low": 1, "close": 2, "volume": 10, "symbol": "BTC/USD"}])
    summary = tract.spray(df)

    assert called == ["first", "bad", "second"]
    assert summary["subscriber_count"] == 3
    assert summary["delivered_count"] == 2
    assert summary["failed_count"] == 1

    tract.unsubscribe(second)
    tract.unsubscribe(second)
    summary_after = tract.spray(df)
    assert summary_after["subscriber_count"] == 2
