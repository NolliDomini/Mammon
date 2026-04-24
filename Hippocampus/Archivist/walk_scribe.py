from __future__ import annotations

from typing import List, Optional

from Hippocampus.Archivist.librarian import librarian


class WalkScribe:
    """
    Compatibility reader for historical walk priors.
    """

    def __init__(self, regime_id: Optional[str] = None, run_id: str = "NA"):
        self.regime_id = str(regime_id or "")
        self.run_id = str(run_id or "NA")

    def discharge(self, regime_id: Optional[str] = None, limit: int = 35000) -> List[float]:
        target_regime = str(regime_id or self.regime_id or "")
        try:
            sql = """
                SELECT mu
                FROM quantized_walk_mint
                WHERE regime_id = ?
                ORDER BY ts DESC
                LIMIT ?
            """
            rows = librarian.read(sql, (target_regime, int(limit)), transport="duckdb")
            return [float(r[0]) for r in rows if r and r[0] is not None]
        except Exception:
            # Walk discharge is advisory; callers already handle empty shock sets.
            return []
