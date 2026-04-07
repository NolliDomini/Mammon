"""
Mammon N95-Optimized Backtest Rotation Script (Piece 18)

Manages a 10-million-bar sliding window for backtesting on hardware-constrained
environments (Intel N95, 8GB RAM).

Responsibilities:
1. Enforce Memory Cap: DuckDB limited to 3GB RAM.
2. Cohort Rotation: Cycle through 40+ symbols using "Least Recently Tested" logic.
3. Automated Promotion: Promote Diamond results to Hormonal Vault.
"""

import sys
import json
import time
import duckdb
import psutil
import shutil
from pathlib import Path
from datetime import datetime, timezone

# --- CONFIGURATION ---
MAMMON_ROOT = Path(__file__).resolve().parents[2]

MEMORY_CAP_GB = 3.0
TARGET_WINDOW_BARS = 10_000_000
COHORT_SIZE = 5  # Number of symbols to rotate per batch

# Cohort Definitions (for balanced selection)
COHORTS = {
    "VOLATILITY": ["VXX", "UVXY", "SQQQ", "TQQQ", "SOXL"],
    "TECH": ["AAPL", "MSFT", "NVDA", "AMD", "TSLA", "GOOGL", "META", "PLTR"],
    "BROAD": ["SPY", "QQQ", "IWM", "DIA", "EEM", "XLF", "XLE", "XLV"],
    "SPECULATIVE": ["AMC", "GME", "COIN", "HOOD", "ARKK", "BITO"],
    "CRYPTO": ["BTC/USD", "ETH/USD", "SOL/USD", "ADA/USD", "DOGE/USD"]
}

class BacktestRotator:
    def __init__(self, root: Path | None = None):
        self.root = root or MAMMON_ROOT
        self.db_path = self.root / "Hospital" / "Memory_care" / "duck.db"
        self.vault_path = self.root / "Hippocampus" / "hormonal_vault.json"
        # Prefer Pituitary path, fallback to Hippocampus if present.
        self.diamond_path = self.root / "Pituitary" / "diamond.json"
        if not self.diamond_path.exists():
            alt = self.root / "Hippocampus" / "diamond.json"
            if alt.exists():
                self.diamond_path = alt
        self.tracker_path = self.root / "Hospital" / "Memory_care" / "rotation_tracker.json"
        self.conn = None
        self._symbol_to_cohort = self._build_symbol_to_cohort()
        self._init_db()

    def _build_symbol_to_cohort(self):
        mapping = {}
        for cohort, symbols in COHORTS.items():
            for symbol in symbols:
                mapping[symbol] = cohort
        return mapping

    def _init_db(self):
        """Initialize DuckDB with N95 memory constraints."""
        try:
            self.conn = duckdb.connect(str(self.db_path))
            self.conn.execute(f"SET memory_limit='{MEMORY_CAP_GB}GB'")
            self.conn.execute("SET threads=3") # Leave 1 core for OS
            print(f"[ROTATOR] DuckDB initialized. Memory Limit: {MEMORY_CAP_GB}GB")
        except Exception as e:
            print(f"[ROTATOR] DB Connection Failed: {e}")
            sys.exit(1)

    def get_symbol_stats(self):
        """Get symbol bar counts and last tested timestamps."""
        tracker = {}
        if self.tracker_path.exists():
            with open(self.tracker_path, "r", encoding="utf-8") as f:
                tracker = json.load(f)

        stats = []
        try:
            rows = self.conn.execute("SELECT symbol, count(*) FROM market_tape GROUP BY symbol").fetchall()
            for sym, count in rows:
                last_ts = tracker.get(sym, 0)
                stats.append(
                    {
                        "symbol": sym,
                        "count": count,
                        "last_tested": last_ts,
                        "cohort": self._symbol_to_cohort.get(sym, "UNCLASSIFIED"),
                    }
                )
        except Exception as e:
            print(f"[ROTATOR] Failed to get stats: {e}")
        
        return stats

    def select_cohort(self):
        """Select next cohort with balanced + least-recently-tested priority."""
        stats = self.get_symbol_stats()
        if not stats:
            return []
        stats.sort(key=lambda x: (float(x.get("last_tested", 0)), x["symbol"]))

        by_cohort = {}
        for row in stats:
            by_cohort.setdefault(row["cohort"], []).append(row["symbol"])

        selected = []
        # Round-robin across defined cohorts first for balance.
        for cohort_name in COHORTS.keys():
            picks = by_cohort.get(cohort_name, [])
            if picks and len(selected) < COHORT_SIZE:
                selected.append(picks.pop(0))

        # Fill remaining slots strictly by least recently tested.
        if len(selected) < COHORT_SIZE:
            for row in stats:
                sym = row["symbol"]
                if sym in selected:
                    continue
                selected.append(sym)
                if len(selected) >= COHORT_SIZE:
                    break

        print(f"[ROTATOR] Selected Cohort: {selected}")
        return selected

    def update_tracker(self, symbols):
        """Updates the rotation tracker with current timestamp."""
        tracker = {}
        self.tracker_path.parent.mkdir(parents=True, exist_ok=True)
        if self.tracker_path.exists():
            with open(self.tracker_path, "r", encoding="utf-8") as f:
                tracker = json.load(f)
        
        now = time.time()
        for s in symbols:
            tracker[s] = now
            
        with open(self.tracker_path, "w", encoding="utf-8") as f:
            json.dump(tracker, f)

    def enforce_window_cap(self, symbols):
        """Keep per-symbol data bounded to target window bars."""
        for sym in symbols:
            try:
                count_row = self.conn.execute(
                    "SELECT COUNT(*) FROM market_tape WHERE symbol = ?",
                    [sym],
                ).fetchone()
                count = int(count_row[0]) if count_row else 0
                if count <= TARGET_WINDOW_BARS:
                    continue
                excess = count - TARGET_WINDOW_BARS
                self.conn.execute(
                    """
                    DELETE FROM market_tape
                    WHERE symbol = ?
                      AND ts IN (
                        SELECT ts FROM market_tape
                        WHERE symbol = ?
                        ORDER BY ts ASC
                        LIMIT ?
                      )
                    """,
                    [sym, sym, excess],
                )
                print(f"[ROTATOR] Pruned {excess} rows for {sym} to maintain {TARGET_WINDOW_BARS} cap.")
            except Exception as e:
                print(f"[ROTATOR] Window cap prune failed for {sym}: {e}")

    def _extract_candidate_params(self, diamond_data):
        candidates = []
        if isinstance(diamond_data.get("best_params"), dict):
            candidates.append(diamond_data.get("best_params"))
        if isinstance(diamond_data.get("candidate_params"), dict):
            candidates.append(diamond_data.get("candidate_params"))
        last_run = diamond_data.get("last_fornix_run")
        if isinstance(last_run, dict):
            if isinstance(last_run.get("best_params"), dict):
                candidates.append(last_run.get("best_params"))
            if isinstance(last_run.get("params"), dict):
                candidates.append(last_run.get("params"))
        for c in candidates:
            if c:
                return c
        return None

    def promote_diamond_params(self):
        """Promote Diamond params into vault with backup + rollback safety."""
        if not self.diamond_path.exists():
            print("[ROTATOR] No Diamond results found.")
            return False

        try:
            with open(self.diamond_path, "r", encoding="utf-8") as f:
                diamond_data = json.load(f)

            candidate_params = self._extract_candidate_params(diamond_data)
            if not isinstance(candidate_params, dict) or not candidate_params:
                print("[ROTATOR] No promotable parameter set found in Diamond data.")
                return False

            if not self.vault_path.exists():
                print(f"[ROTATOR] Vault missing at {self.vault_path}.")
                return False

            backup_path = self.vault_path.with_suffix(".json.bak")
            shutil.copy2(self.vault_path, backup_path)

            with open(self.vault_path, "r", encoding="utf-8") as f:
                vault = json.load(f)

            previous_gold = vault.get("gold")
            if previous_gold:
                history = vault.get("bronze_history") or []
                history.append(previous_gold)
                vault["bronze_history"] = history[-25:]

            run_meta = diamond_data.get("last_fornix_run") if isinstance(diamond_data.get("last_fornix_run"), dict) else {}
            vault["gold"] = {
                "id": f"diamond_promoted_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
                "params": candidate_params,
                "fitness_snapshot": run_meta.get("fitness"),
                "coronated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "origin": "diamond_rotation",
            }

            with open(self.vault_path, "w", encoding="utf-8") as f:
                json.dump(vault, f, indent=2)

            print(f"[ROTATOR] Diamond parameters promoted to vault from {self.diamond_path.name}.")
            return True

        except Exception as e:
            print(f"[ROTATOR] Promotion failed: {e}")
            # Rollback to backup if available.
            backup_path = self.vault_path.with_suffix(".json.bak")
            try:
                if backup_path.exists():
                    shutil.copy2(backup_path, self.vault_path)
            except Exception as rollback_error:
                print(f"[ROTATOR] Rollback failed: {rollback_error}")
            return False

    def run_rotation(self):
        """Main rotation logic."""
        print(f"--- STARTING ROTATION (N95 OPTIMIZED) ---")
        
        # 1. Enforce System Health
        mem = psutil.virtual_memory()
        if mem.percent > 90:
            print(f"[ROTATOR] WARNING: System memory high ({mem.percent}%). Aborting rotation.")
            return

        # 2. Select Cohort
        cohort = self.select_cohort()
        if not cohort:
            print("[ROTATOR] No symbols available.")
            return

        # 3. Enforce per-symbol sliding window before run.
        self.enforce_window_cap(cohort)

        # 3. Simulate Fornix Run (Placeholder command generation)
        # In production, this would invoke Fornix with the selected symbols
        print(f"[ROTATOR] Launching Fornix for: {cohort}")
        # cmd = f"python Hippocampus/fornix.py --symbols {' '.join(cohort)}"
        # print(f"  > {cmd}")
        
        # 4. Update Tracker
        self.update_tracker(cohort)
        
        # 5. Promote Results (with rollback safety)
        self.promote_diamond_params()
        
        print(f"--- ROTATION COMPLETE ---")

if __name__ == "__main__":
    rotator = BacktestRotator()
    rotator.run_rotation()
