"""Structured Mammon Neural Error Registry (MNER) telemetry helpers."""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

ROOT_DIR = Path(__file__).resolve().parents[2]
REGISTRY_PATH = (
    ROOT_DIR
    / "Hippocampus"
    / "Context"
    / "00_READ_FIRST_CANON"
    / "SCHEMA_KEYS"
    / "error_registry.json"
)
MNER_LOG_PATH = ROOT_DIR / "runtime" / "logs" / "mner.jsonl"

_CODE_PATTERN = re.compile(r"^[A-Z]+-[EWF]-[A-Z0-9]+-\d{3,4}$")
_registry_lock = threading.Lock()
_registry_cache: Dict[str, Dict[str, Any]] = {}
_registry_mtime_ns: int = -1


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalize_code(code: str) -> str:
    return str(code or "").strip().upper()


def _load_registry(force: bool = False) -> Dict[str, Dict[str, Any]]:
    global _registry_cache, _registry_mtime_ns
    with _registry_lock:
        try:
            mtime_ns = REGISTRY_PATH.stat().st_mtime_ns
        except Exception:
            mtime_ns = -1
        if not force and _registry_cache and mtime_ns == _registry_mtime_ns:
            return _registry_cache

        data: Dict[str, Any] = {}
        try:
            data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        codes = data.get("codes", {}) if isinstance(data, dict) else {}
        if not isinstance(codes, dict):
            codes = {}
        normalized: Dict[str, Dict[str, Any]] = {}
        for raw_code, meta in codes.items():
            code = _normalize_code(raw_code)
            if not code:
                continue
            if isinstance(meta, dict):
                normalized[code] = meta
            else:
                normalized[code] = {"description": str(meta)}
        _registry_cache = normalized
        _registry_mtime_ns = mtime_ns
        return _registry_cache


def validate_mner_code(code: str) -> bool:
    return bool(_CODE_PATTERN.match(_normalize_code(code)))


def is_registered_mner(code: str) -> bool:
    return _normalize_code(code) in _load_registry()


def emit_mner(
    code: str,
    message: str,
    *,
    source: str = "",
    details: Optional[Dict[str, Any]] = None,
    echo: bool = False,
) -> Dict[str, Any]:
    """
    Write a structured MNER event to runtime/logs/mner.jsonl.
    Unknown/invalid codes are downgraded to MNER-E-INFRA-002 with metadata.
    """
    payload_details = dict(details or {})
    raw_code = _normalize_code(code)
    registry = _load_registry()
    code_ok = validate_mner_code(raw_code) and raw_code in registry
    if code_ok:
        final_code = raw_code
        level = raw_code.split("-", 2)[1]
    else:
        final_code = "MNER-E-INFRA-002"
        level = "E"
        payload_details["requested_code"] = raw_code or "EMPTY"
        payload_details["reason"] = "UNREGISTERED_OR_INVALID_CODE"

    entry = {
        "ts": _utc_iso_now(),
        "code": final_code,
        "level": level,
        "source": str(source or ""),
        "message": str(message or ""),
        "details": payload_details,
    }
    try:
        MNER_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with MNER_LOG_PATH.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(entry, ensure_ascii=True) + "\n")
    except Exception:
        # Intentionally swallow to avoid crashing trading runtime due telemetry.
        pass

    if echo:
        print(f"[{entry['code']}] {entry['message']}")

    return entry


def read_mner_tail(limit: int = 100) -> list[Dict[str, Any]]:
    if limit <= 0:
        return []
    if not MNER_LOG_PATH.exists():
        return []
    ring: list[Dict[str, Any]] = []
    max_len = min(int(limit), 500)
    try:
        with MNER_LOG_PATH.open("r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except Exception:
                    continue
                ring.append(evt if isinstance(evt, dict) else {"message": str(evt)})
                if len(ring) > max_len:
                    ring = ring[-max_len:]
    except Exception:
        return []
    return ring

