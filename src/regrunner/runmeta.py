"""``run.json``: the small per-run summary the UI lists.  Written by the runner and the web supervisor."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def read_meta(run_dir: Path) -> dict[str, Any] | None:
    f = run_dir / "run.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None
    except (OSError, json.JSONDecodeError):
        return None


def update_meta(run_dir: Path, **fields: Any) -> dict[str, Any]:
    """Merge ``fields`` into run.json (keeps what other writers stored) and replace it atomically."""
    meta = {**(read_meta(run_dir) or {}), **fields}
    run_dir.mkdir(parents=True, exist_ok=True)
    tmp = run_dir / f"run.json.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(meta, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(run_dir / "run.json")
    return meta
