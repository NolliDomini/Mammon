import time
import json
from datetime import datetime, timezone
from typing import Dict, Any

from Hippocampus.Archivist.librarian import Librarian

class TreasuryGland:
    """
    Medulla Treasury Gland.
    Owns persistent money-state ledgers for DRY_RUN/PAPER/LIVE execution modes.
    """

    def __init__(self, mode: str = "DRY_RUN", config: Dict[str, Any] = None, librarian: Librarian = None):
        self.mode = (mode or "DRY_RUN").upper()
        self.config = config or {}
        self.librarian = librarian or Librarian()
        self._init_schema()

    def _init_schema(self):
        self.librarian.write_only(
            """
            CREATE TABLE IF NOT EXISTS money_orders (
                intent_id TEXT PRIMARY KEY,
                ts REAL NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                qty REAL NOT NULL,
                trigger_pulse TEXT NOT NULL,
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                price_ref REAL,
                mean REAL,
                sigma REAL,
                z_score REAL,
                risk_score REAL,
                confidence REAL,
                reason TEXT,
                updated_at REAL NOT NULL
            )
            """
        )
        self.librarian.write_only(
            """
            CREATE TABLE IF NOT EXISTS money_fills (
                fill_id TEXT PRIMARY KEY,
                intent_id TEXT NOT NULL,
                ts REAL NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                qty REAL NOT NULL,
                fill_price REAL NOT NULL,
                slippage_bps REAL NOT NULL DEFAULT 0.0,
                slippage_cost REAL NOT NULL DEFAULT 0.0,
                fee REAL NOT NULL DEFAULT 0.0,
                source TEXT NOT NULL,
                mode TEXT NOT NULL
            )
            """
        )
        self.librarian.write_only(
            """
            CREATE TABLE IF NOT EXISTS money_positions (
                symbol TEXT NOT NULL,
                mode TEXT NOT NULL,
                qty REAL NOT NULL,
                avg_price REAL NOT NULL,
                market_price REAL NOT NULL,
                unrealized_pnl REAL NOT NULL,
                realized_pnl REAL NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (symbol, mode)
            )
            """
        )
        self.librarian.write_only(
            """
            CREATE TABLE IF NOT EXISTS money_pnl_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                mode TEXT NOT NULL,
                symbol TEXT,
                gross_pnl REAL NOT NULL,
                slippage_impact REAL NOT NULL,
                fee_impact REAL NOT NULL,
                net_pnl REAL NOT NULL
            )
            """
        )
        self.librarian.write_only(
            """
            CREATE TABLE IF NOT EXISTS money_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                event_type TEXT NOT NULL,
                intent_id TEXT,
                symbol TEXT,
                payload_json TEXT
            )
            """
        )
        self.librarian.write_only(
            "CREATE INDEX IF NOT EXISTS idx_money_orders_status_ts ON money_orders(status, ts)"
        )
        self.librarian.write_only(
            "CREATE INDEX IF NOT EXISTS idx_money_fills_symbol_ts ON money_fills(symbol, ts)"
        )
        self.librarian.write_only(
            "CREATE INDEX IF NOT EXISTS idx_money_pnl_mode_ts ON money_pnl_snapshots(mode, ts)"
        )
        self._ensure_column("money_fills", "slippage_cost", "REAL NOT NULL DEFAULT 0.0")

    def _ensure_column(self, table: str, column: str, definition: str):
        cols = self.librarian.read_only(f"PRAGMA table_info({table})")
        existing = {c["name"] for c in cols}
        if column not in existing:
            self.librarian.write_only(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _slippage_bps(self, symbol: str, sigma: float, price_ref: float) -> float:
        base_bps = float(self.config.get("slippage_bps", 0.0))
        symbol_overrides = self.config.get("symbol_slippage_bps", {}) or {}
        if symbol in symbol_overrides:
            base_bps = float(symbol_overrides[symbol])
        vol_mult = float(self.config.get("slippage_vol_mult", 0.0))
        vol_component_bps = 0.0
        if price_ref > 0 and sigma > 0:
            vol_component_bps = (sigma / price_ref) * 10000.0
        return max(0.0, base_bps + (vol_mult * vol_component_bps))

    def _fee(self, notional: float) -> float:
        fee_bps = float(self.config.get("fee_bps", 0.0))
        return max(0.0, notional * (fee_bps / 10000.0))

    def record_intent(self, intent: Dict[str, Any]):
        # Piece 11: Validation at boundary
        symbol = str(intent.get("symbol", "")).strip()
        qty = float(intent.get("qty", 0.0))
        price = float(intent.get("price_ref", 0.0))
        
        if not symbol or qty <= 0 or price <= 0:
            print(f"[TREASURY_WARN] Invalid intent payload rejected: {symbol} qty={qty} price={price}")
            return

        ts = float(intent.get("ts") or time.time())
        self.librarian.write_only(
            """
            INSERT OR REPLACE INTO money_orders(
                intent_id, ts, symbol, side, qty, trigger_pulse, mode, status,
                price_ref, mean, sigma, z_score, risk_score, confidence, reason, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                intent["intent_id"],
                ts,
                symbol,
                intent.get("side", "BUY"),
                qty,
                intent.get("trigger_pulse", "ACTION"),
                intent.get("mode", self.mode),
                "ARMED",
                price,
                float(intent.get("mean", 0.0)),
                float(intent.get("sigma", 0.0)),
                float(intent.get("z_score", 0.0)),
                float(intent.get("risk_score", 0.0)),
                float(intent.get("confidence", 0.0)),
                intent.get("reason", "ACTION_ARMED"),
                ts,
            ),
        )
        self._audit("ACTION_ARMED", intent.get("intent_id"), symbol, intent)

    def cancel_intent(self, intent_id: str, symbol: str, reason: str):
        self._transition_intent(intent_id, symbol, status="CANCELED", event_type="MINT_CANCELED", reason=reason)
        self._snapshot_pnl(symbol)

    def reject_intent(self, intent_id: str, symbol: str, reason: str):
        self._transition_intent(intent_id, symbol, status="REJECTED", event_type="REJECTED", reason=reason)
        self._snapshot_pnl(symbol)

    def timeout_intent(self, intent_id: str, symbol: str, reason: str):
        self._transition_intent(intent_id, symbol, status="TIMEOUT", event_type="TIMEOUT", reason=reason)
        self._snapshot_pnl(symbol)

    def _transition_intent(self, intent_id: str, symbol: str, status: str, event_type: str, reason: str):
        ts = time.time()
        # Piece 11: Idempotent state update
        self.librarian.write_only(
            """
            UPDATE money_orders
            SET status = ?, reason = ?, updated_at = ?
            WHERE intent_id = ? AND status != 'FILLED'
            """,
            (status, reason, ts, intent_id),
        )
        self._audit(
            event_type,
            intent_id,
            symbol,
            {"reason": reason, "mode": self.mode, "status": status, "ts": ts},
        )

    def fire_intent(
        self,
        intent_id: str,
        symbol: str,
        side: str,
        qty: float,
        fill_price: float,
        *,
        sigma: float = 0.0,
        price_ref: float = 0.0,
    ):
        # Piece 11: Validation
        qty_f = float(qty)
        raw_price = float(fill_price)
        if qty_f <= 0 or raw_price <= 0:
            self.reject_intent(intent_id, symbol, "INVALID_FILL_PAYLOAD")
            return

        ts = time.time()
        fill_id = f"{intent_id}:fill"
        mode = self.mode
        side_u = side.upper()
        slip_bps = self._slippage_bps(symbol, float(sigma), float(price_ref or raw_price))
        slip_frac = slip_bps / 10000.0
        adjusted_price = raw_price * (1.0 + slip_frac if side_u == "BUY" else 1.0 - slip_frac)
        slippage_cost = abs(adjusted_price - raw_price) * qty_f
        fee = self._fee(notional=adjusted_price * qty_f)

        self.librarian.write_only(
            """
            UPDATE money_orders
            SET status = ?, reason = ?, updated_at = ?
            WHERE intent_id = ?
            """,
            ("FILLED", "MINT_FIRED", ts, intent_id),
        )
        self.librarian.write_only(
            """
            INSERT OR REPLACE INTO money_fills(
                fill_id, intent_id, ts, symbol, side, qty, fill_price,
                slippage_bps, slippage_cost, fee, source, mode
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fill_id,
                intent_id,
                ts,
                symbol,
                side_u,
                qty_f,
                adjusted_price,
                slip_bps,
                slippage_cost,
                fee,
                "sim",
                mode,
            ),
        )
        self._apply_fill_to_position(symbol=symbol, side=side_u, qty=qty_f, fill_price=adjusted_price, ts=ts)
        self._audit(
            "MINT_FIRED",
            intent_id,
            symbol,
            {
                "side": side_u,
                "qty": qty_f,
                "fill_price_raw": raw_price,
                "fill_price": adjusted_price,
                "slippage_bps": slip_bps,
                "slippage_cost": slippage_cost,
                "fee": fee,
                "mode": mode,
                "ts": ts,
            },
        )
        self._snapshot_pnl(symbol)

    def partial_fill_intent(
        self,
        intent_id: str,
        symbol: str,
        side: str,
        qty_filled: float,
        fill_price: float,
        *,
        sigma: float = 0.0,
        price_ref: float = 0.0,
    ):
        ts = time.time()
        fill_id = f"{intent_id}:partial:{int(ts * 1000)}"
        side_u = side.upper()
        qty_f = float(qty_filled)
        raw_price = float(fill_price)
        slip_bps = self._slippage_bps(symbol, float(sigma), float(price_ref or raw_price))
        slip_frac = slip_bps / 10000.0
        adjusted_price = raw_price * (1.0 + slip_frac if side_u == "BUY" else 1.0 - slip_frac)
        slippage_cost = abs(adjusted_price - raw_price) * qty_f
        fee = self._fee(notional=adjusted_price * qty_f)
        self.librarian.write_only(
            """
            UPDATE money_orders
            SET status = ?, reason = ?, updated_at = ?
            WHERE intent_id = ?
            """,
            ("PARTIAL_FILLED", "PARTIAL_FILL", ts, intent_id),
        )
        self.librarian.write_only(
            """
            INSERT OR REPLACE INTO money_fills(
                fill_id, intent_id, ts, symbol, side, qty, fill_price,
                slippage_bps, slippage_cost, fee, source, mode
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fill_id,
                intent_id,
                ts,
                symbol,
                side_u,
                qty_f,
                adjusted_price,
                slip_bps,
                slippage_cost,
                fee,
                "sim",
                self.mode,
            ),
        )
        self._apply_fill_to_position(symbol=symbol, side=side_u, qty=qty_f, fill_price=adjusted_price, ts=ts)
        self._audit(
            "PARTIAL_FILL",
            intent_id,
            symbol,
            {
                "side": side_u,
                "qty_filled": qty_f,
                "fill_price_raw": raw_price,
                "fill_price": adjusted_price,
                "slippage_bps": slip_bps,
                "slippage_cost": slippage_cost,
                "fee": fee,
                "mode": self.mode,
                "ts": ts,
            },
        )
        self._snapshot_pnl(symbol)

    def _apply_fill_to_position(self, symbol: str, side: str, qty: float, fill_price: float, ts: float):
        rows = self.librarian.read_only(
            "SELECT qty, avg_price, realized_pnl FROM money_positions WHERE symbol = ? AND mode = ?",
            (symbol, self.mode),
        )
        pos_qty = float(rows[0]["qty"]) if rows else 0.0
        pos_avg = float(rows[0]["avg_price"]) if rows else 0.0
        realized = float(rows[0]["realized_pnl"]) if rows else 0.0

        signed = qty if side.upper() == "BUY" else -qty
        new_qty = pos_qty + signed
        new_avg = pos_avg
        if side.upper() == "BUY":
            if pos_qty <= 0:
                new_avg = fill_price
            else:
                new_avg = ((pos_qty * pos_avg) + (qty * fill_price)) / max(new_qty, 1e-9)
        else:
            realized += (fill_price - pos_avg) * qty
            if new_qty <= 0:
                new_avg = 0.0

        market_price = fill_price
        unrealized = (market_price - new_avg) * new_qty if new_qty > 0 else 0.0
        self.librarian.write_only(
            """
            INSERT OR REPLACE INTO money_positions(
                symbol, mode, qty, avg_price, market_price, unrealized_pnl, realized_pnl, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (symbol, self.mode, new_qty, new_avg, market_price, unrealized, realized, ts),
        )

    def _snapshot_pnl(self, symbol: str):
        row = self.librarian.read_only(
            "SELECT unrealized_pnl, realized_pnl FROM money_positions WHERE symbol = ? AND mode = ?",
            (symbol, self.mode),
        )
        unrealized = float(row[0]["unrealized_pnl"]) if row else 0.0
        realized = float(row[0]["realized_pnl"]) if row else 0.0
        costs = self.librarian.read_only(
            """
            SELECT
                COALESCE(SUM(slippage_cost), 0.0) AS slippage_cost,
                COALESCE(SUM(fee), 0.0) AS fee_cost
            FROM money_fills
            WHERE symbol = ? AND mode = ?
            """,
            (symbol, self.mode),
        )[0]
        slippage_cost = float(costs["slippage_cost"])
        fee_cost = float(costs["fee_cost"])
        gross = realized + unrealized
        net = gross - slippage_cost - fee_cost
        self.librarian.write_only(
            """
            INSERT INTO money_pnl_snapshots(
                ts, mode, symbol, gross_pnl, slippage_impact, fee_impact, net_pnl
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (time.time(), self.mode, symbol, gross, slippage_cost, fee_cost, net),
        )

    def _audit(self, event_type: str, intent_id: str, symbol: str, payload: Dict[str, Any]):
        payload_json = json.dumps(payload, sort_keys=True)
        self.librarian.write_only(
            """
            INSERT INTO money_audit(ts, event_type, intent_id, symbol, payload_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (time.time(), event_type, intent_id, symbol, payload_json),
        )

    def get_account_equity(self, baseline_equity: float = 10000.0) -> float:
        """
        Equity proxy for risk sizing: baseline cash plus realized/unrealized PnL.
        """
        try:
            baseline = float(self.config.get("equity_baseline", baseline_equity))
        except Exception:
            baseline = float(baseline_equity)
        row = self.librarian.read_only(
            """
            SELECT COALESCE(SUM(realized_pnl), 0.0) AS realized,
                   COALESCE(SUM(unrealized_pnl), 0.0) AS unrealized
            FROM money_positions
            WHERE mode = ?
            """,
            (self.mode,),
        )
        if row:
            realized = float(row[0].get("realized", 0.0) or 0.0)
            unrealized = float(row[0].get("unrealized", 0.0) or 0.0)
        else:
            realized = 0.0
            unrealized = 0.0
        return float(max(0.0, baseline + realized + unrealized))

    def get_status(self) -> Dict[str, Any]:
        # Piece 11: Explicit mode isolation
        open_pos_rows = self.librarian.read_only(
            """
            SELECT COUNT(*) AS c
            FROM money_positions
            WHERE mode = ? AND qty > 0
            """,
            (self.mode,),
        )
        open_pos = open_pos_rows[0]["c"] if open_pos_rows else 0

        order_counts = self.librarian.read_only(
            """
            SELECT status, COUNT(*) AS c
            FROM money_orders
            WHERE mode = ?
            GROUP BY status
            """,
            (self.mode,),
        )
        fired = 0
        canceled = 0
        armed = 0
        partial = 0
        rejected = 0
        timeout = 0
        for row in order_counts:
            status = row["status"]
            count = int(row["c"])
            if status == "FILLED":
                fired += count
            elif status == "CANCELED":
                canceled += count
            elif status == "ARMED":
                armed += count
            elif status == "PARTIAL_FILLED":
                partial += count
            elif status == "REJECTED":
                rejected += count
            elif status == "TIMEOUT":
                timeout += count

        pnl_rows = self.librarian.read_only(
            """
            SELECT COALESCE(SUM(realized_pnl), 0.0) AS realized,
                   COALESCE(SUM(unrealized_pnl), 0.0) AS unrealized
            FROM money_positions
            WHERE mode = ?
            """,
            (self.mode,),
        )
        pnl = pnl_rows[0] if pnl_rows else {"realized": 0.0, "unrealized": 0.0}

        return {
            "mode": self.mode,
            "open_positions": int(open_pos),
            "orders": {
                "armed": armed,
                "fired": fired,
                "canceled": canceled,
                "partial": partial,
                "rejected": rejected,
                "timeout": timeout,
            },
            "realized_pnl": float(pnl["realized"]),
            "unrealized_pnl": float(pnl["unrealized"]),
            "source": "sim",
        }

    def mark_to_market(self, symbol: str, market_price: float):
        rows = self.librarian.read_only(
            "SELECT qty, avg_price, realized_pnl FROM money_positions WHERE symbol = ? AND mode = ?",
            (symbol, self.mode),
        )
        if not rows or float(rows[0]["qty"]) <= 0:
            return
        qty = float(rows[0]["qty"])
        avg_price = float(rows[0]["avg_price"])
        realized = float(rows[0]["realized_pnl"])
        unrealized = (market_price - avg_price) * qty
        self.librarian.write_only(
            """
            UPDATE money_positions
            SET market_price = ?, unrealized_pnl = ?, updated_at = ?
            WHERE symbol = ? AND mode = ?
            """,
            (market_price, unrealized, time.time(), symbol, self.mode),
        )

    def get_open_positions_count(self) -> int:
        row = self.librarian.read_only(
            """
            SELECT COUNT(*) AS c
            FROM money_positions
            WHERE mode = ? AND qty > 0
            """,
            (self.mode,),
        )[0]
        return int(row["c"] or 0)

    def get_realized_pnl_for_day(self, day_utc: str = None) -> float:
        # day_utc format: YYYY-MM-DD in UTC.
        if not day_utc:
            day_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        
        # Piece 11: Explicit UTC day boundaries
        day_start = datetime.strptime(day_utc, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
        day_end = day_start + 86400.0
        
        row = self.librarian.read_only(
            """
            SELECT COALESCE(SUM(net_pnl), 0.0) AS net
            FROM money_pnl_snapshots
            WHERE mode = ? AND ts >= ? AND ts < ?
            """,
            (self.mode, day_start, day_end),
        )[0]
        return float(row["net"] or 0.0)

    def reconcile_paper_with_broker(self, broker_positions: Dict[str, Any]) -> Dict[str, Any]:
        """
        Minimal reconciliation loop for PAPER mode:
        compares broker quantity map against local paper positions for the active mode.
        """
        local_rows = self.librarian.read_only(
            """
            SELECT symbol, qty, avg_price
            FROM money_positions
            WHERE mode = ? AND qty <> 0
            """,
            (self.mode,),
        )
        local = {str(r["symbol"]).upper(): float(r["qty"]) for r in local_rows}
        broker = {str(k).upper(): float(v) for k, v in (broker_positions or {}).items()}

        all_symbols = sorted(set(local.keys()) | set(broker.keys()))
        mismatches = []
        for symbol in all_symbols:
            local_qty = float(local.get(symbol, 0.0))
            broker_qty = float(broker.get(symbol, 0.0))
            if abs(local_qty - broker_qty) > 1e-9:
                mismatches.append(
                    {"symbol": symbol, "local_qty": local_qty, "broker_qty": broker_qty}
                )
        self._audit(
            "PAPER_RECONCILE",
            intent_id=None,
            symbol=None,
            payload={
                "mode": self.mode,
                "matched": len(mismatches) == 0,
                "mismatch_count": len(mismatches),
                "mismatches": mismatches[:100],
                "ts": time.time(),
            },
        )
        return {
            "mode": self.mode,
            "matched": len(mismatches) == 0,
            "mismatch_count": len(mismatches),
            "mismatches": mismatches,
        }

    def get_open_positions(self) -> list:
        rows = self.librarian.read_only(
            """
            SELECT p.symbol, p.qty, p.avg_price, p.market_price,
                   o.mean, o.sigma, o.z_score
            FROM money_positions p
            LEFT JOIN (
                SELECT symbol, mean, sigma, z_score, MAX(ts) AS ts
                FROM money_orders
                WHERE mode = ? AND side = 'BUY'
                GROUP BY symbol
            ) o ON o.symbol = p.symbol
            WHERE p.mode = ? AND p.qty > 0
            """,
            (self.mode, self.mode),
        )
        return [dict(r) for r in rows]
