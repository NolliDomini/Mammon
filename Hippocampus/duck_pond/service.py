import duckdb
import pandas as pd
from pathlib import Path
import time
import argparse
import os
from datetime import datetime, timedelta
from typing import List, Optional

class DuckPond:
    """
    Hippocampus/DuckPond: The Data Lake Manager.
    Handles ingestion and pre-calculation of market data.
    V4 FORNIX: Extended with history_synapse table and replay helpers.
    """
    def __init__(self, db_path=None):
        if db_path is None:
            env_path = os.environ.get("MAMMON_DUCK_DB")
            if env_path and str(env_path).strip():
                db_path = env_path
            else:
                db_path = str(Path(__file__).resolve().parents[2] / "Hospital" / "Memory_care" / "duck.db")
        self.db_path = db_path
        self.conn = duckdb.connect(self.db_path)
        self._init_schema()
    
    @staticmethod
    def _env_int(name: str, default: int) -> int:
        raw = os.environ.get(name)
        if raw is None or str(raw).strip() == "":
            return default
        try:
            return int(raw)
        except ValueError:
            return default

    def _init_schema(self):
        """Creates the base tables if they don't exist."""
        # 1. Market Tape (Raw)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS market_tape (
                ts TIMESTAMP,
                symbol VARCHAR,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume DOUBLE
            );
        """)

        # 1b. Market Tape 5m (Live Aggregates)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS market_tape_5m (
                ts TIMESTAMP,
                symbol VARCHAR,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume DOUBLE
            );
        """)
        
        # 2. Cortex Precalc (Smart)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS cortex_precalc (
                ts TIMESTAMP,
                symbol VARCHAR,
                close DOUBLE,
                atr_14 DOUBLE,
                mean_100 DOUBLE,
                upper_band DOUBLE,
                lower_band DOUBLE,
                regime_tag VARCHAR
            );
        """)

        # 3. History Synapse (Fornix Output)
        #    Full BrainFrame snapshots minted during historical replay.
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS history_synapse (
                ts TIMESTAMP,
                symbol VARCHAR,
                pulse_type VARCHAR,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume DOUBLE,
                price DOUBLE,
                active_hi DOUBLE,
                active_lo DOUBLE,
                gear INTEGER,
                tier1_signal INTEGER,
                monte_score DOUBLE,
                tier_score DOUBLE,
                regime_id VARCHAR,
                worst_survival DOUBLE,
                neutral_survival DOUBLE,
                best_survival DOUBLE,
                council_score DOUBLE,
                atr DOUBLE,
                atr_avg DOUBLE,
                adx DOUBLE,
                volume_score DOUBLE,
                decision VARCHAR,
                approved INTEGER,
                final_confidence DOUBLE,
                sizing_mult DOUBLE,
                ready_to_fire INTEGER,
                gold_id INTEGER,
                platinum_id INTEGER
            );
        """)

        # 4. Fornix Checkpoint (Resume Support)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS fornix_checkpoint (
                symbol VARCHAR PRIMARY KEY,
                last_ts TIMESTAMP,
                bars_processed BIGINT,
                mints_generated BIGINT,
                updated_at TIMESTAMP DEFAULT current_timestamp
            );
        """)

        # 3b. Brainframe Mint Archive (long-lived store)
        #     Staging (history_synapse) can be wiped after consumption.
        #     Archive preserves MINT brainframes across runs.
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS brainframe_mint_archive (
                run_id VARCHAR,
                archived_at TIMESTAMP DEFAULT current_timestamp,
                ts TIMESTAMP,
                symbol VARCHAR,
                pulse_type VARCHAR,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume DOUBLE,
                price DOUBLE,
                active_hi DOUBLE,
                active_lo DOUBLE,
                gear INTEGER,
                tier1_signal INTEGER,
                monte_score DOUBLE,
                tier_score DOUBLE,
                regime_id VARCHAR,
                worst_survival DOUBLE,
                neutral_survival DOUBLE,
                best_survival DOUBLE,
                council_score DOUBLE,
                atr DOUBLE,
                atr_avg DOUBLE,
                adx DOUBLE,
                volume_score DOUBLE,
                decision VARCHAR,
                approved INTEGER,
                final_confidence DOUBLE,
                sizing_mult DOUBLE,
                ready_to_fire INTEGER,
                gold_id INTEGER,
                platinum_id INTEGER
            );
        """)

        # 5. Pond Settings (retention/sunset policy)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS pond_settings (
                key VARCHAR PRIMARY KEY,
                value VARCHAR,
                updated_at TIMESTAMP DEFAULT current_timestamp
            );
        """)
        setting_cols = {
            row[1] for row in self.conn.execute("PRAGMA table_info('pond_settings')").fetchall()
        }
        if "value" not in setting_cols:
            self.conn.execute("ALTER TABLE pond_settings ADD COLUMN value VARCHAR")
        if "updated_at" not in setting_cols:
            self.conn.execute("ALTER TABLE pond_settings ADD COLUMN updated_at TIMESTAMP")

        self._init_sunset_policy()

        print("[DUCK_POND] Schema initialized (V5 Live Pipe).")

    # ------------------------------------------------------------------ #
    #  SUNSET POLICY                                                      #
    # ------------------------------------------------------------------ #
    def _set_setting(self, key: str, value: str):
        self.conn.execute("""
            INSERT INTO pond_settings (key, value, updated_at)
            VALUES (?, ?, current_timestamp)
            ON CONFLICT (key) DO UPDATE SET
                value = excluded.value,
                updated_at = now()
        """, [key, str(value)])

    def _set_setting_if_missing(self, key: str, value: str):
        exists = self.conn.execute(
            "SELECT 1 FROM pond_settings WHERE key = ?",
            [key]
        ).fetchone()
        if not exists:
            self._set_setting(key, value)

    def _get_setting(self, key: str, default: str = "") -> str:
        row = self.conn.execute(
            "SELECT value FROM pond_settings WHERE key = ?",
            [key]
        ).fetchone()
        return row[0] if row else default

    def _init_sunset_policy(self):
        self._set_setting_if_missing(
            "sunset.market_tape_days",
            str(self._env_int("MAMMON_SUNSET_MARKET_DAYS", 0))
        )
        self._set_setting_if_missing(
            "sunset.market_tape_5m_days",
            str(self._env_int("MAMMON_SUNSET_MARKET_5M_DAYS", 0))
        )
        self._set_setting_if_missing(
            "sunset.cortex_precalc_days",
            str(self._env_int("MAMMON_SUNSET_CORTEX_DAYS", 0))
        )
        self._set_setting_if_missing(
            "sunset.history_synapse_days",
            str(self._env_int("MAMMON_SUNSET_HISTORY_DAYS", 14))
        )
        self._set_setting_if_missing(
            "sunset.fornix_checkpoint_days",
            str(self._env_int("MAMMON_SUNSET_CHECKPOINT_DAYS", 30))
        )
        self._set_setting_if_missing(
            "sunset.min_interval_minutes",
            str(self._env_int("MAMMON_SUNSET_INTERVAL_MINUTES", 720))
        )
        self._set_setting_if_missing(
            "sunset.brainframe_archive_days",
            str(self._env_int("MAMMON_SUNSET_ARCHIVE_DAYS", 0))
        )
        self._set_setting_if_missing("sunset.last_run_utc", "")

    def get_sunset_policy(self) -> dict:
        return {
            "market_tape_days": int(self._get_setting("sunset.market_tape_days", "0")),
            "market_tape_5m_days": int(self._get_setting("sunset.market_tape_5m_days", "0")),
            "cortex_precalc_days": int(self._get_setting("sunset.cortex_precalc_days", "0")),
            "history_synapse_days": int(self._get_setting("sunset.history_synapse_days", "14")),
            "fornix_checkpoint_days": int(self._get_setting("sunset.fornix_checkpoint_days", "30")),
            "brainframe_archive_days": int(self._get_setting("sunset.brainframe_archive_days", "0")),
            "min_interval_minutes": int(self._get_setting("sunset.min_interval_minutes", "720")),
            "last_run_utc": self._get_setting("sunset.last_run_utc", ""),
        }

    def set_sunset_policy(
        self,
        market_tape_days: Optional[int] = None,
        market_tape_5m_days: Optional[int] = None,
        cortex_precalc_days: Optional[int] = None,
        history_synapse_days: Optional[int] = None,
        fornix_checkpoint_days: Optional[int] = None,
        brainframe_archive_days: Optional[int] = None,
        min_interval_minutes: Optional[int] = None,
    ) -> dict:
        if market_tape_days is not None:
            self._set_setting("sunset.market_tape_days", max(0, int(market_tape_days)))
        if market_tape_5m_days is not None:
            self._set_setting("sunset.market_tape_5m_days", max(0, int(market_tape_5m_days)))
        if cortex_precalc_days is not None:
            self._set_setting("sunset.cortex_precalc_days", max(0, int(cortex_precalc_days)))
        if history_synapse_days is not None:
            self._set_setting("sunset.history_synapse_days", max(0, int(history_synapse_days)))
        if fornix_checkpoint_days is not None:
            self._set_setting("sunset.fornix_checkpoint_days", max(0, int(fornix_checkpoint_days)))
        if brainframe_archive_days is not None:
            self._set_setting("sunset.brainframe_archive_days", max(0, int(brainframe_archive_days)))
        if min_interval_minutes is not None:
            self._set_setting("sunset.min_interval_minutes", max(1, int(min_interval_minutes)))
        return self.get_sunset_policy()

    def _prune_table_by_days(self, table: str, timestamp_col: str, days: int) -> int:
        if days <= 0:
            return 0
        cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        prunable = self.conn.execute(
            f"SELECT count(*) FROM {table} WHERE {timestamp_col} < ?",
            [cutoff]
        ).fetchone()[0]
        if prunable <= 0:
            return 0
        self.conn.execute(
            f"DELETE FROM {table} WHERE {timestamp_col} < ?",
            [cutoff]
        )
        return prunable

    def run_sunset(self, force: bool = False) -> dict:
        """
        Applies policy-driven pruning.
        By default, raw/precalc pruning is disabled to protect historical lakes.
        """
        policy = self.get_sunset_policy()
        now = datetime.utcnow()

        if not force and policy["last_run_utc"]:
            try:
                last = datetime.fromisoformat(policy["last_run_utc"])
                elapsed_min = (now - last).total_seconds() / 60.0
                if elapsed_min < policy["min_interval_minutes"]:
                    return {
                        "ran": False,
                        "reason": "interval_not_elapsed",
                        "minutes_until_next": round(policy["min_interval_minutes"] - elapsed_min, 1),
                        "policy": policy,
                    }
            except ValueError:
                pass

        deleted = {
            "market_tape": self._prune_table_by_days("market_tape", "ts", policy["market_tape_days"]),
            "market_tape_5m": self._prune_table_by_days("market_tape_5m", "ts", policy["market_tape_5m_days"]),
            "cortex_precalc": self._prune_table_by_days("cortex_precalc", "ts", policy["cortex_precalc_days"]),
            "history_synapse": self._prune_table_by_days("history_synapse", "ts", policy["history_synapse_days"]),
            "fornix_checkpoint": self._prune_table_by_days("fornix_checkpoint", "updated_at", policy["fornix_checkpoint_days"]),
            "brainframe_mint_archive": self._prune_table_by_days(
                "brainframe_mint_archive",
                "archived_at",
                policy["brainframe_archive_days"],
            ),
        }
        total_deleted = sum(deleted.values())

        self._set_setting("sunset.last_run_utc", now.isoformat(timespec="seconds"))
        if total_deleted > 0:
            self.conn.execute("CHECKPOINT")

        return {
            "ran": True,
            "deleted": deleted,
            "total_deleted": total_deleted,
            "policy": self.get_sunset_policy(),
        }

    # ------------------------------------------------------------------ #
    #  INGESTION                                                          #
    # ------------------------------------------------------------------ #
    def ingest_csv(self, csv_path: str):
        """Bulk loads a CSV into the market tape (filters to 1Min bars only)."""
        print(f"[DUCK_POND] Ingesting {csv_path}...")
        start = time.time()
        
        # Simple check for emptiness (much faster for validation)
        count = self.conn.execute("SELECT count(*) FROM market_tape").fetchone()[0]
        if count == 0:
            print(f"[DUCK_POND] Tape empty. Ingesting {csv_path}...")
            self.conn.execute(f"""
                INSERT INTO market_tape 
                SELECT ts, symbol, open, high, low, close, volume 
                FROM read_csv_auto('{csv_path}', header=True)
                WHERE interval = '1Min'
            """)
            elapsed = time.time() - start
            new_count = self.conn.execute("SELECT count(*) FROM market_tape").fetchone()[0]
            print(f"[DUCK_POND] Ingested {new_count:,} 1Min bars in {elapsed:.2f}s")
            self.calculate_cortex()
        else:
            print(f"[DUCK_POND] Tape has {count:,} rows. Skipping ingestion.")
            cortex_count = self.conn.execute("SELECT count(*) FROM cortex_precalc").fetchone()[0]
            if cortex_count == 0:
                self.calculate_cortex()

    def ingest_csv_append(self, csv_path: str):
        """Appends a CSV to the market tape (for multi-file ingestion)."""
        print(f"[DUCK_POND] Appending {csv_path}...")
        start = time.time()
        
        before = self.conn.execute("SELECT count(*) FROM market_tape").fetchone()[0]
        self.conn.execute(f"""
            INSERT INTO market_tape 
            SELECT ts, symbol, open, high, low, close, volume 
            FROM read_csv_auto('{csv_path}', header=True)
            WHERE interval = '1Min'
        """)
        after = self.conn.execute("SELECT count(*) FROM market_tape").fetchone()[0]
        added = after - before
        elapsed = time.time() - start
        print(f"[DUCK_POND] Appended {added:,} bars in {elapsed:.2f}s (total: {after:,})")

    # ------------------------------------------------------------------ #
    #  CORTEX PRE-CALCULATION                                             #
    # ------------------------------------------------------------------ #
    def calculate_cortex(self):
        """
        The 'Half Math': Pre-calculates indicators using Vectorized SQL.
        Populates cortex_precalc.
        """
        print("[DUCK_POND] Calculating Cortex Layers (Pre-calc)...")
        start = time.time()
        
        self.conn.execute("DELETE FROM cortex_precalc")
        
        query = """
        INSERT INTO cortex_precalc
        SELECT
            ts,
            symbol,
            close,
            avg(high - low) OVER (
                PARTITION BY symbol ORDER BY ts 
                ROWS BETWEEN 13 PRECEDING AND CURRENT ROW
            ) as atr_14,
            avg(close) OVER (
                PARTITION BY symbol ORDER BY ts 
                ROWS BETWEEN 99 PRECEDING AND CURRENT ROW
            ) as mean_100,
            avg(close) OVER (PARTITION BY symbol ORDER BY ts ROWS BETWEEN 99 PRECEDING AND CURRENT ROW) + 
            (2.0 * stddev(close) OVER (PARTITION BY symbol ORDER BY ts ROWS BETWEEN 99 PRECEDING AND CURRENT ROW)) as upper_band,
            
            avg(close) OVER (PARTITION BY symbol ORDER BY ts ROWS BETWEEN 99 PRECEDING AND CURRENT ROW) - 
            (1.5 * stddev(close) OVER (PARTITION BY symbol ORDER BY ts ROWS BETWEEN 99 PRECEDING AND CURRENT ROW)) as lower_band,
            
            CASE 
                WHEN (high - low) > (avg(high - low) OVER (PARTITION BY symbol ORDER BY ts ROWS BETWEEN 99 PRECEDING AND CURRENT ROW) * 2.0) 
                THEN 'HighVol' 
                ELSE 'Normal' 
            END as regime_tag
            
        FROM market_tape
        """
        self.conn.execute(query)
        print(f"[DUCK_POND] Cortex calculation complete. Time: {time.time()-start:.2f}s")

    # ------------------------------------------------------------------ #
    #  FORNIX HELPERS (Historical Replay)                                 #
    # ------------------------------------------------------------------ #
    def get_tape(self, symbol: str) -> pd.DataFrame:
        """Returns the pre-calculated tape as a Pandas DataFrame (via Arrow)."""
        return self.conn.execute(
            """
            SELECT * FROM cortex_precalc
            WHERE symbol = ?
            ORDER BY ts ASC
            """,
            [symbol],
        ).df()

    def get_symbol_list(self) -> List[str]:
        """Returns all distinct symbols in the market tape."""
        rows = self.conn.execute(
            "SELECT DISTINCT symbol FROM market_tape ORDER BY symbol"
        ).fetchall()
        return [r[0] for r in rows]

    def get_bars_for_symbol(self, symbol: str, after_ts: Optional[str] = None) -> pd.DataFrame:
        """
        Returns chronological 1m OHLCV bars for a symbol from market_tape.
        If after_ts is provided, only returns bars after that timestamp (for resume).
        """
        if after_ts:
            return self.conn.execute(
                """
                SELECT ts, symbol, open, high, low, close, volume
                FROM market_tape
                WHERE symbol = ? AND ts > ?
                ORDER BY ts ASC
                """,
                [symbol, after_ts],
            ).df()
        return self.conn.execute(
            """
            SELECT ts, symbol, open, high, low, close, volume
            FROM market_tape
            WHERE symbol = ?
            ORDER BY ts ASC
            """,
            [symbol],
        ).df()

    def get_bar_count(self, symbol: Optional[str] = None) -> int:
        """Returns total bar count, optionally filtered by symbol."""
        if symbol:
            return self.conn.execute(
                "SELECT count(*) FROM market_tape WHERE symbol = ?",
                [symbol],
            ).fetchone()[0]
        return self.conn.execute("SELECT count(*) FROM market_tape").fetchone()[0]

    def write_synapse_batch(self, tickets: list):
        """
        Bulk inserts minted synapse tickets into history_synapse.
        Each ticket is a dict from BrainFrame.to_synapse_dict().
        """
        if not tickets:
            return
        
        cols = [
            "ts", "symbol", "pulse_type", "open", "high", "low", "close", "volume",
            "price", "active_hi", "active_lo", "gear", "tier1_signal",
            "monte_score", "tier_score", "regime_id",
            "worst_survival", "neutral_survival", "best_survival",
            "council_score", "atr", "atr_avg", "adx", "volume_score",
            "decision", "approved", "final_confidence", "sizing_mult",
            "ready_to_fire", "gold_id", "platinum_id"
        ]
        
        placeholders = ", ".join(["?"] * len(cols))
        col_str = ", ".join(cols)
        
        rows = []
        for t in tickets:
            rows.append(tuple(t.get(c, None) for c in cols))
        
        self.conn.executemany(
            f"INSERT INTO history_synapse ({col_str}) VALUES ({placeholders})",
            rows
        )
        try:
            self.run_sunset(force=False)
        except Exception as e:
            print(f"[DUCK_POND] Sunset skipped after synapse batch: {e}")

    # ------------------------------------------------------------------ #
    #  CHECKPOINT (Resume Support)                                        #
    # ------------------------------------------------------------------ #
    def save_checkpoint(self, symbol: str, last_ts: str, bars_processed: int, mints_generated: int):
        """Saves Fornix progress for resume capability."""
        self.conn.execute("""
            INSERT INTO fornix_checkpoint (symbol, last_ts, bars_processed, mints_generated, updated_at)
            VALUES (?, ?, ?, ?, current_timestamp)
            ON CONFLICT (symbol) DO UPDATE SET
                last_ts = excluded.last_ts,
                bars_processed = excluded.bars_processed,
                mints_generated = excluded.mints_generated,
                updated_at = current_timestamp
        """, [symbol, last_ts, bars_processed, mints_generated])

    def get_checkpoint(self, symbol: str) -> Optional[dict]:
        """Returns the last checkpoint for a symbol, or None."""
        row = self.conn.execute(
            "SELECT last_ts, bars_processed, mints_generated FROM fornix_checkpoint WHERE symbol = ?",
            [symbol]
        ).fetchone()
        if row:
            return {"last_ts": str(row[0]), "bars_processed": row[1], "mints_generated": row[2]}
        return None

    def get_synapse_count(self) -> int:
        """Returns total history synapse ticket count."""
        return self.conn.execute("SELECT count(*) FROM history_synapse").fetchone()[0]

    # ------------------------------------------------------------------ #
    #  LIVE DATA PIPE (V5)                                                #
    # ------------------------------------------------------------------ #
    def _normalize_live_ohlcv_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Normalizes live OHLCV payloads to strict schema:
        ts,symbol,open,high,low,close,volume
        """
        if df is None or df.empty:
            return pd.DataFrame()

        temp_df = df.copy()

        if "pulse_type" in temp_df.columns:
            temp_df = temp_df.drop(columns=["pulse_type"])

        if "ts" not in temp_df.columns:
            temp_df = temp_df.reset_index()
            if "timestamp" in temp_df.columns:
                temp_df.rename(columns={"timestamp": "ts"}, inplace=True)
            elif len(temp_df.columns) > 0 and temp_df.columns[0] != "ts":
                temp_df.rename(columns={temp_df.columns[0]: "ts"}, inplace=True)

        required = ["ts", "symbol", "open", "high", "low", "close", "volume"]
        if any(col not in temp_df.columns for col in required):
            return pd.DataFrame()

        temp_df = temp_df[required].copy()
        temp_df["ts"] = pd.to_datetime(temp_df["ts"], errors="coerce")
        temp_df = temp_df.dropna(subset=["ts", "symbol", "open", "high", "low", "close", "volume"])

        if temp_df.empty:
            return temp_df

        temp_df["symbol"] = temp_df["symbol"].astype(str)
        for col in ["open", "high", "low", "close", "volume"]:
            temp_df[col] = pd.to_numeric(temp_df[col], errors="coerce")

        temp_df = temp_df.dropna(subset=["open", "high", "low", "close", "volume"])
        if temp_df.empty:
            return temp_df

        temp_df = temp_df.sort_values(["symbol", "ts"]).drop_duplicates(subset=["symbol", "ts"], keep="last")
        return temp_df

    def append_live_bars(self, df: pd.DataFrame):
        """
        Appends raw 1m OHLCV bars from the Thalamus into market_tape.
        Deduplicates on (symbol, ts) to prevent double-writes.
        """
        temp_df = self._normalize_live_ohlcv_df(df)
        if temp_df.empty:
            return 0

        # Register as a DuckDB temp table for dedup insert
        self.conn.register("_live_batch", temp_df)
        
        before = self.conn.execute("SELECT count(*) FROM market_tape").fetchone()[0]
        
        self.conn.execute("""
            INSERT INTO market_tape (ts, symbol, open, high, low, close, volume)
            SELECT b.ts, b.symbol, b.open, b.high, b.low, b.close, b.volume
            FROM _live_batch b
            WHERE NOT EXISTS (
                SELECT 1 FROM market_tape m
                WHERE m.symbol = b.symbol AND m.ts = b.ts
            )
        """)
        
        self.conn.unregister("_live_batch")
        
        after = self.conn.execute("SELECT count(*) FROM market_tape").fetchone()[0]
        added = after - before
        if added > 0:
            print(f"[DUCK_POND] Appended {added:,} live bars (total: {after:,})")
            try:
                self.run_sunset(force=False)
            except Exception as e:
                print(f"[DUCK_POND] Sunset skipped after live append: {e}")
        return added

    def append_live_5m_bars(self, df: pd.DataFrame):
        """
        Appends finalized live 5m OHLCV bars into market_tape_5m.
        Deduplicates on (symbol, ts) to prevent double-writes.
        """
        temp_df = self._normalize_live_ohlcv_df(df)
        if temp_df.empty:
            return 0

        self.conn.register("_live_5m_batch", temp_df)
        before = self.conn.execute("SELECT count(*) FROM market_tape_5m").fetchone()[0]

        self.conn.execute("""
            INSERT INTO market_tape_5m (ts, symbol, open, high, low, close, volume)
            SELECT b.ts, b.symbol, b.open, b.high, b.low, b.close, b.volume
            FROM _live_5m_batch b
            WHERE NOT EXISTS (
                SELECT 1 FROM market_tape_5m m
                WHERE m.symbol = b.symbol AND m.ts = b.ts
            )
        """)

        self.conn.unregister("_live_5m_batch")
        after = self.conn.execute("SELECT count(*) FROM market_tape_5m").fetchone()[0]
        added = after - before
        if added > 0:
            print(f"[DUCK_POND] Appended {added:,} live 5m bars (total: {after:,})")
            try:
                self.run_sunset(force=False)
            except Exception as e:
                print(f"[DUCK_POND] Sunset skipped after live 5m append: {e}")
        return added


    def prune_before(self, cutoff_date: str):
        """
        Manual purge: deletes all market_tape rows older than cutoff_date.
        Also cleans cortex_precalc for the same range.
        cutoff_date format: 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS'
        """
        before = self.conn.execute("SELECT count(*) FROM market_tape").fetchone()[0]
        before_5m = self.conn.execute("SELECT count(*) FROM market_tape_5m").fetchone()[0]
        
        self.conn.execute("DELETE FROM market_tape WHERE ts < ?", [cutoff_date])
        self.conn.execute("DELETE FROM market_tape_5m WHERE ts < ?", [cutoff_date])
        self.conn.execute("DELETE FROM cortex_precalc WHERE ts < ?", [cutoff_date])
        
        after = self.conn.execute("SELECT count(*) FROM market_tape").fetchone()[0]
        after_5m = self.conn.execute("SELECT count(*) FROM market_tape_5m").fetchone()[0]
        pruned = before - after
        pruned_5m = before_5m - after_5m
        print(f"[DUCK_POND] Pruned {pruned:,} 1m bars and {pruned_5m:,} 5m bars before {cutoff_date} (remaining 1m: {after:,}, 5m: {after_5m:,})")
        return pruned

    def apply_retention(self, days: int):
        """
        Rolling window: deletes all market_tape rows older than N days from now.
        """
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        print(f"[DUCK_POND] Applying {days}-day retention (cutoff: {cutoff})")
        return self.prune_before(cutoff)

    def clear_history_synapse(self):
        """Wipes the history_synapse and fornix_checkpoint tables (Pineal wipe)."""
        self.conn.execute("DELETE FROM history_synapse")
        self.conn.execute("DELETE FROM fornix_checkpoint")
        print("[DUCK_POND] History synapse and checkpoints cleared (Pineal wipe).")

    def archive_history_synapse(self, run_id: str = "unknown") -> int:
        """
        Copies staged history_synapse tickets into the long-lived archive.
        Returns number of rows archived.
        """
        count = self.get_synapse_count()
        if count <= 0:
            return 0

        self.conn.execute("""
            INSERT INTO brainframe_mint_archive (
                run_id, archived_at, ts, symbol, pulse_type, open, high, low, close, volume,
                price, active_hi, active_lo, gear, tier1_signal, monte_score, tier_score, regime_id,
                worst_survival, neutral_survival, best_survival, council_score, atr, atr_avg, adx,
                volume_score, decision, approved, final_confidence, sizing_mult, ready_to_fire,
                gold_id, platinum_id
            )
            SELECT
                ?, current_timestamp, ts, symbol, pulse_type, open, high, low, close, volume,
                price, active_hi, active_lo, gear, tier1_signal, monte_score, tier_score, regime_id,
                worst_survival, neutral_survival, best_survival, council_score, atr, atr_avg, adx,
                volume_score, decision, approved, final_confidence, sizing_mult, ready_to_fire,
                gold_id, platinum_id
            FROM history_synapse
        """, [run_id])
        print(f"[DUCK_POND] Archived {count:,} history synapse rows under run_id={run_id}.")
        return count

    def archive_and_clear_history_synapse(self, run_id: str = "unknown") -> int:
        """
        Transactionally archive staged history_synapse rows and then wipe staging.
        """
        count = self.get_synapse_count()
        if count <= 0:
            return 0

        try:
            self.conn.execute("BEGIN TRANSACTION")
            self.conn.execute("""
                INSERT INTO brainframe_mint_archive (
                    run_id, archived_at, ts, symbol, pulse_type, open, high, low, close, volume,
                    price, active_hi, active_lo, gear, tier1_signal, monte_score, tier_score, regime_id,
                    worst_survival, neutral_survival, best_survival, council_score, atr, atr_avg, adx,
                    volume_score, decision, approved, final_confidence, sizing_mult, ready_to_fire,
                    gold_id, platinum_id
                )
                SELECT
                    ?, current_timestamp, ts, symbol, pulse_type, open, high, low, close, volume,
                    price, active_hi, active_lo, gear, tier1_signal, monte_score, tier_score, regime_id,
                    worst_survival, neutral_survival, best_survival, council_score, atr, atr_avg, adx,
                    volume_score, decision, approved, final_confidence, sizing_mult, ready_to_fire,
                    gold_id, platinum_id
                FROM history_synapse
            """, [run_id])
            self.conn.execute("DELETE FROM history_synapse")
            self.conn.execute("DELETE FROM fornix_checkpoint")
            self.conn.execute("COMMIT")
            print(f"[DUCK_POND] Archived and wiped {count:,} history synapse rows (run_id={run_id}).")
            return count
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    def get_stats(self) -> dict:
        """Returns all table row counts for the dashboard."""
        return {
            "market_tape": self.conn.execute("SELECT count(*) FROM market_tape").fetchone()[0],
            "market_tape_5m": self.conn.execute("SELECT count(*) FROM market_tape_5m").fetchone()[0],
            "cortex_precalc": self.conn.execute("SELECT count(*) FROM cortex_precalc").fetchone()[0],
            "history_synapse": self.get_synapse_count(),
            "brainframe_mint_archive": self.conn.execute("SELECT count(*) FROM brainframe_mint_archive").fetchone()[0],
            "symbols": len(self.get_symbol_list()),
            "symbol_list": self.get_symbol_list(),
            "sunset_policy": self.get_sunset_policy(),
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DuckPond Data Lake Manager")
    parser.add_argument("--stats", action="store_true", help="Print data lake stats")
    parser.add_argument("--prune-before", type=str, help="Delete bars before date (YYYY-MM-DD)")
    parser.add_argument("--retention", type=int, help="Apply rolling retention (days)")
    parser.add_argument("--wipe-synapse", action="store_true", help="Clear history_synapse (Pineal wipe)")
    parser.add_argument("--sunset-now", action="store_true", help="Run policy-driven sunset immediately")
    args = parser.parse_args()

    pond = DuckPond()

    if args.prune_before:
        pond.prune_before(args.prune_before)
    elif args.retention:
        pond.apply_retention(args.retention)
    elif args.wipe_synapse:
        pond.clear_history_synapse()
    elif args.sunset_now:
        print(pond.run_sunset(force=True))
    else:
        stats = pond.get_stats()
        print(f"Symbols ({stats['symbols']}): {stats['symbol_list'][:5]}...")
        print(f"market_tape:     {stats['market_tape']:>12,} rows")
        print(f"cortex_precalc:  {stats['cortex_precalc']:>12,} rows")
        print(f"history_synapse: {stats['history_synapse']:>12,} rows")
        print(f"sunset_policy:   {stats['sunset_policy']}")
