import pandas as pd
from typing import Any, Callable

class LegacyTwoArgSubscriberAdapter:
    """
    Bridges modern single-DataFrame subscribers to legacy (pulse_type, data) signatures.
    """
    def __init__(self, callback: Any):
        self.callback = callback

    def on_data_received(self, data: pd.DataFrame):
        pulse_type = data["pulse_type"].iloc[-1] if "pulse_type" in data.columns else "ACTION"
        if hasattr(self.callback, "on_data_received"):
            self.callback.on_data_received(pulse_type, data)
        else:
            self.callback(pulse_type, data)
