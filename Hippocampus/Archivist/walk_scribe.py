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
            # Prefer atr_return (real ATR-normalized bar returns) over mu (synthetic drift scalar).
            # atr_return is non-null only for MINT pulses recorded after Phase 2; older rows
            # fall back to mu via COALESCE so the discharge degrades gracefully during transition.
            sql = """
                SELECT COALESCE(atr_return, mu)
                FROM quantized_walk_mint
                WHERE regime_id = ?
                  AND pulse_type = 'MINT'
                  AND (atr_return IS NOT NULL OR mu IS NOT NULL)
                ORDER BY ts DESC
                LIMIT ?
            """
            rows = librarian.read(sql, (target_regime, int(limit)), transport="duckdb")
            return [float(r[0]) for r in rows if r and r[0] is not None]
        except Exception:
            # Walk discharge is advisory; callers already handle empty shock sets.
            return []
