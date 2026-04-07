import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple, Any
from Hippocampus.Archivist.librarian import Librarian


REQUIRED_SCHEMA_KEY_FILES = [
    "Hippocampus/Context/00_READ_FIRST_CANON/SCHEMA_KEYS/README.md",
    "Hippocampus/Context/00_READ_FIRST_CANON/SCHEMA_KEYS/SCHEMA_REGISTRY_INDEX.md",
    "Hippocampus/Context/00_READ_FIRST_CANON/SCHEMA_KEYS/Ecosystem_Memory.schema.md",
    "Hippocampus/Context/00_READ_FIRST_CANON/SCHEMA_KEYS/Ecosystem_Synapse.schema.md",
    "Hippocampus/Context/00_READ_FIRST_CANON/SCHEMA_KEYS/Ecosystem_Optimizer.schema.md",
    "Hippocampus/Context/00_READ_FIRST_CANON/SCHEMA_KEYS/duck.schema.md",
    "Hippocampus/Context/00_READ_FIRST_CANON/SCHEMA_KEYS/control_logs.schema.md",
    "Hippocampus/Context/00_READ_FIRST_CANON/SCHEMA_KEYS/Ecosystem_UI.schema.md",
]


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _db_targets(root: Path) -> List[Tuple[str, Path, str]]:
    return [
        ("sqlite", root / "Hippocampus" / "Archivist" / "Ecosystem_Memory.db", "memory-v1"),
        ("sqlite", root / "Hippocampus" / "Archivist" / "Ecosystem_Synapse.db", "synapse-v1"),
        ("sqlite", root / "Hippocampus" / "Archivist" / "Ecosystem_Optimizer.db", "optimizer-v1"),
        ("sqlite", root / "Hospital" / "Memory_care" / "control_logs.db", "control-v1"),
        ("sqlite", root / "Hippocampus" / "data" / "Ecosystem_UI.db", "ui-v1"),
        ("duckdb", root / "Hospital" / "Memory_care" / "duck.db", "duck-v1"),
    ]


def ensure_schema_versions(root: Path = None) -> List[str]:
    root = root or _project_root()
    touched = []
    for engine, db_path, version in _db_targets(root):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        if engine == "sqlite":
            with Librarian.get_connection(db_path) as con:
                con.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_version (
                        component TEXT PRIMARY KEY,
                        version TEXT NOT NULL,
                        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                    )
                    """
                )
                con.execute(
                    """
                    INSERT INTO schema_version(component, version)
                    VALUES ('core', ?)
                    ON CONFLICT(component) DO UPDATE SET
                        version = excluded.version,
                        updated_at = datetime('now')
                    """,
                    (version,),
                )
                con.commit()
        else:
            try:
                import duckdb
                con = duckdb.connect(str(db_path))
                con.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_version (
                        component VARCHAR PRIMARY KEY,
                        version VARCHAR NOT NULL,
                        updated_at TIMESTAMP DEFAULT current_timestamp
                    )
                    """
                )
                # DuckDB ON CONFLICT behavior has been unstable across versions.
                # Use explicit upsert sequence to guarantee core row persistence.
                con.execute("DELETE FROM schema_version WHERE component = 'core'")
                con.execute(
                    "INSERT INTO schema_version(component, version, updated_at) VALUES ('core', ?, current_timestamp)",
                    [version],
                )
                row = con.execute(
                    "SELECT version FROM schema_version WHERE component = 'core'"
                ).fetchone()
                if row is None or str(row[0]) != str(version):
                    raise RuntimeError("duck_schema_version_persistence_failed")
                con.close()
            except Exception:
                continue
        touched.append(str(db_path))
    return touched


def _sqlite_tables(db_path: Path) -> List[str]:
    with Librarian.get_connection(db_path) as con:
        rows = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        return sorted(str(r[0]) for r in rows)


def _duck_tables(db_path: Path) -> List[str]:
    import duckdb

    con = duckdb.connect(str(db_path))
    try:
        rows = con.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'main'
            """
        ).fetchall()
        return sorted(str(r[0]) for r in rows)
    finally:
        con.close()


def _expected_tables() -> Dict[str, List[str]]:
    return {
        "memory-v1": ["schema_version", "money_orders", "money_fills", "money_positions", "money_pnl_snapshots"],
        "synapse-v1": ["schema_version", "synapse_mint"],
        "optimizer-v1": ["schema_version"],
        "control-v1": ["schema_version"],
        "ui-v1": ["schema_version", "ui_control_audit", "ui_projection_deadletter", "ui_orders"],
        "duck-v1": ["schema_version", "market_tape", "history_synapse", "fornix_checkpoint"],
    }


def run_schema_drift_check(root: Path = None) -> Dict[str, Any]:
    root = root or _project_root()
    expected = _expected_tables()
    issues: List[Dict[str, Any]] = []
    databases: List[Dict[str, Any]] = []

    for engine, db_path, version in _db_targets(root):
        db_info: Dict[str, Any] = {
            "engine": engine,
            "path": str(db_path),
            "version_expected": version,
            "exists": db_path.exists(),
            "issues": [],
        }
        if not db_path.exists():
            db_info["issues"].append("db_missing")
            issues.append({"path": str(db_path), "issue": "db_missing"})
            databases.append(db_info)
            continue
        try:
            if engine == "sqlite":
                tables = _sqlite_tables(db_path)
                with Librarian.get_connection(db_path) as con:
                    # Verify WAL mode
                    journal_mode = con.execute("PRAGMA journal_mode").fetchone()[0]
                    db_info["journal_mode"] = journal_mode
                    if journal_mode.lower() != "wal":
                        db_info["issues"].append("journal_mode_not_wal")
                        issues.append({"path": str(db_path), "issue": "journal_mode_not_wal", "actual": journal_mode})
                    
                    row = con.execute(
                        "SELECT version FROM schema_version WHERE component = 'core' LIMIT 1"
                    ).fetchone()
                version_actual = row[0] if row else None
            else:
                tables = _duck_tables(db_path)
                import duckdb

                con = duckdb.connect(str(db_path))
                try:
                    row = con.execute(
                        "SELECT version FROM schema_version WHERE component = 'core' LIMIT 1"
                    ).fetchone()
                finally:
                    con.close()
                version_actual = row[0] if row else None

            db_info["tables"] = tables
            db_info["version_actual"] = version_actual
            if str(version_actual) != str(version):
                db_info["issues"].append("schema_version_mismatch")
                issues.append(
                    {
                        "path": str(db_path),
                        "issue": "schema_version_mismatch",
                        "expected": version,
                        "actual": version_actual,
                    }
                )
            required = expected.get(version, ["schema_version"])
            missing_tables = [t for t in required if t not in tables]
            if missing_tables:
                db_info["issues"].append("missing_tables")
                issues.append(
                    {
                        "path": str(db_path),
                        "issue": "missing_tables",
                        "missing": missing_tables,
                    }
                )
        except Exception as e:
            db_info["issues"].append("check_failed")
            issues.append({"path": str(db_path), "issue": "check_failed", "detail": str(e)[:160]})
        databases.append(db_info)

    return {
        "ok": len(issues) == 0,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "databases": databases,
        "issues": issues,
    }


def validate_schema_registry_files(root: Path = None) -> Dict[str, List[str]]:
    root = root or _project_root()
    missing = []
    for rel in REQUIRED_SCHEMA_KEY_FILES:
        if not (root / rel).exists():
            missing.append(rel)
    return {"missing": missing}


def _is_optional_schema_target(db_path: str) -> bool:
    p = str(db_path).replace("\\", "/").lower()
    return (
        p.endswith("/hippocampus/data/ecosystem_ui.db")
        or p.endswith("hippocampus/data/ecosystem_ui.db")
        or p.endswith("/hospital/memory_care/duck.db")
        or p.endswith("hospital/memory_care/duck.db")
    )


def run_schema_smoke_check(root: Path = None) -> Dict[str, object]:
    root = root or _project_root()
    enforce = os.environ.get("MAMMON_SCHEMA_ENFORCE", "1").strip() != "0"
    touched = ensure_schema_versions(root)
    reg = validate_schema_registry_files(root)
    missing = reg["missing"]
    drift = run_schema_drift_check(root)
    critical_drift_issues: List[Dict[str, Any]] = []
    for issue in drift.get("issues", []):
        if _is_optional_schema_target(issue.get("path", "")):
            continue
        critical_drift_issues.append(issue)
    ok = (not missing and len(critical_drift_issues) == 0) if enforce else True
    return {
        "ok": ok,
        "enforced": enforce,
        "schema_version_touched": touched,
        "missing_registry_files": missing,
        "drift_ok": bool(drift.get("ok", False)),
        "critical_drift_issues": critical_drift_issues,
        "drift_issues_total": len(drift.get("issues", [])),
    }
