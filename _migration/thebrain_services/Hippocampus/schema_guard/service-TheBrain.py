import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple, Any
from Hippocampus.Archivist.librarian import librarian


def get_required_schema_files(root: Path) -> List[str]:
    """Piece 70: Reads canonical schema list from central Navigator."""
    nav_path = root / "Hippocampus" / "Context" / "NAVIGATOR.md"
    if not nav_path.exists():
        return []
    
    files = []
    try:
        with open(nav_path, "r") as f:
            content = f.read()
            # Extract paths from the 'Central Schema Registry' section
            in_registry = False
            for line in content.splitlines():
                if "Central Schema Registry" in line:
                    in_registry = True
                    continue
                if in_registry and line.strip().startswith("- `"):
                    path = line.split("`")[1]
                    files.append(path)
    except Exception as e:
        print(f"[HIPP-E-P70-708] FAILED_TO_READ_NAVIGATOR: {e}")
    return files


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _db_targets(root: Path) -> List[Tuple[str, Path, str]]:
    """V4: Analytical and Persistence Targets."""
    return [
        ("duckdb", root / "Hippocampus" / "data" / "ecosystem_synapse.duckdb", "synapse-v4"),
        ("duckdb", root / "Hippocampus" / "data" / "ecosystem_params.duckdb", "params-v4"),
    ]


def ensure_schema_versions(root: Path = None) -> List[str]:
    root = root or _project_root()
    touched = []
    for engine, db_path, version in _db_targets(root):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        if engine == "duckdb":
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
                    raise RuntimeError(f"duck_schema_version_persistence_failed_{version}")
                con.close()
            except Exception as e:
                # HIPP-E-P70-706: Schema version check exception
                print(f"[HIPP-E-P70-706] Schema version check failed for {db_path}: {e}")
                continue
        touched.append(str(db_path))
    return touched


def _sqlite_tables(db_path: Path) -> List[str]:
    import sqlite3
    con = sqlite3.connect(str(db_path))
    try:
        rows = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        return sorted(str(r[0]) for r in rows)
    finally:
        con.close()


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
        "synapse-v4": ["schema_version", "synapse_mint", "market_tape", "history_synapse", "fornix_checkpoint"],
        "params-v4": ["schema_version", "param_sets"],
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
            # [HIPP-E-P70-701] Missing Database
            msg = f"[HIPP-E-P70-701] DATABASE_MISSING: {db_path.name}"
            db_info["issues"].append(msg)
            issues.append({"path": str(db_path), "issue": msg})
            databases.append(db_info)
            continue
        try:
            if engine == "sqlite":
                tables = _sqlite_tables(db_path)
                import sqlite3
                con = sqlite3.connect(str(db_path))
                try:
                    # Verify WAL mode
                    journal_mode = con.execute("PRAGMA journal_mode").fetchone()[0]
                    db_info["journal_mode"] = journal_mode
                    if journal_mode.lower() != "wal":
                        db_info["issues"].append("journal_mode_not_wal")
                        issues.append({"path": str(db_path), "issue": "journal_mode_not_wal", "actual": journal_mode})
                    
                    row = con.execute(
                        "SELECT version FROM schema_version WHERE component = 'core' LIMIT 1"
                    ).fetchone()
                finally:
                    con.close()
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
                # [HIPP-E-P70-702] Version Mismatch
                msg = f"[HIPP-E-P70-702] VERSION_MISMATCH: {version_actual} != {version}"
                db_info["issues"].append(msg)
                issues.append(
                    {
                        "path": str(db_path),
                        "issue": msg,
                        "expected": version,
                        "actual": version_actual,
                    }
                )
            required = expected.get(version, ["schema_version"])
            missing_tables = [t for t in required if t not in tables]
            if missing_tables:
                # [HIPP-E-P70-703] Missing Tables
                msg = f"[HIPP-E-P70-703] MISSING_TABLES: {missing_tables}"
                db_info["issues"].append(msg)
                issues.append(
                    {
                        "path": str(db_path),
                        "issue": msg,
                        "missing": missing_tables,
                    }
                )
        except Exception as e:
            # [HIPP-E-P70-707] Drift check failed
            msg = f"[HIPP-E-P70-707] DRIFT_CHECK_FAILED: {str(e)[:100]}"
            db_info["issues"].append(msg)
            issues.append({"path": str(db_path), "issue": msg, "detail": str(e)[:160]})
        databases.append(db_info)

    return {
        "ok": len(issues) == 0,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "databases": databases,
        "issues": issues,
    }


def validate_schema_registry_files(root: Path = None) -> Dict[str, List[str]]:
    root = root or _project_root()
    required_files = get_required_schema_files(root)
    missing = []
    for rel in required_files:
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
