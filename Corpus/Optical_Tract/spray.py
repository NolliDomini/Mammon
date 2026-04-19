import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from Hippocampus.Archivist.librarian import librarian


class OpticalTract:
    """
    Corpus/Optical Tract: synchronous pulse fan-out.
    """

    def __init__(self):
        self.subscribers = []
        self.librarian = librarian
        self.last_delivery = {}
        self.MAX_SUBSCRIBERS = 20
        self.subscriber_names = ["" for _ in range(self.MAX_SUBSCRIBERS)]
        self.delivery_stats = np.zeros(self.MAX_SUBSCRIBERS, dtype=np.float64)

    def subscribe(self, lobe_instance: Any, name: Optional[str] = None):
        if hasattr(lobe_instance, "on_data_received"):
            if lobe_instance in self.subscribers:
                return
            self.subscribers.append(lobe_instance)
            idx = len(self.subscribers) - 1
            if idx < self.MAX_SUBSCRIBERS:
                self.subscriber_names[idx] = name or type(lobe_instance).__name__
            print(f"[OPTICAL_TRACT] Subscribed: {self.subscriber_names[idx]}")

    def unsubscribe(self, lobe_instance: Any):
        if lobe_instance in self.subscribers:
            idx = self.subscribers.index(lobe_instance)
            self.subscribers.pop(idx)
            if idx < self.MAX_SUBSCRIBERS:
                self.subscriber_names[idx] = ""

    def spray(self, df: pd.DataFrame) -> Dict[str, Any]:
        if df is None or df.empty:
            return {"status": "skipped", "reason": "empty_payload"}

        pulse_type = df["pulse_type"].iloc[-1] if "pulse_type" in df.columns else None
        symbol = df["symbol"].iloc[-1] if "symbol" in df.columns else "UNKNOWN"

        start_time = time.perf_counter()
        failed_count = 0
        delivered_count = 0
        delivery_details = []
        self.delivery_stats.fill(0.0)

        for i, sub in enumerate(self.subscribers):
            sub_start = time.perf_counter()
            try:
                sub.on_data_received(df)
                delivered_count += 1
            except Exception as e:
                failed_count += 1
                err_msg = f"[CORP-E-P50-407] {type(e).__name__}: {str(e)[:50]}"
                delivery_details.append(
                    {
                        "lobe": self.subscriber_names[i],
                        "error_type": type(e).__name__,
                        "error": err_msg,
                    }
                )
                try:
                    self.librarian.write(
                        """
                        INSERT INTO broadcast_audit (ts, symbol, pulse_type, target_lobe, error_msg)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            datetime.now(timezone.utc).timestamp(),
                            symbol,
                            pulse_type,
                            self.subscriber_names[i],
                            err_msg,
                        ),
                        transport="timescale",
                    )
                except Exception:
                    pass

            sub_dur = (time.perf_counter() - sub_start) * 1000.0
            if i < self.MAX_SUBSCRIBERS:
                self.delivery_stats[i] = sub_dur

        total_dur_ms = (time.perf_counter() - start_time) * 1000.0
        summary = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "pulse_type": pulse_type,
            "symbol": symbol,
            "subscriber_count": len(self.subscribers),
            "delivered_count": delivered_count,
            "failed_count": failed_count,
            "delivery_mode": "synchronous",
            "delivery_budget_ms": 50.0,
            "total_delivery_ms": total_dur_ms,
            "max_subscriber_ms": np.max(self.delivery_stats) if len(self.subscribers) > 0 else 0.0,
            "errors": delivery_details,
        }
        self.last_delivery = summary
        return summary

    def get_state(self):
        return {
            "last_delivery": self.last_delivery,
            "subscriber_list": [n for n in self.subscriber_names if n != ""],
        }

