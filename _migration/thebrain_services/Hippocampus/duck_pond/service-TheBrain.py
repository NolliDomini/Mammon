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
        self._run_migrations() # Piece 145/146
    
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
                volume DOUBLE,
                bid DOUBLE,
                ask DOUBLE,
                bid_size DOUBLE,
                ask_size DOUBLE
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
                volume DOUBLE,
                bid DOUBLE,
                ask DOUBLE,
                bid_size DOUBLE,
                ask_size DOUBLE
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
                bid_ask_bps DOUBLE,
                spread_score DOUBLE,
                spread_regime VARCHAR,
                val_mean DOUBLE,
                val_std_dev DOUBLE,
                val_z_distance DOUBLE,
                exec_total_cost_bps DOUBLE,
                qty DOUBLE,
                notional DOUBLE,
                cost_adjusted_conviction DOUBLE,
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
                bid_ask_bps DOUBLE,
                spread_score DOUBLE,
                spread_regime VARCHAR,
                val_mean DOUBLE,
                val_std_dev DOUBLE,
                val_z_distance DOUBLE,
                exec_total_cost_bps DOUBLE,
                qty DOUBLE,
                notional DOUBLE,
                cost_adjusted_conviction DOUBLE,
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
        self._init_sunset_policy()

    def _run_migrations(self):
        """Piece 145/146: In-place migration for historical lakes."""
        tables = ["history_synapse", "brainframe_mint_archive"]
        new_cols = [
            ("bid_ask_bps", "DOUBLE"), ("spread_score", "DOUBLE"), ("spread_regime", "VARCHAR"),
            ("val_mean", "DOUBLE"), ("val_std_dev", "DOUBLE"), ("val_z_distance", "DOUBLE"),
            ("exec_total_cost_bps", "DOUBLE"), ("qty", "DOUBLE"), ("notional", "DOUBLE"),
            ("cost_adjusted_conviction", "DOUBLE")
        ]
        for table in tables:
            for col, dtype in new_cols:
                try:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {dtype}")
                except:
                    pass

    def _set_setting(self, key: str, value: str):
        self.conn.execute("""
            INSERT INTO pond_settings (key, value, updated_at)
            VALUES (?, ?, now())
            ON CONFLICT (key) DO UPDATE SET
                value = excluded.value,
                updated_at = now()
        """, [key, str(value)])

    def _set_setting_if_missing(self, key: str, value: str):
        exists = self.conn.execute("SELECT 1 FROM pond_settings WHERE key = ?", [key]).fetchone()
        if not exists: self._set_setting(key, value)

    def _get_setting(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM pond_settings WHERE key = ?", [key]).fetchone()
        return row[0] if row else default

    def _init_sunset_policy(self):
        self._set_setting_if_missing("sunset.market_tape_days", str(self._env_int("MAMMON_SUNSET_MARKET_DAYS", 0)))
        self._set_setting_if_missing("sunset.market_tape_5m_days", str(self._env_int("MAMMON_SUNSET_MARKET_5M_DAYS", 0)))
        self._set_setting_if_missing("sunset.cortex_precalc_days", str(self._env_int("MAMMON_SUNSET_CORTEX_DAYS", 0)))
        self._set_setting_if_missing("sunset.history_synapse_days", str(self._env_int("MAMMON_SUNSET_HISTORY_DAYS", 14)))
        self._set_setting_if_missing("sunset.fornix_checkpoint_days", str(self._env_int("MAMMON_SUNSET_CHECKPOINT_DAYS", 30)))
        self._set_setting_if_missing("sunset.min_interval_minutes", str(self._env_int("MAMMON_SUNSET_INTERVAL_MINUTES", 720)))
        self._set_setting_if_missing("sunset.brainframe_archive_days", str(self._env_int("MAMMON_SUNSET_ARCHIVE_DAYS", 0)))
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

    def _prune_table_by_days(self, table: str, timestamp_col: str, days: int) -> int:
        if days <= 0: return 0
        from datetime import timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        prunable = self.conn.execute(f"SELECT count(*) FROM {table} WHERE {timestamp_col} < ?", [cutoff]).fetchone()[0]
        if prunable <= 0: return 0
        self.conn.execute(f"DELETE FROM {table} WHERE {timestamp_col} < ?", [cutoff])
        return prunable

    def run_sunset(self, force: bool = False) -> dict:
        from datetime import timezone
        policy = self.get_sunset_policy()
        now = datetime.now(timezone.utc)
        deleted = {
            "market_tape": self._prune_table_by_days("market_tape", "ts", policy["market_tape_days"]),
            "market_tape_5m": self._prune_table_by_days("market_tape_5m", "ts", policy["market_tape_5m_days"]),
            "cortex_precalc": self._prune_table_by_days("cortex_precalc", "ts", policy["cortex_precalc_days"]),
            "history_synapse": self._prune_table_by_days("history_synapse", "ts", policy["history_synapse_days"]),
            "fornix_checkpoint": self._prune_table_by_days("fornix_checkpoint", "updated_at", policy["fornix_checkpoint_days"]),
            "brainframe_mint_archive": self._prune_table_by_days("brainframe_mint_archive", "archived_at", policy["brainframe_archive_days"]),
        }
        self._set_setting("sunset.last_run_utc", now.isoformat(timespec="seconds"))
        if sum(deleted.values()) > 0: self.conn.execute("CHECKPOINT")
        return {"ran": True, "deleted": deleted, "total_deleted": sum(deleted.values()), "policy": self.get_sunset_policy()}

    def ingest_csv(self, csv_path: str):
        """Piece 14: Dynamic ingestion for Phase 1 expanded schema."""
        # Check available columns in CSV
        csv_cols = self.conn.execute(f"SELECT * FROM read_csv_auto('{csv_path}', header=True) LIMIT 0").df().columns
        
        target_cols = ["ts", "symbol", "open", "high", "low", "close", "volume"]
        for c in ["bid", "ask", "bid_size", "ask_size"]:
            if c in csv_cols:
                target_cols.append(c)
        
        col_str = ", ".join(target_cols)
        
        self.conn.execute(f"""
            INSERT INTO market_tape ({col_str}) 
            SELECT {col_str} FROM read_csv_auto('{csv_path}', header=True) 
            WHERE interval = '1Min' 
            EXCEPT 
            SELECT {col_str} FROM market_tape
        """)
        
        # Relocated to Council lobe (Indicator Authority)
        from Cerebellum.council.service import Council
        Council().calculate_cortex_cache()

    def get_symbol_list(self) -> List[str]:
        """Returns all distinct symbols in the market tape."""
        rows = self.conn.execute("SELECT DISTINCT symbol FROM market_tape ORDER BY symbol").fetchall()
        return [r[0] for r in rows]

    def get_bar_count(self, symbol: Optional[str] = None) -> int:
        """Returns total bar count, optionally filtered by symbol."""
        if symbol:
            return self.conn.execute("SELECT count(*) FROM market_tape WHERE symbol = ?", [symbol]).fetchone()[0]
        return self.conn.execute("SELECT count(*) FROM market_tape").fetchone()[0]

    def get_bars_for_symbol(self, symbol: str, after_ts: Optional[str] = None) -> pd.DataFrame:
        sql = "SELECT ts, symbol, open, high, low, close, volume FROM market_tape WHERE symbol = ?"
        params = [symbol]
        if after_ts:
            sql += " AND ts > ?"
            params.append(after_ts)
        return self.conn.execute(sql + " ORDER BY ts ASC", params).df()

    def _normalize_live_ohlcv_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """Helper to normalize incoming live data before registration."""
        temp_df = df.copy()
        if temp_df.empty:
            return temp_df
        
        if "ts" not in temp_df.columns and isinstance(temp_df.index, pd.DatetimeIndex):
            temp_df = temp_df.reset_index().rename(columns={"index": "ts", "timestamp": "ts"})
            
        temp_df["symbol"] = temp_df["symbol"].astype(str)
        cols_to_fix = ["open", "high", "low", "close", "volume"]
        for c in ["bid", "ask", "bid_size", "ask_size"]:
            if c in temp_df.columns:
                cols_to_fix.append(c)
                
        for col in cols_to_fix:
            temp_df[col] = pd.to_numeric(temp_df[col], errors="coerce")
            
        temp_df = temp_df.dropna(subset=["open", "high", "low", "close", "volume"])
        if temp_df.empty:
            return temp_df
            
        subset = ["symbol", "ts"]
        temp_df = temp_df.sort_values(subset).drop_duplicates(subset=subset, keep="last")
        return temp_df

    def append_live_bars(self, df: pd.DataFrame):
        """
        Piece 14: Appends raw 1m OHLCV bars including bid/ask/size.
        """
        temp_df = self._normalize_live_ohlcv_df(df)
        if temp_df.empty:
            return 0
            
        self.conn.register("_live_batch", temp_df)
        
        target_cols = ["ts", "symbol", "open", "high", "low", "close", "volume"]
        for c in ["bid", "ask", "bid_size", "ask_size"]:
            if c in temp_df.columns:
                target_cols.append(c)
        
        col_str = ", ".join(target_cols)
        
        before = self.conn.execute("SELECT count(*) FROM market_tape").fetchone()[0]
        
        self.conn.execute(f"""
            INSERT INTO market_tape ({col_str})
            SELECT {col_str} FROM _live_batch
            EXCEPT
            SELECT {col_str} FROM market_tape
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
        Piece 15: Appends finalized 5m OHLCV bars including bid/ask/size.
        """
        temp_df = self._normalize_live_ohlcv_df(df)
        if temp_df.empty:
            return 0
            
        self.conn.register("_live_5m_batch", temp_df)
        
        target_cols = ["ts", "symbol", "open", "high", "low", "close", "volume"]
        for c in ["bid", "ask", "bid_size", "ask_size"]:
            if c in temp_df.columns:
                target_cols.append(c)
        
        col_str = ", ".join(target_cols)
        
        before = self.conn.execute("SELECT count(*) FROM market_tape_5m").fetchone()[0]
        
        self.conn.execute(f"""
            INSERT INTO market_tape_5m ({col_str})
            SELECT {col_str} FROM _live_5m_batch
            EXCEPT
            SELECT {col_str} FROM market_tape_5m
        """)
        
        self.conn.unregister("_live_5m_batch")
        after = self.conn.execute("SELECT count(*) FROM market_tape_5m").fetchone()[0]
        added = after - before
        if added > 0:
            print(f"[DUCK_POND] Appended {added:,} live 5m bars (total: {after:,})")
        return added

    def write_synapse_batch(self, tickets: list):
        if not tickets: return
        cols = [
            "ts", "symbol", "pulse_type", "open", "high", "low", "close", "volume",
            "price", "active_hi", "active_lo", "gear", "tier1_signal",
            "monte_score", "tier_score", "regime_id",
            "worst_survival", "neutral_survival", "best_survival",
            "council_score", "atr", "atr_avg", "adx", "volume_score",
            "decision", "approved", "final_confidence", "sizing_mult",
            "ready_to_fire", "gold_id", "platinum_id",
            "bid_ask_bps", "spread_score", "spread_regime",
            "val_mean", "val_std_dev", "val_z_distance",
            "exec_total_cost_bps", "qty", "notional", "cost_adjusted_conviction"
        ]
        placeholders = ", ".join(["?"] * len(cols))
        rows = [tuple(t.get(c, None) for c in cols) for t in tickets]
        self.conn.executemany(f"INSERT INTO history_synapse ({', '.join(cols)}) VALUES ({placeholders})", rows)

    def save_checkpoint(self, symbol: str, last_ts: str, bars_processed: int, mints_generated: int):
        self.conn.execute("INSERT INTO fornix_checkpoint (symbol, last_ts, bars_processed, mints_generated, updated_at) VALUES (?, ?, ?, ?, now()) ON CONFLICT (symbol) DO UPDATE SET last_ts = excluded.last_ts, bars_processed = excluded.bars_processed, mints_generated = excluded.mints_generated, updated_at = now()", [symbol, last_ts, bars_processed, mints_generated])

    def get_checkpoint(self, symbol: str) -> Optional[dict]:
        row = self.conn.execute("SELECT last_ts, bars_processed, mints_generated FROM fornix_checkpoint WHERE symbol = ?", [symbol]).fetchone()
        return {"last_ts": str(row[0]), "bars_processed": row[1], "mints_generated": row[2]} if row else None

    def get_synapse_count(self) -> int:
        return self.conn.execute("SELECT count(*) FROM history_synapse").fetchone()[0]

    def archive_history_synapse(self, run_id: str = "unknown") -> int:
        count = self.get_synapse_count()
        if count <= 0: return 0
        cols = [
            "ts", "symbol", "pulse_type", "open", "high", "low", "close", "volume",
            "price", "active_hi", "active_lo", "gear", "tier1_signal", "monte_score", "tier_score", "regime_id",
            "worst_survival", "neutral_survival", "best_survival", "council_score", "atr", "atr_avg", "adx",
            "volume_score", "decision", "approved", "final_confidence", "sizing_mult", "ready_to_fire",
            "bid_ask_bps", "spread_score", "spread_regime", "val_mean", "val_std_dev", "val_z_distance",
            "exec_total_cost_bps", "qty", "notional", "cost_adjusted_conviction", "gold_id", "platinum_id"
        ]
        self.conn.execute(f"INSERT INTO brainframe_mint_archive (run_id, archived_at, {', '.join(cols)}) SELECT ?, now(), {', '.join(cols)} FROM history_synapse", [run_id])
        return count

    def close(self):
        if self.conn: self.conn.close()

if __name__ == "__main__":
    pond = DuckPond()
    print(f"DuckPond active: {pond.db_path}")
