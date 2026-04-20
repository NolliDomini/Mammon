"""Validate in-code MNER tags against the canonical registry."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
REGISTRY_PATH = (
    ROOT_DIR
    / "Hippocampus"
    / "Context"
    / "00_READ_FIRST_CANON"
    / "SCHEMA_KEYS"
    / "error_registry.json"
)
CODE_RE = re.compile(r"\b([A-Z]+-[EWF]-[A-Z0-9]+-\d{3,4})\b")


def _load_registry() -> set[str]:
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    codes = data.get("codes", {})
    if not isinstance(codes, dict):
        return set()
    return {str(k).strip().upper() for k in codes.keys() if str(k).strip()}


def _iter_runtime_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT_DIR.rglob("*.py"):
        p = str(path).replace("\\", "/")
        if p.endswith("-TheBrain.py"):
            continue
        if "/tests" in p or "/tests_v2/" in p:
            continue
        if "/.venv/" in p:
            continue
        files.append(path)
    return files


def main() -> int:
    if not REGISTRY_PATH.exists():
        print(f"missing registry: {REGISTRY_PATH}")
        return 2
    registered = _load_registry()
    discovered: set[str] = set()
    for path in _iter_runtime_files():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for match in CODE_RE.findall(text):
            discovered.add(match.strip().upper())

    unknown = sorted(code for code in discovered if code not in registered)
    print(f"registered={len(registered)} discovered={len(discovered)} unknown={len(unknown)}")
    for code in unknown:
        print(f"unknown: {code}")
    return 1 if unknown else 0


if __name__ == "__main__":
    raise SystemExit(main())

