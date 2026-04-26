"""
Mammon MCP Server — full read/write access to all engine databases.

Runs as a sidecar container on the same Docker network.
All AI clients (Claude, Gemini, Codex) connect via SSE: http://localhost:5001/sse
"""

import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Optional

import duckdb
import redis as redis_lib
from fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE = Path(os.getenv("MAMMON_BASE", "/mammon"))
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

# Named registry — all known stores. Clients use these aliases.
SQLITE_DBS: dict[str, Path] = {
    "money":    BASE / "runtime/.tmp_test_local/compat_librarian.db",
    "memory":   BASE / "Hippocampus/Archivist/Ecosystem_Memory.db",
    "synapse":  BASE / "Hippocampus/Archivist/Ecosystem_Synapse.db",
    "ui":       BASE / "Hippocampus/data/Ecosystem_UI.db",
    "hospital": BASE / "Hospital/Memory_care/control_logs.db",
}

DUCKDB_DBS: dict[str, Path] = {
    "synapse_duck": BASE / "Hippocampus/data/ecosystem_synapse.duckdb",
    "params":       BASE / "Hippocampus/data/ecosystem_params.duckdb",
    "fornix":       BASE / "Hospital/Memory_care/duck.db",
}

ALL_DBS = {**SQLITE_DBS, **DUCKDB_DBS}

# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def _sqlite_ro(name: str) -> sqlite3.Connection:
    path = SQLITE_DBS.get(name)
    if path is None:
        raise KeyError(f"Unknown sqlite db {name!r}. Known: {list(SQLITE_DBS)}")
    if not path.exists():
        raise FileNotFoundError(f"{name} db not found at {path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _sqlite_rw(name: str) -> sqlite3.Connection:
    path = SQLITE_DBS.get(name)
    if path is None:
        # Allow raw path as fallback for scan_stores discovered files
        p = Path(name)
        if not p.exists():
            raise FileNotFoundError(f"No sqlite db at {name!r}")
        conn = sqlite3.connect(str(p))
        conn.row_factory = sqlite3.Row
        return conn
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _duckdb_ro(name: str) -> duckdb.DuckDBPyConnection:
    path = DUCKDB_DBS.get(name)
    if path is None:
        raise KeyError(f"Unknown duckdb {name!r}. Known: {list(DUCKDB_DBS)}")
    if not path.exists():
        raise FileNotFoundError(f"{name} db not found at {path}")
    return duckdb.connect(str(path), read_only=True)


def _duckdb_rw(name: str) -> duckdb.DuckDBPyConnection:
    path = DUCKDB_DBS.get(name)
    if path is None:
        # Allow raw path as fallback for scan_stores discovered files
        p = Path(name)
        if not p.exists():
            raise FileNotFoundError(f"No duckdb at {name!r}")
        return duckdb.connect(str(p))
    return duckdb.connect(str(path))


def _redis() -> redis_lib.Redis:
    return redis_lib.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


def _rows_to_dicts(cursor: sqlite3.Cursor) -> list[dict]:
    cols = [d[0] for d in cursor.description or []]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def _duck_rows(conn: duckdb.DuckDBPyConnection, sql: str) -> list[dict]:
    rel = conn.execute(sql)
    cols = [d[0] for d in rel.description]
    return [dict(zip(cols, row)) for row in rel.fetchall()]


def _is_select(sql: str) -> bool:
    return bool(re.match(r"^\s*(SELECT|PRAGMA|DESCRIBE|SHOW|\.schema|EXPLAIN|WITH)\b", sql.strip(), re.IGNORECASE))


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="mammon-db",
    instructions=(
        "Full read/write access to all Mammon trading engine databases and Redis. "
        "Use list_dbs() first to see what exists, scan_stores() to find every file on disk, "
        "schema() to inspect tables, query() for SELECT reads, execute() for writes "
        "(DELETE, DROP, INSERT, UPDATE, CREATE). "
        "Use redis_delete() / redis_flush() to clean Redis keys. "
        "brain_frame() and vault() give live Redis engine state."
    ),
)


@mcp.tool()
def list_dbs() -> dict:
    """Return every known database alias, its type, path, and whether the file exists."""
    result = {}
    for name, path in SQLITE_DBS.items():
        result[name] = {"type": "sqlite", "path": str(path), "exists": path.exists()}
    for name, path in DUCKDB_DBS.items():
        result[name] = {"type": "duckdb", "path": str(path), "exists": path.exists()}
    try:
        _redis().ping()
        result["redis"] = {"type": "redis", "host": REDIS_HOST, "port": REDIS_PORT, "reachable": True}
    except Exception as e:
        result["redis"] = {"type": "redis", "reachable": False, "error": str(e)}
    return result


@mcp.tool()
def scan_stores() -> dict:
    """
    Walk the entire Mammon base directory and return every SQLite and DuckDB file found.
    Includes files not in the named registry (e.g. UUID test artifacts in runtime/).
    Each entry shows path, size_bytes, type, and whether it's a known alias.
    """
    known_paths = {str(p): alias for alias, p in ALL_DBS.items()}
    found: dict[str, dict] = {}

    for ext in ("*.db", "*.sqlite", "*.sqlite3", "*.duckdb"):
        for p in BASE.rglob(ext):
            if p.is_file():
                alias = known_paths.get(str(p))
                # Detect type: duckdb files have a magic header
                db_type = "duckdb" if p.suffix == ".duckdb" else "sqlite"
                if db_type == "sqlite":
                    # Double-check via magic bytes
                    try:
                        with open(p, "rb") as f:
                            magic = f.read(16)
                        if magic.startswith(b"DUCK"):
                            db_type = "duckdb"
                    except OSError:
                        pass
                found[str(p)] = {
                    "type": db_type,
                    "size_bytes": p.stat().st_size,
                    "alias": alias,
                    "in_registry": alias is not None,
                    "relative": str(p.relative_to(BASE)),
                }

    # Sort by path for readability
    return dict(sorted(found.items()))


@mcp.tool()
def schema(db: str, table: Optional[str] = None) -> list[dict]:
    """
    Return schema for a database.
    If table is given, return column info for that table only.
    If table is omitted, return all table names.
    db must be an alias from list_dbs() (not 'redis').
    """
    if db in SQLITE_DBS:
        conn = _sqlite_ro(db)
        try:
            if table:
                cur = conn.execute(f"PRAGMA table_info({table})")
                return _rows_to_dicts(cur)
            else:
                cur = conn.execute(
                    "SELECT name, type FROM sqlite_master WHERE type IN ('table','view') ORDER BY name"
                )
                return _rows_to_dicts(cur)
        finally:
            conn.close()
    elif db in DUCKDB_DBS:
        conn = _duckdb_ro(db)
        try:
            if table:
                return _duck_rows(conn, f"DESCRIBE {table}")
            else:
                return _duck_rows(conn, "SHOW TABLES")
        finally:
            conn.close()
    else:
        raise KeyError(f"Unknown db {db!r}")


@mcp.tool()
def query(db: str, sql: str, limit: int = 200) -> list[dict]:
    """
    Run a read-only SQL query against a named database.
    db must be an alias from list_dbs() (not 'redis').
    A LIMIT clause is appended automatically for SELECT queries (max 500 rows).
    Only SELECT / PRAGMA / DESCRIBE / WITH / EXPLAIN are allowed — use execute() for writes.
    """
    if not _is_select(sql):
        raise ValueError(f"query() is read-only. Use execute() for writes. Got: {sql[:80]!r}")

    if limit > 500:
        limit = 500
    stripped = sql.rstrip().rstrip(";")
    if re.search(r"\bLIMIT\b", sql, re.IGNORECASE) is None:
        stripped = f"{stripped} LIMIT {limit}"

    if db in SQLITE_DBS:
        conn = _sqlite_ro(db)
        try:
            cur = conn.execute(stripped)
            return _rows_to_dicts(cur)
        finally:
            conn.close()
    elif db in DUCKDB_DBS:
        conn = _duckdb_ro(db)
        try:
            return _duck_rows(conn, stripped)
        finally:
            conn.close()
    else:
        raise KeyError(f"Unknown db {db!r}. Use list_dbs() to see options.")


@mcp.tool()
def execute(db: str, sql: str) -> dict:
    """
    Execute any SQL statement against a named database — full write access.
    Handles DELETE, DROP, INSERT, UPDATE, CREATE, TRUNCATE, and SELECT.
    db must be an alias from list_dbs() (not 'redis').
    For SELECT queries, returns up to 500 rows.
    For write statements, returns rows_affected and success status.

    Examples:
      execute('money', 'DELETE FROM money_orders')
      execute('synapse', 'DROP TABLE IF EXISTS synapse_mint')
      execute('params', 'DELETE FROM param_lineage WHERE created_at < ...')
    """
    is_read = _is_select(sql)

    if db in SQLITE_DBS:
        conn = _sqlite_rw(db)
        try:
            cur = conn.execute(sql)
            if is_read:
                rows = _rows_to_dicts(cur)
                conn.commit()
                return {"rows": rows[:500], "count": len(rows)}
            else:
                conn.commit()
                return {"success": True, "rows_affected": cur.rowcount, "sql": sql}
        except Exception as e:
            conn.rollback()
            return {"success": False, "error": str(e), "sql": sql}
        finally:
            conn.close()
    elif db in DUCKDB_DBS:
        conn = _duckdb_rw(db)
        try:
            rel = conn.execute(sql)
            if is_read:
                cols = [d[0] for d in rel.description]
                rows = [dict(zip(cols, row)) for row in rel.fetchall()]
                return {"rows": rows[:500], "count": len(rows)}
            else:
                return {"success": True, "sql": sql}
        except Exception as e:
            return {"success": False, "error": str(e), "sql": sql}
        finally:
            conn.close()
    else:
        raise KeyError(f"Unknown db {db!r}. Use list_dbs() to see options.")


@mcp.tool()
def redis_get(key: str) -> Any:
    """
    Fetch a single Redis key. Returns parsed JSON if the value is JSON,
    otherwise returns the raw string.
    """
    r = _redis()
    t = r.type(key)
    if t == "string":
        val = r.get(key)
        try:
            return json.loads(val)
        except Exception:
            return val
    elif t == "hash":
        return r.hgetall(key)
    elif t == "list":
        return r.lrange(key, 0, 199)
    elif t == "set":
        return list(r.smembers(key))
    elif t == "zset":
        return r.zrange(key, 0, 199, withscores=True)
    else:
        return {"type": t, "key": key, "note": "unsupported type"}


@mcp.tool()
def redis_scan(pattern: str = "mammon:*", count: int = 100) -> list[str]:
    """
    Scan Redis for keys matching a glob pattern.
    Default pattern returns all Mammon keys.
    """
    r = _redis()
    keys = []
    cursor = 0
    while True:
        cursor, batch = r.scan(cursor, match=pattern, count=50)
        keys.extend(batch)
        if cursor == 0 or len(keys) >= count:
            break
    return sorted(keys[:count])


@mcp.tool()
def redis_delete(keys: list[str]) -> dict:
    """
    Delete one or more Redis keys by exact name.
    Returns the number of keys actually deleted.
    Example: redis_delete(['mammon:brain_frame:AAPL', 'mammon:hormonal_vault'])
    """
    r = _redis()
    deleted = r.delete(*keys)
    return {"deleted": deleted, "requested": len(keys), "keys": keys}


@mcp.tool()
def redis_flush(pattern: str) -> dict:
    """
    Delete ALL Redis keys matching a glob pattern. Use with care.
    Returns count of deleted keys.
    Example: redis_flush('mammon:brain_frame:*')  — wipes all brain frames
             redis_flush('mammon:*')               — wipes all Mammon state
    """
    r = _redis()
    keys = []
    cursor = 0
    while True:
        cursor, batch = r.scan(cursor, match=pattern, count=200)
        keys.extend(batch)
        if cursor == 0:
            break
    if not keys:
        return {"deleted": 0, "pattern": pattern, "note": "No keys matched"}
    deleted = r.delete(*keys)
    return {"deleted": deleted, "pattern": pattern, "keys_removed": keys}


@mcp.tool()
def brain_frame() -> dict:
    """
    Return all current brain frame(s) from Redis.
    Keys follow the pattern mammon:brain_frame:*.
    """
    r = _redis()
    cursor = 0
    frames = {}
    while True:
        cursor, keys = r.scan(cursor, match="mammon:brain_frame:*", count=50)
        for k in keys:
            raw = r.get(k)
            try:
                frames[k] = json.loads(raw)
            except Exception:
                frames[k] = raw
        if cursor == 0:
            break
    return frames if frames else {"note": "No brain frames in Redis — engine not running"}


@mcp.tool()
def vault() -> dict:
    """
    Return the hormonal vault from Redis (Gold / Silver / Platinum params).
    This is the live parameter set the engine is currently using.
    """
    r = _redis()
    key = "mammon:hormonal_vault"
    if not r.exists(key):
        return {"note": "Vault not in Redis — engine has not started"}
    try:
        raw_hash = r.hgetall(key)
        decoded = {}
        for k, v in raw_hash.items():
            k = k.decode() if isinstance(k, bytes) else k
            v = v.decode() if isinstance(v, bytes) else v
            try:
                decoded[k] = json.loads(v)
            except Exception:
                decoded[k] = v
        return decoded
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def recent_pulses(n: int = 20) -> list[dict]:
    """
    Return the most recent N rows from synapse_mint (the main pulse tape).
    Each row is one SEED/ACTION/MINT event with all BrainFrame slots captured.
    """
    if n > 200:
        n = 200
    conn = _sqlite_ro("synapse")
    try:
        cur = conn.execute(
            "SELECT * FROM synapse_mint ORDER BY rowid DESC LIMIT ?", (n,)
        )
        rows = _rows_to_dicts(cur)
        return list(reversed(rows))
    except sqlite3.OperationalError as e:
        return [{"error": str(e), "note": "synapse_mint may not exist yet — engine has not run"}]
    finally:
        conn.close()


@mcp.tool()
def money_tape(n: int = 20) -> dict:
    """
    Return the most recent N rows from each money table in the TreasuryGland store:
    money_orders, money_fills, money_positions, money_pnl_snapshots.
    """
    if n > 200:
        n = 200
    tables = ["money_orders", "money_fills", "money_positions", "money_pnl_snapshots"]
    result = {}
    try:
        conn = _sqlite_ro("money")
    except FileNotFoundError:
        return {"error": "money db not found — TreasuryGland has not run yet"}
    try:
        for tbl in tables:
            try:
                cur = conn.execute(f"SELECT * FROM {tbl} ORDER BY rowid DESC LIMIT ?", (n,))
                rows = _rows_to_dicts(cur)
                result[tbl] = list(reversed(rows))
            except sqlite3.OperationalError as e:
                result[tbl] = {"error": str(e)}
    finally:
        conn.close()
    return result


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.getenv("MCP_PORT", 5001))
    print(f"[mammon-mcp] Starting on port {port} — BASE={BASE}")
    mcp.run(transport="sse", host="0.0.0.0", port=port)
