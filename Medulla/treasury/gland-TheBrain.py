import time
import json
from datetime import datetime, timezone
from typing import Dict, Any

from Hippocampus.Archivist.librarian import librarian


class TreasuryGland:
    """
    Medulla Treasury Gland.
    Owns persistent money-state ledgers for DRY_RUN/PAPER/LIVE execution modes.
    """

    def __init__(
        self,
        mode: str = "DRY_RUN",
        config: Dict[str, Any] = None,
        librarian_instance=None,
        librarian=None,
    ):
        self.mode = (mode or "DRY_RUN").upper()
        self.config = config or {}
        # Accept both names for backward compatibility with legacy tests.
        self.librarian = librarian_instance or librarian or globals()["librarian"]
        self._init_schema()

    def _init_schema(self):
        # Piece 116: Schema initialization on TimescaleDB
        writer = getattr(self.librarian, "write_direct", self.librarian.write)
        writer(
            """
            CREATE TABLE IF NOT EXISTS money_orders (
                intent_id TEXT PRIMARY KEY,
                ts DOUBLE PRECISION NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                qty DOUBLE PRECISION NOT NULL,
                trigger_pulse TEXT NOT NULL,
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                price_ref DOUBLE PRECISION,
                mean DOUBLE PRECISION,
                sigma DOUBLE PRECISION,
                z_score DOUBLE PRECISION,
                risk_score DOUBLE PRECISION,
                confidence DOUBLE PRECISION,
                pre_trade_cost_bps DOUBLE PRECISION,
                spread_regime TEXT,
                z_distance DOUBLE PRECISION,
                reason TEXT,
                updated_at DOUBLE PRECISION NOT NULL
            )
            """, transport="timescale"
        )
        writer(
            """
            CREATE TABLE IF NOT EXISTS money_fills (
                fill_id TEXT PRIMARY KEY,
                intent_id TEXT NOT NULL,
                ts DOUBLE PRECISION NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                qty DOUBLE PRECISION NOT NULL,
                fill_price DOUBLE PRECISION NOT NULL,
                slippage_bps DOUBLE PRECISION NOT NULL DEFAULT 0.0,
                slippage_cost DOUBLE PRECISION NOT NULL DEFAULT 0.0,
                fee DOUBLE PRECISION NOT NULL DEFAULT 0.0,
                source TEXT NOT NULL,
                mode TEXT NOT NULL
            )
            """, transport="timescale"
        )
        writer(
            """
            CREATE TABLE IF NOT EXISTS money_positions (
                symbol TEXT NOT NULL,
                mode TEXT NOT NULL,
                qty DOUBLE PRECISION NOT NULL,
                avg_price DOUBLE PRECISION NOT NULL,
                market_price DOUBLE PRECISION NOT NULL,
                unrealized_pnl DOUBLE PRECISION NOT NULL,
                realized_pnl DOUBLE PRECISION NOT NULL,
                updated_at DOUBLE PRECISION NOT NULL,
                PRIMARY KEY (symbol, mode)
            )
            """, transport="timescale"
        )
        writer(
            """
            CREATE TABLE IF NOT EXISTS money_pnl_snapshots (
                id SERIAL PRIMARY KEY,
                ts DOUBLE PRECISION NOT NULL,
                mode TEXT NOT NULL,
                symbol TEXT,
                gross_pnl DOUBLE PRECISION NOT NULL,
                slippage_impact DOUBLE PRECISION NOT NULL,
                fee_impact DOUBLE PRECISION NOT NULL,
                net_pnl DOUBLE PRECISION NOT NULL
            )
            """, transport="timescale"
        )
        writer(
            """
            CREATE TABLE IF NOT EXISTS money_audit (
                id SERIAL PRIMARY KEY,
                ts DOUBLE PRECISION NOT NULL,
                event_type TEXT NOT NULL,
                intent_id TEXT,
                symbol TEXT,
                payload_json TEXT
            )
            """, transport="timescale"
        )
        # Note: Index creation on TimescaleDB
        writer("CREATE INDEX IF NOT EXISTS idx_money_orders_status_ts ON money_orders(status, ts)", transport="timescale")
        writer("CREATE INDEX IF NOT EXISTS idx_money_fills_symbol_ts ON money_fills(symbol, ts)", transport="timescale")
        writer("CREATE INDEX IF NOT EXISTS idx_money_pnl_mode_ts ON money_pnl_snapshots(mode, ts)", transport="timescale")

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
        """Target #56: authoritative intent persistence."""
        # Piece 11: Validation at boundary
        symbol = str(intent.get("symbol", "")).strip()
        qty = float(intent.get("qty", 0.0))
        price = float(intent.get("price_ref", 0.0))
        
        if not symbol or qty <= 0 or price <= 0:
            print(f"[TREASURY_WARN] Invalid intent payload rejected: {symbol} qty={qty} price={price}")
            return

        ts = float(intent.get("ts") or time.time())
        # Piece 56: Standardized multi-transport write
        self.librarian.write(
            """
            INSERT INTO money_orders(
                intent_id, ts, symbol, side, qty, trigger_pulse, mode, status,
                price_ref, mean, sigma, z_score, risk_score, confidence,
                pre_trade_cost_bps, spread_regime, z_distance,
                reason, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (intent_id) DO UPDATE SET
                status = EXCLUDED.status,
                reason = EXCLUDED.reason,
                updated_at = EXCLUDED.updated_at
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
                # Piece 134
                float(intent.get("pre_trade_cost_bps", 0.0)),
                str(intent.get("spread_regime", "UNKNOWN")),
                float(intent.get("z_distance", 0.0)),
                intent.get("reason", "ACTION_ARMED"),
                ts,
            ), transport="timescale"
        )
        self._audit("ACTION_ARMED", intent.get("intent_id"), symbol, intent)

    def record_rejected_intent(self, intent_id: str, symbol: str, qty: float, price: float, reason: str):
        """Piece 13: Centralized terminal state for invalid payloads."""
        ts_now = time.time()
        self.librarian.write(
            """
            INSERT INTO money_orders(
                intent_id, ts, symbol, side, qty, trigger_pulse, mode, status,
                price_ref, mean, sigma, z_score, risk_score, confidence, reason, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (intent_id) DO NOTHING
            """,
            (
                intent_id, ts_now, symbol or "UNKNOWN", "BUY", float(qty or 0.0),
                "ACTION", self.mode, "REJECTED", float(price or 0.0),
                0.0, 0.0, 0.0, 0.0, 0.0, reason, ts_now
            ), transport="timescale"
        )
        self._audit("REJECTED", intent_id, symbol, {"reason": reason, "mode": self.mode, "ts": ts_now})

    def cancel_intent(self, intent_id: str, symbol: str, reason: str, pulse_type: str = "MINT"):
        self._transition_intent(intent_id, symbol, status="CANCELED", event_type="MINT_CANCELED", reason=reason)
        self._snapshot_pnl(symbol, pulse_type)

    def reject_intent(self, intent_id: str, symbol: str, reason: str, pulse_type: str = "MINT"):
        self._transition_intent(intent_id, symbol, status="REJECTED", event_type="REJECTED", reason=reason)
        self._snapshot_pnl(symbol, pulse_type)

    def timeout_intent(self, intent_id: str, symbol: str, reason: str, pulse_type: str = "MINT"):
        self._transition_intent(intent_id, symbol, status="TIMEOUT", event_type="TIMEOUT", reason=reason)
        self._snapshot_pnl(symbol, pulse_type)

    def _transition_intent(self, intent_id: str, symbol: str, status: str, event_type: str, reason: str):
        ts = time.time()
        # Piece 11: Idempotent state update
        self.librarian.write(
            """
            UPDATE money_orders
            SET status = %s, reason = %s, updated_at = %s
            WHERE intent_id = %s AND status != 'FILLED'
            """,
            (status, reason, ts, intent_id), transport="timescale"
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
        pulse_type: str = "MINT",
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

        self.librarian.write(
            """
            UPDATE money_orders
            SET status = %s, reason = %s, updated_at = %s
            WHERE intent_id = %s
            """,
            ("FILLED", "MINT_FIRED", ts, intent_id), transport="timescale"
        )
        self.librarian.write(
            """
            INSERT INTO money_fills(
                fill_id, intent_id, ts, symbol, side, qty, fill_price,
                slippage_bps, slippage_cost, fee, source, mode
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (fill_id) DO NOTHING
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
            ), transport="timescale"
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
        self._snapshot_pnl(symbol, pulse_type)

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
        pulse_type: str = "MINT",
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
        self.librarian.write(
            """
            UPDATE money_orders
            SET status = %s, reason = %s, updated_at = %s
            WHERE intent_id = %s
            """,
            ("PARTIAL_FILLED", "PARTIAL_FILL", ts, intent_id), transport="timescale"
        )
        self.librarian.write(
            """
            INSERT INTO money_fills(
                fill_id, intent_id, ts, symbol, side, qty, fill_price,
                slippage_bps, slippage_cost, fee, source, mode
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (fill_id) DO NOTHING
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
            ), transport="timescale"
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
        rows = self.librarian.read(
            "SELECT qty, avg_price, realized_pnl FROM money_positions WHERE symbol = %s AND mode = %s",
            (symbol, self.mode), transport="timescale"
        )
        # Note: Depending on psycopg2 cursor setup, rows might be tuples or dicts. 
        # Standard MultiTransportLibrarian returns fetchall() tuples.
        pos_qty = float(rows[0][0]) if rows else 0.0
        pos_avg = float(rows[0][1]) if rows else 0.0
        realized = float(rows[0][2]) if rows else 0.0

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
        self.librarian.write(
            """
            INSERT INTO money_positions(
                symbol, mode, qty, avg_price, market_price, unrealized_pnl, realized_pnl, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (symbol, mode) DO UPDATE SET
                qty = EXCLUDED.qty,
                avg_price = EXCLUDED.avg_price,
                market_price = EXCLUDED.market_price,
                unrealized_pnl = EXCLUDED.unrealized_pnl,
                realized_pnl = EXCLUDED.realized_pnl,
                updated_at = EXCLUDED.updated_at
            """,
            (symbol, self.mode, new_qty, new_avg, market_price, unrealized, realized, ts), transport="timescale"
        )

    def _snapshot_pnl(self, symbol: str, pulse_type: str = "MINT"):
        """Piece 58: Timing Gated Snapshotting."""
        if str(pulse_type).upper() != "MINT":
            return

        row = self.librarian.read(
            "SELECT unrealized_pnl, realized_pnl FROM money_positions WHERE symbol = %s AND mode = %s",
            (symbol, self.mode), transport="timescale"
        )
        unrealized = float(row[0][0]) if row else 0.0
        realized = float(row[0][1]) if row else 0.0
        costs = self.librarian.read(
            """
            SELECT
                COALESCE(SUM(slippage_cost), 0.0) AS slippage_cost,
                COALESCE(SUM(fee), 0.0) AS fee_cost
            FROM money_fills
            WHERE symbol = %s AND mode = %s
            """,
            (symbol, self.mode), transport="timescale"
        )[0]
        slippage_cost = float(costs[0])
        fee_cost = float(costs[1])
        gross = realized + unrealized + slippage_cost
        net = gross - slippage_cost - fee_cost
        self.librarian.write(
            """
            INSERT INTO money_pnl_snapshots(
                ts, mode, symbol, gross_pnl, slippage_impact, fee_impact, net_pnl
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (time.time(), self.mode, symbol, gross, slippage_cost, fee_cost, net), transport="timescale"
        )

    def _audit(self, event_type: str, intent_id: str, symbol: str, payload: Dict[str, Any]):
        payload_json = json.dumps(payload, sort_keys=True)
        self.librarian.write(
            """
            INSERT INTO money_audit(ts, event_type, intent_id, symbol, payload_json)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (time.time(), event_type, intent_id, symbol, payload_json), transport="timescale"
        )

    def get_status(self) -> Dict[str, Any]:
        # Piece 11: Explicit mode isolation
        open_pos_rows = self.librarian.read(
            """
            SELECT COUNT(*) AS c
            FROM money_positions
            WHERE mode = %s AND qty > 0
            """,
            (self.mode,), transport="timescale"
        )
        open_pos = open_pos_rows[0][0] if open_pos_rows else 0

        order_counts = self.librarian.read(
            """
            SELECT status, COUNT(*) AS c
            FROM money_orders
            WHERE mode = %s
            GROUP BY status
            """,
            (self.mode,), transport="timescale"
        )
        fired = 0
        canceled = 0
        armed = 0
        partial = 0
        rejected = 0
        timeout = 0
        for row in order_counts:
            status = row[0]
            count = int(row[1])
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
        orders_total = armed + fired + canceled + partial + rejected + timeout

        pnl_rows = self.librarian.read(
            """
            SELECT COALESCE(SUM(realized_pnl), 0.0) AS realized,
                   COALESCE(SUM(unrealized_pnl), 0.0) AS unrealized
            FROM money_positions
            WHERE mode = %s
            """,
            (self.mode,), transport="timescale"
        )
        pnl_realized = pnl_rows[0][0] if pnl_rows else 0.0
        pnl_unrealized = pnl_rows[0][1] if pnl_rows else 0.0
        net_pnl = float(pnl_realized) + float(pnl_unrealized)

        drawdown = 0.0
        win_rate = 0.0
        try:
            pnl_series = self.librarian.read(
                """
                SELECT net_pnl
                FROM money_pnl_snapshots
                WHERE mode = %s
                ORDER BY ts ASC
                """,
                (self.mode,), transport="timescale"
            )
            if pnl_series:
                peak = float(pnl_series[0][0] or 0.0)
                max_dd = 0.0
                wins = 0
                for row in pnl_series:
                    val = float(row[0] or 0.0)
                    if val > peak:
                        peak = val
                    dd = peak - val
                    if dd > max_dd:
                        max_dd = dd
                    if val > 0:
                        wins += 1
                drawdown = float(max_dd)
                win_rate = (wins / max(len(pnl_series), 1)) * 100.0
        except Exception:
            pass

        return {
            "mode": self.mode,
            "open_positions": int(open_pos),
            "orders": int(orders_total),
            "orders_breakdown": {
                "armed": armed,
                "fired": fired,
                "canceled": canceled,
                "partial": partial,
                "rejected": rejected,
                "timeout": timeout,
            },
            "realized_pnl": float(pnl_realized),
            "unrealized_pnl": float(pnl_unrealized),
            "fills": int(fired),
            "positions": int(open_pos),
            "net_pnl": float(net_pnl),
            "drawdown": float(drawdown),
            "win_rate": float(win_rate),
            "source": "sim",
        }

    def get_open_positions_count(self) -> int:
        row = self.librarian.read(
            """
            SELECT COUNT(*) AS c
            FROM money_positions
            WHERE mode = %s AND qty > 0
            """,
            (self.mode,), transport="timescale"
        )[0]
        return int(row[0] or 0)

    def get_realized_pnl_for_day(self, day_utc: str = None) -> float:
        # day_utc format: YYYY-MM-DD in UTC.
        if not day_utc:
            day_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        
        # Piece 11: Explicit UTC day boundaries
        day_start = datetime.strptime(day_utc, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
        day_end = day_start + 86400.0
        
        row = self.librarian.read(
            """
            SELECT COALESCE(SUM(net_pnl), 0.0) AS net
            FROM money_pnl_snapshots
            WHERE mode = %s AND ts >= %s AND ts < %s
            """,
            (self.mode, day_start, day_end), transport="timescale"
        )
        if not row or not row[0]:
            return 0.0
        return float(row[0][0] or 0.0)

    def reconcile_paper_with_broker(self, broker_positions: Dict[str, Any]) -> Dict[str, Any]:
        """
        Minimal reconciliation loop for PAPER mode:
        compares broker quantity map against local paper positions for the active mode.
        """
        local_rows = self.librarian.read(
            """
            SELECT symbol, qty, avg_price
            FROM money_positions
            WHERE mode = %s AND qty <> 0
            """,
            (self.mode,), transport="timescale"
        )
        local = {str(r[0]).upper(): float(r[1]) for r in local_rows}
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
