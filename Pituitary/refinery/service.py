import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional
from Hippocampus.Archivist.librarian import Librarian

class SynapseRefinery:
    """
    Pituitary/Refinery: The Synapse Harvester.
    Aggregates 'Internal Monologue' tickets into training matrices for Diamond.
    """
    def __init__(self, synapse_db_path: Optional[Path] = None):
        self.db_path = synapse_db_path or Path(__file__).resolve().parents[2] / "Hippocampus" / "Archivist" / "Ecosystem_Synapse.db"
        self.librarian = Librarian(db_path=self.db_path)
        self.money_db_path = Path(__file__).resolve().parents[2] / "runtime" / ".tmp_test_local" / "compat_librarian.db"
        self.money_librarian = Librarian(db_path=self.money_db_path)

    def _resolve_time_filter(self) -> tuple[str, str]:
        """
        Determine which timestamp column exists and how to filter it.
        """
        try:
            cols = self.librarian.read_only("PRAGMA table_info('synapse_mint')")
            names = {str(c.get("name", "")).lower() for c in cols if isinstance(c, dict)}
        except Exception:
            names = set()

        if "created_at" in names:
            return "created_at", "datetime(created_at) >= datetime('now', ?)"
        if "ts" in names:
            # ts is typically ISO-8601 text in this silo (e.g., 2026-04-18T21:25:00+00:00).
            return "ts", "datetime(replace(substr(ts, 1, 19), 'T', ' ')) >= datetime('now', ?)"
        return "", ""

    def harvest_training_data(self, hours: int = 24) -> pd.DataFrame:
        """
        Extracts recent synapse tickets and calculates a 'Realized Fitness' score.
        """
        print(f"[REFINERY] Harvesting synapse tickets from last {hours}h...")

        time_col, time_predicate = self._resolve_time_filter()
        lookback = f"-{int(hours)} hours"
        if time_col:
            query = f"""
                SELECT * FROM synapse_mint
                WHERE {time_predicate}
                AND pulse_type = 'MINT'
            """
            params = (lookback,)
        else:
            query = """
                SELECT * FROM synapse_mint
                WHERE pulse_type = 'MINT'
            """
            params = ()
        
        try:
            # V3.1: Use Librarian for unified access
            rows = self.librarian.read_only(query, params)
            df = pd.DataFrame(rows)
            
            if df.empty:
                print("[REFINERY] Lake is empty. No training data available.")
                return pd.DataFrame()

            # Baseline fallback proxy for rows where no money-tape evidence is available.
            baseline = np.where(
                (pd.to_numeric(df.get("active_hi"), errors="coerce") - pd.to_numeric(df.get("active_lo"), errors="coerce")) > 0,
                (
                    pd.to_numeric(df.get("close"), errors="coerce")
                    - pd.to_numeric(df.get("active_lo"), errors="coerce")
                ) / (
                    pd.to_numeric(df.get("active_hi"), errors="coerce")
                    - pd.to_numeric(df.get("active_lo"), errors="coerce")
                ),
                0.5,
            )
            df["realized_pnl"] = baseline

            # Phase 2-A: replace placeholder fitness with realized PnL / risk_taken when available.
            try:
                pnl_rows = self.money_librarian.read_only(
                    """
                    SELECT ts, symbol, net_pnl
                    FROM money_pnl_snapshots
                    WHERE symbol IS NOT NULL
                    ORDER BY symbol, ts
                    """
                )
                pnl_df = pd.DataFrame(pnl_rows)
                if not pnl_df.empty and "symbol" in df.columns:
                    work = df.copy()
                    work["symbol"] = work["symbol"].astype(str)
                    work["event_ts"] = pd.to_datetime(work.get("ts"), errors="coerce", utc=True)
                    work = work.dropna(subset=["event_ts"]).sort_values(["symbol", "event_ts"])

                    pnl_df["symbol"] = pnl_df["symbol"].astype(str)
                    pnl_df["pnl_ts"] = pd.to_datetime(pnl_df["ts"], unit="s", errors="coerce", utc=True)
                    pnl_df["net_pnl"] = pd.to_numeric(pnl_df["net_pnl"], errors="coerce")
                    pnl_df = pnl_df.dropna(subset=["pnl_ts"]).sort_values(["symbol", "pnl_ts"])

                    if not work.empty and not pnl_df.empty:
                        merged = pd.merge_asof(
                            work,
                            pnl_df[["symbol", "pnl_ts", "net_pnl"]],
                            left_on="event_ts",
                            right_on="pnl_ts",
                            by="symbol",
                            direction="backward",
                        )
                        risk_used = pd.to_numeric(merged.get("risk_used"), errors="coerce").abs()
                        notional = pd.to_numeric(merged.get("notional"), errors="coerce").abs()
                        risk_taken = risk_used.where(risk_used > 0, notional)
                        risk_taken = risk_taken.where(risk_taken > 0, 1.0)

                        ratio = merged["net_pnl"] / risk_taken
                        merged["realized_pnl"] = np.clip(ratio, -1.0, 1.0)

                        # Write back only rows where money tape exists; keep baseline elsewhere.
                        fitness_by_ts = (
                            merged.dropna(subset=["realized_pnl"])
                            .set_index(["symbol", "event_ts"])["realized_pnl"]
                            .to_dict()
                        )
                        idx_ts = pd.to_datetime(df.get("ts"), errors="coerce", utc=True)
                        replacement = [
                            fitness_by_ts.get((str(sym), ts), np.nan)
                            for sym, ts in zip(df["symbol"], idx_ts)
                        ]
                        replacement_series = pd.Series(replacement, index=df.index, dtype="float64")
                        has_realized = replacement_series.notna()
                        df.loc[has_realized, "realized_pnl"] = replacement_series[has_realized]
            except Exception as pnl_err:
                print(f"[REFINERY WARN] PnL enrichment skipped: {pnl_err}")

            print(f"[REFINERY] Harvested {len(df)} tickets. Matrix ready.")
            return df
            
        except Exception as e:
            print(f"[REFINERY ERROR] Harvest failed: {e}")
            return pd.DataFrame()

if __name__ == "__main__":
    refinery = SynapseRefinery()
    data = refinery.harvest_training_data()
    if not data.empty:
        print(data[['ts', 'pulse_type', 'realized_fitness']].head())
