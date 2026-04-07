from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, Any
import uuid

import pandas as pd


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def synthetic_ohlcv(
    *,
    symbol: str = "BTC/USD",
    start: str = "2026-01-01 00:00:00",
    periods: int = 10,
    freq: str = "1min",
    base: float = 100.0,
) -> pd.DataFrame:
    idx = pd.date_range(start=start, periods=periods, freq=freq)
    rows = []
    for i, ts in enumerate(idx):
        open_ = base + i
        rows.append(
            {
                "ts": ts,
                "open": open_,
                "high": open_ + 1.0,
                "low": open_ - 1.0,
                "close": open_ + 0.5,
                "volume": 1000 + i,
                "symbol": symbol,
            }
        )
    return pd.DataFrame(rows).set_index("ts")


def frame_stub(
    *,
    price: float = 100.0,
    symbol: str = "BTC/USD",
    monte: float = 1.0,
    confidence: float = 1.0,
    atr: float = 1.0,
    sizing: float = 1.0,
):
    return SimpleNamespace(
        structure=SimpleNamespace(price=price, tier1_signal=1),
        market=SimpleNamespace(symbol=symbol),
        risk=SimpleNamespace(monte_score=monte, tier_score=0.75),
        environment=SimpleNamespace(confidence=confidence, atr=atr),
        command=SimpleNamespace(sizing_mult=sizing, approved=1, ready_to_fire=True, reason="APPROVED"),
    )


@dataclass
class ModeState:
    mode: str = "DRY_RUN"
    trading_enabled: bool = True
    params_frozen: bool = False
    kill_switch: str = "ARMED"


def temp_db_path(prefix: str = "tests_v2") -> Path:
    base = project_root() / "runtime" / ".tmp_test_local"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{prefix}_{uuid.uuid4().hex}.db"

