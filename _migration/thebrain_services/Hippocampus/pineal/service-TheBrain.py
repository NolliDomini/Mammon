import time
from pathlib import Path
from typing import Any, Dict, List
from datetime import datetime, timedelta

from Cerebellum.Soul.utils.timing import enforce_pulse_gate
from Hippocampus.Archivist.librarian import librarian


class Pineal:
    """
    Hippocampus/Pineal: The Circadian Ruler (v2.1 Multi-Transport).
    Authority for memory hygiene and retention governance.
    
    Piece 66 & 67: Multi-Transport Hygiene.
    - Prunes Redis BrainFrames via TTL.
    - Prunes DuckDB analytical windows.
    - Prunes TimescaleDB audit ledgers.
    """
    def __init__(self):
        self.librarian = librarian
        
        # Target #66: Retention Map (hours)
        self.retention_map = {
            "walk_mint": 6,
            "monte_mint": 1,
            "optimizer_mint": 24,
            "synapse_mint": 2160, # 90 days
            "money_pnl_snapshots": 720, # 30 days
            "broadcast_audit": 168 # 7 days
        }

    def secrete_melatonin(self, pulse_type: str = "MINT"):
        """
        The Sleep Cycle.
        V3.2 ANALYTICAL: Executes Multi-Transport pruning.
        """
        # Piece 14: Hygiene only happens at MINT
        if not enforce_pulse_gate(pulse_type, ["MINT"], "Pineal"):
            return

        print("[PINEAL] Secreting Melatonin... (Multi-Transport Hygiene)")
        
        try:
            # 1. Redis Hygiene (Target #67: Ensure TTLs are set)
            self._hygiene_redis()
            
            # 2. DuckDB Hygiene (Target #66: Analytical windowing)
            self._hygiene_duckdb()
            
            # 3. TimescaleDB Hygiene (Target #66: Audit retention)
            self._hygiene_timescale()
            
            print("[PINEAL] Melatonin secretion complete.")
            
        except Exception as e:
            # Piece 71: Standardized MNER for hygiene failure
            print(f"[HIPP-E-P71-705] HYGIENE_CYCLE_FAILED: {e}")

    def _hygiene_redis(self):
        """Ensures all ephemeral BrainFrames have a 60s TTL."""
        try:
            redis_conn = self.librarian.get_redis_connection()
            if not redis_conn: return
            keys = redis_conn.keys("mammon:brain_frame:*")
            for k in keys:
                if redis_conn.ttl(k) == -1: # No TTL set
                    redis_conn.expire(k, 60)
        except Exception as e:
            # HIPP-W-P71-711: Redis hygiene failure
            print(f"[HIPP-W-P71-711] Pineal Redis hygiene failed: {e}")

    def _hygiene_duckdb(self):
        """Prunes analytical tables in DuckDB based on retention map."""
        try:
            tables = ["walk_mint", "monte_mint", "optimizer_mint", "synapse_mint"]
            for table in tables:
                hours = self.retention_map.get(table, 24)
                cutoff = datetime.now() - timedelta(hours=hours)
                
                # Piece 66: Use standardized librarian gateway
                self.librarian.write(
                    f"DELETE FROM {table} WHERE ts < ?",
                    (cutoff,),
                    transport="duckdb"
                )
        except Exception as e:
            # HIPP-W-P71-712: DuckDB hygiene failure
            print(f"[HIPP-W-P71-712] Pineal DuckDB hygiene failed: {e}")

    def _hygiene_timescale(self):
        """Prunes audit and ledger tables in TimescaleDB."""
        try:
            tables = ["money_pnl_snapshots", "broadcast_audit"]
            for table in tables:
                hours = self.retention_map.get(table, 720)
                cutoff = datetime.now() - timedelta(hours=hours)
                
                self.librarian.write(
                    f"DELETE FROM {table} WHERE ts < ?",
                    (cutoff,),
                    transport="timescale"
                )
        except Exception as e:
            # HIPP-W-P71-713: TimescaleDB hygiene failure
            print(f"[HIPP-W-P71-713] Pineal TimescaleDB hygiene failed: {e}")

    def finalize_fornix_staging(self, pond, consumed_by_diamond: bool, run_id: str):
        """
        Finalizes historical replay data.
        Archives synapses and clears staging (only if Diamond consumed them).
        """
        try:
            # 1. Archive
            pond.archive_history_synapse(run_id=run_id)
            
            # 2. Wipe staging only if Diamond successfully processed them
            if consumed_by_diamond:
                pond.clear_history_synapse()
                print(f"[PINEAL] Fornix staging wiped (Consumed by Diamond: {run_id})")
            else:
                print(f"[PINEAL] Fornix staging PRESERVED (Not consumed by Diamond: {run_id})")
                
        except Exception as e:
            # Piece 71: Standardized MNER
            print(f"[HIPP-E-P71-706] FORNIX_FINALIZATION_FAILED: {e}")

if __name__ == "__main__":
    gland = Pineal()
    gland.secrete_melatonin()
