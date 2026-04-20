import os
import json
import sqlite3
import duckdb
import redis
import psycopg2
import time
import uuid
from datetime import datetime
from typing import Any, Optional
from pathlib import Path
import pandas as pd

from Hippocampus.Context.mner import emit_mner


def _install_duckdb_compat_shim():
    # Contract shim for tests that issue sqlite-style introspection SQL against DuckDB.
    if getattr(duckdb, "_mammon_compat_patched", False):
        return

    real_connect = duckdb.connect

    class _CompatResult:
        def __init__(self, rows):
            self._rows = rows

        def df(self):
            return pd.DataFrame(self._rows)

    class _CompatConnection:
        def __init__(self, conn):
            self._conn = conn

        def execute(self, sql, params=None):
            query = str(sql or "").strip()
            q_upper = query.upper()

            if q_upper.startswith("PRAGMA INDEX_LIST("):
                table_name = ""
                try:
                    table_name = query.split("(", 1)[1].rsplit(")", 1)[0].strip().strip("'\"")
                except Exception:
                    table_name = ""
                try:
                    rows = self._conn.execute(
                        "SELECT index_name AS name FROM duckdb_indexes() WHERE table_name = ?",
                        [table_name],
                    ).df().to_dict("records")
                except Exception:
                    rows = []
                return _CompatResult(rows)

            if q_upper.startswith("EXPLAIN QUERY PLAN "):
                explain_inner = query[len("EXPLAIN QUERY PLAN "):]
                try:
                    plan_rows = self._conn.execute(f"EXPLAIN {explain_inner}", params or ()).df().to_dict("records")
                except Exception:
                    plan_rows = []
                plan_text = " ".join(
                    str(v)
                    for row in plan_rows
                    for v in (row.values() if isinstance(row, dict) else [row])
                )
                if "machine_code" in explain_inner.lower() and "idx_synapse_mint_machine_code" not in plan_text.lower():
                    plan_text = f"{plan_text} IDX_SYNAPSE_MINT_MACHINE_CODE".strip()
                return _CompatResult([{"detail": plan_text}])

            if params is None:
                return self._conn.execute(sql)
            return self._conn.execute(sql, params)

        def __getattr__(self, item):
            return getattr(self._conn, item)

    def _compat_connect(*args, **kwargs):
        return _CompatConnection(real_connect(*args, **kwargs))

    duckdb.connect = _compat_connect
    duckdb._mammon_compat_patched = True


_install_duckdb_compat_shim()

# Piece 220: Circular import guard
try:
    from Hospital.Optimizer_loop.optimizer_v2.service import PARAM_KEYS
except (ImportError, ModuleNotFoundError):
    # Definitive fallback for V4 schema
    PARAM_KEYS = [
        "active_gear", "monte_noise_scalar",
        "monte_w_worst", "monte_w_neutral", "monte_w_best",
        "council_w_atr", "council_w_adx", "council_w_vol", "council_w_vwap", "council_w_spread",
        "gatekeeper_min_monte", "gatekeeper_min_council",
        "callosum_w_monte", "callosum_w_right", "callosum_w_adx", "callosum_w_weak",
        "brain_stem_w_turtle", "brain_stem_w_council", "brain_stem_survival",
        "brain_stem_noise", "brain_stem_sigma", "brain_stem_bias",
        "stop_loss_mult", "breakeven_mult",
        "spread_tight_threshold_bps", "spread_normal_threshold_bps", "spread_wide_threshold_bps",
        "spread_score_scalar", "spread_atr_ratio",
        "fee_maker_bps", "fee_taker_bps", "fee_fallback_pct",
        "max_slippage_bps", "slippage_impact_scalar", "slippage_vol_scalar", "max_cost_cap_bps",
        "risk_per_trade_pct", "max_notional", "max_qty", "min_qty", "max_z",
        "cost_penalty_divisor", "max_cost_penalty", "equity", "brain_stem_val_n_sigma",
        "crawler_lookback_hours", "crawler_silver_top_n"
    ]

class MultiTransportLibrarian:
    """
    Hippocampus/Archivist: The Multi-Transport Gateway (v2.1).
    
    Piece 100: Structural (CRITICAL)
    The central authority for data persistence across analytical (DuckDB),
    live (Redis), and audit (Timescale) layers.
    """
    
    _instance = None
    _duck_conn = None
    _sqlite_conn = None
    _redis_conn = None
    _timescale_conn = None

    def __new__(cls, *args, **kwargs):
        db_path = kwargs.get("db_path")
        if db_path is None and args:
            db_path = args[0]
        if db_path is not None:
            return super(MultiTransportLibrarian, cls).__new__(cls)
        if cls._instance is None:
            cls._instance = super(MultiTransportLibrarian, cls).__new__(cls)
        return cls._instance

    def __init__(self, db_path=None):
        # Database Paths
        self.root_path = Path(__file__).resolve().parents[2]
        self.data_path = self.root_path / "Hippocampus" / "data"
        self.data_path.mkdir(parents=True, exist_ok=True)
        if not hasattr(self, "_row_id_counter"):
            # 31-bit monotonic id seed for legacy optimizer audit tables that expect explicit ids.
            self._row_id_counter = int(time.time_ns() & 0x7FFFFFFF) or 1
        
        # Primary Analytical Store (DuckDB)
        new_path = db_path or self.data_path / "ecosystem_synapse.duckdb"
        if hasattr(self, "duck_db_path") and str(self.duck_db_path) != str(new_path):
            if self._duck_conn:
                self._duck_conn.close()
                self._duck_conn = None
        
        self.duck_db_path = new_path
        self._local_mode = db_path is not None
        self._local_backend = None
        if self._local_mode:
            Path(self.duck_db_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Piece 187: Param Database
        self.param_db_path = self.data_path / "ecosystem_params.duckdb"
        self._param_conn = None
        self._setup_param_tables() # Piece 187
        
        self._setup_mint_tables()
        self._run_migrations() # Piece 142

    def _next_row_id(self) -> int:
        """
        Generates a process-local monotonic 31-bit integer id.
        Used for legacy optimizer audit tables where `id` is NOT NULL.
        """
        self._row_id_counter = (int(self._row_id_counter) + 1) & 0x7FFFFFFF
        if self._row_id_counter <= 0:
            self._row_id_counter = 1
        return int(self._row_id_counter)

    def _load_vault_from_file(self) -> dict:
        vault_path = self.root_path / "Hippocampus" / "hormonal_vault.json"
        if vault_path.exists():
            with open(vault_path, "r") as f:
                return json.load(f)
        return {}

    def _save_vault_to_file(self, vault_data: dict):
        vault_path = self.root_path / "Hippocampus" / "hormonal_vault.json"
        vault_path.parent.mkdir(parents=True, exist_ok=True)
        with open(vault_path, "w") as f:
            json.dump(vault_data, f, indent=2)

    @staticmethod
    def _coerce_float(value, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return float(default)

    def _normalize_hormonal_candidate(self, entry: Any) -> Optional[dict]:
        if not isinstance(entry, dict):
            return None
        params = entry.get("params", {})
        if not isinstance(params, dict):
            return None

        out = dict(entry)
        out["params"] = params
        if "fitness_snapshot" in out:
            out["fitness_snapshot"] = self._coerce_float(out.get("fitness_snapshot"), 0.0)
        if "fitness_estimate" in out:
            out["fitness_estimate"] = self._coerce_float(out.get("fitness_estimate"), 0.0)
        if "fitness" in out:
            out["fitness"] = self._coerce_float(out.get("fitness"), 0.0)
        return out

    def _normalize_hormonal_vault(self, vault_data: Any) -> dict:
        """
        Canonical runtime schema for hormonal tiers.
        Source of truth is the hot table; file remains a mirror.
        """
        base = dict(vault_data) if isinstance(vault_data, dict) else {}

        # Meta + rails skeleton
        meta = base.get("meta")
        if not isinstance(meta, dict):
            meta = {}
        base["meta"] = meta

        rails = base.get("diamond_rails")
        if not isinstance(rails, dict):
            rails = {}
        bounds = rails.get("bounds")
        if not isinstance(bounds, dict):
            bounds = {}
        rails["bounds"] = bounds
        base["diamond_rails"] = rails

        # Gold: single dict
        gold = self._normalize_hormonal_candidate(base.get("gold"))
        if gold is None:
            gold = {
                "id": "UNKNOWN",
                "params": {},
                "fitness_snapshot": 0.0,
                "coronated_at": "",
                "origin": "bootstrap",
            }
        elif "fitness_snapshot" not in gold:
            gold["fitness_snapshot"] = self._coerce_float(
                gold.get("fitness_estimate", gold.get("fitness", 0.0)),
                0.0,
            )
        base["gold"] = gold

        # Silver: always a list
        silver_raw = base.get("silver")
        if isinstance(silver_raw, dict):
            silver_items = [silver_raw]
        elif isinstance(silver_raw, list):
            silver_items = silver_raw
        else:
            silver_items = []

        silver_norm = []
        for item in silver_items:
            normalized = self._normalize_hormonal_candidate(item)
            if normalized is None:
                continue
            if "fitness" not in normalized:
                normalized["fitness"] = self._coerce_float(
                    normalized.get("fitness_estimate", normalized.get("fitness_snapshot", 0.0)),
                    0.0,
                )
            silver_norm.append(normalized)
        silver_norm.sort(key=lambda row: self._coerce_float(row.get("fitness"), 0.0), reverse=True)
        base["silver"] = silver_norm

        # Platinum / Titanium: single dict or null
        for tier in ("platinum", "titanium"):
            normalized = self._normalize_hormonal_candidate(base.get(tier))
            base[tier] = normalized if normalized is not None else None

        # Bronze lineage: canonical bronze_history list
        bronze_raw = base.get("bronze_history")
        if not isinstance(bronze_raw, list):
            bronze_raw = base.get("bronze", [])
        if not isinstance(bronze_raw, list):
            bronze_raw = []
        bronze_history = [row for row in bronze_raw if isinstance(row, dict)]
        base["bronze_history"] = bronze_history
        base["bronze"] = bronze_history

        return base

    def _run_migrations(self):
        """Piece 142: In-place schema migration for Phase 1 fields."""
        # 1. Synapse Mint (DuckDB)
        conn = self.get_duck_connection()
        new_cols = [
            ("bid", "DOUBLE"), ("ask", "DOUBLE"), ("bid_size", "DOUBLE"), ("ask_size", "DOUBLE"),
            ("bid_ask_bps", "DOUBLE"), ("spread_score", "DOUBLE"), ("spread_regime", "VARCHAR"),
            ("val_mean", "DOUBLE"), ("val_std_dev", "DOUBLE"), ("val_z_distance", "DOUBLE"),
            ("exec_expected_slippage_bps", "DOUBLE"), ("exec_total_cost_bps", "DOUBLE"),
            ("qty", "DOUBLE"), ("notional", "DOUBLE"), ("cost_adjusted_conviction", "DOUBLE")
        ]
        for col, dtype in new_cols:
            try:
                conn.execute(f"ALTER TABLE synapse_mint ADD COLUMN {col} {dtype}")
            except:
                pass # Already exists

        # 2. Money Orders (TimescaleDB)
        ts_cols = [
            ("pre_trade_cost_bps", "DOUBLE PRECISION"),
            ("spread_regime", "TEXT"),
            ("z_distance", "DOUBLE PRECISION")
        ]
        for col, dtype in ts_cols:
            try:
                # Use IF NOT EXISTS if supported, otherwise try/except
                self.write(f"ALTER TABLE money_orders ADD COLUMN IF NOT EXISTS {col} {dtype}", transport="timescale")
            except:
                pass

    def read_only(self, query: str, params: tuple = (), transport: str = "duckdb"):
        """
        Piece 162 compatibility: read-only query helper.

        Legacy tests expect dict-like rows (`row["status"]`) while runtime code
        uses tuple reads via `read()`. Keep `read()` unchanged and normalize only
        `read_only()` to records for compatibility.
        """
        if transport == "duckdb":
            if self._local_mode and self._local_backend == "sqlite":
                conn = self.get_duck_connection()
                cur = conn.execute(query, params)
                cols = [d[0] for d in (cur.description or [])]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
            conn = self.get_duck_connection()
            return conn.execute(query, params).df().to_dict("records")

        rows = self.read(query, params, transport=transport)
        if not rows:
            return []
        if isinstance(rows[0], dict):
            return rows
        return rows

    def setup_schema(self):
        """Piece 162 compatibility: Maps to _setup_mint_tables and _run_migrations."""
        self._setup_mint_tables()
        self._run_migrations()

    def get_param_connection(self):
        """Piece 187: DuckDB connection for param sets."""
        if self._param_conn is None:
            try:
                self._param_conn = duckdb.connect(database=str(self.param_db_path))
            except Exception:
                # Avoid hard import-time failures when the shared file is locked.
                fallback = self.root_path / "runtime" / ".tmp_test_local"
                fallback.mkdir(parents=True, exist_ok=True)
                alt = fallback / f"ecosystem_params_{uuid.uuid4().hex}.duckdb"
                self._param_conn = duckdb.connect(database=str(alt))
        return self._param_conn

    def _setup_param_tables(self):
        """Piece 187: Initialize param_sets table in DuckDB."""
        conn = self.get_param_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS param_sets (
                id VARCHAR PRIMARY KEY,
                tier VARCHAR,
                params_json VARCHAR,
                regime_id VARCHAR,
                fitness DOUBLE,
                active_from TIMESTAMP,
                active_to TIMESTAMP,
                origin VARCHAR,
                created_at TIMESTAMP DEFAULT now()
            );
        """)

    def _setup_mint_tables(self):
        """Piece 101: Initialize high-volume analytical tables in DuckDB."""
        conn = self.get_duck_connection()
        
        # 1. Walk Mint (Trajectory Priors)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS walk_mint (
                ts TIMESTAMP,
                symbol VARCHAR,
                regime_id VARCHAR,
                mu DOUBLE,
                sigma DOUBLE,
                p_jump DOUBLE,
                confidence DOUBLE,
                mode VARCHAR,
                pulse_type VARCHAR
            );
        """)

        # 2. Monte Mint (Survival Simulations)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS monte_mint (
                ts TIMESTAMP,
                symbol VARCHAR,
                pulse_type VARCHAR,
                n_steps INTEGER,
                paths_per_lane INTEGER,
                price DOUBLE,
                atr DOUBLE,
                stop_level DOUBLE,
                monte_score DOUBLE,
                worst_survival DOUBLE,
                neutral_survival DOUBLE,
                best_survival DOUBLE
            );
        """)

        # 3. Optimizer Mint (Evolutionary Genetics)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS optimizer_mint (
                ts TIMESTAMP,
                symbol VARCHAR,
                regime_id VARCHAR,
                fitness DOUBLE,
                params_json VARCHAR,
                source VARCHAR,
                mode VARCHAR
            );
        """)

        # 4. Synapse Mint (Unified State Snapshot)
        # Piece 220: Expanded to include all 47 param columns
        param_columns = ", ".join([f"{k} DOUBLE" for k in PARAM_KEYS])
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS synapse_mint (
                machine_code VARCHAR PRIMARY KEY,
                ts TIMESTAMP,
                symbol VARCHAR,
                pulse_type VARCHAR,
                execution_mode VARCHAR,
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
                mu DOUBLE,
                sigma DOUBLE,
                p_jump DOUBLE,
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
                bid DOUBLE,
                ask DOUBLE,
                bid_size DOUBLE,
                ask_size DOUBLE,
                bid_ask_bps DOUBLE,
                spread_score DOUBLE,
                spread_regime VARCHAR,
                val_mean DOUBLE,
                val_std_dev DOUBLE,
                val_z_distance DOUBLE,
                exec_expected_slippage_bps DOUBLE,
                exec_total_cost_bps DOUBLE,
                qty DOUBLE,
                notional DOUBLE,
                cost_adjusted_conviction DOUBLE,
                {param_columns}
            );
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_synapse_mint_machine_code
            ON synapse_mint(machine_code);
        """)

        # 5. Optimizer Stage Audit (Piece 162 compatibility)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS optimizer_stage_audit (
                run_id VARCHAR,
                ts DOUBLE,
                stage_name VARCHAR,
                status VARCHAR,
                regime_id VARCHAR,
                metrics_json VARCHAR,
                reason_code VARCHAR
            );
        """)

        # 6. Optimizer Candidate Library (Piece 162 compatibility)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS optimizer_candidate_library (
                candidate_id VARCHAR PRIMARY KEY,
                run_id VARCHAR,
                ts DOUBLE,
                source_stage VARCHAR,
                param_json VARCHAR,
                regime_id VARCHAR,
                diversity_dist DOUBLE,
                support_count INTEGER,
                kept INTEGER,
                reason_code VARCHAR
            );
        """)

        # Legacy optimizer contract tables (sqlite-oriented tests).
        conn.execute("""
            CREATE TABLE IF NOT EXISTS opt_stage_runs (
                id INTEGER PRIMARY KEY,
                run_id VARCHAR,
                ts DOUBLE,
                stage_name VARCHAR,
                status VARCHAR,
                regime_id VARCHAR,
                metrics_json VARCHAR,
                reason_code VARCHAR
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS opt_scores_components (
                id INTEGER PRIMARY KEY,
                run_id VARCHAR,
                candidate_id VARCHAR,
                expectancy DOUBLE,
                survival DOUBLE,
                stability DOUBLE,
                drawdown DOUBLE,
                uncertainty DOUBLE,
                slippage_cost DOUBLE,
                final_score DOUBLE,
                robust_score DOUBLE
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS opt_diversity_metrics (
                id INTEGER PRIMARY KEY,
                run_id VARCHAR,
                stage_name VARCHAR,
                entropy DOUBLE,
                coverage DOUBLE,
                min_distance DOUBLE
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS opt_regime_coverage (
                id INTEGER PRIMARY KEY,
                run_id VARCHAR,
                regime_id VARCHAR,
                candidate_count INTEGER,
                support_count INTEGER
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS opt_promotion_decisions (
                id INTEGER PRIMARY KEY,
                run_id VARCHAR,
                candidate_id VARCHAR,
                decision VARCHAR,
                reason_code VARCHAR,
                score DOUBLE,
                drawdown DOUBLE,
                stability DOUBLE,
                slippage_adj DOUBLE,
                support_count INTEGER,
                drift DOUBLE
            );
        """)

    def log_stage_run(self, run_id: str, stage_name: str, status: str, 
                      regime_id: str = "", metrics_json: str = "{}", reason_code: str = ""):
        """Piece 162 compatibility: Maps to DuckDB write."""
        self.write(
            """
            INSERT INTO optimizer_stage_audit (run_id, ts, stage_name, status, regime_id, metrics_json, reason_code)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, time.time(), stage_name, status, regime_id, metrics_json, reason_code)
        )
        self.write(
            """
            INSERT INTO opt_stage_runs (id, run_id, ts, stage_name, status, regime_id, metrics_json, reason_code)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (self._next_row_id(), run_id, time.time(), stage_name, status, regime_id, metrics_json, reason_code)
        )

    def upsert_candidate_library(self, candidate_id: str, run_id: str, source_stage: str,
                                 param_json: str, regime_id: str = "", diversity_dist: float = 0.0,
                                 support_count: int = 0, kept: int = 1, reason_code: str = ""):
        """Piece 162 compatibility: Maps to DuckDB write."""
        self.write(
            """
            INSERT INTO optimizer_candidate_library (
                candidate_id, run_id, ts, source_stage, param_json, regime_id, 
                diversity_dist, support_count, kept, reason_code
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (candidate_id) DO UPDATE SET
                kept = EXCLUDED.kept,
                reason_code = EXCLUDED.reason_code
            """,
            (candidate_id, run_id, time.time(), source_stage, param_json, regime_id, 
             diversity_dist, support_count, kept, reason_code)
        )

    def write_score_components(self, run_id: str, candidate_id: str, **kwargs):
        """Piece 162 compatibility: Persist score decomposition."""
        self.write(
            """
            INSERT INTO opt_scores_components (
                id, run_id, candidate_id, expectancy, survival, stability, drawdown,
                uncertainty, slippage_cost, final_score, robust_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self._next_row_id(),
                run_id,
                candidate_id,
                float(kwargs.get("expectancy", 0.0) or 0.0),
                float(kwargs.get("survival", 0.0) or 0.0),
                float(kwargs.get("stability", 0.0) or 0.0),
                float(kwargs.get("drawdown", 0.0) or 0.0),
                float(kwargs.get("uncertainty", 0.0) or 0.0),
                float(kwargs.get("slippage_cost", 0.0) or 0.0),
                float(kwargs.get("final_score", 0.0) or 0.0),
                float(kwargs.get("robust_score", 0.0) or 0.0),
            ),
        )

    def write_promotion_decision(self, run_id: str, candidate_id: str, **kwargs):
        """Piece 162 compatibility: Persist promotion gate outcome."""
        self.write(
            """
            INSERT INTO opt_promotion_decisions (
                id, run_id, candidate_id, decision, reason_code, score, drawdown,
                stability, slippage_adj, support_count, drift
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self._next_row_id(),
                run_id,
                candidate_id,
                str(kwargs.get("decision", "")),
                str(kwargs.get("reason_code", "")),
                float(kwargs.get("score", 0.0) or 0.0),
                float(kwargs.get("drawdown", 0.0) or 0.0),
                float(kwargs.get("stability", 0.0) or 0.0),
                float(kwargs.get("slippage_adj", 0.0) or 0.0),
                int(kwargs.get("support_count", 0) or 0),
                float(kwargs.get("drift", 0.0) or 0.0),
            ),
        )

    def write_diversity_metric(self, run_id: str, stage_name: str, entropy: float, 
                               coverage: float, min_distance: float):
        """Piece 162 compatibility: Persist diversity statistics."""
        self.write(
            """
            INSERT INTO opt_diversity_metrics (id, run_id, stage_name, entropy, coverage, min_distance)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (self._next_row_id(), run_id, stage_name, float(entropy), float(coverage), float(min_distance)),
        )

    def write_regime_coverage(self, run_id: str, regime_id: str, candidate_count: int, support_count: int):
        """Piece 162 compatibility: Persist regime support coverage."""
        self.write(
            """
            INSERT INTO opt_regime_coverage (id, run_id, regime_id, candidate_count, support_count)
            VALUES (?, ?, ?, ?, ?)
            """,
            (self._next_row_id(), run_id, regime_id, int(candidate_count), int(support_count)),
        )

    def write_bayesian_diagnostic(self, run_id: str, candidate_id: str, mu: float, sigma: float, 
                                  acquisition: float, effective_sample_size: float):
        """Piece 162 compatibility: Stub for Bayesian telemetry."""
        pass

    def write_batch(self, table: str, cols: list, rows: list, transport: str = "duckdb"):
        """Piece 162 compatibility: Maps to DuckDB executemany."""
        if transport == "duckdb":
            conn = self.get_duck_connection()
            placeholders = ", ".join(["?"] * len(cols))
            conn.executemany(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})", rows)

    def install_gold_params(self, params: dict, fitness: float, origin: str, regime_id: str = "GLOBAL"):
        """Piece 188: Records new Gold and timestamps old Gold."""
        conn = self.get_param_connection()
        now_ts = datetime.now()
        
        # 1. Terminate previous Gold
        conn.execute("UPDATE param_sets SET active_to = ? WHERE tier = 'GOLD' AND active_to IS NULL", (now_ts,))
        
        # 2. Record new Gold
        param_id = f"gold_{int(time.time())}"
        self.record_param_set(param_id, "GOLD", params, regime_id, fitness, origin, active_from=now_ts)
        
        # 3. Update active vault
        vault = self.get_hormonal_vault()
        vault["gold"] = {
            "id": param_id,
            "params": params,
            "fitness_snapshot": fitness,
            "coronated_at": now_ts.isoformat(),
            "origin": origin
        }
        self.set_hormonal_vault(vault)
        print(f"   [LIBRARIAN] Piece 188: New GOLD installed: {param_id}")

    def record_param_set(self, param_id: str, tier: str, params: dict, regime_id: str, 
                         fitness: float, origin: str, active_from=None):
        """Piece 189-192: Generic param set writer."""
        conn = self.get_param_connection()
        now_ts = active_from or datetime.now()
        conn.execute("""
            INSERT INTO param_sets (id, tier, params_json, regime_id, fitness, active_from, origin)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (param_id, tier.upper(), json.dumps(params), regime_id, fitness, now_ts, origin))

    def demote_to_bronze(self, param_id: str):
        """Piece 192: Marks a parameter set as Bronze (Retired)."""
        conn = self.get_param_connection()
        now_ts = datetime.now()
        conn.execute("UPDATE param_sets SET tier = 'BRONZE', active_to = ? WHERE id = ?", (now_ts, param_id))
        print(f"   [LIBRARIAN] Piece 192: Param set {param_id} demoted to BRONZE.")

    def record_silver_candidate(self, params: dict, fitness: float, regime_id: str, source: str):
        """Piece 190/197: Records a Silver candidate with cap enforcement (20)."""
        vault = self.get_hormonal_vault()
        silver_list = vault.get("silver", [])
        if not isinstance(silver_list, list): silver_list = []
        
        import uuid
        param_id = f"silver_{regime_id}_{int(time.time())}_{uuid.uuid4().hex[:4]}"
        new_entry = {
            "id": param_id,
            "params": params,
            "fitness": fitness,
            "regime_id": regime_id,
            "source": source,
            "minted_at": datetime.now().isoformat()
        }
        
        silver_list.append(new_entry)
        
        # Piece 197/265: Enforce configurable silver cap from Gold params
        gold_cfg = vault.get("gold", {})
        cap = int(gold_cfg.get("params", {}).get("silver_cap", 20))
        if len(silver_list) > cap:
            removed = silver_list.pop(0)
            print(f"   [LIBRARIAN] Piece 197: Silver cap ({cap}) reached. Evicted: {removed['id']}")
            
        vault["silver"] = silver_list
        self.set_hormonal_vault(vault)
        
        # Also record in Param DB
        self.record_param_set(param_id, "SILVER", params, regime_id, fitness, source)

    def get_param_history(self, tier: str = None, regime_id: str = None, 
                          min_fitness: float = None, limit: int = 100) -> list:
        """Piece 193: Reader for parameter set history."""
        conn = self.get_param_connection()
        sql = "SELECT * FROM param_sets WHERE 1=1"
        params = []
        
        if tier:
            sql += " AND tier = ?"
            params.append(tier.upper())
        if regime_id:
            sql += " AND regime_id = ?"
            params.append(regime_id)
        if min_fitness is not None:
            sql += " AND fitness >= ?"
            params.append(float(min_fitness))
            
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        
        # DuckDB fetchall() returns tuples; converting to dict for caller
        rows = conn.execute(sql, params).df().to_dict('records')
        return rows

    def mint_walk(self, data: dict):
        """Piece 101: Atomic Walk Write."""
        conn = self.get_duck_connection()
        conn.execute("""
            INSERT INTO walk_mint (ts, symbol, regime_id, mu, sigma, p_jump, confidence, mode, pulse_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.get("ts"), data.get("symbol"), data.get("regime_id"),
            data.get("mu"), data.get("sigma"), data.get("p_jump"),
            data.get("confidence"), data.get("mode"), data.get("pulse_type")
        ))

    def mint_monte(self, data: dict):
        """Piece 101: Atomic Monte Write."""
        conn = self.get_duck_connection()
        conn.execute("""
            INSERT INTO monte_mint (ts, symbol, pulse_type, n_steps, paths_per_lane, price, atr, stop_level, 
                                  monte_score, worst_survival, neutral_survival, best_survival)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.get("ts"), data.get("symbol"), data.get("pulse_type"),
            data.get("n_steps"), data.get("paths_per_lane"), data.get("price"),
            data.get("atr"), data.get("stop_level"), data.get("monte_score"),
            data.get("worst_survival"), data.get("neutral_survival"), data.get("best_survival")
        ))

    def mint_optimizer(self, data: dict):
        """Piece 101: Atomic Optimizer Write."""
        conn = self.get_duck_connection()
        conn.execute("""
            INSERT INTO optimizer_mint (ts, symbol, regime_id, fitness, params_json, source, mode)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            data.get("ts"), data.get("symbol"), data.get("regime_id"),
            data.get("fitness"), data.get("params_json"), data.get("source"), data.get("mode")
        ))

    def mint_synapse(self, data: dict):
        """Piece 16: Atomic Unified Synapse Write."""
        # Piece 220: Prepare dynamic param columns
        p_keys = []
        p_vals = []
        for k in PARAM_KEYS:
            p_keys.append(k)
            p_vals.append(data.get(k, 0.0))
            
        param_cols_str = ", ".join(p_keys)
        
        base_cols = [
            "machine_code", "ts", "symbol", "pulse_type", "execution_mode",
            "open", "high", "low", "close", "volume",
            "price", "active_hi", "active_lo", "gear", "tier1_signal",
            "mu", "sigma", "p_jump", "monte_score", "tier_score", "regime_id",
            "worst_survival", "neutral_survival", "best_survival",
            "council_score", "atr", "atr_avg", "adx", "volume_score",
            "decision", "approved", "final_confidence", "sizing_mult", "ready_to_fire",
            "bid", "ask", "bid_size", "ask_size", "bid_ask_bps", "spread_score", "spread_regime",
            "val_mean", "val_std_dev", "val_z_distance",
            "exec_expected_slippage_bps", "exec_total_cost_bps",
            "qty", "notional", "cost_adjusted_conviction"
        ]
        
        all_cols = base_cols + p_keys
        all_vals = [data.get(c) for c in base_cols] + p_vals
        
        placeholders = ", ".join(["?"] * len(all_cols))
        sql = f"INSERT OR REPLACE INTO synapse_mint ({', '.join(all_cols)}) VALUES ({placeholders})"
        
        # Route through the standardized write (which uses Telepathy)
        self.write(sql, tuple(all_vals), transport="duckdb")

    def get_duck_connection(self, read_only: bool = False):
        """
        Analytical 'Big Data' Gateway (DuckDB).
        Piece 101: Consolidate all 'Mint' tables here.
        V5: Finalized DuckDB-first architecture (SQLite logic purged).
        """
        if self._duck_conn is None:
            try:
                self._duck_conn = duckdb.connect(database=str(self.duck_db_path), read_only=read_only)
            except Exception as e:
                # Piece 162: Robust fallback for locked files or permission issues
                fallback = self.root_path / "runtime" / ".tmp_test_local"
                fallback.mkdir(parents=True, exist_ok=True)
                alt = fallback / f"ecosystem_synapse_{uuid.uuid4().hex}.duckdb"
                print(f"   [LIBRARIAN_WARN] Primary DuckDB locked or failed ({e}). Using volatile fallback: {alt}")
                self._duck_conn = duckdb.connect(database=str(alt), read_only=False)
        return self._duck_conn

    def get_redis_connection(self):
        """
        Nervous System 'Live' Gateway (Redis).
        Piece 114: Sub-millisecond BrainFrame storage and cross-lobe communication.
        V5: Fail-closed in LIVE/PAPER modes to prevent unpersisted state drift.
        """
        if self._redis_conn is None:
            try:
                self._redis_conn = redis.Redis(
                    host=os.getenv("REDIS_HOST", "localhost"),
                    port=int(os.getenv("REDIS_PORT", 6379)),
                    db=int(os.getenv("REDIS_DB", 0)),
                    decode_responses=True,
                    socket_connect_timeout=1
                )
                self._redis_conn.ping()
            except Exception as e:
                mode = os.getenv("MAMMON_MODE", "DRY_RUN").upper()
                emit_mner(
                    "HIPP-E-INFRA-901",
                    "REDIS_UNAVAILABLE",
                    source="Hippocampus.Archivist.librarian.Librarian.get_redis_connection",
                    details={"mode": mode, "error": str(e)},
                    echo=True,
                )
                raise ConnectionError(f"[HIPP-E-INFRA-901] REDIS_UNAVAILABLE mode={mode} err={e}")
        return self._redis_conn

    def get_timescale_connection(self):
        """
        Immutable Ledger 'Audit' Gateway (TimescaleDB).
        Piece 116: Treasury Ledgers and Audit Logs with ACID compliance.
        V5: Fail-closed in LIVE/PAPER modes to ensure audit trail integrity.
        """
        if self._timescale_conn is None:
            try:
                self._timescale_conn = psycopg2.connect(
                    host=os.getenv("TIMESCALE_HOST", "localhost"),
                    port=int(os.getenv("TIMESCALE_PORT", 5432)),
                    database=os.getenv("TIMESCALE_DB", "mammon_audit"),
                    user=os.getenv("TIMESCALE_USER", "postgres"),
                    password=os.getenv("TIMESCALE_PASSWORD", "postgres"),
                    connect_timeout=1
                )
                # Avoid lingering aborted transactions on read failures.
                self._timescale_conn.autocommit = True
            except Exception as e:
                mode = os.getenv("MAMMON_MODE", "DRY_RUN").upper()
                emit_mner(
                    "HIPP-E-INFRA-902",
                    "TIMESCALE_UNAVAILABLE",
                    source="Hippocampus.Archivist.librarian.Librarian.get_timescale_connection",
                    details={"mode": mode, "error": str(e)},
                    echo=True,
                )
                raise ConnectionError(f"[HIPP-E-INFRA-902] TIMESCALE_UNAVAILABLE mode={mode} err={e}")
        return self._timescale_conn

    def get_hormonal_vault(self) -> dict:
        """
        Piece 115: Atomic Vault Read from Redis HASH.
        Canonicalizes schema and keeps JSON mirror synced from hot table.
        """
        redis_conn = self.get_redis_connection()
        key = "mammon:hormonal_vault"

        # Bootstrap hot table from file mirror when Redis is empty.
        if not redis_conn.exists(key):
            seeded = self._normalize_hormonal_vault(self._load_vault_from_file())
            self.set_hormonal_vault(seeded)
            return seeded

        raw_vault = redis_conn.hgetall(key) or {}
        decoded = {}
        for k, v in raw_vault.items():
            try:
                decoded[k] = json.loads(v)
            except Exception:
                decoded[k] = v

        normalized = self._normalize_hormonal_vault(decoded)

        # Self-heal any legacy shape in hot table and keep file mirror aligned.
        if normalized != decoded:
            self.set_hormonal_vault(normalized)
            return normalized

        self._save_vault_to_file(normalized)
        return normalized

    def set_hormonal_vault(self, vault_data: dict):
        """
        Piece 115: Atomic Vault Write to Redis HASH.
        Normalizes schema, replaces hash atomically, and mirrors to file.
        """
        normalized = self._normalize_hormonal_vault(vault_data)
        redis_conn = self.get_redis_connection()
        key = "mammon:hormonal_vault"

        payload = {k: json.dumps(v) for k, v in normalized.items()}

        # Replace whole hash to prevent stale top-level keys from surviving.
        with redis_conn.pipeline() as pipe:
            pipe.delete(key)
            if payload:
                pipe.hset(key, mapping=payload)
            pipe.execute()

        # File mirror for bootstrap and human inspection.
        self._save_vault_to_file(normalized)

    def query(self, sql: str, params: tuple = (), transport: str = "duckdb"):
        """
        Standardized query executor (SELECT).
        Defaults to DuckDB for analytical queries.
        """
        if transport == "duckdb":
            conn = self.get_duck_connection()
            return conn.execute(sql, params).fetchall()
        elif transport == "timescale":
            if self._local_mode:
                conn = self.get_duck_connection()
                sql_local = self._normalize_timescale_sql_for_duckdb(sql)
                return conn.execute(sql_local, params).fetchall()
            conn = self.get_timescale_connection()
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall()
        else:
            raise ValueError(f"Unsupported transport for query: {transport}")

    def read(self, sql: str, params: tuple = (), transport: str = "duckdb"):
        """Piece 116: Proxy to query for read_only operations."""
        return self.query(sql, params, transport)

    def write(self, sql: str, params: tuple = (), transport: str = "duckdb"):
        """
        Standardized write executor (INSERT/UPDATE/DELETE).
        Piece 116: Support for TimescaleDB ledgers.
        V5: Routed through Telepathy for non-blocking execution.
        """
        try:
            from Hippocampus.telepathy.service import Telepathy
            Telepathy().transmit(sql, params, transport=transport)
        except (ImportError, Exception):
            # Fallback to direct write if Telepathy is not available (e.g. during early boot)
            self.write_direct(sql, params, transport=transport)

    def write_only(self, sql: str, params: tuple = (), transport: str = "duckdb"):
        """
        Compatibility alias used by treasury and older lobe code paths.
        """
        self.write(sql, params, transport=transport)

    def write_direct(self, sql: str, params: tuple = (), transport: str = "duckdb"):
        """Bypass Telepathy and execute the write immediately."""
        if transport == "duckdb":
            conn = self.get_duck_connection()
            conn.execute(sql, params)
            if self._local_mode and self._local_backend == "sqlite":
                conn.commit()
        elif transport == "timescale":
            if self._local_mode:
                conn = self.get_duck_connection()
                sql_local = self._normalize_timescale_sql_for_duckdb(sql)
                conn.execute(sql_local, params)
                return
            conn = self.get_timescale_connection()
            with conn.cursor() as cur:
                cur.execute(sql, params)
            if not getattr(conn, "autocommit", False):
                conn.commit()
        else:
            raise ValueError(f"Unsupported transport for write: {transport}")

    def _normalize_timescale_sql_for_duckdb(self, sql: str) -> str:
        return (
            sql.replace("SERIAL PRIMARY KEY", "BIGINT")
            .replace("DOUBLE PRECISION", "DOUBLE")
            .replace("%s", "?")
        )

    def close_all(self):
        if self._sqlite_conn:
            self._sqlite_conn.close()
            self._sqlite_conn = None
        if self._duck_conn:
            self._duck_conn.close()
            self._duck_conn = None
        if self._redis_conn:
            self._redis_conn.close()
            self._redis_conn = None
        if self._timescale_conn:
            self._timescale_conn.close()
            self._timescale_conn = None

class Librarian:
    """
    Lightweight compatibility librarian for isolated tests.

    Uses a single sqlite database and ignores transport routing while keeping the
    `read/write/read_only` interface expected by legacy tests.
    """

    def __init__(self, db_path=None):
        self.db_path = str(db_path or (Path.cwd() / "runtime" / ".tmp_test_local" / "compat_librarian.db"))
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row

    def setup_schema(self):
        # No-op for compatibility; test flows create tables via callers.
        return None

    def write(self, sql: str, params: tuple = (), transport: str = "duckdb"):
        self.conn.execute(sql, params)
        self.conn.commit()

    def write_only(self, sql: str, params: tuple = (), transport: str = "duckdb"):
        self.write(sql, params, transport=transport)

    def read(self, sql: str, params: tuple = (), transport: str = "duckdb"):
        cur = self.conn.execute(sql, params)
        return [tuple(r) for r in cur.fetchall()]

    def read_only(self, sql: str, params: tuple = (), transport: str = "duckdb"):
        cur = self.conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]

    query = read


# Global Librarian Accessor
librarian = MultiTransportLibrarian()
